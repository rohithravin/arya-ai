"""Deterministic routing check: no note was created for a personal fact."""

import rewardkit as rk

# Personal preferences are memory, not documents: a well-behaved agent
# must not also write this into the notes vault.
rk.command_succeeds("test -z \"$(find notes -name '*.md' -print -quit)\"")
