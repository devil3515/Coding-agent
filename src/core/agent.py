"""Async core reasoning loop of the coding agent with phase-based state machine."""
import json
import asyncio
from rich.console import Console
from rich.text import Text
from src.llm.base import Message
from src.tools.registry import ToolRegistry
from src.memory.base import BaseMemory
from src.memory.long_term import LongTermMemory
from src.safety.guardrails import is_safe_path, is_shell_safe
from src.tools.planning import create_project_plan as _create_project_plan
from src.core.state import (
    AgentPhase,
    is_tool_allowed,
    PhaseTransition,
    format_phase_banner,
    get_allowed_tools,
)


class Agent:
    """
    The core reasoning loop of the coding agent.
    Now with phase-based state machine for plan enforcement.
    """

    def __init__(
        self,
        llm,
        registry: ToolRegistry,
        memory: BaseMemory,
        console: Console,
        ltm: LongTermMemory = None,
        llm_config: dict = None,
        working_directory: str = None,
        session_id: str = None,
    ):
        self.llm = llm
        self.registry = registry
        self.memory = memory
        self.console = console
        self.ltm = ltm
        self.llm_config = llm_config or {}
        self.working_directory = working_directory
        self.session_id = session_id

        # --- TOKEN TRACKING STATE ---
        self.session_input_tokens = 0
        self.session_output_tokens = 0

        # --- PLAN STATE ---
        self.current_plan: list[dict] = []

        # --- PHASE STATE ---
        self.phase = AgentPhase.IDLE

        # --- TOUCHED FILES STATE ---
        self.touched_files = set()

        # --- PENDING VERIFICATION ---
        # Files written this turn that need auto-verification
        self._pending_verification: list[str] = []

        # --- SEARCH CONTEXT TRACKER ---
        self._discovered_context: dict[str, str] = {}

        # --- SKILL STATE ---
        self.active_skill_name: str | None = None

    def _count_tokens(self, messages: list[Message]) -> int:
        """Local token counter using tiktoken if available."""
        if hasattr(self.memory, "_count_tokens"):
            return self.memory._count_tokens(messages)
        total = 0
        for m in messages:
            if m.content:
                total += len(m.content) // 4
            if m.tool_calls:
                for tc in m.tool_calls:
                    total += len(str(tc.arguments)) // 4
        return total

    def get_context_usage(self) -> dict:
        """Get context window usage based on the ACTUAL context sent to LLM."""
        actual_context = self._build_context()
        used_tokens = self._count_tokens(actual_context)
        context_window = 128000
        if hasattr(self.memory, "context_window"):
            context_window = self.memory.context_window
        available_tokens = context_window - used_tokens
        buffer_tokens = int(context_window * 0.02)
        return {
            "used": used_tokens,
            "available": max(0, available_tokens - buffer_tokens),
            "total": context_window,
            "percentage": min(100, (used_tokens / context_window) * 100),
            "model": getattr(self.memory, "model", "unknown"),
        }

    def print_context_bar(self):
        """Print an accurate context window usage bar."""
        usage = self.get_context_usage()
        if not usage:
            return
        used = usage["used"]
        total = usage["total"]
        pct = usage["percentage"]
        if pct < 50:
            color = "green"
            status_emoji = "✅"
        elif pct < 75:
            color = "yellow"
            status_emoji = "⚠️"
        elif pct < 90:
            color = "orange3"
            status_emoji = "🔶"
        else:
            color = "red"
            status_emoji = "🚨"
        bar_width = 30
        filled = int((pct / 100) * bar_width)
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty
        def fmt(n: int) -> str:
            return f"{n/1000:.1f}K" if n >= 1000 else str(n)
        text = Text()
        text.append(f"{status_emoji} Context: ", style="dim")
        text.append(bar, style=color)
        text.append(f"  {fmt(used)}/{fmt(total)} tokens ({pct:.1f}%)", style="dim")
        self.console.print(text)

    def _print_token_usage(self, response, action_text: str):
        """Helper to format and print token usage cleanly."""
        self.session_input_tokens += response.input_tokens
        self.session_output_tokens += response.output_tokens
        session_total = self.session_input_tokens + self.session_output_tokens
        self.console.print(
            f"[dim]🪙 [bold cyan]In:[/bold cyan] {response.input_tokens:,} | "
            f"[bold magenta]Out:[/bold magenta] {response.output_tokens:,} | "
            f"[bold white]Session:[/bold white] {session_total:,}[/dim]"
        )
        self.console.print(f"[dim]{action_text}[/dim]")

    def _transition_phase(self, new_phase: AgentPhase):
        """Transition to a new phase and notify the user."""
        if self.phase == new_phase:
            return
        old_phase = self.phase
        self.phase = new_phase
        banner = format_phase_banner(new_phase)
        self.console.print(f"[bold cyan]🔄 Phase transition: {old_phase.value.upper()} → {new_phase.value.upper()}[/bold cyan]")
        self.console.print(f"[dim]{banner}[/dim]")

        # On transition to VERIFYING, auto-inject verification instructions
        if new_phase == AgentPhase.VERIFYING:
            verify_msg = (
                "All planned steps are complete. Please verify your changes by reading "
                "the files you modified and running any relevant tests. "
                "Use update_plan_status to mark verification as complete when satisfied."
            )
            self.memory.add_message(Message(role="user", content=verify_msg))
            self.console.print("[dim]📝 Auto-injected verification instructions into context.[/dim]")

    def _check_phase_transition(self):
        """Check if we should auto-transition based on plan state."""
        new_phase = PhaseTransition.check_transition(
            self.phase, self.current_plan, self._pending_verification
        )
        if new_phase:
            self._transition_phase(new_phase)

    async def _auto_verify(self, file_path: str):
        """Auto-verify a file by reading it back after write/diff."""
        self.console.print(f"[dim]🔍 Auto-verifying {file_path}...[/dim]")
        result = await self.registry.aexecute("read_file", {"file_path": file_path})
        # Add verification result as a system note in memory
        verify_note = f"[AUTO-VERIFY] File {file_path} after modification:
{result[:500]}"
        self.memory.add_message(Message(role="tool", content=verify_note, tool_call_id="auto-verify"))
        # Remove from pending
        if file_path in self._pending_verification:
            self._pending_verification.remove(file_path)

    async def chat(self, user_input: str, max_iterations: int = 10) -> str | None:
        """
        Takes user input, runs the async agent loop with phase enforcement,
        and returns the final text response.
        """
        # -- ADD USER INPUT -----------------------------------------------------
        self.memory.add_message(Message(role="user", content=user_input))

        # Reset phase for new task if we're in COMPLETED
        if self.phase == AgentPhase.COMPLETED:
            self._transition_phase(AgentPhase.IDLE)
            self.current_plan = []
            self._pending_verification = []

        iteration_count = 0

        while True:
            iteration_count += 1

            # -- KILL SWITCH ----------------------------------------------------
            if iteration_count >= max_iterations:
                self.console.print("[bold red]⚠️ Max iterations reached. Forcing final response.[/bold red]")
                self.memory.add_message(Message(
                    role="user",
                    content="You have looped too many times. Please provide your final summary based on what you know."
                ))
                context = self._build_context()
                final_response = await self.llm.async_complete(
                    context,
                    tools=None,
                    max_tokens=self.llm_config.get("max_tokens", 6000)
                )
                self._print_token_usage(final_response, "🛑 Forced final response.")
                self.memory.add_message(Message(role="assistant", content=final_response.content))
                return final_response.content

            # -- BUILD FRESH CONTEXT --------------------------------------------
            context = self._build_context()

            # -- ASK LLM (ASYNC) ------------------------------------------------
            # Only expose tools allowed in current phase
            available_tools = self.registry.get_schemas_for_phase(self.phase)
            try:
                response = await self.llm.async_complete(
                    context,
                    tools=available_tools,
                    max_tokens=self.llm_config.get("max_tokens", 6000)
                )
            except Exception as api_err:
                self.console.print(f"[bold red]⚠️ LLM API error (iteration {iteration_count}): {api_err}[/bold red]")
                self.memory.add_message(Message(role="assistant", content=f"[API error: {api_err}]"))
                return f"The LLM API returned an error: {api_err}"

            # -- CHECK IF LLM IS DONE -------------------------------------------
            if response.is_final:
                self._print_token_usage(response, "✅ Final response generated.")
                self.memory.add_message(Message(role="assistant", content=response.content))
                return response.content

            else:
                if not response.tool_calls:
                    self._print_token_usage(response, "⚠️ Response cut off (hit max_tokens limit).")
                    self.memory.add_message(Message(role="assistant", content=response.content or "[Response truncated]"))
                    return response.content or "[Response truncated due to length limit]"

                self._print_token_usage(response, f"🧠 Requested {len(response.tool_calls)} tool(s).")

                for tool_call in response.tool_calls:
                    self.memory.add_message(Message(role="assistant", content=None, tool_calls=[tool_call]))

                    try:
                        args = json.loads(tool_call.arguments)
                    except (json.JSONDecodeError, TypeError) as parse_err:
                        result = f"Error: Could not parse arguments for '{tool_call.name}' — malformed JSON: {parse_err}"
                        self.console.print(f"[bold red]{result}[/bold red]")
                        self.memory.add_message(Message(role="tool", content=result, tool_call_id=tool_call.id))
                        continue

                    # ==========================================
                    # 0. PHASE ENFORCEMENT
                    # ==========================================
                    if not is_tool_allowed(self.phase, tool_call.name):
                        allowed = get_allowed_tools(self.phase)
                        result = (
                            f"⛔ PHASE ERROR: Tool '{tool_call.name}' is not allowed in {self.phase.value} phase. "
                            f"Allowed tools: {', '.join(allowed)}"
                        )
                        self.console.print(f"[bold red]{result}[/bold red]")
                        self.memory.add_message(Message(role="tool", content=result, tool_call_id=tool_call.id))
                        continue

                    # ==========================================
                    # 1. SECURITY INTERCEPTION LAYER
                    # ==========================================
                    is_safe = True
                    block_reason = ""

                    if tool_call.name in ["read_file", "write_file", "apply_diff", "search_codebase"]:
                        file_path = args.get("file_path", "")
                        is_safe, block_reason = is_safe_path(file_path, self.working_directory)

                    elif tool_call.name == "run_shell_command":
                        command = args.get("command", "")
                        is_safe, block_reason = is_shell_safe(command, self.working_directory)

                    if not is_safe:
                        result = block_reason
                        self.console.print(f"[bold red]{block_reason}[/bold red]")

                    # ==========================================
                    # 2. PLAN CREATION TRACKING
                    # ==========================================
                    elif tool_call.name == "create_project_plan":
                        steps = args.get("steps", [])
                        self.current_plan = _create_project_plan(steps)
                        self.console.print("\n[bold cyan]📋 Project Plan Created:[/bold cyan]")
                        for i, step in enumerate(self.current_plan):
                            files_hint = f" → {', '.join(step['files'])}" if step["files"] else ""
                            self.console.print(f" [dim][ ][/dim] Step {i+1}: {step['title']}{files_hint}")
                        self.console.print("")
                        result = f"Plan created with {len(self.current_plan)} steps."
                        # Auto-transition: IDLE → PLANNING
                        self._transition_phase(AgentPhase.PLANNING)
                        # Auto-mark first step as in_progress
                        if self.current_plan:
                            self.current_plan[0]["status"] = "in_progress"
                            self._check_phase_transition()

                    # ==========================================
                    # 3. Human-in-the-Loop Questions
                    # ==========================================
                    elif tool_call.name == "ask_user_question":
                        q_type = args.get("question_type", "text")
                        question = args.get("question", "Please clarify:")

                        if q_type == "mcq" and args.get("options"):
                            self.console.print(f"\n[bold yellow]❓ AGENT QUESTION:[/bold yellow] {question}")
                            for i, opt in enumerate(args["options"]):
                                self.console.print(f" [bold cyan]{i+1}.[/bold cyan] {opt}")
                            user_answer = await asyncio.to_thread(
                                self.console.input,
                                "[bold blue]Your choice (number or text):> [/bold blue]"
                            )
                        else:
                            user_answer = await asyncio.to_thread(
                                self.console.input,
                                f"\n[bold yellow]❓ AGENT QUESTION:[/bold yellow] {question}\n"
                                f"[bold blue]Your answer:> [/bold blue]"
                            )
                        result = f"User answered: {user_answer}"

                    # ==========================================
                    # 4. Plan Updates
                    # ==========================================
                    elif tool_call.name in ["update_plan_text", "update_plan_status"]:
                        if tool_call.name == "update_plan_text":
                            step_num = args.get("step_number")
                            new_text = args.get("new_text", "")
                            if self.current_plan and step_num and 1 <= step_num <= len(self.current_plan):
                                self.current_plan[step_num - 1]["title"] = new_text
                                result = f"Step {step_num} renamed to: {new_text}"
                            else:
                                result = f"Error: step_number {step_num} out of range."
                        else:
                            step_num = args.get("step_number")
                            status = args.get("status")
                            if self.current_plan and step_num and 1 <= step_num <= len(self.current_plan):
                                self.current_plan[step_num - 1]["status"] = status
                                icon = {"completed": "✅", "in_progress": "🔄", "failed": "❌"}.get(status, "?")
                                step_title = self.current_plan[step_num - 1]["title"]
                                self.console.print(f" {icon} Step {step_num}: {step_title}")
                                result = f"Step {step_num} marked as {status}."
                                # Check for phase transition after status update
                                self._check_phase_transition()
                            else:
                                result = f"Error: step_number {step_num} out of range."

                    # ==========================================
                    # 5. NORMAL TOOL EXECUTION (ASYNC)
                    # ==========================================
                    else:
                        result = await self.registry.aexecute(tool_call.name, args)

                        if tool_call.name in ["write_file", "apply_diff"]:
                            fp = args.get("file_path")
                            if fp:
                                self.touched_files.add(fp)
                                self._pending_verification.append(fp)

                    # -- PRINT TOOL EXECUTION ------------------------------------
                    self.console.print(f"[bold cyan]🔧 Tool:[/bold cyan] [magenta]{tool_call.name}[/magenta]")
                    if args:
                        args_str = str(args)
                        if len(args_str) > 100:
                            args_str = args_str[:100] + "... [truncated]"
                        self.console.print(f"[dim] Args: {args_str}[/dim]")

                    preview = result.replace("\n", " ")[:150].strip()
                    if len(result.replace("\n", " ")) > 150:
                        preview += "..."
                    self.console.print(f"[white] Result: {preview}[/white]")

                    # -- SAVE RESULT TO MEMORY -----------------------------------
                    self.memory.add_message(Message(role="tool", content=result, tool_call_id=tool_call.id))

                    # -- TRACK SEARCH CONTEXT ------------------------------------
                    if tool_call.name == "search_codebase":
                        query = args.get("query", "")
                        if query and result and "No functions" not in result:
                            summary = result.replace("\n", " ")[:200]
                            self._discovered_context[query.lower()] = summary
                            for word in query.lower().split():
                                if len(word) > 3:
                                    self._discovered_context[f"kw:{word}"] = summary

                    elif tool_call.name == "get_codebase_overview":
                        dir_arg = args.get("directory", self.working_directory or ".")
                        if result and "No code symbols" not in result:
                            summary = result.replace("\n", " ")[:200]
                            self._discovered_context[f"overview:{dir_arg}"] = summary

                    elif tool_call.name == "get_file_tree":
                        dir_arg = args.get("directory", self.working_directory or ".")
                        if result and "not found" not in result.lower():
                            summary = result.replace("\n", " ")[:200]
                            self._discovered_context[f"tree:{dir_arg}"] = summary

                # -- AUTO-VERIFICATION AFTER EACH TURN -------------------------
                if self.phase == AgentPhase.EXECUTING and self._pending_verification:
                    for fp in list(self._pending_verification):
                        await self._auto_verify(fp)

                self.console.print("[dim]⏳ Processing tool results...[/dim]")

    def _build_context(self) -> list[Message]:
        """
        Builds a fresh context list every turn.
        Injects LTM, search context, working directory, active plan,
        and CURRENT PHASE into a NEW system message.
        """
        base_context = self.memory.get_context()

        if base_context and base_context[0].role == "system":
            system_content = base_context[0].content
            history = base_context[1:]
        else:
            system_content = "You are a helpful coding assistant."
            history = base_context

        sections = [system_content]

        # -- PHASE INDICATOR --
        allowed_tools = get_allowed_tools(self.phase)
        sections.append(
            f"[CURRENT PHASE: {self.phase.value.upper()}]\n"
            f"You are in the {self.phase.value} phase. "
            f"Allowed tools: {', '.join(allowed_tools)}. "
            f"Do NOT call tools outside this list."
        )

        if self.ltm:
            past_context, ltm_token_count = self.ltm.get_recent_context(limit=5)
            if past_context and ltm_token_count < 3000:
                sections.append(past_context)

        if self._discovered_context:
            search_lines = ["\n" + "="*60 + "\n🔍 PREVIOUSLY DISCOVERED CONTEXT (CRITICAL - DO NOT RE-SEARCH)\n" + "="*60]
            for query, summary in list(self._discovered_context.items())[:10]:
                if not query.startswith("kw:"):
                    search_lines.append(f"• '{query}': {summary}")
            search_lines.append("\n⚠️ IMPORTANT: These searches have already been done. USE this context instead of re-searching.")
            sections.append("\n".join(search_lines))

        if self.working_directory:
            sections.append(
                f"[SYSTEM NOTE]: You are currently operating in the directory: {self.working_directory}. "
                f"You MUST use relative paths from this directory (e.g., 'src/main.py'). "
                f"NEVER use absolute paths like /Users/name/... unless explicitly asked."
            )

        if self.current_plan:
            active_idx = next(
                (i for i, s in enumerate(self.current_plan) if s["status"] == "in_progress"),
                None
            )
            plan_lines = []
            for i, step in enumerate(self.current_plan):
                n = i + 1
                icon = {"completed": "✅", "in_progress": "🔄", "failed": "❌"}.get(step["status"], "[ ]")
                files_hint = f" → {', '.join(step['files'])}" if step["files"] else ""
                marker = " ← YOU ARE HERE" if i == active_idx else ""
                plan_lines.append(f"{icon} Step {n}: {step['title']}{files_hint}{marker}")

            total = len(self.current_plan)
            step_label = f"Step {active_idx + 1} of {total}" if active_idx is not None else f"{total} steps"
            header = f"[ACTIVE PLAN — {step_label}]"
            sections.append(f"{header}\n" + "\n".join(plan_lines))

        fresh_system = Message(role="system", content="\n\n".join(sections))
        return [fresh_system] + history