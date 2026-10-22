"""Tests for the notes store and the notes tools.

Each test gets a fresh vault via the `notes_dir` fixture. These are the
hardening tests from docs/notes.md build order step 4: path jail, round
trips, conflict CAS, restore, caps, todo semantics. Pure filesystem — no
model, no network.
"""

import json
import os
import stat

import pytest

from arya.notes import store
from arya.tools import execute


@pytest.fixture()
def notes_dir(tmp_path, monkeypatch):
    path = tmp_path / "notes"
    path.mkdir()
    monkeypatch.setenv("ARYA_NOTES_DIR", str(path))
    return path


def call(tool, **args):
    return json.loads(execute(tool, json.dumps(args)))


def write(name, content, mode="create", read_token=None):
    args = {"name": name, "content": content, "mode": mode}
    if read_token is not None:
        args["read_token"] = read_token
    return call("write_note", **args)


def read(name, offset=0):
    return call("read_note", name=name, offset=offset)


def edit(name, old_text, new_text, read_token):
    return call(
        "edit_note", name=name, old_text=old_text, new_text=new_text,
        read_token=read_token,
    )


# --- Path jail ---------------------------------------------------------------


ESCAPE_NAMES = [
    "../escape.md",
    "/etc/passwd",
    "a/../../b.md",
    ".trash/foo.md",
    ".git/config",
    "topics/.hidden.md",
    "topics/x%2e%2e.md",
    "topics/x\\..\\y.md",
    "topics/nul\x00byte.md",
    "",
]


@pytest.mark.parametrize("name", ESCAPE_NAMES)
def test_jail_rejects_escape_names(notes_dir, name):
    assert "error" in write(name, "nope")
    assert "error" in read(name)
    assert not list(notes_dir.rglob("*.md"))


def test_jail_rejects_symlinked_note_file(notes_dir):
    target = notes_dir.parent / "outside.md"
    target.write_text("stolen")
    (notes_dir / "innocent.md").symlink_to(target)
    assert "error" in read("innocent.md")
    assert "error" in edit(
        "innocent.md", "stolen", "x", read_token="0" * 16
    )
    # The symlink must never have been followed: the target is untouched.
    assert target.read_text() == "stolen"


def test_jail_rejects_symlinked_parent_directory(notes_dir):
    # The CVE-2026-34452 class: an lstat of the final component only
    # misses a symlinked parent. The whole path must be walked.
    real = notes_dir.parent / "elsewhere"
    real.mkdir()
    (notes_dir / "topics").mkdir()
    (notes_dir / "topics" / "sub").symlink_to(real)
    assert "error" in write("topics/sub/evil.md", "nope")
    assert not (real / "evil.md").exists()


def test_jail_rejects_fifo(notes_dir):
    os.mkfifo(notes_dir / "pipe.md")
    assert "error" in read("pipe.md")


def test_jail_rejects_relative_notes_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARYA_NOTES_DIR", "relative/notes")
    with pytest.raises(ValueError):
        store.notes_dir()


# --- Round trips ---------------------------------------------------------------


def test_create_append_read(notes_dir):
    assert write("topics/design.md", "First entry.")["created"]
    assert write("topics/design.md", "Second entry.", mode="append")["appended"]
    result = read("topics/design.md")
    body = result["content"]
    # First entry undated (frontmatter dates it), append gets a dated header.
    assert body.index("First entry.") < body.index("Second entry.")
    assert "### " in body
    assert result["truncated"] is False


def test_append_same_day_single_header(notes_dir):
    write("topics/log.md", "One.", mode="append")
    write("topics/log.md", "Two.", mode="append")
    body = read("topics/log.md")["content"]
    assert body.count("### ") == 1


def test_append_creates_file_without_header(notes_dir):
    write("todo.md", "- [ ] first <!-- t1 -->", mode="append")
    body = read("todo.md")["content"]
    assert "### " not in body
    assert "- [ ] first" in body


def test_create_duplicate_refused_with_siblings(notes_dir):
    write("topics/design.md", "entry")
    result = write("topics/design.md", "again")
    assert "error" in result
    assert "topics/design.md" in result.get("existing_in_directory", [])


