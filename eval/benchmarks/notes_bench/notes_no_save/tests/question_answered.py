"""Deterministic reply check: the trivial question was answered.

The positive dimension that keeps a nop at 0.0: doing nothing saves
nothing but also never answers.
"""

import rewardkit as rk

rk.command_succeeds("grep -q 22 reply.txt")
