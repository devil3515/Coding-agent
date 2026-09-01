import os
import json
from typing import Any, Generator, AsyncGenerator
from openai import OpenAI, AsyncOpenAI
from .base import LLMProvider, LLMResponse, LLMResponseError, Message, ToolCall
from src.audit.logger import AuditEvent

class OpenAIProvider(LLMProvider):
    """OpenAI Provider for coding agent."""

    def __init__(self, config: dict, audit_callback=None):
        super().__init__(audit_callback=audit_callback)
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
        """Turn the OpenAI chat-completions response object into LLMResponse.

        Defensive against malformed responses — some providers (notably
        OpenRouter free-tier and certain proxies) return HTTP 200 with a
        payload where `choices`, `choices[0].message`, `choices[0].message.tool_calls`,
        `choices[0].finish_reason`, or `usage` is None. We raise a typed
        LLMResponseError naming the offending field so the agent can feed the
        model a precise diagnostic instead of a raw TypeError."""
        choices = getattr(response, "choices", None)
        if not choices:
            raise LLMResponseError(
                "malformed OpenAI response: 'choices' is empty or None"
            )
        choice = choices[0]

        message = getattr(choice, "message", None)
        if message is None:
            raise LLMResponseError(
                "malformed OpenAI response: 'choices[0].message' is None"
            )

        tool_calls = []
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        for tc in raw_tool_calls:
            tool_calls.append(ToolCall(
                id = tc.id,
                name = tc.function.name,
                arguments = tc.function.arguments,
            ))

        stop_reason = getattr(choice, "finish_reason", None) or "unknown"
        if stop_reason == "tool_calls":
            stop_reason = "tool_use"
        elif stop_reason == "stop":
            stop_reason = "end_turn"

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return LLMResponse(
            content = getattr(message, "content", None),
            tool_calls = tool_calls,
            stop_reason = stop_reason,
            input_tokens = input_tokens,
            output_tokens = output_tokens,
        )

    def complete(self, messages: list[Message], tools: list[dict] = None, **kwargs: Any) -> LLMResponse:
        from datetime import datetime, timezone
        openai_messages = self._format_messages(messages)
        create_kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        if tools:
            create_kwargs["tools"] = tools

        # llm_request
        if self.audit_callback:
            try:
                self.audit_callback(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=None,
                    event_type="llm_request",
                    model=self.model,
                    metadata={"num_messages": len(openai_messages), "has_tools": bool(tools)},
                ))
            except Exception:
                pass

        try:
            response = self.client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            # llm_error
            if self.audit_callback:
                try:
                    self.audit_callback(AuditEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        session_id=None,
                        event_type="llm_error",
                        model=self.model,
                        result_summary=str(exc)[:500],
                        result_content=str(exc),
                    ))
                except Exception:
                    pass
            raise

        try:
            parsed = self._parse_response(response)
        except LLMResponseError as exc:
            # Malformed payload — surface as llm_error so the agent loop
            # can feed the model the precise diagnostic and decide whether
            # to retry, change tactics, or hand off to the user.
            if self.audit_callback:
                try:
                    self.audit_callback(AuditEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        session_id=None,
                        event_type="llm_error",
                        model=self.model,
                        result_summary=str(exc)[:500],
                        result_content=str(exc),
                    ))
                except Exception:
                    pass
            raise
        # llm_response — OpenAI emits NO thinking event.
        if self.audit_callback:
            try:
                self.audit_callback(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=None,
                    event_type="llm_response",
                    model=self.model,
                    input_tokens=parsed.input_tokens,
                    output_tokens=parsed.output_tokens,
                    metadata={"stop_reason": parsed.stop_reason, "has_tool_calls": bool(parsed.tool_calls)},
                ))
            except Exception:
                pass
        return parsed

    async def async_complete(self, messages: list[Message], tools: list[dict] = None, **kwargs: Any) -> LLMResponse:
        """Asynchronous completion."""
        from datetime import datetime, timezone
        openai_messages = self._format_messages(messages)
        create_kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        if tools:
            create_kwargs["tools"] = tools

        # llm_request
        if self.audit_callback:
            try:
                self.audit_callback(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=None,
                    event_type="llm_request",
                    model=self.model,
                    metadata={"num_messages": len(openai_messages), "has_tools": bool(tools)},
                ))
            except Exception:
                pass

        try:
            response = await self.async_client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            # llm_error
            if self.audit_callback:
                try:
                    self.audit_callback(AuditEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        session_id=None,
                        event_type="llm_error",
                        model=self.model,
                        result_summary=str(exc)[:500],
                        result_content=str(exc),
                    ))
                except Exception:
                    pass
            raise

        try:
            parsed = self._parse_response(response)
        except LLMResponseError as exc:
            # Malformed payload — mirror the HTTP-error branch above so the
            # audit log records the exact field that was None.
            if self.audit_callback:
                try:
                    self.audit_callback(AuditEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        session_id=None,
                        event_type="llm_error",
                        model=self.model,
                        result_summary=str(exc)[:500],
                        result_content=str(exc),
                    ))
                except Exception:
                    pass
            raise
        # llm_response — OpenAI emits NO thinking event.
        if self.audit_callback:
            try:
                self.audit_callback(AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    session_id=None,
                    event_type="llm_response",
                    model=self.model,
                    input_tokens=parsed.input_tokens,
                    output_tokens=parsed.output_tokens,
                    metadata={"stop_reason": parsed.stop_reason, "has_tool_calls": bool(parsed.tool_calls)},
                ))
            except Exception:
                pass
        return parsed


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