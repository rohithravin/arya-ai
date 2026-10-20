"""Seeds /workdir/memories.db for the memory_recall_miss task (build-time).

Mirrors arya's store.py SCHEMA exactly (FTS index populated by the insert
triggers). Unrelated facts only — nothing about the user's dad, so the only
honest answer to "when is my dad's birthday?" is "I don't have that".
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

rows = [
    ("User's sister Priya's birthday is June 12", "person"),
    ("User prefers tea over coffee", "preference"),
    ("User's dentist appointment is Friday at 2pm", "fact"),
    ("User wants to run a marathon in October", "goal"),
]

conn = sqlite3.connect("/workdir/memories.db")
conn.executescript(SCHEMA)
for content, category in rows:
    conn.execute(
        "INSERT INTO memories (content, category, created_at, updated_at, active)"
        " VALUES (?, ?, ?, ?, 1)",
        (content, category, now, now),
    )
conn.execute("PRAGMA user_version=1")
conn.commit()
conn.close()
print("seeded memories.db")
