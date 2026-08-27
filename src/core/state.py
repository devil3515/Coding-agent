"""Agent state machine for phase-based plan enforcement."""
from enum import Enum, auto
from typing import Optional


class AgentPhase(Enum):
    """
    The agent operates in distinct phases. Each phase restricts which
    tools are available, preventing the LLM from freestyling outside
    the intended workflow.
    """
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    RETRYING = "retrying"


# Tools allowed in each phase.
# If a tool is NOT listed here for the current phase, the harness blocks it.
PHASE_TOOL_ALLOWLIST: dict[AgentPhase, list[str]] = {
    AgentPhase.IDLE: [
        "read_file",
        "get_codebase_overview",
        "get_file_tree",
        "search_codebase",
        "create_project_plan",
        "ask_user_question",
        "run_shell_command",
        "run_git",
        "find_files",
        "update_scratchpad",
        "read_scratchpad",
    ],
    AgentPhase.PLANNING: [
        "read_file",
        "get_codebase_overview",
        "get_file_tree",
        "search_codebase",
        "create_project_plan",
        "update_plan_text",
        "ask_user_question",
        "find_files",
        "update_scratchpad",
        "read_scratchpad",
    ],
    AgentPhase.EXECUTING: [
        "read_file",
        "write_file",
        "apply_diff",
        "run_shell_command",
        "run_git",
        "update_plan_status",
        "update_plan_text",
        "ask_user_question",
        "find_files",
        "update_scratchpad",
        "read_scratchpad",
    ],
    AgentPhase.VERIFYING: [
        "read_file",
        "run_shell_command",
        "run_git",
        "update_plan_status",
        "ask_user_question",
        "find_files",
        "update_scratchpad",
        "read_scratchpad",
    ],
    AgentPhase.COMPLETED: [
        "ask_user_question",
        "read_scratchpad",
    ],
    AgentPhase.RETRYING: [
        "read_file",
        "write_file",
        "apply_diff",
        "run_shell_command",
        "run_git",
        "update_plan_status",
        "update_plan_text",
        "ask_user_question",
        "find_files",
        "update_scratchpad",
        "read_scratchpad",
    ],
}


def is_tool_allowed(phase: AgentPhase, tool_name: str) -> bool:
    """Check if a tool is permitted in the given phase."""
    allowed = PHASE_TOOL_ALLOWLIST.get(phase, [])
    return tool_name in allowed


def get_allowed_tools(phase: AgentPhase) -> list[str]:
    """Return the list of tools allowed in the given phase."""
    return PHASE_TOOL_ALLOWLIST.get(phase, [])


class PhaseTransition:
    """
    Tracks when the agent should auto-transition between phases.
    Called after plan updates to check if all steps hit a target status.
    """

    @staticmethod
    def check_transition(
        current_phase: AgentPhase,
        plan: list[dict],
        pending_verification: list[str],
    ) -> Optional[AgentPhase]:
        """
        Determine if the agent should transition to a new phase.
        Returns the new phase or None if no transition needed.
        """
        if not plan:
            return None

        # PLANNING → EXECUTING: first step becomes in_progress
        if current_phase == AgentPhase.PLANNING:
            if any(s.get("status") == "in_progress" for s in plan):
                return AgentPhase.EXECUTING

        # EXECUTING → VERIFYING: all steps completed or failed
        if current_phase == AgentPhase.EXECUTING:
            if all(s.get("status") in ("completed", "failed") for s in plan):
                return AgentPhase.VERIFYING

        # VERIFYING → RETRYING: any step failed and needs rework (Phase 2)
        if current_phase == AgentPhase.VERIFYING:
            if any(s.get("status") == "failed" for s in plan):
                return AgentPhase.RETRYING

        # VERIFYING → COMPLETED: verification passed (no pending files)
        if current_phase == AgentPhase.VERIFYING:
            if not pending_verification:
                # Also check if user explicitly marked verification done
                # or if we auto-verified everything
                if all(s.get("status") == "completed" for s in plan):
                    return AgentPhase.COMPLETED

        # RETRYING → EXECUTING: user or harness decides to retry
        if current_phase == AgentPhase.RETRYING:
            if any(s.get("status") == "in_progress" for s in plan):
                return AgentPhase.EXECUTING

        return None


def format_phase_banner(phase: AgentPhase) -> str:
    """Return a human-readable banner for the current phase."""
    banners = {
        AgentPhase.IDLE: "🟡 IDLE — Waiting for task",
        AgentPhase.PLANNING: "🔵 PLANNING — Read/search only. No writes allowed.",
        AgentPhase.EXECUTING: "🟢 EXECUTING — Write, edit, and run commands.",
        AgentPhase.VERIFYING: "🟣 VERIFYING — Confirm changes, run tests.",
        AgentPhase.COMPLETED: "✅ COMPLETED — Task finished.",
        AgentPhase.RETRYING: "🔁 RETRYING — Re-attempting failed steps.",
    }
    return banners.get(phase, f"Unknown phase: {phase.value}")