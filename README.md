# arya-ai

Agentic Personal Assistant — a personal project to build a life-assistant
agent on a hand-rolled harness (no agent framework/SDK underneath).

## Layout

- [`arya/`](arya/) — the agent itself: a uv-managed Python project with the
  harness (model loop, tracing). See [`arya/README.md`](arya/README.md) to
  run it, and [`arya/docs/architecture.md`](arya/docs/architecture.md) for
  how it's built.
- `eval/` — offline evaluation harness for Arya's traced runs. Not started
  yet.

## Stack

- **Model access:** [Fireworks](https://fireworks.ai) (open models, via its
  OpenAI-compatible API)
- **Language:** Python, managed with [uv](https://docs.astral.sh/uv/)
- **Observability:** OpenTelemetry tracing, viewed through
  [MLflow](https://mlflow.org)
