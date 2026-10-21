"""Deterministic store check: the correction exists in the vault."""

import rewardkit as rk

rk.command_succeeds("grep -rqi forge notes/ --exclude-dir=.trash")
