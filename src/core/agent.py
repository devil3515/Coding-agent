"""Async core reasoning loop of the coding agent with phase-based state machine."""
import json
import re
import asyncio
from datetime import datetime, timezone
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
from src.verification.engine import VerificationEngine
from src.tools.scratchpad import get_scratchpad_summary
from src.audit.logger import AuditEvent

# Tools whose execution counts as a "read" for the read-budget gate.
# Writes, plan tools, user questions, and version-control commands do not.
READ_ONLY_TOOLS = frozenset({
    "read_file",
    "search_codebase",
    "get_codebase_overview",
    "get_file_tree",
    "find_files",
    "read_scratchpad",
})

# Shell commands that contain output redirection or pipes to write files
# are treated as writes for the purposes of the read budget. We still rely
# on is_shell_safe to actually block destructive commands.
_SHELL_REDIRECT_TOKENS = (">", ">>", "| tee", ">&", "2>")

# Matches "(File: <path>, Line: <n>)" lines emitted by search_codebase.
_SEARCH_FILE_RE = re.compile(r"\(File:\s*([^,)]+),")


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
        harness: dict = None,
        audit_logger=None,  # NEW
    ):
        self.llm = llm
        self.registry = registry
        self.memory = memory
        self.console = console
        self.ltm = ltm
        self.llm_config = llm_config or {}
        self.working_directory = working_directory
        self.session_id = session_id

        # --- HARNESS CONFIG ---
        # Working-memory + read-budget pacing. Fall back to the same defaults
        # as src/config/settings.py if the section is absent.
        defaults = {
            "read_budget": 5,
            "scratchpad_inject_tokens": 800,
            "scratchpad_max_chars": 20000,
        }
        self.harness = {**defaults, **(harness or {})}
        self.audit_logger = audit_logger

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

        # --- READ-BUDGET TRACKER (reset at the start of every chat() call) ---
        self._read_only_calls_this_turn: int = 0
        self._files_read_this_turn: list[str] = []
        self._scratchpad_updated_this_turn: bool = False
        self._nudge_injected_this_turn: bool = False

        # --- VERIFICATION ENGINE ---
        self.verification = VerificationEngine(
            registry=registry,
            working_directory=working_directory or ".",
            console=console,
        )

    # ------------------------------------------------------------------ #
    # Read-budget classification
    # ------------------------------------------------------------------ #
    def _is_shell_read_only(self, command: str) -> bool:
        """Heuristic: a shell command counts as a read unless it redirects output."""
        if not command:
            return False
        return not any(tok in command for tok in _SHELL_REDIRECT_TOKENS)

    def _classify_tool_call(self, tool_name: str, args: dict) -> str:
        """Return 'read', 'write', or 'neutral' for the given tool call."""
        if tool_name == "update_scratchpad":
            return "scratchpad"
        if tool_name in ("write_file", "apply_diff"):
            return "write"
        if tool_name in (
            "create_project_plan",
            "update_plan_status",
            "update_plan_text",
            "ask_user_question",
            "run_git",
        ):
            return "neutral"
        if tool_name in READ_ONLY_TOOLS:
            return "read"
        if tool_name == "run_shell_command":
            cmd = (args or {}).get("command", "")
            return "read" if self._is_shell_read_only(cmd) else "neutral"
        return "neutral"

    def _reset_turn_trackers(self):
        """Reset per-turn counters. Called at the start of every chat() invocation."""
        self._read_only_calls_this_turn = 0
        self._files_read_this_turn = []
        self._scratchpad_updated_this_turn = False
        self._nudge_injected_this_turn = False
        # Agentic retry budget for malformed LLM responses: one fresh retry
        # per chat() turn so a consistently broken provider can't pin the
        # agent in an infinite loop.
        self._llm_error_retries = 0

    def _emit(self, event: AuditEvent) -> None:
        if self.audit_logger is None:
            return
        try:
            self.audit_logger.event(event)
        except Exception:
            # Audit must never break the loop; quiet by design.
            pass

    def _maybe_inject_nudge(self):
        """Inject a one-time nudge asking the LLM to update the scratchpad.

        Fires at most once per turn, only when the read budget is exhausted
        and the LLM has not yet called update_scratchpad.
        """
        if self._nudge_injected_this_turn:
            return
        if self._scratchpad_updated_this_turn:
            return
        budget = int(self.harness.get("read_budget", 5) or 5)
        if self._read_only_calls_this_turn < budget:
            return

        nudge = (
            f"[Harness Nudge] You have made {self._read_only_calls_this_turn} "
            f"read-only tool calls this turn without updating your scratchpad. "
            f"Before reading more, call update_scratchpad to record: "
            f"(1) your current hypothesis, "
            f"(2) any files you have already eliminated, and "
            f"(3) what you plan to read next and why."
        )
        self.memory.add_message(Message(role="user", content=nudge))
        self._emit(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            event_type="harness_nudge",
            working_directory=self.working_directory,
            metadata={"reads_this_turn": self._read_only_calls_this_turn, "budget": budget},
        ))
        self.console.print(
            f"[bold yellow]🟡 Harness nudge: {self._read_only_calls_this_turn} "
            f"reads without a scratchpad update — asking the agent to commit "
            f"to a hypothesis.[/bold yellow]"
        )
        self._nudge_injected_this_turn = True

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

    async def _transition_phase(self, new_phase: AgentPhase):
        """Transition to a new phase and notify the user."""
        if self.phase == new_phase:
            return
        old_phase = self.phase
        self.phase = new_phase
        banner = format_phase_banner(new_phase)
        self.console.print(f"[bold cyan]🔄 Phase transition: {old_phase.value.upper()} → {new_phase.value.upper()}[/bold cyan]")
        self._emit(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            event_type="phase_transition",
            phase=new_phase.value,
            working_directory=self.working_directory,
            metadata={"from": old_phase.value, "to": new_phase.value},
        ))
        self.console.print(f"[dim]{banner}[/dim]")

        # On transition to VERIFYING, auto-inject verification instructions
        if new_phase == AgentPhase.VERIFYING:
            self.console.print("[bold cyan]🔬 Phase 2 Self-Verification: Running full test suite...[/bold cyan]")
            reports = await self.verification.run_full_verification()
            for report in reports:
                self.memory.add_message(Message(
                    role="user",
                    content=f"[Full Verification Report]:\n{self.verification.format_report_for_llm(report)}"
                ))
                self._emit(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=self.session_id,
                    event_type="verification_report",
                    phase=new_phase.value,
                    working_directory=self.working_directory,
                    result_status="success" if report.overall_pass else "error",
                    result_summary="passed" if report.overall_pass else "failed",
                    result_content=self.verification.format_report_for_llm(report),
                    metadata={"scope": "full"},
                ))

            verify_msg = (
                "All planned steps are complete. Full verification results are above. "
                "Please review any failures, fix issues if needed, and use update_plan_status "
                "to mark verification as complete when satisfied."
            )
            self.memory.add_message(Message(role="user", content=verify_msg))
            self.console.print("[dim]📝 Auto-injected full verification results into context.[/dim]")

    async def _check_phase_transition(self):
        """Check if we should auto-transition based on plan state."""
        new_phase = PhaseTransition.check_transition(
            self.phase, self.current_plan, self._pending_verification
        )
        if new_phase:
            await self._transition_phase(new_phase)

    async def _auto_verify(self, file_path: str):
        """Auto-verify a file by reading it back after write/diff."""
        report = await self.verification.verify_file(file_path)

        self.memory.add_message(Message(
            role="user",
            content=f"[Auto-Verification Report for {file_path}]:\n{self.verification.format_report_for_llm(report)}"
        ))
        self._emit(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            event_type="verification_report",
            working_directory=self.working_directory,
            result_status="success" if report.overall_pass else "error",
            result_summary="passed" if report.overall_pass else "failed",
            result_content=self.verification.format_report_for_llm(report),
            metadata={"file": file_path},
        ))

        if not report.overall_pass:
            self.console.print(f"[bold red]❌ Verification failed for {file_path}. Details injected into context.[/bold red]")
        else:
            self.console.print(f"[bold green]✅ Verification passed for {file_path}[/bold green]")

        if file_path in self._pending_verification:
            self._pending_verification.remove(file_path)

    async def chat(self, user_input: str, max_iterations: int = 10) -> str | None:
        """
        Takes user input, runs the async agent loop with phase enforcement,
        and returns the final text response.
        """
        # -- RESET PER-TURN DEBUG-HARNESS TRACKERS -----------------------------
        self._reset_turn_trackers()

        # -- SESSION_START (first turn of a chat() call only) --
        self._emit(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            event_type="session_start",
            working_directory=self.working_directory,
            metadata={"input_preview": user_input[:200]},
        ))

        # -- ADD USER INPUT -----------------------------------------------------
        self.memory.add_message(Message(role="user", content=user_input))
        self._emit(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            event_type="user_input",
            working_directory=self.working_directory,
            result_content=user_input,
            result_summary=user_input[:500],
        ))

        # Reset phase for new task if we're in COMPLETED
        if self.phase == AgentPhase.COMPLETED:
            await self._transition_phase(AgentPhase.IDLE)
            self.current_plan = []
            self._pending_verification = []

        iteration_count = 0

        while True:
            iteration_count += 1
            # Update the registry's per-call context so emitted events are
            # correlated with this iteration.
            self.registry.current_iteration = iteration_count
            self.registry.current_phase = self.phase.value

            # -- KILL SWITCH ----------------------------------------------------
            if iteration_count >= max_iterations:
                self.console.print("[bold red]⚠️ Max iterations reached. Forcing final response.[/bold red]")
                self._emit(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=self.session_id,
                    event_type="kill_switch",
                    iteration=iteration_count,
                    phase=self.phase.value,
                    working_directory=self.working_directory,
                    metadata={"max_iterations": max_iterations},
                ))
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
                self._emit(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=self.session_id,
                    event_type="assistant_message",
                    iteration=iteration_count,
                    phase=self.phase.value,
                    working_directory=self.working_directory,
                    result_content=final_response.content,
                    result_summary=(final_response.content or "")[:500],
                    model=getattr(self.llm, "model", None),
                    input_tokens=final_response.input_tokens,
                    output_tokens=final_response.output_tokens,
                ))
                self._emit(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=self.session_id,
                    event_type="session_end",
                    iteration=iteration_count,
                    phase=self.phase.value,
                    working_directory=self.working_directory,
                    metadata={"exit_reason": "kill_switch"},
                ))
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
                self._emit(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=self.session_id,
                    event_type="llm_error",
                    iteration=iteration_count,
                    phase=self.phase.value,
                    working_directory=self.working_directory,
                    model=getattr(self.llm, "model", None),
                    result_summary=str(api_err)[:500],
                    result_content=str(api_err),
                ))
                err_str = str(api_err)
                # Some providers (notably GMICloud / 400) reject a turn when the
                # model's tool_call.id doesn't match a tool the provider knows
                # about. This is recoverable: drop the broken turn, re-prompt
                # with a hint to use a clean final answer, and continue.
                if "tool id" in err_str.lower() and "not found" in err_str.lower():
                    self.console.print(
                        f"[bold yellow]⚠️ Provider rejected a stale tool id "
                        f"(iteration {iteration_count}). Re-prompting with a "
                        f"clean final-answer request.[/bold yellow]"
                    )
                    self.memory.add_message(Message(
                        role="user",
                        content=(
                            "Your previous tool call was rejected by the provider "
                            "(stale tool id). Please respond with a final text "
                            "answer based on what you already know, or call a "
                            "single new tool with a fresh id."
                        ),
                    ))
                    # Force the loop to rebuild context and call the LLM again.
                    continue
                # Malformed LLM response (e.g. OpenRouter free-tier returns
                # HTTP 200 but `choices` is None, or `usage` is missing). This
                # is transient infrastructure flakiness, not a model mistake —
                # surface the exact field that was None so the model can
                # either retry the same request or pivot to a different
                # strategy. Cap to one retry per turn to avoid an infinite
                # loop when a provider is consistently broken; if the
                # retry also fails we fall through to the generic return
                # below.
                if "malformed" in err_str.lower() and getattr(self, "_llm_error_retries", 0) < 1:
                    self._llm_error_retries = getattr(self, "_llm_error_retries", 0) + 1
                    self.console.print(
                        f"[bold yellow]⚠️ Malformed LLM response "
                        f"(iteration {iteration_count}): {err_str}. "
                        f"Sleeping 1.5s before re-prompting.[/bold yellow]"
                    )
                    # OpenRouter free-tier 200-with-bad-body is often a
                    # sub-second provider hiccup; a tiny backoff makes the
                    # retry land on a healthy request slot more often than not.
                    await asyncio.sleep(1.5)
                    self.memory.add_message(Message(
                        role="user",
                        content=(
                            f"The LLM provider returned a malformed response "
                            f"on your previous turn: {err_str}. "
                            f"Please try again — either repeat your last "
                            f"action with a slightly different phrasing, or "
                            f"pivot to a different tool / approach."
                        ),
                    ))
                    continue
                self.console.print(f"[bold red]⚠️ LLM API error (iteration {iteration_count}): {api_err}[/bold red]")
                self.memory.add_message(Message(role="assistant", content=f"[API error: {api_err}]"))
                return f"The LLM API returned an error: {api_err}"

            if response.is_final:
                self._print_token_usage(response, "✅ Final response generated.")
                self.memory.add_message(Message(role="assistant", content=response.content))
                self._emit(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=self.session_id,
                    event_type="assistant_message",
                    iteration=iteration_count,
                    phase=self.phase.value,
                    working_directory=self.working_directory,
                    result_content=response.content,
                    result_summary=(response.content or "")[:500],
                    model=getattr(self.llm, "model", None),
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                ))
                self._emit(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=self.session_id,
                    event_type="session_end",
                    iteration=iteration_count,
                    phase=self.phase.value,
                    working_directory=self.working_directory,
                    metadata={"exit_reason": "is_final"},
                ))
                return response.content

            else:
                if not response.tool_calls:
                    self._print_token_usage(response, "⚠️ Response cut off (hit max_tokens limit).")
                    content = response.content or "[Response truncated]"
                    self.memory.add_message(Message(role="assistant", content=content))
                    self._emit(AuditEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        session_id=self.session_id,
                        event_type="assistant_message",
                        iteration=iteration_count,
                        phase=self.phase.value,
                        working_directory=self.working_directory,
                        result_content=content,
                        result_summary=content[:500],
                        model=getattr(self.llm, "model", None),
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        metadata={"exit_reason": "cut_off"},
                    ))
                    self._emit(AuditEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        session_id=self.session_id,
                        event_type="session_end",
                        iteration=iteration_count,
                        phase=self.phase.value,
                        working_directory=self.working_directory,
                        metadata={"exit_reason": "cut_off"},
                    ))
                    return content

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
                    # 0a. HARNESS TRACKING (pre-execution)
                    # ==========================================
                    # Update the per-turn read budget, file list, and scratchpad
                    # flag based on the call we are about to make. We do this
                    # before the phase check so blocked calls don't pollute the
                    # counters — but we do it after parsing args.
                    classification = self._classify_tool_call(tool_call.name, args)
                    if classification == "read":
                        self._read_only_calls_this_turn += 1
                        if tool_call.name == "read_file":
                            fp = args.get("file_path")
                            if fp and fp not in self._files_read_this_turn:
                                self._files_read_this_turn.append(fp)
                    elif classification == "scratchpad":
                        self._scratchpad_updated_this_turn = True

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
                        self._emit(AuditEvent(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            session_id=self.session_id,
                            event_type="tool_blocked",
                            iteration=iteration_count,
                            phase=self.phase.value,
                            tool_name=tool_call.name,
                            arguments=args,
                            result_status="blocked",
                            result_summary=result,
                            result_content=result,
                            working_directory=self.working_directory,
                            metadata={"block_reason": "phase_disallowed", "allowed_tools": list(allowed)},
                        ))
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
                        self._emit(AuditEvent(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            session_id=self.session_id,
                            event_type="tool_blocked",
                            iteration=iteration_count,
                            phase=self.phase.value,
                            tool_name=tool_call.name,
                            arguments=args,
                            result_status="blocked",
                            result_summary=block_reason,
                            result_content=block_reason,
                            working_directory=self.working_directory,
                            metadata={"block_reason": "security"},
                        ))

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
                        await self._transition_phase(AgentPhase.PLANNING)
                        # Auto-mark first step as in_progress
                        if self.current_plan:
                            self.current_plan[0]["status"] = "in_progress"
                            await self._check_phase_transition()
                            self._emit(AuditEvent(
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                session_id=self.session_id,
                                event_type="plan_state_change",
                                iteration=iteration_count,
                                phase=self.phase.value,
                                working_directory=self.working_directory,
                                metadata={"change": "create", "step_count": len(self.current_plan)},
                            ))

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
                                await self._check_phase_transition()
                                self._emit(AuditEvent(
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    session_id=self.session_id,
                                    event_type="plan_state_change",
                                    iteration=iteration_count,
                                    phase=self.phase.value,
                                    working_directory=self.working_directory,
                                    metadata={"change": "status", "step": step_num, "status": status},
                                ))
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
                            # Capture file paths the search touched so we can
                            # tell the LLM "you've already searched these".
                            for match in _SEARCH_FILE_RE.finditer(result):
                                fp = match.group(1).strip()
                                if fp and fp not in self._files_read_this_turn:
                                    self._files_read_this_turn.append(fp)

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

                # -- HARNESS NUDGE (after every iteration, at most once) -------
                self._maybe_inject_nudge()

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
            # Drop the kw: copies we keep for internal indexing. They are
            # silent — we only show the original query → summary mapping.
            # Cap at 25 to keep the prompt bounded.
            visible_items = [
                (k, v) for k, v in self._discovered_context.items()
                if not k.startswith("kw:")
            ][:25]

            if visible_items:
                search_lines = [
                    "\n" + "=" * 60,
                    "🔍 PREVIOUSLY DISCOVERED CONTEXT",
                    "[CRITICAL — DO NOT RE-SEARCH THESE. The harness has injected "
                    "the results into your context. Reading or searching them again "
                    "wastes iterations.]",
                    "=" * 60,
                ]
                for query, summary in visible_items:
                    search_lines.append(f"• '{query}': {summary}")
                sections.append("\n".join(search_lines))

        if self._files_read_this_turn:
            files_list = ", ".join(self._files_read_this_turn)
            sections.append(
                f"[FILES ALREADY READ THIS TURN]: {files_list}\n"
                f"[You do not need to read them again — the contents are in your "
                f"context above or in the scratchpad below.]"
            )

        # Scratchpad auto-injection. Read the file fresh every turn because
        # the LLM may have updated it since _build_context was last called.
        try:
            scratchpad_max_chars = int(self.harness.get("scratchpad_inject_tokens", 800) or 800) * 4
        except (TypeError, ValueError):
            scratchpad_max_chars = 3200
        scratchpad = get_scratchpad_summary(
            self.working_directory or ".",
            max_chars=scratchpad_max_chars,
        )
        if scratchpad.get("exists") and scratchpad.get("content", "").strip():
            header_parts = ["=" * 60, "📝 SCRATCHPAD"]
            if scratchpad.get("modified_at"):
                header_parts.append(
                    f"last updated {scratchpad['modified_at']}, "
                    f"{scratchpad.get('line_count', 0)} lines "
                    f"(~{scratchpad.get('char_count', 0) // 4} tokens)"
                )
            header_parts.append("=" * 60)
            body = scratchpad["content"]
            if scratchpad.get("truncated"):
                body += "\n[truncated to fit, call read_scratchpad for full]"
            else:
                body += "\n[End of scratchpad. Call read_scratchpad to see the full content.]"
            sections.append("\n".join(header_parts) + "\n" + body)
        else:
            sections.append(
                "=" * 60 + "\n📝 SCRATCHPAD — empty.\n"
                "[No scratchpad yet. Call update_scratchpad to start one. It is "
                "your working memory across turns.]\n" + "=" * 60
            )

        if self.working_directory:
            sections.append(
                f"[SYSTEM NOTE]: You are currently operating in the directory: {self.working_directory}. "
                f"You MUST use relative paths from this directory (e.g., 'src/main.py'). "
                f"NEVER use absolute paths like /Users/name/... unless explicitly asked."
            )

        if self.current_plan:
            active_idx = next(
                (i for i, s in enumerate(self.current_plan) if s.get("status") == "in_progress"),
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