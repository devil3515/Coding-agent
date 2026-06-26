from src.memory.base import BaseMemory
from src.llm.base import Message
import tiktoken

class ShortTermMemory(BaseMemory):
    """Fast, in-memory sliding window. No database required."""

    def __init__(self, system_prompt: str, max_tokens: int = 8000, model: str = "gpt-4o",):
        self.system_prompt = Message(role="system", content=system_prompt)
        self.history: list[Message] = []
        self.max_tokens = max_tokens

        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, messages: list[Message]) -> int:
        token_count = 0
        for m in messages:
            token_count +=3
            if m.content:
                token_count += len(self.encoding.encode(m.content))
            if m.tool_calls:
                for tc in m.tool_calls:
                    token_count += len(self.encoding.encode(tc.name))
                    token_count += len(self.encoding.encode(str(tc.arguments)))
            if m.tool_call_id:
                token_count += len(self.encoding.encode(m.tool_call_id))
        return token_count


    def add_message(self, message: Message):
        self.history.append(message)
        self._enforce_token_limit()

    def _enforce_token_limit(self):
        while True:
            totl_tokens = self._count_tokens(self.history)
            if totl_tokens <= self.max_tokens:
                break

            if len(self.history) <= 1:
                print(f"[Warning] Single message exceeds token limit.")
                break

            drop_index = -1
            for i,msg in enumerate(self.history):
                is_safe_to_drop = (
                    msg.role != "tool" or
                    msg.role != "system" and
                    not (i+1 < len(self.history) and self.history[i+1].role == "tool")
                )
                if is_safe_to_drop:
                    drop_index = i
                    break

            if drop_index != -1:
                self.history.pop(drop_index)
            else:
                self.history.pop(0)


    def get_context(self) -> list[Message]:
        return [self.system_prompt] + self.history