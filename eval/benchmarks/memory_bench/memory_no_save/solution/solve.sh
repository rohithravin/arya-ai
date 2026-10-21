#!/bin/bash
# Reference solution: the store is pre-seeded empty (schema only) by the
# task's Dockerfile, so the oracle only produces the reply artifact. Both
# verifier dimensions (zero-rows store check + judges) must be satisfiable.
set -eu

cat > /workdir/reply.txt <<'EOF'
That sounds rough — bumper-to-bumper traffic before the day even starts is draining. Hope the commute home is kinder, and get some rest!
EOF
