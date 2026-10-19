import uuid
from collections.abc import Iterator

import mlflow
from mlflow.entities import SpanType
from openai import OpenAI

from arya.config import settings

SYSTEM_PROMPT = "You are Arya, a helpful personal assistant."


class Agent:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.fireworks_api_key, base_url=settings.fireworks_base_url
        )
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.session_id = str(uuid.uuid4())

    @mlflow.trace(
        name="agent_step",
        span_type=SpanType.AGENT,
        output_reducer=lambda chunks: "".join(chunks),
    )
    def step(self, user_input: str) -> Iterator[str]:
        mlflow.update_current_trace(
            metadata={"mlflow.trace.session": self.session_id}
        )
        self.messages.append({"role": "user", "content": user_input})

        stream = self.client.chat.completions.create(
            model=settings.model,
            messages=self.messages,
            stream=True,
        )

        reply_parts = []
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                reply_parts.append(delta)
                yield delta

        self.messages.append(
            {"role": "assistant", "content": "".join(reply_parts)}
        )
