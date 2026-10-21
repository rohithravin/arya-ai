#!/bin/bash
# Reference solution: write the memory row directly and produce the reply
# artifact. Both verifier dimensions must be satisfiable.
set -eu

python3 - <<'EOF'
import sqlite3
import time

now = time.time()
conn = sqlite3.connect("/workdir/memories.db")
conn.execute(
    "CREATE TABLE IF NOT EXISTS memories ("
    " id INTEGER PRIMARY KEY, content TEXT NOT NULL,"
    " category TEXT NOT NULL, created_at REAL NOT NULL,"
    " updated_at REAL NOT NULL, superseded_by INTEGER,"
    " active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)))"
)
conn.execute(
    "INSERT INTO memories (content, category, created_at, updated_at, active)"
    " VALUES (?, 'preference', ?, ?, 1)",
    ("The user really can't stand cilantro", now, now),
)
conn.commit()
print("row saved")
EOF

cat > /workdir/reply.txt <<'EOF'
Got it — noted that you can't stand cilantro. I'll keep that in mind.
EOF
