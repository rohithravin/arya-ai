"""Deterministic store check: no note was created."""

import rewardkit as rk

rk.command_succeeds("test -z \"$(find notes -name '*.md' -print -quit)\"")
