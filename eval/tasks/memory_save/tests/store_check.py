"""Deterministic store check: the fact was saved as an active memory row."""

import rewardkit as rk

rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 1 AND content LIKE '%Priya%' AND content LIKE '%June 12%'",
    1,
)
