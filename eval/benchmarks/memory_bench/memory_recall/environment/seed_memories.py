"""Seeds /workdir/memories.db for the memory_recall task (build-time).

Mirrors arya's store.py SCHEMA exactly (FTS index populated by the insert
triggers) so the agent's tools work against it unmodified. The target row
(Priya's birthday) is seeded with a stale, superseded sibling — recall must
filter on `active = 1` — alongside distractors that must not surface.
"""

import sqlite3

# Must match arya/src/arya/memory/store.py SCHEMA (FTS + triggers included).
SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY,
    content       TEXT NOT NULL,
    category      TEXT NOT NULL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    superseded_by INTEGER,
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, content=memories, content_rowid=id
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content)
  VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content)
  VALUES ('delete', old.id, old.content);
  INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

now = 1_000_000_000.0

conn = sqlite3.connect("/workdir/memories.db")
conn.executescript(SCHEMA)

rows = [
    # (content, category)
    ("User's sister Priya's birthday is June 10", "person"),  # id 1 — stale, superseded below
    ("User's sister Priya's birthday is June 12", "person"),  # id 2 — the target
    ("User prefers tea over coffee", "preference"),
    ("User's dentist appointment is Friday at 2pm", "fact"),
    ("User wants to run a marathon in October", "goal"),
]
for content, category in rows:
    conn.execute(
        "INSERT INTO memories (content, category, created_at, updated_at, active)"
        " VALUES (?, ?, ?, ?, 1)",
        (content, category, now, now),
    )
# The stale June-10 row (id 1) is superseded by the correct June-12 row (id 2):
# recall joining on `active = 1` must not return it.
conn.execute(
    "UPDATE memories SET active = 0, superseded_by = 2, updated_at = ? WHERE id = 1",
    (now + 1,),
)
conn.execute("PRAGMA user_version=1")
conn.commit()
conn.close()
print("seeded memories.db")
