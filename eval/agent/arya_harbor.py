"""Arya as a Harbor agent.

The adapter runs on the host (Harbor's model: the agent drives the sandbox
via `environment.exec`). Arya itself runs *inside* the sandbox through the
driver script (`driver.py`), so the memory store (`memories.db`) and the
agent's reply live in the trial's container — isolated per trial, and
directly inspectable by the task's verifier.

The agent exposes exactly Arya's existing toolset (`remember`/`recall`,
registered by importing `arya.tools`); nothing agent-side is added or
changed — the eval measures the agent you actually use.

Run (from `eval/`, harbor installed via `uv tool install harbor`):

    PYTHONPATH=agent uv tool run harbor run \
        --path tasks/memory_save \
        --agent arya_harbor:AryaAgent

Conventions the adapter imposes on tasks (see README.md):
- the arya source is uploaded to /opt/arya-src (imported via PYTHONPATH)
- the driver is uploaded to /agent/driver.py
- the memory DB lives at /workdir/memories.db (ARYA_MEMORY_DB)
- the notes vault lives at /workdir/notes (ARYA_NOTES_DIR)
- the agent's final reply is written to /workdir/reply.txt
- the raw transcript is written to /workdir/conversation.json
- every session's {instruction, reply} is written to /workdir/sessions.json
  (multi-session tasks separate instructions in instruction.md with the
  session-break marker below; each session runs a fresh Agent sharing the
  trial's stores)
"""

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import (
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from harbor.models.trajectories.agent import Agent as TrajectoryAgent

DRIVER_HOST_PATH = Path(__file__).parent / "driver.py"
DRIVER_SANDBOX_PATH = "/agent/driver.py"

# The local arya package source (repo root / arya / src), uploaded into the
# sandbox at setup so trials measure the code being developed.
ARYA_SRC_HOST_PATH = Path(__file__).parents[2] / "arya" / "src"
ARYA_SRC_SANDBOX_PATH = "/opt/arya-src"

# arya/.env is not uploaded (the sandbox's dotenv search finds nothing), so
# the key is resolved on the host: .env first, as arya does locally, then the
# shell.
ARYA_ENV_HOST_PATH = ARYA_SRC_HOST_PATH.parent / ".env"

MEMORY_DB = "/workdir/memories.db"
NOTES_DIR = "/workdir/notes"
REPLY_PATH = "/workdir/reply.txt"
CONVERSATION_PATH = "/workdir/conversation.json"
SESSIONS_PATH = "/workdir/sessions.json"

# Multi-session tasks separate their per-session instructions in
# instruction.md with this marker line; the adapter splits on it and the
# driver runs each session against a fresh Agent (fresh context) sharing
# the trial's stores. Single-session instructions have no marker and run
# exactly as before. The marker must be a whole line of its own: a
# mid-line occurrence is a mistake, not a session break.
SESSION_MARKER = "--- SESSION BREAK ---"
SESSION_MARKER_RE = re.compile(r"(?m)^--- SESSION BREAK ---[ \t]*\r?$")


def split_sessions(instruction: str) -> list[str]:
    """Split an instruction into per-session instructions on the marker line.

    Raises ValueError on malformed shapes (empty segments, a stray
    mid-line marker) — a task author's typo must fail loudly, not
    silently renumber sessions.
    """
    sessions = SESSION_MARKER_RE.split(instruction)
    if not sessions or any(not s.strip() for s in sessions):
        raise ValueError("empty session (missing or doubled session-break marker)")
    for s in sessions:
        if SESSION_MARKER in s:
            raise ValueError("mid-line session-break marker inside a session")
    return [s.strip() for s in sessions]


class AryaAgent(BaseAgent):
    capabilities = AgentCapabilities(atif=True)

    @staticmethod
    def name() -> str:
        return "arya"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        # Upload the local arya source (the eval measures the exact code
        # being developed — the Dockerfile provides only its dependencies).
        await environment.upload_dir(ARYA_SRC_HOST_PATH, ARYA_SRC_SANDBOX_PATH)
        await environment.upload_file(DRIVER_HOST_PATH, DRIVER_SANDBOX_PATH)
        # Fail fast if the sandbox is not usable (arya importable, key
        # present).
        result = await environment.exec(
            "python -c 'import arya, arya.tools'",
            env={"PYTHONPATH": ARYA_SRC_SANDBOX_PATH},
            timeout_sec=60,
        )
        if result.return_code != 0:
            raise RuntimeError(
                f"arya not importable in sandbox: {result.stderr or result.stdout}"
            )

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        instructions = split_sessions(instruction)
        env = {
            # Multi-session: JSON array, one fresh-Agent session each. The
            # single-instruction form also sets ARYA_INSTRUCTION for
            # backwards compatibility with direct-drive runs.
            "ARYA_INSTRUCTIONS": json.dumps(instructions),
            "ARYA_MEMORY_DB": MEMORY_DB,
            "ARYA_NOTES_DIR": NOTES_DIR,
            "ARYA_REPLY_PATH": REPLY_PATH,
            "ARYA_CONVERSATION_PATH": CONVERSATION_PATH,
            "ARYA_SESSIONS_PATH": SESSIONS_PATH,
            "PYTHONPATH": ARYA_SRC_SANDBOX_PATH,
            # The sandbox resolves the model API itself; the task's
            # environment must allow api.fireworks.ai.
            "FIREWORKS_API_KEY": dotenv_values(ARYA_ENV_HOST_PATH).get(
                "FIREWORKS_API_KEY"
            )
            or os.environ.get("FIREWORKS_API_KEY", ""),
        }
        result = await environment.exec(
            f"python {DRIVER_SANDBOX_PATH}",
            env=env,
            cwd="/workdir",
            # Generous: a multi-session trial runs several full turns, and
            # a timeout would discard every session's artifacts (they are
            # written only after the last session completes).
            timeout_sec=600,
        )
        if result.return_code != 0:
            raise RuntimeError(
                f"driver failed ({result.return_code}): "
                f"{(result.stdout or '')[-2000:]}"
            )
        # The driver's stdout carries MLflow logging; the clean reply and
        # the transcript are the files the driver wrote. Harbor merges
        # stderr into stdout, so result.stdout is the full driver output.
        # Missing artifacts are an error, not an empty default — a silent
        # fallback would make a failed trial look like an empty one.
        async def _cat(path: str) -> str:
            cat = await environment.exec(f"cat {path}", timeout_sec=30)
            if cat.return_code != 0:
                raise RuntimeError(f"driver wrote no {path}")
            return cat.stdout or ""

        reply = await _cat(REPLY_PATH)
        transcript = json.loads(await _cat(CONVERSATION_PATH))
        sessions = json.loads(await _cat(SESSIONS_PATH))
        messages = transcript.get("messages", [])
        # Token usage summed across ALL sessions (conversation.json carries
        # only the final one; sessions.json carries every session's).
        usage = [u for s in sessions for u in s.get("usage", []) if u]
        model_name = transcript.get("model")
        context.metadata = {
            "reply": reply.strip(),
            "n_messages": len(messages),
            "sessions": [
                {"instruction": s["instruction"][:200], "reply": s["reply"][:500]}
                for s in sessions
            ],
            "driver_output": (result.stdout or "").strip()[-2000:],
        }
        self._write_trajectory(messages, usage, model_name)
        usage = [u for u in usage if u]  # drop empty entries (no usage chunk)
        if usage:
            context.n_input_tokens = sum(
                (u.get("prompt_tokens") or 0) for u in usage
            )
            context.n_output_tokens = sum(
                (u.get("completion_tokens") or 0) for u in usage
            )
            context.n_cache_tokens = sum(
                (u.get("cached_tokens") or 0) for u in usage
            )
        self.logger.info("arya reply: %s", reply.strip()[:500])

    def _write_trajectory(
        self, messages: list[dict[str, Any]], usage: list[dict], model_name: str | None
    ) -> None:
        """Convert Arya's message history to an ATIF trajectory document.

        `usage` is Arya's per-model-call usage log (in call order), mapped
        onto the agent steps in order. Harbor reads `logs_dir/trajectory.json`
        back to backfill model usage into the trial result.
        """
        trajectory = Trajectory(
            agent=TrajectoryAgent(
                name="arya",
                version=self.version(),
                model_name=model_name,
                tool_definitions=None,
            ),
            steps=self._messages_to_steps(messages, iter(usage)),
        )
        path = self.logs_dir / "trajectory.json"
        path.write_text(
            json.dumps(trajectory.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _messages_to_steps(messages: list[dict[str, Any]], usage) -> list[Step]:
        steps: list[Step] = []
        step_id = 1
        i = 0
        while i < len(messages):
            msg = messages[i]
            role, content = msg.get("role"), msg.get("content")
            tool_calls = msg.get("tool_calls")

            if role == "system":
                steps.append(
                    Step(step_id=step_id, source="system", message=content or "")
                )
                step_id += 1
            elif role == "user":
                steps.append(
                    Step(step_id=step_id, source="user", message=content or "")
                )
                step_id += 1
            elif role == "assistant":
                # Tool messages following this assistant turn become its
                # ATIF observation.
                results = []
                while i + 1 < len(messages) and messages[i + 1].get("role") == "tool":
                    i += 1
                    results.append(
                        ObservationResult(
                            source_call_id=messages[i].get("tool_call_id"),
                            content=messages[i].get("content"),
                        )
                    )
                calls = None
                if tool_calls:
                    calls = [
                        ToolCall(
                            tool_call_id=c["id"],
                            function_name=c["function"]["name"],
                            arguments=json.loads(c["function"]["arguments"] or "{}"),
                        )
                        for c in tool_calls
                    ]
                # Each agent step is exactly one model call; per-call usage
                # entries (skipping empty ones) map in call order.
                u = next((u for u in usage if u), None)
                metrics = (
                    Metrics(
                        prompt_tokens=u.get("prompt_tokens"),
                        completion_tokens=u.get("completion_tokens"),
                        cached_tokens=u.get("cached_tokens"),
                    )
                    if u
                    else None
                )
                steps.append(
                    Step(
                        step_id=step_id,
                        source="agent",
                        message=content or "",
                        tool_calls=calls,
                        observation=(
                            Observation(results=results) if results else None
                        ),
                        metrics=metrics,
                        llm_call_count=1,
                    )
                )
                step_id += 1
            i += 1
        return steps
