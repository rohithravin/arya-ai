"""Deterministic store check: the meeting went into the notes vault."""

import rewardkit as rk

# The task is notes_bench: an agent that routes the meeting to `remember`
# instead must not pass. Filename is the model's slug, so grep the vault;
# todo.md is excluded (appending the action item to the todo list is not
# saving the meeting note), and so is the trash subtree.
rk.command_succeeds(
    "grep -rqEi 'renew|expir|contract' notes/"
    " --exclude-dir=.trash --exclude=todo.md"
)
