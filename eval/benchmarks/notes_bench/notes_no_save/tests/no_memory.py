"""Deterministic store check: no memory rows were written."""

import rewardkit as rk

# A store that was opened (e.g. a recall that found nothing) legitimately
# exists with zero rows; only saved content fails this. A missing db
# passes too.
rk.command_succeeds(
    "test ! -f memories.db || python3 -c"
    " 'import sqlite3; c = sqlite3.connect(\"memories.db\");"
    " exit(0 if c.execute(\"SELECT COUNT(*) FROM memories\").fetchone()[0] == 0"
    " else 1)'"
)
