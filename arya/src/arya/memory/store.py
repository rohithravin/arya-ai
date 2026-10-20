"""Persistent memory store for Arya.

SQLite-backed, FTS5-indexed. See docs/memory.md for the design.
"""

import os
import re
import sqlite3
import time
from pathlib import Path

from arya import env  # noqa: F401  (loads .env before the db path is read)

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "memories.db"

SCHEMA_VERSION = 1

MAX_CONTENT_LENGTH = 500
RECALL_LIMIT = 5

CATEGORIES = ("fact", "preference", "person", "goal")

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


def db_path() -> Path:
    return Path(os.environ.get("ARYA_MEMORY_DB", str(DEFAULT_DB_PATH)))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        # First creation: index anything present (e.g. a restored DB) and
        # stamp the schema version for future migrations.
        conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()


# Function/question words that carry no retrieval signal. Tokens under 3
# chars are dropped too (also almost all stopwords) — otherwise "when is
# my sister's birthday" AND-matches every row containing "is", and the
# OR fallback would admit nearly the whole store.
STOPWORDS = frozenset(
    """the and for that this with about when what where who whom whose why how
    does did was were are you your from have has had not but all any can
    will would should there their""".split()
)


def _contentful_tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"\w+", text)
        if len(t) >= 3 and t.lower() not in STOPWORDS
    ]


def _fts_query(text: str) -> str | None:
    """Tight FTS5 MATCH form: contentful tokens, AND-joined."""
    tokens = _contentful_tokens(text)
    if not tokens:
        return None
    return " ".join(f'"{token}"' for token in tokens)


def _fts_query_loose(text: str) -> str | None:
    """Loose form: the same contentful tokens, OR-joined."""
    tokens = _contentful_tokens(text)
    if not tokens:
        return None
    return " OR ".join(f'"{token}"' for token in tokens)


def remember(conn: sqlite3.Connection, content: str, category: str,
             supersedes: int | None = None) -> dict:
    if category not in CATEGORIES:
        return {"error": f"category must be one of {list(CATEGORIES)}"}
    content = content.strip()
    if not content:
        return {"error": "content must not be empty"}
    if len(content) > MAX_CONTENT_LENGTH:
        return {"error": f"content exceeds {MAX_CONTENT_LENGTH} characters"}

    now = time.time()
    try:
        cursor = conn.execute(
            "INSERT INTO memories (content, category, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (content, category, now, now),
        )
        new_id = cursor.lastrowid

        supersession_failed = None
        if supersedes is not None and supersedes == new_id:
            # Rowid reuse after a delete could make a stale id hit the new
            # row itself; that would create a dead self-referencing row.
            supersession_failed = f"cannot supersede memory {supersedes} (itself)"
        elif supersedes is not None:
            old = conn.execute(
                "SELECT active FROM memories WHERE id = ?", (supersedes,)
            ).fetchone()
            if old is None or not old[0]:
                supersession_failed = (
                    f"memory {supersedes} not found or already inactive"
                )
            else:
                conn.execute(
                    "UPDATE memories SET active = 0, superseded_by = ?,"
                    " updated_at = ? WHERE id = ? AND active = 1 AND id != ?",
                    (new_id, now, supersedes, new_id),
                )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        return {"error": f"database error: {exc}"}

    result: dict = {"id": new_id, "saved": content}
    if supersession_failed:
        result["supersession_failed"] = supersession_failed
    return result


