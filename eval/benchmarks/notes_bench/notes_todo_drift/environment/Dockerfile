FROM python:3.12-slim

WORKDIR /workdir

# Arya's dependencies only — the adapter uploads the arya source itself at
# trial time (environment.upload_dir), so trials measure the local code.
# uv is needed by the verifier (rewardkit runs via uvx).
RUN pip install --no-cache-dir mlflow openai python-dotenv uv

# Seed a near-duplicate todo list at image build (the memory_recall
# pattern): same names, similar tasks, so the toggle must land on the
# right line. One printf format string, no extra arguments — printf
# re-applies its format per argument.
RUN mkdir -p /workdir/notes && printf -- \
    '- [ ] email Sam about the quarterly review <!-- t1 -->\n- [ ] email Sam about the invoice <!-- t2 -->\n- [ ] email Pam about the quarterly review <!-- t3 -->\n' \
    > /workdir/notes/todo.md

CMD ["bash"]
