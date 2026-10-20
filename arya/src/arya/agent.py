import uuid
from collections.abc import Iterator

import mlflow
from mlflow.entities import SpanType
from openai import OpenAI

from arya.config import settings
from arya.prompts.system import SYSTEM_PROMPT
from arya.tools import execute, schemas


class ToolCall:
    def __init__(self, index: int) -> None:
        self.index = index
        self.id: str | None = None
        self.name: str | None = None
        self.args: str = ""

    def add_delta(self, delta) -> None:
        # Later fragments carry None for everything except the argument
        # deltas; never overwrite the accumulated id/name with None.
        if delta.id:
            self.id = delta.id
        if delta.function and delta.function.name:
            self.name = delta.function.name
        if delta.function and delta.function.arguments:
            self.args += delta.function.arguments


class Agent:
    """Holds conversation state and the primitives of one agent step.

    A step is a single request-execute-observe cycle: one streaming model
    turn, plus tool execution if the model requested calls. Iterating steps
    into a loop until the model replies is agent_loop's job.
    """

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.fireworks_api_key, base_url=settings.fireworks_base_url
        )
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.session_id = str(uuid.uuid4())
        # Set by step(): True when tool results are pending and the model
        # must be called again before the turn is complete.
        self.pending_tool_calls: bool = False
        # One entry per completed model call (in order): token usage from
        # the final streamed chunk, via stream_options={"include_usage": True}.
        self.usage_log: list[dict] = []

    @mlflow.trace(
        name="agent_step",
        span_type=SpanType.AGENT,
        output_reducer=lambda chunks: "".join(chunks),
    )
    def step(self) -> Iterator[str]:
        """One agent step: a model turn, executing any requested tool calls.

        Yields text deltas as they arrive — for a plain reply
        (pending_tool_calls=False) or prose emitted alongside tool calls
        (pending_tool_calls=True).
        """
        self.pending_tool_calls = False

        calls: dict[int, ToolCall] = {}
        reply = _ReplyBuffer(self.messages)
        reasoning_parts: list[str] = []
        finish_reason = None
        stream = self.client.chat.completions.create(
            model=settings.model,
            messages=self.messages,
            stream=True,
            tools=schemas(),
            stream_options={"include_usage": True},
        )
        usage = None
        try:
            for chunk in stream:
                if chunk.usage:
                    # Usage arrives on a trailing chunk with empty choices.
                    usage = chunk.usage
                    continue
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
                    reply.append(delta.content)
                # Reasoning models stream their chain of thought separately
                # (reasoning_content); capture it on the span so it isn't lost.
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_parts.append(reasoning)
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
                for fragment in delta.tool_calls or []:
                    call = calls.setdefault(fragment.index, ToolCall(fragment.index))
                    call.add_delta(fragment)
        finally:
            self.usage_log.append(self._usage_dict(usage))
            span = mlflow.get_current_active_span()
            if span:
                attrs = {}
                if reasoning_parts:
                    attrs["reasoning_content"] = "".join(reasoning_parts)
                if finish_reason:
                    attrs["finish_reason"] = finish_reason
                if usage is not None:
                    attrs.update(self._usage_dict(usage))
                if attrs:
                    span.set_attributes(attrs)
            # Appended in finally so a consumer abandoning the generator
            # still leaves consistent history. Tool turns commit their own
            # (single) assistant message below instead.
            if not calls:
                reply.commit_assistant()

        if not calls:
            return

        # A tool turn: execute, and let the loop call again.
        ordered = [calls[i] for i in sorted(calls)]
        self._execute_tool_calls(ordered, preamble="".join(reply.parts))
        self.pending_tool_calls = True

    def model_reply(self) -> Iterator[str]:
        """One streaming model call with no tools attached — the forced
        fallback when the loop hits its iteration cap."""
        reply = _ReplyBuffer(self.messages)
        usage = None
        stream = self.client.chat.completions.create(
            model=settings.model,
            messages=self.messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        try:
            for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage
                    continue
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
                    reply.append(delta)
        finally:
            self.usage_log.append(self._usage_dict(usage))
            reply.commit_assistant()
            self.pending_tool_calls = False

    @staticmethod
    def _usage_dict(usage) -> dict:
        if usage is None:
            return {}
        d = usage.model_dump() if hasattr(usage, "model_dump") else {}
        details = d.get("completion_tokens_details") or {}
        prompt_details = d.get("prompt_tokens_details") or {}
        return {
            "prompt_tokens": d.get("prompt_tokens"),
            "completion_tokens": d.get("completion_tokens"),
            "cached_tokens": prompt_details.get("cached_tokens"),
            "reasoning_tokens": details.get("reasoning_tokens"),
        }

    def _execute_tool_calls(self, calls: list[ToolCall], preamble: str) -> list[str]:
        """Execute each requested call and append the assistant tool_calls
        message (carrying any streamed preamble text as its content) plus
        one tool result per id."""
        results = [
            execute(call.name or "", call.args, tool_call_id=call.id)
            for call in calls
        ]

        self.messages.append(
            {
                "role": "assistant",
                "content": preamble or None,
                "tool_calls": [
                    {
                        "id": c.id or f"synthetic-{c.index}",
                        "type": "function",
                        "function": {"name": c.name or "", "arguments": c.args},
                    }
                    for c in calls
                ],
            }
        )
        for call, result in zip(calls, results):
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id or f"synthetic-{call.index}",
                    "content": result,
                }
            )
        return results


class _ReplyBuffer:
    """Accumulates streamed text and commits it to history exactly once.

    Appending happens in the producer's finally block rather than after the
    yield loop: if the consumer abandons the generator mid-stream, the
    assistant turn still lands in history instead of vanishing (which would
    leave two consecutive user messages on the next turn).
    """

    def __init__(self, messages: list[dict]) -> None:
        self._messages = messages
        self._parts: list[str] = []
        self._committed = False

    def append(self, delta: str) -> None:
        self._parts.append(delta)

    @property
    def parts(self) -> str:
        return "".join(self._parts)

    def commit_assistant(self) -> None:
        if not self._committed:
            self._messages.append(
                {"role": "assistant", "content": "".join(self._parts)}
            )
            self._committed = True
