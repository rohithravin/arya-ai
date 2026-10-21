FROM python:3.12-slim

WORKDIR /workdir

# Arya's dependencies only — the adapter uploads the arya source itself at
# trial time (environment.upload_dir), so trials measure the local code.
# uv is needed by the verifier (rewardkit runs via uvx).
RUN pip install --no-cache-dir mlflow openai python-dotenv uv

# Seed the memory store at image build: the exact schema arya's store.py
# creates, with unrelated facts — and deliberately NOTHING about the
# user's dad, the thing the instruction asks about.
COPY seed_memories.py /tmp/seed_memories.py
RUN python /tmp/seed_memories.py && rm /tmp/seed_memories.py

CMD ["bash"]