def test_create_slugifies_only_on_create(notes_dir):
    write("topics/My Design Notes.md", "entry")
    assert (notes_dir / "topics" / "my-design-notes.md").exists()
    # A human-created non-slug file is addressed byte-for-byte, never
    # split by normalization. (Directory name differs by more than case:
    # APFS is case-insensitive, so "Topics" vs "topics" is one directory.)
    handwritten = notes_dir / "Journal" / "My Notes.md"
    handwritten.parent.mkdir(parents=True)
    handwritten.write_text("human note")
    result = read("Journal/My Notes.md")
    assert "human note" in result["content"]
    # Appending to it lands in the same file, not a slug-cased twin.
    write("Journal/My Notes.md", "appended line", mode="append")
    assert "appended line" in read("Journal/My Notes.md")["content"]
    assert not (notes_dir / "journal" / "my-notes.md").exists()


def test_find_lists_with_previews_and_total(notes_dir):
    write("topics/alpha.md", "Alpha body text")
    write("topics/beta.md", "Beta body text")
    result = call("find_notes")
    assert result["total"] == 2
    names = [n["name"] for n in result["notes"]]
    assert "topics/alpha.md" in names and "topics/beta.md" in names


def test_find_matches_filename_first(notes_dir):
    write("topics/calendar.md", "Nothing about dates in the body at all.")
    result = call("find_notes", query="calendar")
    assert result["matches"][0] == {
        "name": "topics/calendar.md",
        "match": "filename",
    }


def test_find_matches_contents_case_insensitively(notes_dir):
    write("topics/food.md", "The QUARTERLY numbers were strong.")
    result = call("find_notes", query="quarterly")
    assert result["matches"][0]["name"] == "topics/food.md"
    assert "QUARTERLY" in result["matches"][0]["match"]


def test_find_short_tokens_work(notes_dir):
    # find_notes deliberately does NOT reuse recall's >=3-char token rule.
    write("topics/ml.md", "Notes about ML ops.")
    assert call("find_notes", query="ML")["matches"][0]["name"] == "topics/ml.md"


def test_find_excludes_trash(notes_dir):
    write("topics/gone.md", "bye")
    call("delete_note", name="topics/gone.md")
    assert call("find_notes")["total"] == 0
    assert call("find_notes", query="bye")["matches"] == []


def test_digest_reports_overflow_not_silent_truncation(notes_dir, monkeypatch):
    monkeypatch.setattr(store, "DIGEST_MAX_LINES", 3)
    for i in range(6):
        write(f"topics/n{i}.md", f"note number {i}")
    text = store.digest()
    assert "notes vault:" in text
    assert "+3 more notes" in text  # never silently dropped


def test_digest_includes_todo_and_none_when_empty(notes_dir):
    assert store.digest() is None
    write("todo.md", "- [ ] one <!-- t1 -->", mode="append")
    text = store.digest()
    assert "todo.md:" in text
    assert "- [ ] one" in text


# --- Conflict CAS -------------------------------------------------------------


def test_replace_requires_token(notes_dir):
    write("topics/a.md", "original")
    assert "error" in write("topics/a.md", "new", mode="replace")


def test_replace_rejects_stale_token(notes_dir):
    write("topics/a.md", "original")
    assert "error" in write("topics/a.md", "new", mode="replace", read_token="0" * 16)
    # The original is intact.
    assert "original" in read("topics/a.md")["content"]


def test_replace_success_backs_up_and_replaces(notes_dir):
    write("topics/a.md", "original")
    token = read("topics/a.md")["read_token"]
    assert write("topics/a.md", "new body", mode="replace", read_token=token)["replaced"]
    assert "new body" in read("topics/a.md")["content"]
    # Pre-replace backup exists in .trash with the old content.
    backups = list((notes_dir / ".trash").rglob("a.md"))
    assert len(backups) == 1
    assert "original" in backups[0].read_text()


def test_edit_requires_and_checks_token(notes_dir):
    write("topics/a.md", "original text here")
    assert "error" in edit("topics/a.md", "original", "x", read_token="")
    assert "error" in edit("topics/a.md", "original", "x", read_token="0" * 16)
    token = read("topics/a.md")["read_token"]
    assert edit("topics/a.md", "original", "changed", read_token=token)["edited"]
    assert "changed" in read("topics/a.md")["content"]


