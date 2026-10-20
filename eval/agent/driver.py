"""Runs inside the Harbor sandbox: one Arya turn, driven by ARYA_INSTRUCTION.

Writes the final reply to ARYA_REPLY_PATH (if set) so the task verifier can
check the agent's output text; the memory store lands at ARYA_MEMORY_DB.
"""

import json
import os

from arya.agent import Agent
from arya.agent_loop import run_turn
from arya.tracing import init_tracing


def main() -> int:
    instruction = os.environ.get("ARYA_INSTRUCTION", "").strip()
    if not instruction:
        print("ARYA_INSTRUCTION not set", file=os.stderr)
        return 2

    # SQLite-backed tracing inside the sandbox; without this MLflow defaults
    # to the deprecated './mlruns' file store and raises.
    init_tracing()
    agent = Agent()
    parts = []
    for chunk in run_turn(agent, instruction):
        parts.append(chunk)
    reply = "".join(parts)

    # The reply goes to the file only: the process's stdout carries MLflow's
    # logging output, which must not pollute the recorded reply.
    reply_path = os.environ["ARYA_REPLY_PATH"]
    with open(reply_path, "w", encoding="utf-8") as f:
        f.write(reply)
    # Full transcript + per-call token usage for the adapter's ATIF export.
    from arya.config import settings

    with open(os.environ["ARYA_CONVERSATION_PATH"], "w", encoding="utf-8") as f:
        json.dump(
            {
                "messages": agent.messages,
                "usage": agent.usage_log,
                "model": settings.model,
            },
            f,
            ensure_ascii=False,
        )
    print(reply, file=os.sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
