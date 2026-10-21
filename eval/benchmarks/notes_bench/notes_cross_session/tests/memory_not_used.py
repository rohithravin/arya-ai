"""Deterministic routing check: the window went to notes, not memory."""

import rewardkit as rk

# This is a notes task: a well-behaved agent must not ALSO write the
# window as a memory row (the two-store routing rule). A missing
# memories.db is fine (nothing remembered); content matching is
# sqlite-stored plain text, greppable with -a. Negative guard: passing
# requires the fact NOT to be in the store.
rk.command_succeeds("! grep -aqi -e 'deploy' -e 'satur' memories.db 2>/dev/null")
