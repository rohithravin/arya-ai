#!/bin/bash
# Reference solution: the store is pre-seeded by the task's Dockerfile
# (with nothing about the user's dad), so the oracle only produces the
# reply artifact. Both verifier dimensions must be satisfiable.
set -eu

cat > /workdir/reply.txt <<'EOF'
I don't have your dad's birthday in my notes yet. If you tell me, I'll remember it!
EOF
