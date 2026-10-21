#!/usr/bin/env python3
"""Import eval trial trajectories into MLflow as traces.

On by default (each run_agent.py sweep lands in MLflow); set
ARYA_EVAL_MLFLOW=0 to skip it. Hierarchy, matching arya's REPL
conventions:

- experiment = one run_agent.py invocation (arya-eval/<timestamp>,
  overridable via ARYA_EVAL_EXPERIMENT)
- session    = one trial/attempt (mlflow.trace.session = the harbor trial
  name, e.g. memory_save__HuxLkii — each attempt is its own group under
  the Session column in the MLflow UI)
- trace      = one trial: request = the task instruction, response = the
  agent's final reply, intermediate_outputs = the full ATIF steps,
  tags = task / trial / reward for filtering

Uses the same MLFLOW_TRACKING_URI convention as arya itself (default
sqlite:///mlflow.db, from the eval project directory).
"""

import json
import os
from pathlib import Path
from datetime import datetime

# Repo root (not cwd) so eval traces and arya's REPL traces share one store
# at <repo>/mlflow.db instead of sprouting per-directory mlflow.db files.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_experiment: str | None = None


def enabled() -> bool:
    return os.environ.get("ARYA_EVAL_MLFLOW", "1") != "0"


def begin_run() -> str:
    """Open a uniquely named experiment for this run_agent invocation."""
    global _experiment
    _experiment = os.environ.get(
        "ARYA_EVAL_EXPERIMENT",
        f"arya-eval/{datetime.now().strftime('%Y-%m-%d__%H-%M-%S')}",
    )
    return _experiment


def _render_transcript(steps: list[dict]) -> str:
    """Human-readable transcript: messages, tool calls, and tool results."""
    lines: list[str] = []
    for s in steps:
        source = s.get("source")
        msg = s.get("message") or ""
        if source == "agent":
            lines.append(f"[assistant] {msg}".rstrip())
            for call in s.get("tool_calls") or []:
                args = json.dumps(call.get("arguments") or {})
                lines.append(f"  -> tool call: {call.get('function_name')}({args})")
            for result in (s.get("observation") or {}).get("results") or []:
                lines.append(f"  <- tool result: {result.get('content')}")
        else:
            lines.append(f"[{source}] {msg}".rstrip())
    return "\n".join(lines)


def _trial_window(trial_dir: Path) -> tuple[int, int] | None:
    """(start_ms, end_ms) of the agent phase, from result.json."""
    try:
        result = json.loads((trial_dir / "result.json").read_text())
        agent = result.get("agent_execution") or {}
        started, finished = agent.get("started_at"), agent.get("finished_at")
        if not (started and finished):
            return None
        from datetime import datetime

        def epoch_ms(iso: str) -> float:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000

        return int(epoch_ms(started)), int(epoch_ms(finished))
    except (OSError, ValueError):
        return None


