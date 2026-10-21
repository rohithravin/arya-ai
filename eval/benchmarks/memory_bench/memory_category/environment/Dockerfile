FROM python:3.12-slim

WORKDIR /workdir

# Arya's dependencies only — the adapter uploads the arya source itself at
# trial time (environment.upload_dir), so trials measure the local code.
# uv is needed by the verifier (rewardkit runs via uvx).
RUN pip install --no-cache-dir mlflow openai python-dotenv uv

# Seed an EMPTY memory store (schema only, zero rows) at build time: the
# agent's tools create the schema lazily on first use, so without this a
# verifier query against a store the agent never touched would error
# instead of reading 0.
COPY seed_memories.py /tmp/seed_memories.py
RUN python /tmp/seed_memories.py && rm /tmp/seed_memories.py

CMD ["bash"]
