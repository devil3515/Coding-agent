"""Tool registry with Pydantic validation and audit logging."""
import json
import time
from typing import Callable, Any, Optional
from pydantic import BaseModel, ValidationError

from audit.logger import AuditLogger


class ToolRegistry:
    """
    Registers tools, validates arguments with Pydantic, and logs every
    execution to an append-only audit trail.
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

    def execute(self, tool_name: str, arguments: dict) -> str:
        """Executes a tool by name with validation and audit logging."""
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."

        # ---- 1. PYDANTIC VALIDATION ----
        if tool_name in self.pydantic_schemas:
            try:
                validated = self.pydantic_schemas[tool_name](**arguments)
                arguments = validated.model_dump()
            except ValidationError as e:
                return f"Error: Invalid arguments for '{tool_name}': {e}"

        # ---- 2. EXECUTE WITH TIMING ----
        start_time = time.perf_counter()
        try:
            result = self.tools[tool_name](**arguments)
        except Exception as e:
            result = f"Error executing tool: {str(e)}"

        duration_ms = (time.perf_counter() - start_time) * 1000

        # ---- 3. AUDIT LOG ----
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