"""Deterministic store check: the toggle landed on the RIGHT item.

Near-duplicate lines are the point: 'email Sam about the invoice' (t2)
must be done while 'email Sam about the quarterly review' (t1) stays
open — the model had to read the file and match the exact line, not
guess by name.
"""

import rewardkit as rk

rk.command_succeeds("grep -Fq -- '- [x] email Sam about the invoice' notes/todo.md")
