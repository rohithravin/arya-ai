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
    agent.py     # Agent class: conversation state + one-step primitives
    agent_loop.py # run_turn: compose steps until the model replies
    main.py      # entrypoint (`uv run arya`, `uv run arya memories ...`)
    prompts/
      system.py  # the system prompt, kept out of agent code
    tools/
      registry.py # generic tool registry: register/schemas/execute
      memory.py   # remember/recall tool definitions + handlers
      notes.py    # find/read/write/edit/delete/restore note tool definitions
    memory/
      store.py    # SQLite + FTS5 storage layer (data only, no tool knowledge)
    notes/
      store.py    # jailed markdown-file notes store + turn-start digest
  tests/
    test_memory.py # memory store + tool tests (uv run pytest tests/)
    test_notes.py  # notes hardening tests (jail, CAS, restore, caps, todos)
  docs/
    architecture.md
    memory.md
    notes.md
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

The memory store path (`ARYA_MEMORY_DB`, default `<repo>/memories.db`) is
read by `memory/store.py` rather than `Settings`, because the `memories` CLI
must run without importing `arya.config` (which requires a Fireworks API
key). It shares the same `.env` loading via `arya/env.py`.

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

`step()` is one agent **step**: a single streaming model turn plus tool
execution if the model requested calls. It is a **generator**, decorated
with `@mlflow.trace(..., output_reducer=...)`:

1. Calls the model with `stream=True` and `tools` attached, yielding text
   deltas as they arrive while accumulating tool-call fragments (keyed by
   `tool_call.index`), skipping chunks with an empty `choices` list
   (providers, including Fireworks, may send a trailing usage-only chunk).
2. If no tool calls were requested: the assembled reply is appended to
   history as the `assistant` turn (in a `finally` block, so a consumer
   abandoning the generator still leaves consistent history) and
   `pending_tool_calls` is `False` — the turn is done.
3. If tool calls were requested: the calls are executed via the tools
   registry, the assistant `tool_calls` message
   (with any streamed preamble as its content) plus one `role=tool` result
   per id are appended, and `pending_tool_calls` is `True` — the loop must
   call again.

The user message is appended by `run_turn`, not by `step`.

Because `step` is a generator, the outer loop stays simple. The **agent
loop** lives in `agent_loop.py` (`run_turn`): feed the user turn in, then
repeatedly `Agent.step()` — one request-execute-observe cycle per step —
until the model produces a plain reply (no more tool calls), capped at
`max_iterations` (default 5), after which one final tools-disabled model
call (`Agent.model_reply()`) forces a reply. Every failure path (malformed
JSON, unknown tool, tool exception) appends an error tool result via the
registry so the message history stays valid. Each tool execution gets its
own `@mlflow.trace` span (`TOOL` type, named after the tool, opened in the
registry); design details in [`memory.md`](memory.md).

### `main.py` — REPL entrypoint

The `arya` console script (`uv run arya`). Responsibilities:

- Calls `init_tracing()` once, then constructs one `Agent`.
- Runs a plain `while True` read-eval-print loop: read a line, `exit`/`quit`
  to stop, otherwise call `agent_loop.run_turn(agent, line)`.
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
  -> agent_loop.run_turn(agent, user_input)
       -> appends user message to agent.messages
       -> Agent.step()   [one per iteration, up to max_iterations]
            -> calls Fireworks chat.completions.create(..., stream=True)
                 (mlflow.openai.autolog() wraps this call as a CHAT_MODEL span)
            -> yields each text delta as it arrives
            -> if tool calls requested:
                 -> registry executes each call (TOOL span per tool)
                 -> appends assistant tool_calls message + tool results
                 -> loop calls step() again
       -> if the iteration cap is hit: agent.model_reply() (no tools)
  -> main.py prints each yielded chunk, paced by stream_delay_ms
  -> loop back to read the next line
```

Every turn produces one MLflow trace: the `agent_turn` (AGENT) root, nested
`agent_step` (AGENT) spans per step, per-tool `TOOL` spans, and the
`Completions` (CHAT_MODEL) spans from autolog. All traces from one `arya`
process share the same `mlflow.trace.session` value.

Since notes landed, each turn also starts with a derived notes digest
injected as a system message (`notes/store.digest()` via `agent_loop`) —
the capped vault overview the model sees before choosing tools, so note
discovery never depends on the model volunteering a search. It is data,
clearly delimited, never instructions.

## What's explicitly not here yet

- **Memory/notes curation beyond explicit tools.** Persistent memory
  ([`memory.md`](memory.md)) and notes ([`notes.md`](notes.md)) both
  exist and are agent-driven, but there is no offline
  reflection/dreaming pass, no embeddings, no vault condensation pass,
  and no git-backed notes history.
- **No further tools.** Memory and notes are the tool surface; the agent
  cannot touch a calendar/email yet (the calendar design conversation
  lives in `notes.md`'s history — provider protocol, deferred).
- **Eval harness lives in the sibling project.** Store-level tests live
  here (`tests/`); the model-behavior eval rig (Harbor, `memory_bench`,
  `notes_bench`) is `../eval/` — a separate uv project with its own docs.
- **No multi-provider abstraction.** Model access is Fireworks-specific
  (albeit via the generic OpenAI client interface), not behind a
  provider-agnostic layer.

These are deliberate sequencing choices, not oversights — tracing was set up
before any agent capability existed specifically so every future addition
(tools, memory, eval) is observable from the moment it's introduced.
