"""The agent loop: compose Agent steps into a full conversation turn.

One step is a single request-execute-observe cycle (see Agent.step). This
loop feeds a user turn in and steps until the model produces a plain reply
(no more tool calls), capped at max_iterations — after which one final
tools-disabled model call forces a reply.
"""

from collections.abc import Iterator

import mlflow
from mlflow.entities import SpanType

from arya.agent import Agent

DEFAULT_MAX_ITERATIONS = 5


def run_turn(
    agent: Agent, user_input: str, max_iterations: int = DEFAULT_MAX_ITERATIONS
) -> Iterator[str]:
    # The span is opened manually rather than via @mlflow.trace so the
    # recorded inputs are the user turn only — the decorator would also
    # serialize the agent argument as an unhelpful object repr.
    with mlflow.start_span(name="agent_turn", span_type=SpanType.AGENT) as span:
        mlflow.update_current_trace(
            metadata={"mlflow.trace.session": agent.session_id}
        )
        span.set_inputs({"user_input": user_input, "max_iterations": max_iterations})

        agent.messages.append({"role": "user", "content": user_input})

        parts: list[str] = []
        steps = 0
        try:
            for _ in range(max_iterations):
                for chunk in agent.step():
                    parts.append(chunk)
                    yield chunk
                steps += 1
                # Iteration count on the root span (the step spans are
                # positionless by design — the primitive doesn't know its
                # place in the loop); children appear in iteration order.
                span.set_attributes({"steps": steps})
                if not agent.pending_tool_calls:
                    return
            # Cap exhausted: force a plain reply without tools.
            span.set_attributes({"cap_hit": True})
            for chunk in agent.model_reply():
                parts.append(chunk)
                yield chunk
        finally:
            span.set_outputs("".join(parts))
