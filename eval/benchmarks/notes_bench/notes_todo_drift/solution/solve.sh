#!/bin/bash
# Reference solution: the seeded todo list with the dentist item added and
# the invoice item toggled — every other line byte-identical to the seed.
# Produces the reply artifact too.
set -eu

cat > /workdir/notes/todo.md <<'EOF'
- [ ] email Sam about the quarterly review <!-- t1 -->
- [x] email Sam about the invoice <!-- t2 -->
- [ ] email Pam about the quarterly review <!-- t3 -->
- [ ] book the dentist <!-- t4 -->
EOF

cat > /workdir/reply.txt <<'EOF'
Done — "book the dentist" is on the list, and I crossed off the Sam invoice email. The quarterly-review emails to Sam and Pam are still open.
EOF