def test_edit_backs_up_before_edit(notes_dir):
    write("topics/a.md", "keep this")
    token = read("topics/a.md")["read_token"]
    edit("topics/a.md", "keep this", "replaced this", read_token=token)
    backups = list((notes_dir / ".trash").rglob("a.md"))
    assert "keep this" in backups[0].read_text()


def test_edit_ambiguous_match_refuses(notes_dir):
    write("topics/a.md", "entry entry entry")
    token = read("topics/a.md")["read_token"]
    result = edit("topics/a.md", "entry", "x", read_token=token)
    assert result["error"].startswith("old_text matches 3 places")


def test_edit_missing_text_reports_current(notes_dir):
    write("topics/a.md", "actual content")
    token = read("topics/a.md")["read_token"]
    result = edit("topics/a.md", "not present", "x", read_token=token)
    assert "error" in result
    assert "current_content" in result


def test_edit_crlf_normalized_matching(notes_dir):
    # A human editor's Windows-style save must not break every future edit.
    (notes_dir / "topics" / "win.md").parent.mkdir(parents=True, exist_ok=True)
    (notes_dir / "topics" / "win.md").write_text("line one\r\nline two\r\n")
    token = read("topics/win.md")["read_token"]
    assert edit("topics/win.md", "line one\r\nline two", "flattened", read_token=token)["edited"]
    assert "flattened" in read("topics/win.md")["content"]


def test_edit_new_text_may_be_empty(notes_dir):
    write("topics/a.md", "stale passage\nkeep this")
    token = read("topics/a.md")["read_token"]
    assert edit("topics/a.md", "stale passage\n", "", read_token=token)["edited"]
    assert "stale" not in read("topics/a.md")["content"]


def test_own_write_updates_token(notes_dir):
    # The agent's own append must not leave the model's token valid-but-
    # stale in a way that looks like a human race; a fresh read after the
    # own write must always succeed.
    write("topics/a.md", "one")
    write("topics/a.md", "two", mode="append")
    token = read("topics/a.md")["read_token"]
    assert write("topics/a.md", "three", mode="replace", read_token=token)["replaced"]


# --- Delete / restore ----------------------------------------------------------


def test_delete_is_soft_and_restorable(notes_dir):
    write("topics/keep.md", "precious content")
    assert call("delete_note", name="topics/keep.md")["deleted"]
    assert "error" in read("topics/keep.md")
    assert call("find_notes")["total"] == 0
    assert call("restore_note", name="topics/keep.md")["restored"]
    assert "precious content" in read("topics/keep.md")["content"]


def test_restore_preserves_relative_path(notes_dir):
    # Two files with the same basename must not collide in .trash.
    write("a/keep.md", "content A")
    write("b/keep.md", "content B")
    call("delete_note", name="a/keep.md")
    call("delete_note", name="b/keep.md")
    assert call("restore_note", name="b/keep.md")["restored"]
    assert "content B" in read("b/keep.md")["content"]
    assert call("restore_note", name="a/keep.md")["restored"]
    assert "content A" in read("a/keep.md")["content"]


def test_restore_refuses_when_live_file_exists(notes_dir):
    write("topics/x.md", "original")
    call("delete_note", name="topics/x.md")
    write("topics/x.md", "replacement")
    result = call("restore_note", name="topics/x.md")
    assert "error" in result
    assert "replacement" in read("topics/x.md")["content"]


def test_restore_restores_edit_backups(notes_dir):
    write("topics/a.md", "before")
    token = read("topics/a.md")["read_token"]
    edit("topics/a.md", "before", "after", read_token=token)
    call("delete_note", name="topics/a.md")
    # The most recent .trash entry is the edit backup.
    assert call("restore_note", name="topics/a.md")["restored"]
    assert "after" in read("topics/a.md")["content"]


