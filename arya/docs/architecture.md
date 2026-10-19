# Arya Architecture

Arya is a personal, life-assistant agent built on a hand-rolled harness rather
than an existing agent framework/SDK. This doc describes the design as it
stands today — a single-turn, no-tools chat loop with tracing wired in from
the start.

## Goals driving the current design

- **Own the harness.** No agent SDK or framework underneath — the model call,
  conversation state, and I/O are all explicit code in this repo.
- **Open models via Fireworks.** Model access goes through Fireworks'
  OpenAI-compatible endpoint, not a vendor-specific SDK.
- **Observability from day one.** Every model call is traced via OpenTelemetry
  (through MLflow's tracing layer) so behavior is inspectable before any
  complexity (tools, multi-step reasoning) is added.

## Module layout

```
arya/
  src/arya/
    config.py    # environment-driven settings, loaded once at import time
    tracing.py   # MLflow tracking/experiment setup + OpenAI autolog
    agent.py     # Agent class: conversation state + one model call per turn
    main.py      # REPL entrypoint (`uv run arya`)
  docs/
    architecture.md
  .env / .env.example
```

### `config.py` — `Settings`

A single `Settings` class reads all configuration from the environment at
import time (via `python-dotenv`, with `override=True` so the project's own
`.env` wins over any same-named variable already present in the shell).
Failing fast on a missing `FIREWORKS_API_KEY` (a `KeyError` at import) is
intentional — there's no valid way to run the agent without it, so there's
nothing to gracefully degrade to.

Settings:

| Setting            | Env var                 | Default                                            |
|---------------------|--------------------------|-----------------------------------------------------|
| `fireworks_api_key` | `FIREWORKS_API_KEY`     | *(required, no default)*                           |
| `fireworks_base_url`| `FIREWORKS_BASE_URL`    | `https://api.fireworks.ai/inference/v1`             |
| `model`             | `ARYA_MODEL`             | `accounts/fireworks/models/glm-5p3-flash`          |
| `mlflow_tracking_uri` | `MLFLOW_TRACKING_URI` | `sqlite:///mlflow.db`                               |
| `mlflow_experiment` | `MLFLOW_EXPERIMENT`     | `arya`                                              |
| `stream_delay_ms`   | `ARYA_STREAM_DELAY_MS`  | `20`                                                |

### `tracing.py` — `init_tracing()`

Called once at process start (from `main.py`). It:

1. Points MLflow at a SQLite-backed tracking store
   (`sqlite:///mlflow.db`) — MLflow 3.x retired the plain file store
   (`./mlruns`), so a database backend is required even for fully local use.
2. Sets/creates the `arya` experiment.
3. Calls `mlflow.openai.autolog()`, which patches the OpenAI SDK so every
   `chat.completions.create(...)` call is automatically captured as a span —
   including when `stream=True`, where MLflow buffers the chunk iterator and
   reconstructs the full completion for the trace after the stream ends.

MLflow's tracing is itself built on OpenTelemetry — `mlflow.openai.autolog()`
gives OTel-based spans per model call with no manual instrumentation needed
for the pieces that exist today. Manual `@mlflow.trace` spans are added only
at application boundaries that autolog doesn't see on its own (see
`agent.py` below).

View traces with:

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
```

### `agent.py` — `Agent`

The `Agent` class holds all per-conversation state:

- `self.client` — an `openai.OpenAI` client pointed at Fireworks' base URL.
- `self.messages` — the full chat history (`system`, `user`, `assistant`
  turns), passed back to the model on every call. There is no summarization
  or truncation yet — the whole history grows unbounded for the life of the
  process.
- `self.session_id` — a UUID generated once per `Agent` instance, used purely
  for trace grouping (see below).

`step(user_input)` is the only operation the agent supports. It is a
**generator**, decorated with `@mlflow.trace(..., output_reducer=...)`:

1. Tags the current trace with `mlflow.trace.session` so every turn in one
   conversation shares a session id in MLflow, even though each turn is its
   own trace (a trace represents one logical execution — a turn — not an
   open-ended conversation; session metadata is how multiple traces get tied
   back together in the UI).
2. Appends the user message to history.
3. Calls the model with `stream=True` and yields text deltas as they arrive,
   skipping any chunk with an empty `choices` list (providers, including
   Fireworks, may send a trailing usage-only chunk with no choices).
4. Once the stream ends, appends the full assembled reply to history as the
   `assistant` turn.

Because `step` is a generator, there is deliberately **no agent loop** here
yet. An "agent loop" — call the model, execute a requested tool, feed the
result back, call the model again, repeat until done — only makes sense once
the agent has tools to call. Today there is nothing to loop over: one call in,
one streamed reply out. When tool-calling is added, that request → execute →
observe → repeat cycle will live either inside `step()` or in a new
`agent_loop.py`, separate from the outer REPL loop in `main.py`.

### `main.py` — REPL entrypoint

The `arya` console script (`uv run arya`). Responsibilities:

- Calls `init_tracing()` once, then constructs one `Agent`.
- Runs a plain `while True` read-eval-print loop: read a line, `exit`/`quit`
  to stop, otherwise call `agent.step(...)`.
- `print_chunk()` paces the printed output to `stream_delay_ms` per
  character (default `20ms`, in the range of comfortable silent-reading
  speed) so fast models don't dump their whole reply onto the screen in one
  burst. Setting `ARYA_STREAM_DELAY_MS=0` disables pacing and prints each
  chunk as soon as it's received.

This REPL loop is the *outer* loop (conversation turns); it is unrelated to
the tool-calling agent loop described above.

## Request flow (current, single turn)

```
user types a line
  -> main.py reads it
  -> agent.step(user_input)
       -> appends user message to self.messages
       -> calls Fireworks chat.completions.create(..., stream=True)
            (mlflow.openai.autolog() wraps this call as a CHAT_MODEL span)
       -> yields each text delta
            (outer @mlflow.trace call wraps the whole generator as an
             AGENT span named "agent_step", tagged with the session id)
       -> appends full assistant reply to self.messages
  -> main.py prints each yielded chunk, paced by stream_delay_ms
  -> loop back to read the next line
```

Every turn produces one MLflow trace with two spans: the `agent_step` (AGENT)
root and the nested `Completions` (CHAT_MODEL) span from autolog. All traces
from one `arya` process share the same `mlflow.trace.session` value.

## What's explicitly not here yet

- **No tools.** The agent can only talk; it cannot call functions, search,
  read files, or touch a calendar/email/notes — the actual "life assistant"
  capabilities.
- **No agent loop.** Follows directly from having no tools — see `agent.py`
  above.
- **No persistent memory.** Conversation history lives only in
  `Agent.messages`, in process memory. Nothing survives a restart; there's no
  memory store across sessions yet.
- **No eval harness.** The `eval/` directory exists at the repo root but is
  currently empty.
- **No multi-provider abstraction.** Model access is Fireworks-specific
  (albeit via the generic OpenAI client interface), not behind a
  provider-agnostic layer.

These are deliberate sequencing choices, not oversights — tracing was set up
before any agent capability existed specifically so every future addition
(tools, memory, eval) is observable from the moment it's introduced.
