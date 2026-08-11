"""Tool registry with Pydantic validation, audit logging, and async support."""
import json
import time
import inspect
from typing import Callable, Any, Optional
from pydantic import BaseModel, ValidationError

from src.audit.logger import AuditLogger
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
            return f"Error: Tool '{tool_name}' not found."

        if tool_name in self.pydantic_schemas:
            try:
                validated = self.pydantic_schemas[tool_name](**arguments)
                arguments = validated.model_dump()
            except ValidationError as e:
                return f"Error: Invalid arguments for '{tool_name}': {e}"

        start_time = time.perf_counter()
        try:
            result = self.tools[tool_name](**arguments)
        except Exception as e:
            result = f"Error executing tool: {str(e)}"

        duration_ms = (time.perf_counter() - start_time) * 1000

        if self.audit_logger:
            self.audit_logger.log_tool_call(
                session_id=self.session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                duration_ms=duration_ms,
                working_directory=self.working_directory,
            )

        return str(result)

    async def aexecute(self, tool_name: str, arguments: dict) -> str:
        """Asynchronous tool execution with validation and audit logging.

        Automatically detects if the registered function returns an awaitable
        (coroutine) and awaits it; otherwise calls it synchronously.
        """
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."

        if tool_name in self.pydantic_schemas:
            try:
                validated = self.pydantic_schemas[tool_name](**arguments)
                arguments = validated.model_dump()
            except ValidationError as e:
                return f"Error: Invalid arguments for '{tool_name}': {e}"

        start_time = time.perf_counter()
        try:
            result = self.tools[tool_name](**arguments)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            result = f"Error executing tool: {str(e)}"

        duration_ms = (time.perf_counter() - start_time) * 1000

        if self.audit_logger:
            self.audit_logger.log_tool_call(
                session_id=self.session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                duration_ms=duration_ms,
                working_directory=self.working_directory,
            )

        return str(result)