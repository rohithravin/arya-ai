#!/usr/bin/env python3
"""Verifier sanity for tasks under eval/benchmarks/<bench>/<task>/.

For every selected task: the oracle (reference solution) must score reward
1.0 on every attempt, and nop (do nothing) must score 0.0 on every attempt.
This validates the verifiers themselves — cheap, and agent-free in the
sense that no agent behavior is involved, only the task's solution +
verifier.

Task selection (positional args, default: all tasks in all benchmarks):
    memory_bench                 every task in that benchmark
    memory_bench/memory_save     one specific task

Usage (from eval/):
    uv run python scripts/verify_tasks.py [attempts] [bench | bench/task ...]
                                                       # attempts default 5
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = ROOT / "benchmarks"
ARYA_ENV = ROOT.parent / "arya" / ".env"


def harbor_env() -> dict[str, str]:
    """The environment for harbor: FIREWORKS_API_KEY from arya/.env first,
    then the shell — the order arya uses locally. Harbor substitutes it into
    each task's `${FIREWORKS_API_KEY}` (the verifier's LLM judges)."""
    key = dotenv_values(ARYA_ENV).get("FIREWORKS_API_KEY") or os.environ.get(
        "FIREWORKS_API_KEY", ""
    )
    return {**os.environ, "FIREWORKS_API_KEY": key}


def harbor_command() -> list[str]:
    if shutil.which("harbor"):
        return ["harbor"]
    return ["uv", "tool", "run", "harbor"]


def select_tasks(args: list[str]) -> list[Path]:
    """Resolve bench and bench/task selectors to task directories."""
    all_tasks = sorted(
        p.parent for p in BENCHMARKS_DIR.glob("*/*/task.toml")
    )
    if not args:
        return all_tasks

    by_name = {str(t.relative_to(BENCHMARKS_DIR)): t for t in all_tasks}
    benches = {t.parent.name for t in all_tasks}
    selected: list[Path] = []
    for arg in args:
        if arg in by_name:  # bench/task
            selected.append(by_name[arg])
        elif arg in benches:
            selected.extend(t for t in all_tasks if t.parent.name == arg)
        else:
            known = "\n  ".join(
                sorted(b for b in benches)
                + sorted(by_name)
            )
            raise SystemExit(
                f"unknown selector {arg!r}; known benchmarks/tasks:\n  {known}"
            )
    return selected


def run_trials(task: Path, agent: str, attempts: int) -> tuple[str, list[Path]]:
    """Run one task with one agent; returns (job_dir, trial result paths)."""
    proc = subprocess.run(
        harbor_command()
        + ["run", "-p", str(task.relative_to(ROOT)), "-a", agent, "-k", str(attempts)],
        input="Y",
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=harbor_env(),
    )
    match = re.search(r"jobs/(\S+?)/result\.json", proc.stdout + proc.stderr)
    if not match:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:], file=sys.stderr)
        raise SystemExit(f"no job result found for {task.relative_to(BENCHMARKS_DIR)}/{agent}")
    job_dir = ROOT / "jobs" / match.group(1)
    return match.group(1), sorted(job_dir.glob("*/result.json"))


def check(task_name: str, agent: str, expected: float, trials: list[Path]) -> bool:
    ok = True
    for trial in trials:
        result = json.loads(trial.read_text())
        exception = result.get("exception_info")
        reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get(
            "reward"
        )
        name = trial.parent.name
        if exception:
            print(f"FAIL {task_name}/{agent}/{name}: exception {exception}")
            ok = False
        elif reward != expected:
            print(f"FAIL {task_name}/{agent}/{name}: reward {reward}, expected {expected}")
            ok = False
        else:
            print(f"pass {task_name}/{agent}/{name}: reward {reward}")
    return ok


def main() -> int:
    args = sys.argv[1:]
    attempts = int(args[0]) if args else 5
    tasks = select_tasks(args[1:])
    if not tasks:
        raise SystemExit(f"no tasks found under {BENCHMARKS_DIR}")
    print(f"{len(tasks)} task(s), {attempts} attempt(s) each, oracle + nop\n")

    ok = True
    for task in tasks:
        name = str(task.relative_to(BENCHMARKS_DIR))
        for agent, expected in (("oracle", 1.0), ("nop", 0.0)):
            job, trials = run_trials(task, agent, attempts)
            if len(trials) != attempts:
                print(
                    f"FAIL {name}/{agent}: {len(trials)} trials,"
                    f" expected {attempts} (job {job})"
                )
                ok = False
                continue
            ok = check(name, agent, expected, trials) and ok
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
