"""Deterministic store checks: the correction was saved via supersession.

The store is pre-seeded with one active wrong row ("June 12"). A correct
agent saves the corrected fact as a new active row and supersedes the old
one (active -> 0, superseded_by -> the new row's id). Saving without
superseding — leaving contradictory memories — must fail.
"""

import rewardkit as rk

# The corrected fact exists as an active row.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 1 AND content LIKE '%Priya%' AND content LIKE '%June 15%'",
    1,
)

# The stale June-12 row was superseded (inactive) — regardless of how the
# corrected row phrases the change: an agent that writes "June 15 (corrected
# from June 12)" has an active row mentioning June 12 too, and that is
# correct behavior, not a stale row.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories"
    " WHERE active = 0 AND content LIKE '%June 12%'",
    1,
)

# Supersession chain intact: the stale row points at the corrected row.
rk.sqlite_query_equals(
    "memories.db",
    "SELECT COUNT(*) FROM memories old JOIN memories new ON old.superseded_by = new.id"
    " WHERE old.active = 0 AND old.content LIKE '%June 12%'"
    " AND new.active = 1 AND new.content LIKE '%June 15%'",
    1,
)
