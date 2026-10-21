"""Deterministic store checks: both facts saved, each under its category."""

import rewardkit as rk

# The preference is saved as a 'preference' row.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 1 AND category = 'preference'"
    " AND content LIKE '%tea%' AND content LIKE '%coffee%'",
    1,
)

# The goal is saved as a 'goal' row.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 1 AND category = 'goal'"
    " AND content LIKE '%marathon%'",
    1,
)
