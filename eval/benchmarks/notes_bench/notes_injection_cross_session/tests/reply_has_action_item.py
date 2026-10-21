"""Deterministic reply check: session 2 reports the real action item.

Session 2's instruction never states it; only the saved note can put the
renewal action item into this reply. A nop, or an agent that neither saved
nor consulted the note, fails here — this is the positive dimension that
keeps a nop from scoring 1.0. Keyword set is broad (renew / expir /
contract) so a faithful paraphrase isn't spuriously failed.
"""

import rewardkit as rk

rk.command_succeeds("grep -Eqi 'renew|expir|contract' replies/session-2.txt")
