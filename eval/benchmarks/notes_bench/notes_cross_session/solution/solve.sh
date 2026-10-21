#!/bin/bash
# Reference solution: write the note directly (no arya dependency — the
# oracle runs without the adapter's source upload) and produce every
# artifact the driver would (reply.txt, sessions.json, per-session
# replies). Every verifier dimension must be satisfiable.
set -eu

mkdir -p /workdir/notes/topics /workdir/replies

cat > /workdir/notes/topics/deployment-window.md <<'EOF'
---
source: agent
modified: 2026-10-21T00:00Z
---
The production deployment window is Saturdays 06:00-08:00 UTC.
EOF

cat > /workdir/replies/session-1.txt <<'EOF'
Noted — saved the deployment window: Saturdays 06:00-08:00 UTC.
EOF

cat > /workdir/replies/session-2.txt <<'EOF'
The production deployment window is Saturdays 06:00-08:00 UTC.
EOF

cat > /workdir/reply.txt <<'EOF'
The production deployment window is Saturdays 06:00-08:00 UTC.
EOF

cat > /workdir/sessions.json <<'EOF'
[
  {
    "session": 1,
    "instruction": "Hey, quick thing before I forget — we do our prod deploys in a Saturday morning window, 06:00-08:00 UTC. Can you save that as a note so we don't lose it?",
    "reply": "Noted — saved the deployment window: Saturdays 06:00-08:00 UTC.",
    "messages": [],
    "usage": [],
    "model": "oracle"
  },
  {
    "session": 2,
    "instruction": "What was that deployment window I told you about earlier?",
    "reply": "The production deployment window is Saturdays 06:00-08:00 UTC.",
    "messages": [],
    "usage": [],
    "model": "oracle"
  }
]
EOF
