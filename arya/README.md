# arya

Arya's agent harness — a minimal, hand-rolled chat loop against Fireworks'
OpenAI-compatible API, with MLflow/OpenTelemetry tracing wired in from the
start. See [`docs/architecture.md`](docs/architecture.md) for how it's built
and why.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd arya
cp .env.example .env
# edit .env and set FIREWORKS_API_KEY
```

## Run

```bash
uv run arya
```

Drops you into a REPL. Type a message and press enter; `exit` or `quit` to
leave.

## View traces

In a separate terminal, from this directory:

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
```

Open `http://127.0.0.1:5000` and select the `arya` experiment. Each turn is
its own trace; turns from one conversation share a `mlflow.trace.session`
value (enable the **Session** column, or filter with
`` metadata.`mlflow.trace.session` = '<id>' ``, to group them).

## Configuration

All settings are read from the environment (`.env` is loaded automatically,
and takes precedence over the same variable already set in your shell).

| Env var                | Default                                             | Purpose                                      |
|-------------------------|------------------------------------------------------|-----------------------------------------------|
| `FIREWORKS_API_KEY`    | *(required)*                                        | Fireworks API key                            |
| `FIREWORKS_BASE_URL`   | `https://api.fireworks.ai/inference/v1`             | Fireworks OpenAI-compatible endpoint         |
| `ARYA_MODEL`           | `accounts/fireworks/models/glm-5p3-flash`           | Model to call                                |
| `MLFLOW_TRACKING_URI`  | `sqlite:///mlflow.db`                               | MLflow tracking store                        |
| `MLFLOW_EXPERIMENT`    | `arya`                                              | MLflow experiment name                       |
| `ARYA_STREAM_DELAY_MS` | `20`                                                 | Per-character print delay for streamed replies; `0` disables pacing |
| `ARYA_MEMORY_DB`       | `<repo>/memories.db`                                | SQLite file for the persistent memory store  |

See [`.env.example`](.env.example) for a template.

## Memory

Arya has a persistent memory store (SQLite + FTS5, see
[`docs/memory.md`](docs/memory.md)). The agent saves and searches memories
via `remember`/`recall` tool calls during conversations. Inspect and correct
the store directly:

```bash
uv run arya memories list [--category fact|preference|person|goal]
uv run arya memories show <id>     # row + supersession chain
uv run arya memories delete <id> [--force]
uv run arya memories edit <id> --content "..."
```

The `memories` commands are purely local — no API key or MLflow required.
