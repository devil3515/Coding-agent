"""Context compiler for assembling structured prompts."""

import logging
from typing import Any, Dict, List, Optional

from .redaction import redact_value
from .schemas import Checkpoint, ContextSections, SessionSummary, TaskState

logger = logging.getLogger(__name__)


class ContextCompiler:
    """
    Compiles context messages for the LLM using structured tagged sections.

    The compiler assembles various context sources into a prioritized list
    of chat messages with XML-tagged sections for clarity and parsing.
    """

    # Priority order for sections
    SECTION_PRIORITY = [
        "system_policy",
        "task",
        "plan",
        "checkpoint",
        "session_summary",
        "recent_turns",
    ]

    def __init__(
        self,
        system_prompt: str,
        max_recent_turns: int = 12,
        max_checkpoint_observation_chars: int = 2000,
    ):
        """
        Initialize the context compiler.

        Args:
            system_prompt: The base system policy/instructions.
            max_recent_turns: Maximum number of recent turns to include.
            max_checkpoint_observation_chars: Max chars for checkpoint observations.
        """
        self.system_prompt = system_prompt
        self.max_recent_turns = max_recent_turns
        self.max_checkpoint_observation_chars = max_checkpoint_observation_chars

    def compile(
        self,
        task: Optional[TaskState] = None,
        checkpoint: Optional[Checkpoint] = None,
        session_summary: Optional[SessionSummary] = None,
        recent_turns: Optional[List[Dict[str, Any]]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Compile context sections into a list of chat messages.

        Args:
            task: Current task state (optional).
            checkpoint: Latest checkpoint (optional).
            session_summary: Session summary (optional).
            recent_turns: Recent conversation turns (optional).
            extra: Extra context sections for future extension (optional).

        Returns:
            List of chat message dicts ready for LLM API.
        """
        sections = ContextSections(
            system_policy=self.system_prompt,
            task=self._format_task(task) if task else None,
            plan=self._format_plan(task) if task else None,
            checkpoint=self._format_checkpoint(checkpoint) if checkpoint else None,
            session_summary=self._format_session_summary(session_summary)
            if session_summary
            else None,
            recent_turns=self._limit_recent_turns(recent_turns or []),
            extra=extra,
        )

        return self._build_messages(sections)

    def _format_task(self, task: TaskState) -> str:
        """Format task state into a text section."""
        lines = [
            f"Goal: {task.goal}",
            f"Status: {task.status}",
        ]
        if task.repo:
            lines.append(f"Repository: {task.repo}")
        if task.current_hypothesis:
            lines.append(f"Current Hypothesis: {task.current_hypothesis}")
        if task.next_action:
            lines.append(f"Next Action: {task.next_action}")
        if task.completed_steps:
            lines.append("\nCompleted Steps:")
            for i, step in enumerate(task.completed_steps, 1):
                lines.append(f"  {i}. {step}")
        if task.failed_attempts:
            lines.append("\nFailed Attempts:")
            for i, attempt in enumerate(task.failed_attempts, 1):
                lines.append(f"  {i}. {attempt}")
        return "\n".join(lines)

    def _format_plan(self, task: TaskState) -> str:
        """Format plan from task state."""
        if not task.plan:
            return ""
        lines = ["Plan:"]
        for i, step in enumerate(task.plan, 1):
            status = "✓" if i <= len(task.completed_steps) else "○"
            lines.append(f"  {status} Step {i}: {step}")
        return "\n".join(lines)

    def _format_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Format checkpoint into a text section with redaction."""
        # Redact sensitive data first
        redacted_observation = checkpoint.last_observation
        if redacted_observation:
            # Truncate if too long
            if len(redacted_observation) > self.max_checkpoint_observation_chars:
                redacted_observation = (
                    redacted_observation[: self.max_checkpoint_observation_chars]
                    + "... [truncated]"
                )
            # Redact secrets
            redacted_observation = redact_value(redacted_observation)

        lines = [
            f"Step: {checkpoint.step}",
        ]
        if checkpoint.last_action:
            lines.append(f"Last Action: {checkpoint.last_action}")
        if redacted_observation:
            lines.append(f"Last Observation: {redacted_observation}")
        if checkpoint.next_action:
            lines.append(f"Next Action: {checkpoint.next_action}")
        if checkpoint.files_modified:
            lines.append(f"Files Modified: {', '.join(checkpoint.files_modified)}")
        return "\n".join(lines)

    def _format_session_summary(self, summary: SessionSummary) -> str:
        """Format session summary into a text section."""
        lines = [f"Summary: {summary.summary}"]
        if summary.important_decisions:
            lines.append("\nImportant Decisions:")
            for decision in summary.important_decisions:
                lines.append(f"  - {decision}")
        if summary.open_questions:
            lines.append("\nOpen Questions:")
            for question in summary.open_questions:
                lines.append(f"  - {question}")
        if summary.files_touched:
            lines.append(f"\nFiles Touched: {', '.join(summary.files_touched)}")
        return "\n".join(lines)

    def _limit_recent_turns(
        self, turns: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Limit recent turns to max count and redact sensitive data."""
        limited = turns[-self.max_recent_turns :] if len(turns) > self.max_recent_turns else turns
        # Redact each turn
        return [redact_value(turn) for turn in limited]

    def _build_messages(self, sections: ContextSections) -> List[Dict[str, Any]]:
        """Build the final message list from sections."""
        messages = []

        # System message with tagged sections
        system_parts = []

        # Always include system policy
        system_parts.append(f"<system_policy>\n{sections.system_policy}\n</system_policy>")

        # Add optional sections in priority order
        if sections.task:
            system_parts.append(f"<task>\n{sections.task}\n</task>")

        if sections.plan:
            system_parts.append(f"<plan>\n{sections.plan}\n</plan>")

        if sections.checkpoint:
            system_parts.append(f"<checkpoint>\n{sections.checkpoint}\n</checkpoint>")

        if sections.session_summary:
            system_parts.append(
                f"<session_summary>\n{sections.session_summary}\n</session_summary>"
            )

        # Combine system parts
        system_content = "\n\n".join(system_parts)
        messages.append({"role": "system", "content": system_content})

        # Add recent turns as user/assistant messages
        for turn in sections.recent_turns:
            # Ensure turn has required fields
            if isinstance(turn, dict) and "role" in turn:
                messages.append(turn)

        # Handle extra sections if present
        if sections.extra:
            logger.debug("Extra sections provided but not included in Sprint 1")

        return messages
