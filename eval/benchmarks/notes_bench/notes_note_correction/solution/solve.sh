#!/bin/bash
# Reference solution: correct the seeded note in place (the stale
# decision replaced, not appended as a contradiction) and produce the
# reply artifact.
set -eu

cat > /workdir/notes/topics/ci-choice.md <<'EOF'
---
source: agent
modified: 2026-10-21T00:00Z
---
We chose Forge for CI. Deploys run on every merge to main.
EOF

cat > /workdir/reply.txt <<'EOF'
Fixed — your CI note now says Forge, with the GitHub Actions decision removed.
EOF
