from abc import ABC, abstractmethod
from typing import Generator, Any, AsyncGenerator
from dataclasses import dataclass, field

class LLMResponseError(Exception):
    """Raised when an LLM provider returns a structurally valid HTTP response
    that cannot be parsed into an LLMResponse — e.g. choices is None, the
    message is missing, usage is missing, etc. Providers should raise it; the
    agent loop catches it (same as it catches network exceptions) and turns it
    into a recoverable `llm_error` audit event so the model can decide whether
    to retry, switch tactics, or surface the error."""

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str

@dataclass
class Message:
    role: str
    content: str | list
    name: str = None
    tool_call_id: str = None
    tool_calls: list[ToolCall] = field(default_factory=list)

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    stop_reason: str
    thinking: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def is_final(self) -> bool:
        return self.stop_reason in ("end_turn", "stop") and not self.tool_calls



class LLMProvider(ABC):
    """Base class for all LLMs."""

    def __init__(self, audit_callback=None):
        self.audit_callback = audit_callback

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        """Chat with the LLM."""
        ...

    @abstractmethod
    def stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> Generator[str, None, None]:
        """Stream the response from the LLM."""
        ...

    @abstractmethod
    async def async_complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        """Async version of complete """
        ...

    @abstractmethod
    async def async_stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> AsyncGenerator[str, None]:
        """Asynchronous stream from the LLM."""
        ...