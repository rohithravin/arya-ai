#!/bin/bash
# Reference solution: supersede the seeded June-12 row with a corrected
# June-15 row (raw SQL, no arya dependency) and produce the reply artifact.
# Every verifier dimension must be satisfiable.
set -eu

python3 - <<'EOF'
import sqlite3
import time

now = time.time()
conn = sqlite3.connect("/workdir/memories.db")
cursor = conn.execute(
    "INSERT INTO memories (content, category, created_at, updated_at, active)"
    " VALUES (?, 'person', ?, ?, 1)",
    ("User's sister Priya's birthday is June 15", now, now),
)
new_id = cursor.lastrowid
conn.execute(
    "UPDATE memories SET active = 0, superseded_by = ?, updated_at = ?"
    " WHERE id = 1",
    (new_id, now),
)
conn.commit()
print("correction saved")
EOF

cat > /workdir/reply.txt <<'EOF'
No worries — corrected! Priya's birthday is June 15. I've updated my notes.
EOF
