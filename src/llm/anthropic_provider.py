import os
from typing import Any, Generator
from anthropic import Anthropic
from .base import LLMProvider, LLMResponse, Message, ToolCall


class AnthropicProvider(LLMProvider):
    """Anthropic Provider for coding agent."""

    def __init__(self, config: dict):
        self.model = config.get("model", "claude-3-5-sonnet-20241022")
        api_key = config.get("api_key", os.getenv("ANTHROPIC_API_KEY"))
        self.client = Anthropic(
            api_key=api_key,
        )
        self.default_temperature = config.get("temperature", 0.7)
        self.default_max_tokens = config.get("max_tokens", 2048)

    def _format_messages(self, messages: list[Message]) -> list[dict]:
        """Translates internal Message dataclass → Anthropic dict format"""
        formatted = []
        for m in messages:
            msg_dict = {"role": m.role, "content": []}

            # Handle content
            if m.content is not None:
                if isinstance(m.content, str):
                    msg_dict["content"].append({"type": "text", "text": m.content})
                elif isinstance(m.content, list):
                    for item in m.content:
                        if isinstance(item, str):
                            msg_dict["content"].append({"type": "text", "text": item})
                        else:
                            msg_dict["content"].append(item)

            # Handle tool calls
            if m.tool_calls:
                for tc in m.tool_calls:
                    msg_dict["content"].append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })

            # Handle tool result
            if m.tool_call_id is not None:
                # For tool results, we need to format differently
                # Tool results are handled separately in the complete method
                continue

            formatted.append(msg_dict)
        return formatted

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Format tools for Anthropic"""
        formatted_tools = []
        for tool in tools:
            formatted_tools.append({
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "input_schema": tool["function"]["parameters"]
            })
        return formatted_tools

    def complete(self, messages: list[Message], tools: list[dict] = None, **kwargs: Any) -> LLMResponse:
        # Separate system messages from regular messages
        system_message = None
        formatted_messages = []

        for m in messages:
            if m.role == "system":
                system_message = m.content
            else:
                formatted_messages.append(m)

        # Format messages for Anthropic
        anthropic_messages = self._format_messages(formatted_messages)

        # Build API kwargs
        create_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": anthropic_messages,
            "temperature": kwargs.get("temperature", self.default_temperature),
            "max_tokens": kwargs.get("max_tokens", self.default_max_tokens),
            "system": system_message,
        }

        if tools:
            create_kwargs["tools"] = self._format_tools(tools)

        response = self.client.messages.create(**create_kwargs)

        # Parse response
        content = None
        tool_calls = []
        thinking = None

        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))
            elif block.type == "thinking":
                thinking = block.thinking

        # Determine stop reason
        stop_reason = response.stop_reason or "end_turn"
        if stop_reason == "tool_use":
            stop_reason = "tool_use"

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            thinking=thinking,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def stream(self, messages: list[Message], tools: list[dict] = None, **kwargs: Any) -> Generator[LLMResponse, None, None]:
        # Separate system messages from regular messages
        system_message = None
        formatted_messages = []

        for m in messages:
            if m.role == "system":
                system_message = m.content
            else:
                formatted_messages.append(m)

        anthropic_messages = self._format_messages(formatted_messages)

        create_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": anthropic_messages,
            "temperature": kwargs.get("temperature", self.default_temperature),
            "max_tokens": kwargs.get("max_tokens", self.default_max_tokens),
            "system": system_message,
        }

        if tools:
            create_kwargs["tools"] = self._format_tools(tools)

        with self.client.messages.stream(**create_kwargs) as stream:
            for text_delta in stream.text_stream:
                if text_delta:
                    yield LLMResponse(
                        content=text_delta,
                        tool_calls=[],
                        stop_reason="streaming",
                    )
