"""Deterministic store check: the preference became an active memory row."""

import rewardkit as rk

rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories WHERE active = 1 AND content LIKE '%cilantro%'",
    1,
)
