import mlflow

from arya.config import settings


def init_tracing() -> None:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment)
    mlflow.openai.autolog()
