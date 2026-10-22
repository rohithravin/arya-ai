"""Tests for the multi-session instruction splitter (adapter side).

The session-break marker is task authors' input surface: malformed shapes
must fail loudly (a typo silently renumbering sessions corrupts trials),
and the normal shapes must split exactly.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from arya_harbor import split_sessions  # noqa: E402


def test_single_instruction_untouched():
    assert split_sessions("Remember my sister's birthday is June 12.") == [
        "Remember my sister's birthday is June 12."
    ]


def test_two_sessions():
    assert split_sessions(
        "Save this note: deploy Saturdays.\n"
        "--- SESSION BREAK ---\n"
        "What's the deployment window?"
    ) == ["Save this note: deploy Saturdays.", "What's the deployment window?"]


def test_crlf_instructions():
    assert split_sessions(
        "first\r\n--- SESSION BREAK ---\r\nsecond"
    ) == ["first", "second"]


def test_marker_with_trailing_whitespace():
    assert split_sessions("a\n--- SESSION BREAK ---  \nb") == ["a", "b"]


def test_three_sessions_preserve_order():
    assert split_sessions("a\n--- SESSION BREAK ---\nb\n--- SESSION BREAK ---\nc") == [
        "a",
        "b",
        "c",
    ]


@pytest.mark.parametrize(
    "bad",
    [
        # Marker only: no sessions at all.
        "--- SESSION BREAK ---",
        # Doubled marker: an empty session between them.
        "a\n--- SESSION BREAK ---\n--- SESSION BREAK ---\nb",
        # Missing session text before the marker.
        "--- SESSION BREAK ---\nsecond",
        # Mid-line marker: prose, not a session break.
        "please explain --- SESSION BREAK --- to me",
    ],
)
def test_malformed_shapes_raise(bad):
    with pytest.raises(ValueError):
        split_sessions(bad)
