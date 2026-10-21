#!/bin/bash
# Reference solution: save both facts under their correct categories (raw
# SQL, no arya dependency) and produce the reply artifact. Every verifier
# dimension must be satisfiable.
set -eu

python3 - <<'EOF'
import sqlite3
import time

now = time.time()
conn = sqlite3.connect("/workdir/memories.db")
conn.execute(
    "INSERT INTO memories (content, category, created_at, updated_at, active)"
    " VALUES (?, 'preference', ?, ?, 1)",
    ("User prefers tea over coffee", now, now),
)
conn.execute(
    "INSERT INTO memories (content, category, created_at, updated_at, active)"
    " VALUES (?, 'goal', ?, ?, 1)",
    ("User's goal is to run a marathon in October", now, now),
)
conn.commit()
print("rows saved")
EOF

cat > /workdir/reply.txt <<'EOF'
Got it — I've noted that you prefer tea over coffee and that your goal is to run a marathon in October. I'll remember both!
EOF
