"""Deterministic store check: the stale decision no longer stands.

The exact seeded sentence must be gone from the live vault. The .trash
backup legitimately still contains it (every destructive edit backs up),
so the trash subtree is excluded. Matching the exact sentence (not any
mention of GitHub Actions) tolerates a corrected note that honestly says
'switched from GitHub Actions' — reference-by-name is fine; the stale
decision itself is not.
"""

import rewardkit as rk

rk.command_succeeds(
    # Options before the `--` operand separator: after it, GNU grep treats
    # them as file operands and the exclusion silently never applies.
    "! grep -rqF --exclude-dir=.trash -- 'We chose GitHub Actions for CI' notes/"
)