def log_trial(trial_dir: Path, task: str, reward: float | None) -> str | None:
    """Log one trial's trajectory.json to MLflow; returns the trace id.

    Builds a real span tree (root span for the trial, an LLM span per model
    call, a TOOL span per tool call) via the low-level tracing client —
    mlflow.log_trace is deprecated (and only ever logged one flat span).
    Per-step timing isn't in the ATIF export, so child spans get synthetic
    sequential sub-intervals of the trial's real wall-clock window.

    No-op (returns None) unless ARYA_EVAL_MLFLOW=1.
    """
    if not enabled():
        return None

    import uuid

    import mlflow
    from mlflow.entities import Span as MlflowSpan, SpanType, TraceState
    from mlflow.entities.trace_location import (
        MlflowExperimentLocation,
        TraceLocation,
        TraceLocationType,
    )
    from mlflow.tracing.client import TraceInfo, TracingClient
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
    from opentelemetry.trace.status import Status, StatusCode

    if not os.environ.get("MLFLOW_TRACKING_URI"):
        mlflow.set_tracking_uri(f"sqlite:///{_REPO_ROOT / 'mlflow.db'}")
    # Create the experiment with an explicit artifact location — the
    # low-level span store needs one, and plain set_experiment leaves it
    # None on a sqlite tracking store (which log_spans then trips over).
    exp_name = _experiment or "arya-eval"
    client = TracingClient(tracking_uri=mlflow.get_tracking_uri())
    store_client = mlflow.MlflowClient(tracking_uri=mlflow.get_tracking_uri())
    experiment = store_client.get_experiment_by_name(exp_name)
    if experiment is None:
        store_client.create_experiment(
            exp_name, artifact_location=f"file://{_REPO_ROOT / 'mlartifacts'}"
        )
        experiment = store_client.get_experiment_by_name(exp_name)
    if not experiment.artifact_location:
        raise RuntimeError(
            f"experiment {exp_name!r} has no artifact location (created by an"
            " older import path); delete it and rerun to recreate it properly"
        )

    traj = json.loads((trial_dir / "agent" / "trajectory.json").read_text())
    steps = traj.get("steps") or []
    request = next(
        (s.get("message") for s in steps if s.get("source") == "user"), ""
    )
    response = next(
        (s.get("message") for s in reversed(steps) if s.get("source") == "agent"),
        "",
    )
    window = _trial_window(trial_dir) or (None, None)
    duration_ms = (window[1] - window[0]) if window else None

    # One OTel trace per trial: root span + child spans per step, each
    # wrapped as an MLflow Span for client.log_spans.
    trace_id = uuid.uuid4().hex
    root_id = int(uuid.uuid4().hex[:16], 16)
    context = SpanContext(
        trace_id=int(trace_id, 16),
        span_id=root_id,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    root = ReadableSpan(
        name=task,
        context=context,
        attributes={
            # mlflow reads the trace id from this attribute, not the OTel
            # context — without it, log_spans sees trace_id=None and fails.
            "mlflow.traceRequestId": trace_id,
            "mlflow.spanType": SpanType.CHAIN,
            # flat primitives only — dicts JSON-encoded
            "mlflow.spanInputs": json.dumps({"instruction": request}),
            "mlflow.spanOutputs": json.dumps({"reply": response}),
            "arya.eval.transcript": _render_transcript(steps),
            "arya.eval.synthetic_timing": "true",
        },
        kind=SpanKind.INTERNAL,
        status=Status(StatusCode.OK),
        start_time=(window[0] or 0) * 1_000_000,
        end_time=(window[1] or 0) * 1_000_000,
    )
    spans = [MlflowSpan(root)]

    # Child spans: one per model call / tool call, in step order, spread
    # evenly over the trial window (synthetic timing, flagged above).
    n_children = sum(
        max(1, len(s.get("tool_calls") or [])) if s.get("source") == "agent" else 0
        for s in steps
    )
    slot_ms = (duration_ms / (n_children + 1)) if duration_ms and n_children else 0
    t = window[0] if window else 0

    def child_span(name: str, span_type: str, attrs: dict, width_ms: int) -> None:
        nonlocal t
        t += slot_ms
        spans.append(
            MlflowSpan(
                ReadableSpan(
                    name=name,
                    context=SpanContext(
                        trace_id=int(trace_id, 16),
                        span_id=int(uuid.uuid4().hex[:16], 16),
                        is_remote=True,
                        trace_flags=TraceFlags(TraceFlags.SAMPLED),
                    ),
                    parent=context,
                    attributes={
                        "mlflow.traceRequestId": trace_id,
                        "mlflow.spanType": span_type,
                        **{
                            k: (json.dumps(v) if isinstance(v, dict) else v)
                            for k, v in attrs.items()
                        },
                    },
                    kind=SpanKind.INTERNAL,
                    status=Status(StatusCode.OK),
                    start_time=int(t) * 1_000_000,
                    end_time=int(t + width_ms) * 1_000_000,
                )
            )
        )

    for s in steps:
        if s.get("source") != "agent":
            continue
        call = s.get("tool_calls") or []
        obs = (s.get("observation") or {}).get("results") or []
        attrs = {"message": s.get("message") or ""}
        if s.get("metrics"):
            attrs.update(
                {
                    f"mlflow.tokenCount.{k}": v
                    for k, v in s["metrics"].items()
                    if v is not None
                }
            )
        child_span(
            f"model call ({s.get('step_id')})",
            SpanType.LLM,
            attrs,
            slot_ms,
        )
        for c in call:
            # Each observation result pairs with its tool call by
            # source_call_id — show only this call's result, not the
            # whole step's list.
            own = next(
                (r for r in obs if r.get("source_call_id") == c.get("tool_call_id")),
                None,
            )
            child_span(
                f"tool: {c.get('function_name')}",
                SpanType.TOOL,
                {
                    "mlflow.spanInputs": json.dumps(c.get("arguments") or {}),
                    "mlflow.spanOutputs": json.dumps(
                        own.get("content") if own else None
                    ),
                },
                slot_ms,
            )

    info = TraceInfo(
        trace_id=trace_id,
        trace_location=TraceLocation(
            type=TraceLocationType.MLFLOW_EXPERIMENT,
            mlflow_experiment=MlflowExperimentLocation(experiment.experiment_id),
        ),
        request_time=window[0] or 0,
        state=TraceState.OK,
        request_preview=request[:200],
        response_preview=response[:200],
        client_request_id=None,
        execution_duration=duration_ms,
        tags={
            "mlflow.traceName": task,
            # One session per trial/attempt (like the REPL's
            # per-conversation session): each attempt is its own group
            # under the Session column in the MLflow UI.
            "mlflow.trace.session": trial_dir.name,
            "task": task,
            "trial": trial_dir.name,
            "reward": "" if reward is None else str(reward),
        },
    )
    client.start_trace(info)
    client.log_spans(experiment.experiment_id, spans)
    return trace_id
