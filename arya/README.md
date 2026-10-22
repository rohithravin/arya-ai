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
uv run mlflow ui --backend-store-uri sqlite:///<repo>/mlflow.db   # shared repo-root store
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
| `MLFLOW_TRACKING_URI`  | `sqlite:///<repo>/mlflow.db` (repo root)            | MLflow tracking store (shared with the eval harness) |
| `MLFLOW_EXPERIMENT`    | `arya`                                              | MLflow experiment name                       |
| `ARYA_STREAM_DELAY_MS` | `20`                                                 | Per-character print delay for streamed replies; `0` disables pacing |
| `ARYA_MEMORY_DB`       | `<repo>/memories.db`                                | SQLite file for the persistent memory store  |
| `ARYA_NOTES_DIR`       | `~/.arya/notes/`                                    | Markdown notes vault root (must resolve absolute) |

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

## Notes

Arya also has a notes vault — the agent's own working memory, a directory
of markdown files it writes for its own future turns (see
[`docs/notes.md`](docs/notes.md)): decision write-ups, per-topic context,
`todo.md`, and content you ask it to save. Routing is by content shape:
atomic facts/preferences/goals go to **memory**; structured documents go
to **notes** — regardless of whether you said "remember this" or "note
this".

Six tools (`find_notes`, `read_note`, `write_note`, `edit_note`,
`delete_note`, `restore_note`) operate on a path-jailed store with
provenance frontmatter, write-time secret screening, changed-since-read
tokens, and reversible destructive ops (soft delete + backups in a
`.trash/` subtree). Every turn starts with a derived, capped digest of
the vault so the agent always knows what it has noted. The vault is plain
markdown: inspect it with your editor — nothing in it requires Arya to
read.
