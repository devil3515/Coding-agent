"""Structured audit logging for the unified agent event stream."""
import json
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional
from dataclasses import dataclass, field, asdict


class AuditEventType(str, Enum):
    TOOL_CALL = "tool_call"
    TOOL_BLOCKED = "tool_blocked"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    LLM_ERROR = "llm_error"
    LLM_THINKING = "llm_thinking"   # v2: Anthropic extended-thinking blocks
    USER_INPUT = "user_input"
    ASSISTANT_MESSAGE = "assistant_message"
    PHASE_TRANSITION = "phase_transition"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    HARNESS_NUDGE = "harness_nudge"
    KILL_SWITCH = "kill_switch"
    PLAN_STATE_CHANGE = "plan_state_change"
    VERIFICATION_REPORT = "verification_report"


@dataclass
class AuditEvent:
    """Unified audit event. All fields are optional except timestamp /
    session_id / event_type. Callers fill only the fields relevant to the
    event type — the rest stay None."""
    timestamp: str
    session_id: Optional[str]
    event_type: str
    iteration: Optional[int] = None
    phase: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[dict] = None
    result_status: Optional[str] = None
    result_summary: Optional[str] = None      # capped at 500 chars
    result_content: Optional[str] = None      # full payload
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[float] = None
    working_directory: Optional[str] = None
    metadata: dict = field(default_factory=dict)


from src.audit.store import AuditStore


class AuditLogger:
    """Append-only audit logger. Writes one JSON object per line to
    `.agent-audit/events-YYYYMMDD.jsonl`, and best-effort to a MongoDB
    collection. Failures never propagate and never print — they are
    recorded in the event's metadata as `file_persist_error` or
    `mongo_persist_error`."""

    JSONL_FILENAME = "events-{date}.jsonl"
    RESULT_SUMMARY_CAP = 500

    def __init__(
        self,
        log_dir: str = ".agent-audit",
        mongo_uri: Optional[str] = None,
        db_name: str = "coding_agent",
        collection: str = "audit_events",
        session_id: Optional[str] = None,
        working_directory: Optional[str] = None,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.working_directory = working_directory
        self._file = self.log_dir / self.JSONL_FILENAME.format(
            date=datetime.now(timezone.utc).strftime("%Y%m%d")
        )
        self._store: Optional[AuditStore] = None
        if mongo_uri:
            self._store = AuditStore(uri=mongo_uri, db_name=db_name, collection=collection)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def event(self, event: AuditEvent) -> None:
        """Single entry point for emitting an audit event. Never raises."""
        # Backfill session_id and working_directory if missing.
        if event.session_id is None:
            event.session_id = self.session_id
        if event.working_directory is None:
            event.working_directory = self.working_directory

        # Cap the result_summary at 500 chars (preserve full content separately).
        if event.result_summary and len(event.result_summary) > self.RESULT_SUMMARY_CAP:
            event.result_summary = event.result_summary[: self.RESULT_SUMMARY_CAP]

        # File write — failure is captured into metadata.
        try:
            self._write_jsonl(event)
        except Exception as exc:  # noqa: BLE001 — audit must never raise
            event.metadata["file_persist_error"] = repr(exc)

        # Mongo write — failure is captured into metadata. If the store
        # was never constructed (no mongo_uri) skip silently.
        if self._store is None:
            return
        try:
            self._store.write(event)
        except Exception as exc:  # noqa: BLE001
            event.metadata["mongo_persist_error"] = repr(exc)
            # Best-effort: also reflect the mongo failure into the file
            # so a later read can see it.
            try:
                self._write_jsonl(event)
            except Exception:
                pass

    @staticmethod
    def _read_legacy(path: Path) -> Iterator[AuditEvent]:
        """Yield AuditEvent objects from an old-format JSONL file
        (audit-YYYYMMDD.jsonl). Recognised by the presence of `tool_name`
        and absence of `event_type`."""
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "event_type" in obj:
                    # Already in the new schema — yield as-is.
                    yield AuditEvent(**{k: obj.get(k) for k in (
                        "timestamp", "session_id", "event_type", "iteration",
                        "phase", "tool_name", "arguments", "result_status",
                        "result_summary", "result_content", "model",
                        "input_tokens", "output_tokens", "duration_ms",
                        "working_directory",
                    ) if k in obj}, metadata=obj.get("metadata") or {})
                else:
                    # Legacy shape → tool_call.
                    yield AuditEvent(
                        timestamp=obj.get("timestamp"),
                        session_id=obj.get("session_id"),
                        event_type="tool_call",
                        tool_name=obj.get("tool_name"),
                        arguments=obj.get("arguments"),
                        result_status=obj.get("result_status"),
                        result_summary=obj.get("result_summary"),
                        duration_ms=obj.get("duration_ms"),
                        working_directory=obj.get("working_directory"),
                    )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _write_jsonl(self, event: AuditEvent) -> None:
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), default=str) + "\n")