def test_trash_retention_prunes_old_entries(notes_dir, monkeypatch):
    write("topics/old.md", "content")
    call("delete_note", name="topics/old.md")
    entry = next((notes_dir / ".trash").iterdir())
    old = entry.stat().st_mtime - (store.TRASH_RETENTION_DAYS + 1) * 86400
    os.utime(entry, (old, old))
    write("topics/new.md", "content")  # any destructive op prunes
    call("delete_note", name="topics/new.md")
    assert not entry.exists()


def test_read_and_tools_cannot_reach_trash(notes_dir):
    write("topics/secret.md", "trashed content")
    call("delete_note", name="topics/secret.md")
    for name in (".trash", ".trash/anything.md"):
        assert "error" in read(name)


# --- Caps ----------------------------------------------------------------------


def test_empty_content_rejected_everywhere(notes_dir):
    write("topics/a.md", "filler")
    token = read("topics/a.md")["read_token"]
    assert "error" in write("topics/b.md", "   ")
    assert "error" in write("topics/a.md", " ", mode="append")
    # replace-with-empty is a delete by typo; deletes have their own tool.
    assert "error" in write("topics/a.md", "", mode="replace", read_token=token)


def test_write_caps_enforced(notes_dir):
    assert "error" in write("big.md", "x" * (store.MAX_NOTE_BYTES + 1))
    assert "error" in write(
        "topics/a.md", "y" * (store.MAX_APPEND_BYTES + 1), mode="append"
    )


def test_read_truncation_flags_and_offsets(notes_dir, monkeypatch):
    monkeypatch.setattr(store, "MAX_READ_LINES", 5)
    write("long.md", "\n".join(f"line {i}" for i in range(12)))
    first = read("long.md")
    assert first["truncated"] is True
    assert first["next_offset"] == 5
    second = read("long.md", offset=first["next_offset"])
    assert "line 5" in second["content"]


def test_find_limits_enforced(notes_dir):
    for i in range(store.FIND_LIST_LIMIT + 5):
        write(f"topics/n{i}.md", "filler")
    result = call("find_notes")
    assert len(result["notes"]) == store.FIND_LIST_LIMIT
    assert result["total"] == store.FIND_LIST_LIMIT + 5


def test_secret_screening_on_write(notes_dir):
    for secret in (
        "my key is sk-abcdefghijklmnopqrstuv",
        "aws key AKIAIOSFODNN7EXAMPLE here",
        "-----BEGIN RSA PRIVATE KEY-----",
        "api_key = supersecretvalue123",
    ):
        assert "error" in write("topics/keys.md", secret)
        assert not (notes_dir / "topics" / "keys.md").exists()


# --- Todo semantics -------------------------------------------------------------


def test_todo_replace_always_refused(notes_dir):
    write("todo.md", "- [ ] a <!-- t1 -->", mode="append")
    token = read("todo.md")["read_token"]
    assert "error" in write("todo.md", "- [ ] b <!-- t2 -->", mode="replace", read_token=token)


def test_todo_toggle_via_edit_only_touches_one_line(notes_dir):
    lines = [f"- [ ] task {i} <!-- t{i} -->" for i in range(5)]
    for line in lines:
        write("todo.md", line, mode="append")
    token = read("todo.md")["read_token"]
    result = edit("todo.md", "- [ ] task 2 <!-- t2 -->", "- [x] task 2 <!-- t2 -->", token)
    assert result["edited"]
    body = read("todo.md")["content"]
    assert "- [x] task 2" in body
    for i in (0, 1, 3, 4):
        assert f"- [ ] task {i} <!-- t{i} -->" in body


def test_edit_todo_refuses_without_fresh_read(notes_dir):
    write("todo.md", "- [ ] task <!-- t1 -->", mode="append")
    assert "error" in edit("todo.md", "- [ ] task", "- [x] task", read_token="stale")


# --- Provenance frontmatter -----------------------------------------------------


def test_frontmatter_written_and_modified_refreshed(notes_dir):
    write("topics/a.md", "body")
    first = read("topics/a.md")["modified"]
    assert read("topics/a.md")["content"].startswith("body")  # frontmatter stripped
    write("topics/a.md", "more", mode="append")
    second = read("topics/a.md")["modified"]
    assert second >= first
