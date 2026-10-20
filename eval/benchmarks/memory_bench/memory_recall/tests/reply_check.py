"""Deterministic reply check: the answer states the remembered date."""

import rewardkit as rk

rk.file_contains("reply.txt", "June 12")
