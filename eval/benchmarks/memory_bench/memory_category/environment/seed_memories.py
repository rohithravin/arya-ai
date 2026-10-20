"""Creates an empty /workdir/memories.db for the memory_category task.

Mirrors arya's store.py SCHEMA exactly (table + FTS5 index + triggers),
zero rows, so the verifier's category-count queries read 0 whether or not
the agent ever touches a tool.
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

conn = sqlite3.connect("/workdir/memories.db")
conn.executescript(SCHEMA)
conn.execute("PRAGMA user_version=1")
conn.commit()
conn.close()
print("created empty memories.db")
