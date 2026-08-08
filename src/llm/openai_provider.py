import os
import json
from typing import Any, Generator, AsyncGenerator
from openai import OpenAI, AsyncOpenAI
from .base import LLMProvider, LLMResponse, Message, ToolCall

class OpenAIProvider(LLMProvider):
    """OpenAI Provider for coding agent."""

    def __init__(self, config: dict):
        self.model = config.get("model", "gpt-4o-mini")
        api_key = config.get("api_key", os.getenv("OPENAI_API_KEY"))
        base_url = config.get("base_url")

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.async_client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    def _format_messages(self, messages: list[Message]) -> list[dict]:
        """Translates internal Message dataclass → OpenAI dict format"""
        formatted = []
        for m in messages:
            msg_dict = {"role": m.role}

            if m.content is not None:
                msg_dict["content"] = m.content

            if m.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)
                        }
                    }
                    for tc in m.tool_calls
                ]

            if m.tool_call_id is not None:
                msg_dict["tool_call_id"] = m.tool_call_id
                if "content" not in msg_dict:
                    msg_dict["content"] = ""

            formatted.append(msg_dict)
        return formatted

    def _parse_response(self, response) -> LLMResponse:
        choice = response.choices[0]

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    id = tc.id,
                    name = tc.function.name,
                    arguments = tc.function.arguments,
                ))

        stop_reason = choice.finish_reason
        if stop_reason == "tool_calls":
            stop_reason = "tool_use"
        elif stop_reason == "stop":
            stop_reason = "end_turn"

        return LLMResponse(
            content = choice.message.content,
            tool_calls = tool_calls,
            stop_reason = stop_reason,
            input_tokens = response.usage.prompt_tokens,
            output_tokens = response.usage.completion_tokens,
        )

    def complete(self, messages: list[Message], tools: list[dict] = None, **kwargs: Any) -> LLMResponse:
        openai_messages = self._format_messages(messages)

        create_kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        if tools:
            create_kwargs["tools"] = tools

        response = self.client.chat.completions.create(**create_kwargs)
        return self._parse_response(response)

    async def async_complete(self, messages: list[Message], tools: list[dict] = None, **kwargs: Any) -> LLMResponse:
        """Asynchronous completion."""
        openai_messages = self._format_messages(messages)
        create_kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        if tools:
            create_kwargs["tools"] = tools

        response = await self.async_client.chat.completions.create(**create_kwargs)
        return self._parse_response(response)


    def stream(self, messages: list[Message], **kwargs: Any) -> Generator[LLMResponse, None, None]:
        openai_messages = self._format_messages(messages)
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


    async def async_stream(self, messages: list[Message], **kwargs: Any) -> AsyncGenerator[str, None]:
        """Asynchronous stream."""
        openai_messages = self._format_messages(messages)
        stream = await self.async_client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content