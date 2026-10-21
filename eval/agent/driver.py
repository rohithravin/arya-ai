"""Runs inside the Harbor sandbox: one or more Arya sessions, driven by env.

Single-session (backwards compatible): ARYA_INSTRUCTION is one string; one
Agent, one turn.

Multi-session: ARYA_INSTRUCTIONS is a JSON array of instructions; each runs
against a **fresh Agent** (empty conversation, fresh context) while sharing
the trial's /workdir stores — exactly the things that survive a real process
restart (memories.db, notes/), and nothing else. This is what makes
cross-session persistence and two-session prompt injection measurable.

Artifacts (paths from env, all under /workdir):
- ARYA_REPLY_PATH: the final session's reply (verifier convention, unchanged)
- ARYA_CONVERSATION_PATH: the final session's transcript + usage
- ARYA_SESSIONS_PATH: every session's {instruction, reply} in order
  (plus per-session reply files at <replies dir>/session-<n>.txt so
  verifiers can check one session's reply without JSON parsing)
"""

import json
import os

from arya.agent import Agent
from arya.agent_loop import run_turn
from arya.tracing import init_tracing


def _instructions() -> list[str]:
    raw_list = os.environ.get("ARYA_INSTRUCTIONS", "").strip()
    if raw_list:
        try:
            instructions = json.loads(raw_list)
        except json.JSONDecodeError as exc:
            print(f"ARYA_INSTRUCTIONS is not valid JSON: {exc}", file=os.stderr)
            raise SystemExit(2) from exc
        if (
            not isinstance(instructions, list)
            or not instructions
            or not all(isinstance(i, str) and i.strip() for i in instructions)
        ):
            print(
                "ARYA_INSTRUCTIONS must be a non-empty JSON array of"
                " non-empty strings",
                file=os.stderr,
            )
            raise SystemExit(2)
        return instructions
    single = os.environ.get("ARYA_INSTRUCTION", "").strip()
    if not single:
        print("ARYA_INSTRUCTION not set", file=os.stderr)
        raise SystemExit(2)
    return [single]


def main() -> int:
    instructions = _instructions()

    # SQLite-backed tracing inside the sandbox; without this MLflow defaults
    # to the deprecated './mlruns' file store and raises.
    init_tracing()

    sessions: list[dict] = []
    for i, instruction in enumerate(instructions, start=1):
        # A fresh Agent per session: fresh conversation and context. Only the
        # stores on disk carry over — the variable under test.
        agent = Agent()
        parts = []
        for chunk in run_turn(agent, instruction):
            parts.append(chunk)
        reply = "".join(parts)
        from arya.config import settings

        sessions.append(
            {
                "session": i,
                "instruction": instruction,
                "reply": reply,
                # Full per-session transcript + usage: token accounting and
                # trace import can cover every session, not just the last.
                "messages": agent.messages,
                "usage": agent.usage_log,
                "model": settings.model,
            }
        )

    # The reply goes to files only: the process's stdout carries MLflow's
    # logging output, which must not pollute the recorded reply.
    sessions_path = os.environ.get("ARYA_SESSIONS_PATH") or os.path.join(
        os.path.dirname(os.environ["ARYA_REPLY_PATH"]) or ".", "sessions.json"
    )
    with open(os.environ["ARYA_REPLY_PATH"], "w", encoding="utf-8") as f:
        f.write(sessions[-1]["reply"])
    with open(sessions_path, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)
    # Per-session reply files: verifier-friendly, no JSON parsing needed.
    replies_dir = os.path.join(os.path.dirname(os.environ["ARYA_REPLY_PATH"]), "replies")
    os.makedirs(replies_dir, exist_ok=True)
    for s in sessions:
        with open(
            os.path.join(replies_dir, f"session-{s['session']}.txt"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(s["reply"])
    # Full transcript + per-call token usage for the adapter's ATIF export
    # (the final session's agent: the adapter's trajectory is the last
    # conversation; earlier sessions live in sessions.json).
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
    for s in sessions:
        print(f"[session {s['session']}] {s['reply']}", file=os.sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
