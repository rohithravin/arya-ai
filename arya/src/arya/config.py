import os
from pathlib import Path

from arya import env  # noqa: F401  (loads .env before settings are read)

# Anchored at the repo root (not cwd) so the REPL and the eval harness
# share one store instead of each sprouting its own mlflow.db.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings:
    fireworks_api_key: str = os.environ["FIREWORKS_API_KEY"]
    fireworks_base_url: str = os.environ.get(
        "FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"
    )
    model: str = os.environ.get(
        "ARYA_MODEL", "accounts/fireworks/models/glm-5p3-flash"
    )
    mlflow_tracking_uri: str = os.environ.get(
        "MLFLOW_TRACKING_URI", f"sqlite:///{_REPO_ROOT / 'mlflow.db'}"
    )
    mlflow_experiment: str = os.environ.get("MLFLOW_EXPERIMENT", "arya")
    stream_delay_ms: float = float(os.environ.get("ARYA_STREAM_DELAY_MS", "20"))


settings = Settings()
