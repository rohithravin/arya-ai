# Arya evals (Harbor)

Runs the Arya agent — the exact code you use daily, toolset unchanged
(`remember`/`recall` only) — against [Harbor](https://github.com/harbor-framework/harbor)
tasks that score memory behavior deterministically.

This is its own uv project: it imports `arya` as a (path-pinned) dependency,
plus `harbor`. Trials measure **the exact local code**: the adapter uploads
`arya/src` into the sandbox at setup time (`environment.upload_dir`) and the
sandbox imports it via `PYTHONPATH` — each task's Dockerfile provides only
arya's dependencies (`mlflow`, `openai`, `python-dotenv`), so there is no
commit re-pinning and no drift between what you run and what you evaluate.

## Setup

```bash
cd eval
uv sync                         # arya (from ../arya) + harbor
uv tool install harbor          # the harbor CLI (drives trials)
export FIREWORKS_API_KEY=...    # passed into the sandbox by the adapter
```

## Run

```bash
cd eval
PYTHONPATH=agent uv tool run harbor run \
    --path tasks/memory_save \
    --agent arya_harbor:AryaAgent
```

(`PYTHONPATH=agent` because Harbor imports the adapter class by module path;
the `harbor` CLI runs in its own tool environment.)

## Drive the agent directly (no Harbor)

The same driver the adapter uploads into the sandbox:

```bash
ARYA_INSTRUCTION="Remember that my dentist appointment is Friday at 2pm." \
ARYA_MEMORY_DB=/tmp/memories.db ARYA_REPLY_PATH=/tmp/reply.txt \
    uv run python agent/driver.py
```

## How it works

- `agent/arya_harbor.py` — Harbor `BaseAgent` adapter. Harbor runs the agent
  on the host; the adapter drives the sandbox via `environment.exec`, so
  Arya itself runs **inside the trial container** via `agent/driver.py` —
  the memory store is isolated per trial and inspectable by the verifier.
- `agent/driver.py` — runs inside the sandbox: one `run_turn` on the task
  instruction; writes the reply to `/workdir/reply.txt`.
- `tasks/<name>/` — Harbor task directories:
  - `instruction.md` — the conversational input
  - `environment/Dockerfile` — installs the arya package at a pinned commit
  - `tests/test.sh` — verifier; queries `/workdir/memories.db` and writes
    the numeric reward to `/logs/verifier/reward.txt`
  - `solution/solve.sh` — reference solution (writes the memory row directly)

## Adapter conventions

| Path (in sandbox)      | Meaning                              |
|------------------------|--------------------------------------|
| `/opt/arya-src`        | the uploaded arya source (PYTHONPATH) |
| `/agent/driver.py`     | the uploaded driver script           |
| `/workdir/memories.db` | the trial's memory store              |
| `/workdir/reply.txt`   | the agent's final reply text          |

## Tasks

| Task           | Instruction                               | Verifier checks                          |
|----------------|-------------------------------------------|------------------------------------------|
| `memory_save`  | "Remember that my sister Priya's birthday is June 12." | active row containing Priya + June 12 |

Testing a task without the agent (uses the reference solution):

```bash
cd eval
uv tool run harbor tasks test tasks/memory_save --solution
```

## Verifier sanity (oracle=1.0, nop=0.0)

`scripts/verify_tasks.py` runs every task under `tasks/` with the **oracle**
(the task's reference solution — must score reward 1.0 on every attempt)
and **nop** (does nothing — must score 0.0), N attempts each (default 5).
This validates the verifiers themselves, judges included, and is what the
`eval-verifier.yml` GitHub workflow runs on PRs touching `eval/`:

```bash
cd eval
uv run python scripts/verify_tasks.py 5
```

Adding a task: drop the directory under `tasks/` with a `task.toml`, an
`instruction.md`, a `solution/solve.sh` that satisfies **every** verifier
dimension (the oracle must be able to score 1.0), and verifier criteria
that nop cannot pass. The sanity script picks it up automatically.
