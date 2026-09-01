"""Tool registry with Pydantic validation, audit logging, and async support."""
import json
import time
import inspect
from datetime import datetime, timezone
from typing import Callable, Any, Optional
from pydantic import BaseModel, ValidationError

from src.audit.logger import AuditLogger, AuditEvent
from src.core.state import AgentPhase, PHASE_TOOL_ALLOWLIST


class ToolRegistry:
    """
    Registers tools, validates arguments with Pydantic, and logs every
    execution to an append-only audit trail. Supports both sync and async
    tool functions.
    """

    def __init__(
        self,
        audit_logger: Optional[AuditLogger] = None,
        session_id: Optional[str] = None,
        working_directory: Optional[str] = None,
    ):
        self.tools: dict[str, Callable] = {}
        self.schemas: list[dict] = []
        self.pydantic_schemas: dict[str, type[BaseModel]] = {}
        self.audit_logger = audit_logger
        self.session_id = session_id
        self.working_directory = working_directory
        # Per-call context the loop sets before each tool execution so emitted
        # events are correlated back to the LLM iteration that requested them.
        self.current_iteration: Optional[int] = None
        self.current_phase: Optional[str] = None

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        function: Callable,
        pydantic_schema: Optional[type[BaseModel]] = None,
    ):
        """Registers a tool and its OpenAI-compatible schema."""
        self.tools[name] = function
        self.schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        })
        if pydantic_schema:
            self.pydantic_schemas[name] = pydantic_schema

    def get_schemas_for_phase(self, phase: AgentPhase) -> list[dict]:
        """
        Return only the tool schemas allowed in the given phase.
        This restricts what the LLM can even SEE in its tool list,
        preventing it from calling disallowed tools at the API level.
        """
        allowed = PHASE_TOOL_ALLOWLIST.get(phase, [])
        return [s for s in self.schemas if s["function"]["name"] in allowed]

    def execute(self, tool_name: str, arguments: dict) -> str:
        """Synchronous tool execution with validation and audit logging."""
        if tool_name not in self.tools:
            result = f"Error: Tool '{tool_name}' not found."
            self._emit_blocked(tool_name, arguments, "not_found", result)
            return result

        if tool_name in self.pydantic_schemas:
            try:
                validated = self.pydantic_schemas[tool_name](**arguments)
                arguments = validated.model_dump()
            except ValidationError as e:
                result = f"Error: Invalid arguments for '{tool_name}': {e}"
                self._emit_blocked(tool_name, arguments, "validation_error", result)
                return result

        start_time = time.perf_counter()
        try:
            result = self.tools[tool_name](**arguments)
        except Exception as e:
            result = f"Error executing tool: {str(e)}"

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._emit_tool_call(tool_name, arguments, result, duration_ms)
        return str(result)

    async def aexecute(self, tool_name: str, arguments: dict) -> str:
        """Asynchronous tool execution with validation and audit logging.

        Automatically detects if the registered function returns an awaitable
        (coroutine) and awaits it; otherwise calls it synchronously.
        """
        if tool_name not in self.tools:
            result = f"Error: Tool '{tool_name}' not found."
            self._emit_blocked(tool_name, arguments, "not_found", result)
            return result

        if tool_name in self.pydantic_schemas:
            try:
                validated = self.pydantic_schemas[tool_name](**arguments)
                arguments = validated.model_dump()
            except ValidationError as e:
                result = f"Error: Invalid arguments for '{tool_name}': {e}"
                self._emit_blocked(tool_name, arguments, "validation_error", result)
                return result

        start_time = time.perf_counter()
        try:
            result = self.tools[tool_name](**arguments)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            result = f"Error executing tool: {str(e)}"

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._emit_tool_call(tool_name, arguments, result, duration_ms)
        return str(result)

    def _emit_tool_call(self, tool_name: str, arguments: dict, result, duration_ms: float) -> None:
        if not self.audit_logger:
            return
        is_error = isinstance(result, str) and (result.startswith("Error") or result.startswith("⛔"))
        self.audit_logger.event(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            event_type="tool_call",
            iteration=self.current_iteration,
            phase=self.current_phase,
            tool_name=tool_name,
            arguments=arguments,
            result_status="error" if is_error else "success",
            result_summary=str(result),
            result_content=str(result),
            duration_ms=round(duration_ms, 2),
            working_directory=self.working_directory,
        ))

    def _emit_blocked(self, tool_name: str, arguments: dict, reason: str, message: str) -> None:
        if not self.audit_logger:
            return
        self.audit_logger.event(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            event_type="tool_blocked",
            iteration=self.current_iteration,
            phase=self.current_phase,
            tool_name=tool_name,
            arguments=arguments,
            result_status="blocked",
            result_summary=message,
            result_content=message,
            working_directory=self.working_directory,
            metadata={"block_reason": reason},
        ))