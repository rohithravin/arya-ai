"""Memory tools: `remember` and `recall` over the memory store."""

from arya.memory import store
from arya.tools import registry


def _remember(args: dict) -> object:
    supersedes = args.get("supersedes")
    if supersedes is not None and not isinstance(supersedes, int):
        return {"error": "supersedes must be an integer memory id"}
    conn = store._connect()
    try:
        store._init_schema(conn)
        result = store.remember(
            conn,
            content=str(args.get("content", "")),
            category=str(args.get("category", "")),
            supersedes=supersedes,
        )
        # The new row is committed even when supersession failed, so the
        # store now holds two active facts. Give the model what it needs to
        # close the loop: the ids still active on this topic, one of which
        # it can retry against.
        if "supersession_failed" in result:
            matches = store.recall(conn, result["saved"])
            if isinstance(matches, list):
                result["active_memories_matching"] = [
                    {"id": m["id"], "content": m["content"]}
                    for m in matches
                    if m["id"] != result["id"]
                ]
            result["hint"] = (
                "the outdated memory is still active; retry remember with"
                " supersedes set to the matching memory's id"
            )
        return result
    finally:
        conn.close()


def _recall(args: dict) -> object:
    conn = store._connect()
    try:
        store._init_schema(conn)
        return store.recall(conn, str(args.get("query", "")))
    finally:
        conn.close()


registry.register(
    "remember",
    {
        "description": (
            "Save a durable fact about the user or their life. Use only"
            " for durable facts, preferences, people, and goals — not"
            " conversation filler. To replace an existing (now outdated)"
            " memory, pass its id as supersedes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "One atomic, self-contained fact.",
                },
                "category": {
                    "type": "string",
                    "enum": list(store.CATEGORIES),
                },
                "supersedes": {
                    "type": "integer",
                    "description": (
                        "Id of the outdated memory this one replaces"
                        " (from recall). Omit for new facts."
                    ),
                },
            },
            "required": ["content", "category"],
        },
    },
    _remember,
)

registry.register(
    "recall",
    {
        "description": (
            "Search your saved memories. Call early when a topic involves"
            " people, places, projects, or habits the user has mentioned"
            " before."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text search query.",
                }
            },
            "required": ["query"],
        },
    },
    _recall,
)
