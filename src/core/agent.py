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


class Agent:
    """
    The core reasoning loop of the coding agent.
    Completely decoupled from the CLI. Now fully async.
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

        # --- TOUCHED FILES STATE ---
        self.touched_files = set()

        # --- SEARCH CONTEXT TRACKER ---
        self._discovered_context: dict[str, str] = {}

        # --- SKILL STATE ---
        self.active_skill_name: str | None = None

    def _count_tokens(self, messages: list[Message]) -> int:
        """Local token counter using tiktoken if available."""
        if hasattr(self.memory, "_count_tokens"):
            return self.memory._count_tokens(messages)
        # Fallback: rough estimate (~4 chars per token)
        total = 0
        for m in messages:
            if m.content:
                total += len(m.content) // 4
            if m.tool_calls:
                for tc in m.tool_calls:
                    total += len(str(tc.arguments)) // 4
        return total

    def get_context_usage(self) -> dict:
        """
        Get context window usage based on the ACTUAL context that will be
        sent to the LLM (including injected system prompt sections).
        """
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

        # Color based on usage
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

        # Visual bar (30 chars wide)
        bar_width = 30
        filled = int((pct / 100) * bar_width)
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty

        def fmt(n: int) -> str:
            return f"{n/1000:.1f}K" if n >= 1000 else str(n)

        # Use Rich Text for proper color handling
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

        # Per-turn breakdown
        self.console.print(
            f"[dim]🪙 [bold cyan]In:[/bold cyan] {response.input_tokens:,} | "
            f"[bold magenta]Out:[/bold magenta] {response.output_tokens:,} | "
            f"[bold white]Session:[/bold white] {session_total:,}[/dim]"
        )
        self.console.print(f"[dim]{action_text}[/dim]")

    async def chat(self, user_input: str, max_iterations: int = 10) -> str | None:
        """
        Takes user input, runs the async agent loop, and returns the final text response.
        """
        # -- ADD USER INPUT -----------------------------------------------------
        self.memory.add_message(Message(role="user", content=user_input))

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
                final_response = await self.llm.acomplete(
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
            try:
                response = await self.llm.acomplete(
                    context,
                    tools=self.registry.schemas,
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

                self.console.print("[dim]⏳ Processing tool results...[/dim]")

    def _build_context(self) -> list[Message]:
        """
        Builds a fresh context list every turn.
        Injects LTM, search context, working directory, and active plan
        into a NEW system message without mutating the memory cache.
        """
        base_context = self.memory.get_context()

        if base_context and base_context[0].role == "system":
            system_content = base_context[0].content
            history = base_context[1:]
        else:
            system_content = "You are a helpful coding assistant."
            history = base_context

        sections = [system_content]

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