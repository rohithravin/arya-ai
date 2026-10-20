"""Deterministic store check: no active memory rows were written."""

import rewardkit as rk

rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories WHERE active = 1",
    0,
)
