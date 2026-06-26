from abc import ABC, abstractmethod
from typing import Generator, Any
from dataclasses import dataclass, field

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

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        """Chat with the LLM."""
        ...

    @abstractmethod
    def stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> Generator[str, None, None]:
        """Stream the response from the LLM."""
        ...