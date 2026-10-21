FROM python:3.12-slim

WORKDIR /workdir

# Arya's dependencies only — the adapter uploads the arya source itself at
# trial time (environment.upload_dir), so trials measure the local code.
# uv is needed by the verifier (rewardkit runs via uvx).
RUN pip install --no-cache-dir mlflow openai python-dotenv uv

CMD ["bash"]
