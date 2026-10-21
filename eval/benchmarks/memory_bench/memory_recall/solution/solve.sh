#!/bin/bash
# Reference solution: the store is pre-seeded by the task's Dockerfile, so
# the oracle only produces the reply artifact. Both verifier dimensions
# (deterministic reply check + judges) must be satisfiable.
set -eu

cat > /workdir/reply.txt <<'EOF'
Your sister Priya's birthday is June 12.
EOF
