"""Tests for the memory store and the memory tools.

Each test gets a fresh database via the `db_path` fixture.
"""

import json

import pytest

from arya.memory import store
from arya.tools import execute


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "memories.db"
    monkeypatch.setenv("ARYA_MEMORY_DB", str(path))
    return path


def remember(content, category="fact", supersedes=None):
    args = {"content": content, "category": category}
    if supersedes is not None:
        args["supersedes"] = supersedes
    return json.loads(execute("remember", json.dumps(args)))


def recall(query):
    return json.loads(execute("recall", json.dumps({"query": query})))


# --- remember ---------------------------------------------------------------


def test_remember_returns_id_and_content(db_path):
    result = remember("Prefers morning workouts", category="preference")
    assert result == {"id": 1, "saved": "Prefers morning workouts"}


def test_remember_bad_category(db_path):
    assert "error" in remember("x", category="other")


def test_remember_empty_content(db_path):
    assert "error" in remember("   ")


def test_remember_too_long_content(db_path):
    assert "error" in remember("y" * 501)


def test_remember_bad_json(db_path):
    assert "error" in json.loads(execute("remember", "{content:"))


def test_unknown_tool(db_path):
    assert "error" in json.loads(execute("nope", "{}"))


def test_remember_supersedes(db_path):
    old = remember("Prefers morning workouts", category="preference")
    new = remember("Switched to evening workouts", category="preference",
                   supersedes=old["id"])
    assert "supersession_failed" not in new
    assert store.show_memory(old["id"])["chain"][0]["active"] is False


def test_remember_supersedes_unknown_id(db_path):
    result = remember("x fact", supersedes=99)
    assert "supersession_failed" in result


def test_remember_supersedes_non_integer(db_path):
    result = json.loads(execute(
        "remember", '{"content": "x", "category": "fact", "supersedes": "1"}'
    ))
    assert "error" in result


def test_remember_self_supersede(db_path):
    # Simulate rowid reuse: supersedes targets the id the new row gets.
    remember("first fact")
    next_id = max(m["id"] for m in store.list_memories()) + 1
    result = remember("self test", supersedes=next_id)
    assert "supersession_failed" in result
    assert store.show_memory(next_id)["chain"][0]["active"] is True


# --- recall -----------------------------------------------------------------


def test_recall_finds_saved_fact(db_path):
    remember("User works on arya-ai")
    # keyword-based recall; paraphrase matching ("gym" vs "workout") is a
    # documented v1 limitation — embeddings are the v2 fix
    results = recall("arya-ai")
    assert len(results) == 1
    assert results[0]["content"] == "User works on arya-ai"


def test_recall_excludes_superseded(db_path):
    old = remember("Prefers morning workouts", category="preference")
    remember("Switched to evening workouts", category="preference",
             supersedes=old["id"])
    contents = str(recall("workouts habit"))
    assert "morning workouts" not in contents


@pytest.mark.parametrize("query", [
    "arya-ai??", "c++", "user:likes coffee", "what's", "",
])
def test_recall_safe_on_arbitrary_text(db_path, query):
    results = recall(query)
    assert isinstance(results, list)


def test_recall_empty_db(db_path):
    assert recall("anything") == []


# --- inspection helpers ------------------------------------------------------


def test_list_and_filter(db_path):
    remember("a fact", category="fact")
    remember("a preference", category="preference")
    assert len(store.list_memories()) == 2
    listed = store.list_memories(category="fact")
    assert [m["content"] for m in listed] == ["a fact"]


def test_show_chain(db_path):
    old = remember("old fact")
    remember("new fact", supersedes=old["id"])
    chain = store.show_memory(old["id"])["chain"]
    assert chain[0]["superseded_by"] == 2
    assert chain[1]["id"] == 2


def test_delete_refuses_referenced(db_path):
    old = remember("old fact")
    new = remember("new fact", supersedes=old["id"])
    error = store.delete_memory(new["id"])
    assert error and "referenced" in error


def test_delete_force_nulls_chain(db_path):
    old = remember("old fact")
    new = remember("new fact", supersedes=old["id"])
    assert store.delete_memory(new["id"], force=True) is None
    assert store.show_memory(old["id"])["chain"][0]["superseded_by"] is None


def test_delete_missing(db_path):
    assert "no memory" in store.delete_memory(999)


def test_edit_bumps_and_validates(db_path):
    m = remember("original fact")
    assert store.edit_memory(m["id"], "corrected fact") is None
    listed = {mem["id"]: mem for mem in store.list_memories()}
    assert listed[m["id"]]["content"] == "corrected fact"
    assert "must not be empty" in store.edit_memory(m["id"], "   ")
    assert "exceeds" in store.edit_memory(m["id"], "z" * 501)


def test_fts_synced_after_delete_and_edit(db_path):
    m = remember("User works on arya-ai")
    gone = remember("temp fact")
    store.delete_memory(gone["id"])
    store.edit_memory(m["id"], "User works on the arya-ai repo")
    contents = str(recall("arya-ai"))
    assert "repo" in contents
    assert "temp fact" not in contents
