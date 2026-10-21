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
```

`FIREWORKS_API_KEY` is read on the host from `arya/.env` first, then the shell
(`export FIREWORKS_API_KEY=...`) if `.env` has none. `.env` wins, matching
arya's local `override=True` behavior. The adapter passes it into the sandbox
for the agent (the file itself is not uploaded). `scripts/run_agent.py` and
`scripts/verify_tasks.py` pass it to harbor, which substitutes it into each
task's `${FIREWORKS_API_KEY}` for the verifier's LLM judges. A bare
`harbor run` takes the verifier's key from the shell only.

## Run

```bash
cd eval
PYTHONPATH=agent uv tool run harbor run \
    --path benchmarks/memory_bench/memory_save \
    --agent arya_harbor:AryaAgent
```

(`PYTHONPATH=agent` because Harbor imports the adapter class by module path;
the `harbor` CLI runs in its own tool environment.)

## Drive the agent directly (no Harbor)

The same driver the adapter uploads into the sandbox:

```bash
ARYA_INSTRUCTION="Remember that my dentist appointment is Friday at 2pm." \
ARYA_MEMORY_DB=/tmp/memories.db ARYA_REPLY_PATH=/tmp/reply.txt \
ARYA_CONVERSATION_PATH=/tmp/conversation.json \
    uv run python agent/driver.py
```

## How it works

- `agent/arya_harbor.py` — Harbor `BaseAgent` adapter. Harbor runs the agent
  on the host; the adapter drives the sandbox via `environment.exec`, so
  Arya itself runs **inside the trial container** via `agent/driver.py` —
  the memory store is isolated per trial and inspectable by the verifier.
- `agent/driver.py` — runs inside the sandbox: one `run_turn` on the task
  instruction; writes the reply to `/workdir/reply.txt`.
- `benchmarks/<bench>/<name>/` — Harbor task directories, grouped into
  benchmarks (e.g. `benchmarks/memory_bench/memory_save/`):
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

## Benchmarks and tasks

Tasks live under `benchmarks/<bench>/<name>/`. Each benchmark has its own
`benchmarks/<bench>/README.md` describing what that benchmark tests and
listing its tasks:

- [`benchmarks/memory_bench/`](benchmarks/memory_bench/) — whether the
  right facts get saved (atomically, in the right category), recalled
  (the right row, respecting supersession), corrected (via supersession),
  and withheld (transient chatter not saved, unknown facts admitted).

Testing a task without the agent (uses the reference solution):

```bash
cd eval
uv tool run harbor tasks test benchmarks/memory_bench/memory_save --solution
```

## Run the agent on all tasks

`scripts/run_agent.py` runs the Arya agent (the local code) on every task —
or a filtered subset — N attempts each, reporting per-trial rewards and a
per-task mean (rewards are a report, not pass/fail; see "Verifier sanity"
below for the pass/fail check):

```bash
cd eval
uv run python scripts/run_agent.py                          # all tasks, 3 attempts each
uv run python scripts/run_agent.py 5 memory_bench           # one benchmark
uv run python scripts/run_agent.py 5 memory_bench/memory_save   # one task
```

Every sweep is imported into MLflow as traces: one experiment per run
(`arya-eval/<timestamp>`, name it via `ARYA_EVAL_EXPERIMENT`), one session
per trial, each trace carrying task/trial/reward tags. View with
`uv run mlflow ui --backend-store-uri sqlite:///mlflow.db` (same store as
Arya itself). Set `ARYA_EVAL_MLFLOW=0` to skip the import.

## Verifier sanity (oracle=1.0, nop=0.0)

`scripts/verify_tasks.py` runs every selected task with the **oracle**
(the task's reference solution — must score reward 1.0 on every attempt)
and **nop** (does nothing — must score 0.0), N attempts each (default 5).
This validates the verifiers themselves, judges included, and is what the
`eval-verifier.yml` GitHub workflow runs on PRs touching `eval/`:

```bash
cd eval
uv run python scripts/verify_tasks.py                           # all tasks, 5 attempts each
uv run python scripts/verify_tasks.py 5 memory_bench            # one benchmark
uv run python scripts/verify_tasks.py 5 memory_bench/memory_save    # one task
```

Adding a task: see the benchmark's README under `benchmarks/<bench>/`.
