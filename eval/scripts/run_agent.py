#!/usr/bin/env python3
"""Run the Arya agent (the local code) on tasks under
eval/benchmarks/<bench>/<task>/.

Unlike scripts/verify_tasks.py (oracle + nop, validating the verifiers),
this measures the agent itself: N attempts per task, reporting per-trial
rewards and a per-task mean.

Each sweep is imported into MLflow as traces (experiment
arya-eval/<timestamp>, one session per trial) — set ARYA_EVAL_MLFLOW=0
to skip the import, ARYA_EVAL_EXPERIMENT to name the experiment.

Task selection (positional args, default: all tasks in all benchmarks):
    memory_bench                 every task in that benchmark
    memory_bench/memory_save     one specific task

Usage (from eval/):
    uv run python scripts/run_agent.py [attempts] [bench | bench/task ...]
                                                       # attempts default 3
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mlflow_import import begin_run as mlflow_begin_run, enabled as mlflow_enabled, log_trial

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = ROOT / "benchmarks"
AGENT = "arya_harbor:AryaAgent"


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


def run_task(task: Path, attempts: int) -> tuple[str, list[Path]]:
    """Run the agent on one task; returns (job_dir, trial result paths)."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "agent")}
    proc = subprocess.run(
        harbor_command()
        + ["run", "-p", str(task.relative_to(ROOT)), "-a", AGENT, "-k", str(attempts)],
        input="Y",
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    match = re.search(r"jobs/(\S+?)/result\.json", proc.stdout + proc.stderr)
    if not match:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:], file=sys.stderr)
        raise SystemExit(
            f"no job result found for {task.relative_to(BENCHMARKS_DIR)}"
        )
    job_dir = ROOT / "jobs" / match.group(1)
    return match.group(1), sorted(job_dir.glob("*/result.json"))


def trial_reward(result: dict) -> float | None:
    return ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")


def main() -> int:
    args = sys.argv[1:]
    attempts = int(args[0]) if args else 3
    tasks = select_tasks(args[1:])
    if not tasks:
        raise SystemExit(f"no tasks found under {BENCHMARKS_DIR}")
    print(f"{len(tasks)} task(s), {attempts} attempt(s) each, agent {AGENT}\n")
    if mlflow_enabled():
        print(f"MLflow import: on (experiment {mlflow_begin_run()})\n")

    ok = True
    for task in tasks:
        name = str(task.relative_to(BENCHMARKS_DIR))
        job, trials = run_task(task, attempts)
        rewards = []
        for trial in trials:
            result = json.loads(trial.read_text())
            if result.get("exception_info"):
                print(f"FAIL {name}/{trial.parent.name}: exception"
                      f" {result['exception_info']}")
                ok = False
                continue
            reward = trial_reward(result)
            if reward is None:
                print(f"FAIL {name}/{trial.parent.name}: no reward in result")
                ok = False
                continue
            print(f"pass {name}/{trial.parent.name}: reward {reward}")
            # Opt-in (ARYA_EVAL_MLFLOW=1): the trial becomes an MLflow trace.
            log_trial(trial.parent, name, reward)
            rewards.append(reward)
        if len(rewards) != attempts:
            print(f"FAIL {name}: {len(rewards)} scored trials,"
                  f" expected {attempts} (job {job})")
            ok = False
            continue
        mean = sum(rewards) / len(rewards)
        print(f"--> {name}: mean {mean:.3f} over {len(rewards)} trials\n")

    print("DONE" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
