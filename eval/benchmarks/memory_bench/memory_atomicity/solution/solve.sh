#!/bin/bash
# Reference solution: three atomic rows (raw SQL, no arya dependency) and
# the reply artifact. Every verifier dimension must be satisfiable.
set -eu

python3 - <<'EOF'
import sqlite3
import time

now = time.time()
conn = sqlite3.connect("/workdir/memories.db")
rows = [
    "User's sister Priya's birthday is June 12",
    "User's brother Arjun's birthday is March 3",
    "User's dad's birthday is November 8",
]
for content in rows:
    conn.execute(
        "INSERT INTO memories (content, category, created_at, updated_at, active)"
        " VALUES (?, 'person', ?, ?, 1)",
        (content, now, now),
    )
conn.commit()
print("rows saved")
EOF

cat > /workdir/reply.txt <<'EOF'
Got it — I've noted all three birthdays: your sister Priya's on June 12, your brother Arjun's on March 3, and your dad's on November 8. I'll remember them!
EOF
