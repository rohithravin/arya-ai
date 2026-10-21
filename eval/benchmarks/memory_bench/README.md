# memory_bench

Scores Arya's memory behavior end-to-end: whether the right facts get
**saved** (atomically, in the right category), **recalled** (the right row,
respecting supersession), **corrected** (via supersession, not duplicate
contradictions), and **withheld** (transient chatter not saved, unknown
facts admitted rather than confabulated) — plus whether the reply matches
what the store actually contains.

Every task is a single conversational turn with the agent's real toolset
(`remember`/`recall` only). Stores are seeded deterministically at image
build (exact `store.py` schema, so the tools work against them unmodified),
and each task's verifier combines deterministic SQL checks on
`/workdir/memories.db` with LLM judges on `/workdir/reply.txt`
(oracle = 1.0, nop = 0.0 — see the scripts in `scripts/`).

## Tasks

| Task             | Instruction                               | Verifier checks                          |
|------------------|-------------------------------------------|------------------------------------------|
| `memory_save`    | "Remember that my sister Priya's birthday is June 12." | active row containing Priya + June 12 |
| `memory_recall`  | "When is my sister Priya's birthday?" (store pre-seeded, incl. a superseded stale row) | reply states June 12 |
| `memory_no_save` | "Ugh, the traffic on my commute this morning was absolutely brutal. I'm exhausted." | zero active rows in the store |
| `memory_correction` | "Actually, I told you Priya's birthday wrong — it's June 15, not June 12." (stale row pre-seeded) | June-15 row active, June-12 row inactive with superseded_by chain |
| `memory_category` | "Two things before I forget: I prefer tea over coffee, and my goal is to run a marathon in October." | two active rows: `preference` (tea) + `goal` (marathon) |
| `memory_recall_miss` | "When is my dad's birthday?" (store pre-seeded with unrelated facts) | no row mentioning dad; reply admits not having it, no confabulated date |
| `memory_atomicity` | "Remember these birthdays: my sister Priya's is June 12, my brother Arjun's is March 3, and my dad's is November 8." | three atomic `person` rows, no blob row |

## Adding a task

Drop the directory under `benchmarks/memory_bench/` with a `task.toml`, an
`instruction.md`, a `solution/solve.sh` that satisfies **every** verifier
dimension (the oracle must be able to score 1.0), and verifier criteria
that nop cannot pass. `scripts/verify_tasks.py` and `scripts/run_agent.py`
pick it up automatically.
