"""Structured audit logging for agent tool calls."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class AuditEvent:
    timestamp: str
    session_id: Optional[str]
    tool_name: str
    arguments: dict
    result_status: str
    result_summary: str
    duration_ms: float
    working_directory: Optional[str] = None


class AuditLogger:
    """Append-only structured audit logger. One JSONL file per day."""

    def __init__(self, log_dir: str = ".agent-audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.log_dir / f"audit-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

    def log(self, event: AuditEvent):
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), default=str) + "\n")

    def log_tool_call(
        self,
        session_id: Optional[str],
        tool_name: str,
        arguments: dict,
        result: str,
        duration_ms: float,
        working_directory: Optional[str] = None,
        blocked: bool = False,
    ):
        status = "blocked" if blocked else ("error" if result.startswith("Error") or result.startswith("⛔") else "success")
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            result_status=status,
            result_summary=result[:500],
            duration_ms=round(duration_ms, 2),
            working_directory=working_directory,
        )
        self.log(event)
