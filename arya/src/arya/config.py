import os

from arya import env  # noqa: F401  (loads .env before settings are read)


class Settings:
    fireworks_api_key: str = os.environ["FIREWORKS_API_KEY"]
    fireworks_base_url: str = os.environ.get(
        "FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"
    )
    model: str = os.environ.get(
        "ARYA_MODEL", "accounts/fireworks/models/glm-5p3-flash"
    )
    mlflow_tracking_uri: str = os.environ.get(
        "MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"
    )
    mlflow_experiment: str = os.environ.get("MLFLOW_EXPERIMENT", "arya")
    stream_delay_ms: float = float(os.environ.get("ARYA_STREAM_DELAY_MS", "20"))


settings = Settings()
