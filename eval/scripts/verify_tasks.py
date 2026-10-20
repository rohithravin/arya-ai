#!/usr/bin/env python3
"""Verifier sanity for all tasks under eval/tasks/.

For every task: the oracle (reference solution) must score reward 1.0 on
every attempt, and nop (do nothing) must score 0.0 on every attempt. This
validates the verifiers themselves — cheap, and agent-free in the sense
that no agent behavior is involved, only the task's solution + verifier.

Usage (from eval/):
    uv run python scripts/verify_tasks.py [attempts]   # default 5
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "tasks"


def harbor_command() -> list[str]:
    if shutil.which("harbor"):
        return ["harbor"]
    return ["uv", "tool", "run", "harbor"]


def run_trials(task: Path, agent: str, attempts: int) -> tuple[str, list[Path]]:
    """Run one task with one agent; returns (job_dir, trial result paths)."""
    proc = subprocess.run(
        harbor_command()
        + ["run", "-p", str(task.relative_to(ROOT)), "-a", agent, "-k", str(attempts)],
        input="Y",
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    match = re.search(r"jobs/(\S+?)/result\.json", proc.stdout + proc.stderr)
    if not match:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:], file=sys.stderr)
        raise SystemExit(f"no job result found for {task.name}/{agent}")
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
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    tasks = sorted(p for p in TASKS_DIR.iterdir() if (p / "task.toml").is_file())
    if not tasks:
        raise SystemExit(f"no tasks found under {TASKS_DIR}")
    print(f"{len(tasks)} task(s), {attempts} attempt(s) each, oracle + nop\n")

    ok = True
    for task in tasks:
        for agent, expected in (("oracle", 1.0), ("nop", 0.0)):
            job, trials = run_trials(task, agent, attempts)
            if len(trials) != attempts:
                print(
                    f"FAIL {task.name}/{agent}: {len(trials)} trials,"
                    f" expected {attempts} (job {job})"
                )
                ok = False
                continue
            ok = check(task.name, agent, expected, trials) and ok
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
