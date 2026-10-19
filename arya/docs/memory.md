# Arya Memory — v1 Design

This doc specifies v1 of Arya's persistent memory: an explicit, tool-based
memory store the agent reads and writes during conversations. It is the first
agent capability beyond plain chat, and it introduces the tool-calling loop
that every later capability (calendar, todos) will reuse.

See [`architecture.md`](architecture.md) for the current no-tools harness this
builds on.

## Design stance

Two reference points, from how Anthropic and OpenAI each approach agent
memory:

- **Anthropic (memory as files):** give the agent generic read/write tools over
  a memory directory; no retrieval engine, no embeddings. The agent curates
  its own memory, live, and reads it back just-in-time. Boring, inspectable,
  and every write is auditable.
- **OpenAI (memory as distilled state):** persist the raw transcript, then run
  a background "dreaming" pass that synthesizes the memory state — catching
  implicit facts a live tool call misses, and rewriting stale facts as time
  passes.

**v1 takes Anthropic's storage philosophy and leaves OpenAI's curation
pipeline for v2.** An explicit tool is instant, debuggable via MLflow traces,
and is the prerequisite for v2 anyway (the offline pass needs the same store
and schema). What v1 deliberately does not attempt: catching implicit facts,
staleness rewriting, and embeddings-based retrieval — all v2+.

## Goals / non-goals

**Goals**

- Arya remembers facts across restarts, and recalls the relevant ones into
  the conversation.
- Every memory read/write the *agent* performs is an explicit, traced tool
  call — inspectable in MLflow alongside the model call that caused it.
- Introduces the tool-calling agent loop (`request → execute → observe →
  repeat`) — one-step primitives in `agent.py`, composition in
  `agent_loop.py` — generic enough for future tools.

**Non-goals (v1)**

- No offline reflection/dreaming pass — the live agent is the only writer (v2).
- No embeddings or vector search — SQLite FTS5 only.
- No per-turn automatic memory injection — retrieval is agent-initiated (an
  always-injected summary layer is a v2 candidate).
- No contradiction resolution beyond simple supersession.

## Storage

SQLite (same backend MLflow already uses, zero new dependencies), one file:
`memories.db` in the project root, **separate from `mlflow.db`**, configured
via a new `ARYA_MEMORY_DB` setting (default anchored to the repo root via
`Path(__file__).resolve()`, never the process CWD — a relative path would
silently create a second, empty DB when `arya` is launched from another
directory, which looks exactly like memory loss). `memories.db`,
`memories.db-wal`, and `memories.db-shm` are gitignored — the contents are
personal data.

```sql
CREATE TABLE memories (
    id          INTEGER PRIMARY KEY,
    content     TEXT NOT NULL,     -- one atomic, self-contained fact
    category    TEXT NOT NULL,     -- 'fact' | 'preference' | 'person' | 'goal'
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,     -- bumped on every content edit/supersession
    superseded_by INTEGER,         -- set when replaced; soft-delete chain
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, content=memories, content_rowid=id
);
```

Design rules for the data:

- **Atomic facts, not summaries.** Each row is one self-contained statement
  ("Prefers morning workouts"), never a paragraph. Atomic rows can be
  individually retrieved, updated, and superseded. `remember` caps content
  length (e.g. 500 chars) so one huge memory can't bloat every future context.
- **Supersession, not edits.** When a fact changes ("switched to decaf"), the
  old row is deactivated and pointed at a new row via `superseded_by`. The
  write history is preserved for free and re-consolidation stays possible.
- **`category` is a coarse enum**, chosen by the agent at write time. It exists
  to make the inspection CLI readable, not to drive retrieval.
- **`updated_at` is bumped on every mutation** (CLI edit, supersession);
  `recall` returns it alongside `created_at` so corrected facts report their
  true recency.

### FTS sync — the external-content pitfall

With `content=memories` external-content tables, a plain `DELETE FROM
memories_fts WHERE rowid=...` does **not** remove terms (verified: the row
stays matchable and later raises `fts5: missing row ... from content table`).
The special `'delete'` command is mandatory, and `INSERT OR REPLACE` must be
avoided (its implicit delete doesn't fire the trigger without
`recursive_triggers`). Sync via exactly these triggers:

```sql
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content)
  VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER memories_au AFTER UPDATE OF content ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content)
  VALUES ('delete', old.id, old.content);
  INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
```

