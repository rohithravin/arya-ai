# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Two separate uv-managed Python projects (each has its own `pyproject.toml` / `uv.lock` — run commands from inside the project directory):

- `arya/` — the agent itself: a hand-rolled harness (no agent framework/SDK) against Fireworks' OpenAI-compatible API, with MLflow/OpenTelemetry tracing and a SQLite+FTS5 persistent memory store. See `arya/docs/architecture.md` and `arya/docs/memory.md`.
- `eval/` — Harbor-based eval harness. Imports `arya` as a path-pinned dependency and runs it inside per-trial Docker sandboxes to score memory behavior deterministically. See `eval/README.md`.

## arya

```bash
cd arya
uv sync
cp .env.example .env            # set FIREWORKS_API_KEY
uv run arya                     # REPL agent
uv run pytest tests/            # tests
uv run pytest tests/test_memory.py -k <name>   # single test
uv run mlflow ui --backend-store-uri sqlite:///<repo>/mlflow.db   # traces at :5000 (shared repo-root store)
```

- `arya memories list|show|delete|edit` — local memory-store inspection commands; no API key or MLflow needed.
- All settings come from env vars via `config.py` (`.env` loaded with `override=True`, so the file wins over the shell). Missing `FIREWORKS_API_KEY` raises at import time, intentionally.
- Architecture: `agent.py` (conversation state + one-step primitives) → `agent_loop.py` (`run_turn`, plus the turn-start notes digest injection) → `main.py` (REPL / memories CLI). Tools are registered in `tools/registry.py` (`memory.py` defines `remember`/`recall`; `notes.py` defines the six notes tools over `notes/store.py`); `memory/store.py` and `notes/store.py` are pure storage with no tool knowledge. Routing rule: atomic facts → memory, structured documents → notes, regardless of the user's phrasing. System prompt lives in `prompts/system.py`, separate from agent code.
- `memories.db` / `mlflow.db` at the repo and project roots are local state, not code.

## eval

```bash
cd eval
uv sync
uv tool install harbor
export FIREWORKS_API_KEY=...    # optional for scripts/ (arya/.env wins); bare `harbor run` verifiers need it

# Run the agent against a Harbor task (adapter imported by module path from agent/)
PYTHONPATH=agent uv tool run harbor run --path benchmarks/memory_bench/memory_save --agent arya_harbor:AryaAgent

# Drive the agent directly, no Harbor
ARYA_INSTRUCTION="..." ARYA_MEMORY_DB=/tmp/memories.db ARYA_REPLY_PATH=/tmp/reply.txt \
    ARYA_CONVERSATION_PATH=/tmp/conversation.json uv run python agent/driver.py

# Run the agent on all tasks (or a benchmark, or one task)
uv run python scripts/run_agent.py
uv run python scripts/run_agent.py 5 memory_bench/memory_save

# Verify verifiers: oracle (reference solution) must score 1.0, nop must score 0.0
uv run python scripts/verify_tasks.py 5

# Test a task without the agent, using the reference solution
uv tool run harbor tasks test benchmarks/memory_bench/memory_save --solution
```

- `agent/arya_harbor.py` — Harbor `BaseAgent` adapter; runs on the host and drives the sandbox via `environment.exec`. `arya/.env` is not uploaded, so the adapter resolves `FIREWORKS_API_KEY` on the host (`arya/.env` first, then the shell) and passes it in. Arya itself executes **inside the trial container** via `agent/driver.py`, with `arya/src` uploaded to `/opt/arya-src` (PYTHONPATH) so trials evaluate the exact local code — no commit pinning.
- Sandbox conventions: `/workdir/memories.db` (trial's memory store), `/workdir/reply.txt` (final reply), `/logs/verifier/reward.txt` (numeric reward written by `benchmarks/<bench>/<name>/tests/test.sh`).
- Tasks live in `benchmarks/<bench>/<name>/` with `task.toml`, `instruction.md`, a `solution/solve.sh` that satisfies **every** verifier dimension, and criteria a nop cannot pass. Both `scripts/verify_tasks.py` (oracle/nop sanity) and `scripts/run_agent.py` (agent scoring) select tasks by benchmark (`memory_bench`) or task path (`memory_bench/memory_save`); the `eval-verifier.yml` workflow runs the sanity script on every PR.
