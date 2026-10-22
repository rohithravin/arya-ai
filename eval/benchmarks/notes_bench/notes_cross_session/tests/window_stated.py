"""Deterministic reply check: the actual window, not just the day."""

import rewardkit as rk

# The reply must state the time window. Dash- and phrasing-agnostic
# ("06:00-08:00", en-dash, "6-8am", "6 to 8") so a faithful paraphrase
# isn't spuriously failed; a short non-digit separator keeps it from
# matching unrelated digits.
rk.command_succeeds(
    "grep -Eqi '0?6[:.]?00[^0-9]{0,3}0?8[:.]?00|6[^0-9]{1,4}8'"
    " replies/session-2.txt"
)
