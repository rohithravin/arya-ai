"""Deterministic reply check: session 2 (fresh context) answers from the note."""

import rewardkit as rk

# Session 2's instruction never states the window; only the note on disk
# can put the day into this reply. A nop, or an agent whose session 2
# doesn't consult the vault, fails here.
rk.command_succeeds("grep -qi 'saturday' replies/session-2.txt")
