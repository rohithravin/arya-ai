"""Notes tools over the jailed notes store. See docs/notes.md for the design."""

from arya.notes import store
from arya.tools import registry

_FIND_SCHEMA = {
    "description": (
        "List or search your notes. Without a query: every note with a"
        " one-line preview (≤50) plus a total count. With a query:"
        " matches by filename first, then by content (≤20). Open only"
        " the relevant notes — never the whole vault."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text search terms, or omit to list all notes.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (optional).",
            },
        },
        "required": [],
    },
}


def _find(args: dict) -> object:
    return store.find(args.get("query") or None, args.get("limit"))


_READ_SCHEMA = {
    "description": (
        "Read one note's full contents. The result includes a read_token"
        " — required by write_note(replace) and edit_note for their"
        " changed-since-read check. Use next_offset to continue a"
        " truncated read."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Note path relative to the notes root, exactly as find_notes returned.",
            },
            "offset": {
                "type": "integer",
                "description": "Line to start from (for a truncated read's next_offset).",
            },
        },
        "required": ["name"],
    },
}


def _read(args: dict) -> object:
    offset = args.get("offset") or 0
    if not isinstance(offset, int) or offset < 0:
        return {"error": "offset must be a non-negative integer"}
    return store.read(str(args.get("name", "")), offset)


_WRITE_SCHEMA = {
    "description": (
        "Write a note. mode 'create' (default) makes a new note and"
        " fails if the name exists. 'append' adds an entry to an"
        " existing note (creating it if absent) — the default for"
        " anything that should keep history. 'replace' rewrites the"
        " whole file and requires the read_token from a recent"
        " read_note; it refuses todo.md. Never store secrets in notes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Note path (find_notes returns canonical names)."},
            "content": {"type": "string", "description": "The note entry or full contents."},
            "mode": {
                "type": "string",
                "enum": ["create", "append", "replace"],
                "description": "create (default), append, or replace.",
            },
            "read_token": {
                "type": "string",
                "description": "Required for replace: the token from a recent read_note.",
            },
        },
        "required": ["name", "content"],
    },
}


def _write(args: dict) -> object:
    mode = args.get("mode", "create")
    if mode not in ("create", "append", "replace"):
        return {"error": "mode must be create, append, or replace"}
    read_token = args.get("read_token")
    if read_token is not None and not isinstance(read_token, str):
        return {"error": "read_token must be a string"}
    return store.write(
        str(args.get("name", "")),
        str(args.get("content", "")),
        mode=mode,
        read_token=read_token,
    )


_EDIT_SCHEMA = {
    "description": (
        "Correct one passage of a note: old_text must match exactly and"
        " unambiguously in the note (after CRLF normalization). Requires"
        " the read_token from a recent read_note. The default tool for"
        " fixing a stale or wrong note; new_text may be empty to remove"
        " a passage."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Note path, exactly as find_notes returned."},
            "old_text": {"type": "string", "description": "The exact text to replace."},
            "new_text": {"type": "string", "description": "The replacement (may be empty)."},
            "read_token": {"type": "string", "description": "The token from a recent read_note."},
        },
        "required": ["name", "old_text", "read_token"],
    },
}


def _edit(args: dict) -> object:
    read_token = args.get("read_token")
    if not isinstance(read_token, str) or not read_token:
        return {"error": "read_token (from a recent read_note) is required"}
    return store.edit(
        str(args.get("name", "")),
        str(args.get("old_text", "")),
        str(args.get("new_text", "")),
        read_token=read_token,
    )


_DELETE_SCHEMA = {
    "description": (
        "Delete a whole note (soft delete: it is moved to the vault's"
        " trash and is restorable with restore_note). To remove one"
        " passage or todo item, use edit_note instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Note path, exactly as find_notes returned."}
        },
        "required": ["name"],
    },
}


def _delete(args: dict) -> object:
    return store.delete(str(args.get("name", "")))


_RESTORE_SCHEMA = {
    "description": (
        "Undo a delete_note or a destructive write_note(edit) on a note:"
        " restores the most recent trashed copy. Refuses if a live note"
        " already has that name."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Note path to restore."}
        },
        "required": ["name"],
    },
}


def _restore(args: dict) -> object:
    return store.restore(str(args.get("name", "")))


registry.register("find_notes", _FIND_SCHEMA, _find)
registry.register("read_note", _READ_SCHEMA, _read)
registry.register("write_note", _WRITE_SCHEMA, _write)
registry.register("edit_note", _EDIT_SCHEMA, _edit)
registry.register("delete_note", _DELETE_SCHEMA, _delete)
registry.register("restore_note", _RESTORE_SCHEMA, _restore)
