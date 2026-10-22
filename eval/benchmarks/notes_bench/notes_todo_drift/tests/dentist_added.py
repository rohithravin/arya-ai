"""Deterministic store check: the new todo item was added."""

import rewardkit as rk

rk.command_succeeds("grep -qi 'dentist' notes/todo.md")
