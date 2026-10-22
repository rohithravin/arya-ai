FROM python:3.12-slim

WORKDIR /workdir

# Arya's dependencies only — the adapter uploads the arya source itself at
# trial time (environment.upload_dir), so trials measure the local code.
# uv is needed by the verifier (rewardkit runs via uvx).
RUN pip install --no-cache-dir mlflow openai python-dotenv uv

# Seed an outdated decision note at image build (the memory_recall
# pattern), agent-native with provenance frontmatter.
RUN mkdir -p /workdir/notes/topics && printf -- \
    '---\nsource: agent\nmodified: 2026-10-01T00:00Z\n---\nWe chose GitHub Actions for CI. Deploys run on every merge to main.\n' \
    > /workdir/notes/topics/ci-choice.md

CMD ["bash"]
