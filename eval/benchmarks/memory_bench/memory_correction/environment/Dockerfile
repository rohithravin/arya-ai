FROM python:3.12-slim

WORKDIR /workdir

# Arya's dependencies only — the adapter uploads the arya source itself at
# trial time (environment.upload_dir), so trials measure the local code.
# uv is needed by the verifier (rewardkit runs via uvx).
RUN pip install --no-cache-dir mlflow openai python-dotenv uv

# Seed the memory store at image build: the exact schema arya's store.py
# creates (table + FTS5 index + triggers), with one stale fact the agent
# must correct via supersession.
COPY seed_memories.py /tmp/seed_memories.py
RUN python /tmp/seed_memories.py && rm /tmp/seed_memories.py

CMD ["bash"]
