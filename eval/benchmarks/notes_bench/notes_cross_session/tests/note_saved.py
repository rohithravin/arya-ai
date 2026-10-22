"""Deterministic store check: the window was saved as a note on disk."""

import rewardkit as rk

# The note's filename is the model's choice (slug); grep the vault. The
# trash subtree is excluded: a note written and then soft-deleted was not
# saved.
rk.command_succeeds("grep -rqi 'saturday' notes/ --exclude-dir=.trash")
