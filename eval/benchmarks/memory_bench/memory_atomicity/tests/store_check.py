"""Deterministic store checks: three atomic rows, one birthday each.

The instruction carries three entangled facts. A correct agent writes
three separate self-contained rows (what FTS recall quality depends on),
not one blob — a blob here would quietly degrade every later recall.
"""

import rewardkit as rk

# Each birthday is saved as its own active 'person' row.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 1 AND category = 'person'"
    " AND content LIKE '%Priya%' AND content LIKE '%June 12%'",
    1,
)
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 1 AND category = 'person'"
    " AND content LIKE '%Arjun%' AND content LIKE '%March 3%'",
    1,
)
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 1 AND category = 'person'"
    " AND (content LIKE '%dad%' OR content LIKE '%father%')"
    " AND content LIKE '%November 8%'",
    1,
)

# Exactly three active rows — no extra or duplicated saves.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories WHERE active = 1",
    3,
)

# No blob row: no active row mentions two different people.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories WHERE active = 1 AND ("
    " (content LIKE '%Priya%' AND content LIKE '%Arjun%')"
    " OR (content LIKE '%Priya%' AND (content LIKE '%dad%' OR content LIKE '%father%'))"
    " OR (content LIKE '%Arjun%' AND (content LIKE '%dad%' OR content LIKE '%father%'))"
    ")",
    0,
)