Schema init is idempotent (`CREATE ... IF NOT EXISTS`), versioned via
`PRAGMA user_version` (v2's reflection pass will migrate), and runs
`INSERT INTO memories_fts(memories_fts) VALUES('rebuild')` on first creation.
Connections: per-operation, opened inside context managers, with
`PRAGMA journal_mode=WAL` and an explicit `busy_timeout` so a running REPL
and `arya memories delete` can coexist.

## Tools

Two tools, exposed to the model as OpenAI function definitions:

### `remember(content, category, supersedes?)`

Write a memory. The agent calls it when the user says something durable —
explicitly ("remember that…") or clearly worth keeping. `supersedes` is an
optional integer: the id of an active memory this fact replaces. Semantics,
executed as **one transaction** — insert the new row first, then
`UPDATE memories SET active=0, superseded_by=<new id>, updated_at=? WHERE
id=? AND active=1`:

- Unknown or already-inactive id → the write still succeeds, but the tool
  result tells the model supersession failed (it can correct course).
- Already-superseded id → same as above; the model should supersede the
  *current* successor instead.

### `recall(query)`

FTS5 search over active memories. The model sends natural language, so raw
text must never hit `MATCH` directly — verified failures include `what's`
(apostrophe), `c++` (`+`), `user:likes` (column syntax), and `?`/empty
strings, each an uncaught `sqlite3.OperationalError` that would kill the
session. Query construction in the tool implementation:

1. Tokenize with `re.findall(r"\w+", query)`; reject empty → return `[]`.
2. Quote each token (`f'"{t}"'`), OR-join them (recall is recall — recall
   broadly, let ranking filter).
3. Join FTS against the base table for the `active=1` filter (the FTS table
   only has `content`; a bare `WHERE active=1` errors with "no such column"):

```sql
SELECT m.id, m.content, m.category, m.created_at, m.updated_at
FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid
WHERE memories_fts MATCH ? AND m.active = 1
ORDER BY memories_fts.rank LIMIT 5;
```

4. Wrap the whole thing in `try/except sqlite3.OperationalError` → return `[]`
   (an error result to the model, never an exception into the REPL).

Results serialize as a JSON list of `{id, content, category, created_at,
updated_at}`.

System prompt guidance (in `SYSTEM_PROMPT`) tells Arya to recall early when a
topic involving people/places/projects/habits comes up, and to be
conservative with `remember` — durable facts and preferences, not
conversation filler. A flash-class model over-saving junk is the main quality
risk; the prompt biases against it and MLflow traces make over-saving
visible.

## Tool-calling loop (the real work of v1)

The loop lives in `agent_loop.py` (`run_turn`), which composes `Agent.step()`
primitives (described as "not here yet" in the pre-tools
[`architecture.md`](architecture.md)). `Agent.step()` is a single
request-execute-observe cycle; `run_turn` appends the user message, steps
until the model replies without tool calls, and forces a fallback reply at
the cap. `tools` is passed on **every** `chat.completions.create` call in
the loop, not just the first.

### Accumulating streamed tool-call fragments

With `stream=True`, tool calls arrive as fragments: the first chunk for an
index carries `id`/`type`/`function.name` with empty arguments; later chunks
carry only `function.arguments` deltas (and `None` for everything else);
`finish_reason="tool_calls"` arrives at the end. Accumulate into a
`dict[tool_call_index] -> {id, name, args}` — never overwrite `id`/`name`
with the `None` values from later deltas, and append
`delta.function.arguments or ""` rather than assigning. Execute only after
the stream ends (detect a tool turn by the accumulated calls, not by
`finish_reason` alone). Multiple calls execute in `index` order.

### The message-history invariant

The doc's previous draft said "plain `role=tool` messages" — that alone is
invalid (Fireworks 400s on a missing `tool_call_id`, and silently no-ops an
orphan tool message). Per iteration, the history must contain, in order:

```python
# 1. the assistant turn that requested the calls
self.messages.append({
    "role": "assistant",
    "content": text_or_None,
    "tool_calls": [{
        "id": c["id"], "type": "function",
        "function": {"name": c["name"], "arguments": c["args"]},  # JSON *string*
    } for c in calls],
})
# 2. one tool message per call id, same order, string content
for c in calls:
    self.messages.append({
        "role": "tool",
        "tool_call_id": c["id"],
        "content": json.dumps(result),   # always a str
    })
```

### Failure semantics

Every failure path must leave `self.messages` valid: the last assistant
message with `tool_calls` must always be followed by exactly one tool result
per id. Concretely:

- Malformed/truncated JSON arguments (`json.JSONDecodeError`), unknown tool
  name, or a tool exception → append a tool message whose content is an
  error string (e.g. `{"error": "invalid arguments: ..."}`) and continue the
  loop — the model can recover.
- Missing tool id (malformed stream) → synthesize one before executing.
- Hitting the loop cap (`run_turn`'s `max_iterations` parameter, default 5):
  make one final model call with `tools` omitted so the model produces a
  plain reply.
- `main.py` wraps the `run_turn(...)` iteration in `try/except` so an
  unexpected tool error can never kill the REPL session.

Mixed turns (text deltas *and* tool calls in one response) are allowed by the
API: the text is streamed to the user as it arrives and becomes the content
of the assistant `tool_calls` message. Text is also appended to history in a
`finally` block, so a consumer abandoning the generator mid-stream still
leaves a consistent transcript.

Each turn is one MLflow trace: an `agent_turn` (AGENT) root span in
`run_turn`, nested `agent_step` (AGENT) spans per step, and one `TOOL` span
per tool execution (named after the tool, opened in the tools registry), with
autolog's `Completions` (CHAT_MODEL) spans underneath.

### No progress indicator

Tool turns surface nothing to the user by default: the model's prose (if
any) streams as it arrives, and the turn simply continues after tool
execution. Tool activity is visible in the MLflow traces, not the terminal.

## Inspection CLI

`uv run arya memories <subcommand>` — argv dispatch, **not** the chat REPL.
This requires refactoring `main.py`: `def main(argv=None)`, argparse
subparsers with `required=False` (bare `arya` still enters the REPL), and —
critically — dispatching `memories` **before** importing `arya.agent` or
calling `init_tracing()`. Today `config.py` evaluates
`os.environ["FIREWORKS_API_KEY"]` at import time, so without lazy imports
every memory command would demand a model credential and spin up MLflow for
purely local database reads. `Agent` and `init_tracing` are imported inside
the REPL branch only.

Commands:

- `arya memories list [--category C]` — active memories
- `arya memories show <id>` — row + supersession chain
- `arya memories delete <id>` — refuse if another row's `superseded_by`
  points at it (null the pointer in a transaction first, or require
  `--force`); hard delete is the one operation that bypasses the
  history-preserving rule, and it's the user's explicit choice
- `arya memories edit <id> --content "..."` — direct correction; bumps
  `updated_at` (the FTS update trigger re-syncs the index)

This makes "why does Arya think that?" answerable in one command, which is
the difference between a memory system you trust and one you tolerate.

## Failure modes & mitigations

| Risk | Mitigation |
|---|---|
| Model forgets to call `remember`/`recall` | Prompt guidance; accepted v1 limitation (v2 offline pass is the fix) |
| Model over-saves junk | Conservative prompt; visible in traces; `arya memories delete` |
| Stale facts linger | Accepted in v1; supersession exists but relies on the agent noticing; time-aware rewriting is v2 |
| Runaway tool loop | Hard cap (5) + final tools-disabled model call |
| FTS misses paraphrases ("gym" vs "workout") | Accepted; embeddings are the v2 upgrade when observed |
| Invalid history after a failed tool turn | Always one tool result per id, including synthetic error results |
| Corrupt/second DB from CWD or concurrent runs | Absolute `ARYA_MEMORY_DB` default, WAL mode, busy_timeout, idempotent schema |

## Build order

1. `memory/store.py` — schema (with FTS triggers above), connection helper,
   `remember`/`recall` internals (query construction, supersession
   transaction)
2. `main.py` refactor — `main(argv=None)`, `memories` subcommands dispatched
   before any API-key/tracing initialization
3. `tools/registry.py` + `tools/memory.py` — generic registry and the
   `remember`/`recall` tool definitions (memory tools are the first client)
4. Tool-calling loop — `agent.py` step primitives + `agent_loop.py`
   composition, with the failure semantics above
5. System prompt guidance + tuning against real usage
6. Docs sync — update `architecture.md`'s "What's explicitly not here yet"
   and README (new setting, CLI, gitignore entries)
7. (v2, out of scope here) end-of-session reflection pass, always-injected
   summary layer, embeddings
