"""Tool registry: the single source of truth for agent-callable tools.

A tool is a name, an OpenAI function schema, and a callable taking the parsed
argument dict. `registry` aggregates them for `chat.completions.create(tools=)`
and `execute()` dispatches a call. Every tool failure returns an error string
— `execute` never raises into the agent loop.
"""

import json
from collections.abc import Callable

import mlflow
from mlflow.entities import SpanType

ToolFn = Callable[[dict], object]

_TOOLS: dict[str, tuple[ToolFn, dict]] = {}


def register(name: str, schema: dict, fn: ToolFn) -> None:
    if name in _TOOLS:
        raise ValueError(f"tool {name!r} is already registered")
    _TOOLS[name] = (fn, schema)


def schemas() -> list[dict]:
    return [
        {"type": "function", "function": {"name": name, **schema}}
        for name, (_, schema) in _TOOLS.items()
    ]


def names() -> set[str]:
    return set(_TOOLS)


def execute(name: str, arguments_json: str, tool_call_id: str | None = None) -> str:
    """Run a tool by name; returns the JSON tool-result string."""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"invalid arguments: {exc}"})
    if not isinstance(args, dict):
        return json.dumps({"error": "arguments must be a JSON object"})
    if name not in _TOOLS:
        return json.dumps({"error": f"unknown tool: {name}"})
    fn, _ = _TOOLS[name]
    # One span per tool, named after the tool, so MLflow traces can be
    # filtered per tool. tool_call_id is recorded for observation
    # correlation (e.g. ATIF export).
    with mlflow.start_span(name=name, span_type=SpanType.TOOL) as span:
        span.set_inputs(args)
        if tool_call_id:
            span.set_attribute("tool_call_id", tool_call_id)
        try:
            result = fn(args)
        except Exception as exc:  # tool failure is recoverable for the model
            result = {"error": f"tool {name} failed: {exc}"}
            span.set_attribute("error", str(exc))
        span.set_outputs(result)
        return json.dumps(result)
