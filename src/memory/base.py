from abc import ABC, abstractmethod
from src.llm.base import Message

class BaseMemory(ABC):
    """
    Abstract base for all memory systems.
    The Agent doesn't care if memory is in RAM, MongoDB, or Redis.
    It only knows it can add messages and get the current context.
    """
    @abstractmethod
    def add_message(self, message: Message):
        """Store a message."""
        ...

    @abstractmethod
    def get_context(self) -> list[Message]:
        """Retrieve the system prompt + relevant history."""
        ...