def recall(conn: sqlite3.Connection, query: str) -> list[dict] | dict:
    """Search active memories. Returns a list of matches, or {"error": ...}
    if the index is unusable — an empty store and a broken index must not
    look identical to the caller."""
    match = _fts_query(query)
    if match is None:
        return []
    try:
        # AND-joined tokens first (precision); fall back to the looser
        # OR-joined match so a single unmatched token doesn't hide the
        # rest of the query's results (recall).
        rows = conn.execute(
            "SELECT m.id, m.content, m.category, m.created_at, m.updated_at"
            " FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid"
            " WHERE memories_fts MATCH ? AND m.active = 1"
            " ORDER BY memories_fts.rank LIMIT ?",
            (match, RECALL_LIMIT),
        ).fetchall()
        if not rows:
            loose = _fts_query_loose(query)
            if loose and loose != match:
                rows = conn.execute(
                    "SELECT m.id, m.content, m.category, m.created_at, m.updated_at"
                    " FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid"
                    " WHERE memories_fts MATCH ? AND m.active = 1"
                    " ORDER BY memories_fts.rank LIMIT ?",
                    (loose, RECALL_LIMIT),
                ).fetchall()
    except sqlite3.OperationalError as exc:
        return {"error": f"memory index unavailable: {exc}"}
    return [
        {
            "id": row[0],
            "content": row[1],
            "category": row[2],
            "created_at": row[3],
            "updated_at": row[4],
        }
        for row in rows
    ]


# --- Inspection CLI helpers (used by main.py) -----------------------------


def list_memories(category: str | None = None) -> list[dict]:
    conn = _connect()
    try:
        _init_schema(conn)
        if category:
            rows = conn.execute(
                "SELECT id, content, category, created_at, updated_at,"
                " superseded_by FROM memories WHERE active = 1 AND category = ?"
                " ORDER BY updated_at DESC",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, content, category, created_at, updated_at,"
                " superseded_by FROM memories WHERE active = 1"
                " ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                "id": r[0],
                "content": r[1],
                "category": r[2],
                "created_at": r[3],
                "updated_at": r[4],
                "superseded_by": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()


def show_memory(memory_id: int) -> dict | None:
    conn = _connect()
    try:
        _init_schema(conn)
        chain: list[dict] = []
        visited: set[int] = set()
        current: int | None = memory_id
        while current is not None and current not in visited:
            # Visited-set guard: a corrupted chain (self-reference) must not
            # hang the CLI.
            visited.add(current)
            row = conn.execute(
                "SELECT id, content, category, created_at, updated_at,"
                " superseded_by, active FROM memories WHERE id = ?",
                (current,),
            ).fetchone()
            if row is None:
                break
            chain.append(
                {
                    "id": row[0],
                    "content": row[1],
                    "category": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                    "superseded_by": row[5],
                    "active": bool(row[6]),
                }
            )
            current = row[5]
        return chain[0] | {"chain": chain} if chain else None
    finally:
        conn.close()


def delete_memory(memory_id: int, force: bool = False) -> str | None:
    """Hard-delete a memory. Returns an error message, or None on success."""
    conn = _connect()
    try:
        _init_schema(conn)
        referenced = conn.execute(
            "SELECT id FROM memories WHERE superseded_by = ?", (memory_id,)
        ).fetchone()
        if referenced and not force:
            return (
                f"memory {memory_id} is referenced by supersession chain"
                f" (memory {referenced[0]}); use --force to delete anyway"
            )
        if force:
            # Null dangling pointers first, or rowid reuse could later make
            # the chain point at an unrelated memory.
            conn.execute(
                "UPDATE memories SET superseded_by = NULL WHERE superseded_by = ?",
                (memory_id,),
            )
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        if cursor.rowcount == 0:
            return f"no memory with id {memory_id}"
        conn.commit()
        return None
    except sqlite3.Error as exc:
        conn.rollback()
        return f"database error: {exc}"
    finally:
        conn.close()


def edit_memory(memory_id: int, content: str) -> str | None:
    """Correct a memory's content in place. Returns an error message or None."""
    content = content.strip()
    if not content:
        return "content must not be empty"
    if len(content) > MAX_CONTENT_LENGTH:
        return f"content exceeds {MAX_CONTENT_LENGTH} characters"
    conn = _connect()
    try:
        _init_schema(conn)
        cursor = conn.execute(
            "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
            (content, time.time(), memory_id),
        )
        if cursor.rowcount == 0:
            return f"no memory with id {memory_id}"
        conn.commit()
        return None
    except sqlite3.Error as exc:
        conn.rollback()
        return f"database error: {exc}"
    finally:
        conn.close()
