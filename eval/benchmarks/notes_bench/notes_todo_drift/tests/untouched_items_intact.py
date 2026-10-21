"""Deterministic store check: untouched items survived byte-exact.

The documented TodoWrite failure mode is a whole-list rewrite losing
items; a toggle that only flipped one line leaves the others exactly as
seeded, id comments included.
"""

import rewardkit as rk

rk.command_succeeds(
    "grep -Fq -- '- [ ] email Sam about the quarterly review <!-- t1 -->'"
    " notes/todo.md"
    " && grep -Fq -- '- [ ] email Pam about the quarterly review <!-- t3 -->'"
    " notes/todo.md"
)
