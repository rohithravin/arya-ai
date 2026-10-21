"""Persistent notes store for Arya: a jailed directory of markdown files.

Pure IO, no tool knowledge (mirroring arya.memory.store). See
docs/notes.md for the design: path-jail, canonical relative-path ids,
provenance frontmatter, secret screening, CAS read-tokens, a soft-delete
`.trash/` with restore, numeric caps, and the turn-start digest.
"""

import hashlib
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from arya import env  # noqa: F401  (loads .env before the notes path is read)

DEFAULT_NOTES_DIR = Path.home() / ".arya" / "notes"

# --- Numeric caps (one tunable place) ---------------------------------------

MAX_NOTE_BYTES = 64 * 1024  # whole-file write cap
MAX_APPEND_BYTES = 8 * 1024  # per-append cap
MAX_READ_BYTES = 16 * 1024  # read_note result cap
MAX_READ_LINES = 400  # read_note result cap (whichever binds first)
PREVIEW_CHARS = 80
FIND_LIST_LIMIT = 50
FIND_QUERY_LIMIT = 20
DIGEST_MAX_LINES = 50
DIGEST_MAX_CHARS = 2048
TRASH_RETENTION_DAYS = 30

# --- Name rules --------------------------------------------------------------

# Dot-prefixed components are reserved everywhere (.trash/, editor junk).
_DOT_COMPONENT = re.compile(r"^\.")
# Control characters, separators, and glob/escape metacharacters never
# appear in a usable note name.
_ILLEGAL_CHARS = re.compile(r"[\x00-\x1f\\/`$*?{}\[\]<>|;\"'&!~^]")
# Create-time slug normalization (write-only: existing files are addressed
# byte-for-byte by the id find/read returned).
_SLUG_STRIP = re.compile(r"[^a-z0-9 ._/-]+")
_SLUG_COLLAPSE = re.compile(r"[ /]+")

# Secret-shaped content is refused at write time ("store where the secret
# lives", never in a note). Deliberately conservative patterns.
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),  # generic API key prefix
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:api[-_]?key|secret|token|password)\b\s*[:=]\s*\S{12,}", re.I),
)

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def notes_dir() -> Path:
    raw = os.environ.get("ARYA_NOTES_DIR", str(DEFAULT_NOTES_DIR))
    root = Path(raw).expanduser()
    if not root.is_absolute():
        # A relative path silently creates a second, empty vault from a
        # different CWD — the memory.md lesson: that looks like data loss.
        raise ValueError(f"ARYA_NOTES_DIR must be absolute after ~ expansion: {raw!r}")
    return root


# --- Path jail ---------------------------------------------------------------


def _validate_components(name: str) -> PurePosixPath:
    """Validate a note id and return its normalized PurePosixPath.

    Raises ValueError on any escape form; never touches the filesystem.
    """
    if not name or not isinstance(name, str):
        raise ValueError("note name must be a non-empty string")
    if "\x00" in name or "\\" in name:
        raise ValueError("note name contains an illegal character")
    if "%" in name:
        # No URL-encoded traversal to decode-and-check; refuse outright.
        raise ValueError("note name must not contain '%'")
    p = PurePosixPath(name)
    if p.is_absolute():
        raise ValueError("note name must be relative to the notes root")
    if any(part in ("", ".", "..") for part in p.parts):
        raise ValueError("note name must not contain '.' or '..' components")
    for part in p.parts:
        if _DOT_COMPONENT.match(part):
            raise ValueError(f"dot-prefixed paths are reserved: {part!r}")
        if _ILLEGAL_CHARS.search(part):
            raise ValueError(f"note name component has illegal characters: {part!r}")
    return p


def _resolve(name: str) -> Path:
    """Canonicalize a validated name against the root, rejecting symlinks."""
    root = notes_dir()
    rel = _validate_components(name)
    current = root
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink in notes path: {part!r}")
    target = root / rel
    # lstat of the final component too: a symlinked note file must not be
    # followed (the TOCTOU class that shipped as CVE-2026-34452).
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"note exists but is not a regular file: {name!r}")
    return target


def slugify(name: str) -> str:
    """Create-time normalization; write-only (existing ids pass through)."""
    p = _validate_components(name)
    parts = []
    for part in p.parts:
        part = _SLUG_COLLAPSE.sub("-", part.strip().lower())
        part = _SLUG_STRIP.sub("", part).strip("-._ ")
        if part:
            parts.append(part)
    if not parts:
        raise ValueError("note name has no usable characters")
    result = "/".join(parts)
    if not result.endswith(".md"):
        result += ".md"
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _now_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_token(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _screen_secrets(content: str) -> str | None:
    for pattern in SECRET_PATTERNS:
        m = pattern.search(content)
        if m:
            return m.group(0)[:24]
    return None


# --- Frontmatter (provenance) ------------------------------------------------


def _write_frontmatter(source: str = "agent") -> str:
    return f"---\nsource: {source}\nmodified: {_now_iso()}\n---\n"


def _frontmatter_block(text: str | None) -> str:
    """The (refreshed) frontmatter block for a note: new, or updated-in-place.

    Provenance (`source`) is preserved — it is a fact about origin, not
    recency; `modified` is refreshed on every mutation.
    """
    today = _now_iso()
    if text and (m := FRONTMATTER_RE.match(text)):
        inner = m.group(1)
        inner = re.sub(r"^modified:.*$", f"modified: {today}", inner, flags=re.M)
        if "modified:" not in inner:
            inner += f"\nmodified: {today}"
        return f"---\n{inner}\n---\n"
    return _write_frontmatter()


def _strip_frontmatter(text: str) -> str:
    if m := FRONTMATTER_RE.match(text):
        return text[m.end() :]
    return text


# --- Listing / search --------------------------------------------------------


def _iter_notes() -> list[Path]:
    """All notes as absolute paths, mtime-ordered, newest first."""
    root = notes_dir()
    if not root.exists():
        return []
    paths = [
        p
        for p in root.rglob("*.md")
        if ".trash" not in p.parts and not _DOT_COMPONENT.match(p.name)
    ]
    return sorted(paths, key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True)


def _preview(text: str) -> str:
    for line in _strip_frontmatter(text).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:PREVIEW_CHARS]
    return "(empty note)"


def find(query: str | None = None, limit: int | None = None) -> dict:
    """Discovery: list with previews, or filename-first then content search."""
    notes = _iter_notes()
    if not query:
        cap = limit or FIND_LIST_LIMIT
        entries = []
        for p in notes[:cap]:
            entries.append(
                {
                    "name": _rel(p),
                    "preview": _preview(p.read_text(errors="replace")),
                    "bytes": p.stat().st_size,
                }
            )
        return {"notes": entries, "total": len(notes)}

    terms = [t.lower() for t in query.split() if t.strip()]
    cap = limit or FIND_QUERY_LIMIT
    matches: list[dict] = []
    # Filenames first — "calendar" must hit topics/calendar.md even if the
    # body never says it.
    for p in notes:
        if len(matches) >= cap:
            break
        if any(t in str(_rel(p)).lower() for t in terms):
            matches.append({"name": _rel(p), "match": "filename"})
    # Then contents, case-insensitive substring, first matching line
    # (reported in its original casing, not the lowered search copy).
    for p in notes:
        if len(matches) >= cap:
            break
        if any(m["name"] == _rel(p) for m in matches):
            continue
        lines = _strip_frontmatter(p.read_text(errors="replace")).splitlines()
        for line in lines:
            if any(t in line.lower() for t in terms):
                matches.append(
                    {"name": _rel(p), "match": line.strip()[:PREVIEW_CHARS]}
                )
                break
    return {"matches": matches, "total": len(matches)}


def _rel(p: Path) -> str:
    return str(p.relative_to(notes_dir()))


def read(name: str, offset: int = 0) -> dict:
    """Full contents with a truncation flag, read_token, and modified time."""
    path = _resolve(name)
    if not path.exists():
        return {"error": f"no note named {name!r}"}
    text = path.read_text(errors="replace")
    body = _strip_frontmatter(text)
    lines = body.splitlines(keepends=True)
    window = lines[offset:]
    if len(window) > MAX_READ_LINES or sum(len(l) for l in window) > MAX_READ_BYTES:
        window = window[:MAX_READ_LINES]
        truncated = True
        next_offset = offset + len(window)
    else:
        truncated = False
        next_offset = None
    return {
        "name": _rel(path),
        "content": "".join(window),
        "truncated": truncated,
        "next_offset": next_offset,
        "read_token": _read_token(path),
        "modified": _modified_of(path),
    }


def _modified_of(path: Path) -> str:
    text = path.read_text(errors="replace")
    if m := FRONTMATTER_RE.match(text):
        fm = m.group(1)
        if mm := re.search(r"^modified:\s*(.+)$", fm, re.M):
            return mm.group(1).strip()
    return datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%MZ")


# --- Writes ------------------------------------------------------------------


def _backup(path: Path, tag: str) -> Path:
    """Copy a note into .trash/<ns>-<tag>/<relpath> (relative path preserved)."""
    root = notes_dir()
    entry = root / ".trash" / f"{time.time_ns()}-{tag}"
    dest = entry / _rel(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest


def _prune_trash() -> None:
    """Retention: trash entries older than TRASH_RETENTION_DAYS disappear."""
    root = notes_dir()
    trash = root / ".trash"
    if not trash.exists():
        return
    cutoff = time.time() - TRASH_RETENTION_DAYS * 86400
    for entry in trash.iterdir():
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry)
        except OSError:
            pass  # retention is hygiene, never a hard failure


def _check_content(content: str, cap: int) -> dict | None:
    if not content.strip():
        return {"error": "content must not be empty"}
    if len(content.encode()) > cap:
        return {"error": f"content exceeds {cap} bytes"}
    if secret := _screen_secrets(content):
        return {
            "error": (
                f"content looks like a secret ({secret!r}); do not store"
                " secrets in notes — store where the secret lives"
            )
        }
    return None


def write(
    name: str,
    content: str,
    mode: str = "create",
    read_token: str | None = None,
) -> dict:
    if mode not in ("create", "append", "replace"):
        return {"error": "mode must be create, append, or replace"}
    rel = _validate_components(name)

    if mode == "create":
        # Slug-normalize only on create: existing files are addressed by
        # the exact id find/read returned.
        slugged = slugify(name)
        path = _resolve(slugged)
        if path.exists():
            siblings = [_rel(p) for p in _iter_notes() if p.parent == path.parent][:10]
            return {
                "error": f"note {slugged!r} already exists; use append or edit",
                "existing_in_directory": siblings,
            }
        if err := _check_content(content, MAX_NOTE_BYTES):
            return err
        path.parent.mkdir(parents=True, exist_ok=True)
        text = _write_frontmatter() + content.rstrip("\n") + "\n"
        _tmp_write(path, text)
        return {"name": _rel(path), "created": True, "bytes": len(text.encode())}

    path = _resolve(str(rel))

    if mode == "append":
        if err := _check_content(content, MAX_APPEND_BYTES):
            return err
        path.parent.mkdir(parents=True, exist_ok=True)
        body = content.rstrip("\n") + "\n"
        if path.exists():
            existing = path.read_text(errors="replace")
            old_body = _strip_frontmatter(existing)
            # Date-section headers only under topics/: an undated running
            # document (todo.md, scratch/) reads better as a flat log.
            if path.parent.relative_to(notes_dir()).parts[:1] == ("topics",):
                body = _append_header(existing) + body
            text = _frontmatter_block(existing) + old_body + body
            _tmp_write(path, text)
        else:
            # No header on a note's first entry; the frontmatter dates it.
            text = _write_frontmatter() + body
            _tmp_write(path, text)
        return {"name": _rel(path), "appended": True}

    if mode == "replace":
        if _rel(path) == "todo.md":
            return {"error": "todo.md may only be appended or edited, never replaced"}
        if not path.exists():
            return {"error": f"no note named {name!r} to replace"}
        if not read_token:
            return {"error": "replace requires the read_token from a recent read_note"}
        if err := _check_content(content, MAX_NOTE_BYTES):
            return err
        current_token = _read_token(path)
        if read_token != current_token:
            return {
                "error": "note changed since read (token mismatch); re-read"
                " and retry",
                "read_token": current_token,
                "current_content": _capped(path),
            }
        _backup(path, "replace")
        # Preserve the provenance header, refresh modified, new body.
        text = _frontmatter_block(path.read_text(errors="replace"))
        text += content.rstrip("\n") + "\n"
        _tmp_write(path, text)
        _prune_trash()
        return {"name": _rel(path), "replaced": True}


def _append_header(existing: str) -> str:
    """A dated section header unless the last section is already today's."""
    body = _strip_frontmatter(existing)
    today = _now_date()
    headers = re.findall(r"^### (\d{4}-\d{2}-\d{2})", body, re.M)
    return "" if headers and headers[-1] == today else f"### {today}\n"


def _tmp_write(path: Path, text: str) -> Path:
    """Atomic write: temp file in the target directory, then os.replace."""
    tmp = path.parent / f".{path.name}.{time.time_ns()}.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _capped(path: Path) -> str:
    body = _strip_frontmatter(path.read_text(errors="replace"))
    return body[:PREVIEW_CHARS * 8]


def edit(
    name: str,
    old_text: str,
    new_text: str,
    read_token: str | None = None,
) -> dict:
    """Exact-match correction: gated, backed up, loud on drift or ambiguity."""
    if not old_text:
        return {"error": "old_text must not be empty"}
    if len(new_text.encode()) > MAX_APPEND_BYTES:
        return {"error": f"new_text exceeds {MAX_APPEND_BYTES} bytes"}
    if secret := _screen_secrets(new_text):
        return {"error": f"new_text looks like a secret ({secret!r})"}
    path = _resolve(name)
    if not path.exists():
        return {"error": f"no note named {name!r}"}
    if not read_token:
        return {"error": "edit_note requires the read_token from a recent read_note"}
    if read_token != _read_token(path):
        return {
            "error": "note changed since read (token mismatch); re-read and retry",
            "read_token": _read_token(path),
            "current_content": _capped(path),
        }
    text = path.read_text(errors="replace")
    body = _strip_frontmatter(text)
    # CRLF normalization: a human editor's save must not break every
    # future edit.
    body = body.replace("\r\n", "\n")
    old_norm = old_text.replace("\r\n", "\n")
    count = body.count(old_norm)
    if count == 0:
        return {
            "error": "old_text not found; the note may have changed",
            "current_content": _capped(path),
        }
    if count > 1:
        return {
            "error": f"old_text matches {count} places; provide a longer,"
            " unambiguous match",
            "current_content": _capped(path),
        }
    _backup(path, "edit")
    new_body = body.replace(old_norm, new_text, 1)
    text = _frontmatter_block(text) + new_body
    _tmp_write(path, text)
    return {"name": _rel(path), "edited": True}


def delete(name: str) -> dict:
    """Soft delete: move to .trash/<ns>-delete/<relpath>, restorable."""
    path = _resolve(name)
    if not path.exists():
        return {"error": f"no note named {name!r}"}
    entry = notes_dir() / ".trash" / f"{time.time_ns()}-delete"
    dest = entry / _rel(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dest)
    _prune_trash()
    return {"name": _rel(path), "deleted": True, "restorable": True}


def restore(name: str) -> dict:
    """Restore the most recent .trash entry for a name (delete or backup)."""
    root = notes_dir()
    rel = _validate_components(name)
    trash = root / ".trash"
    if not trash.exists():
        return {"error": f"no trashed note named {name!r}"}
    candidates = sorted(
        (e for e in trash.iterdir() if (e / str(rel)).exists()),
        key=lambda e: e.name,
        reverse=True,
    )
    if not candidates:
        return {"error": f"no trashed note named {name!r}"}
    src = candidates[0] / str(rel)
    live = root / str(rel)
    if live.exists():
        return {
            "error": f"a note named {name!r} already exists; delete or edit"
            " it first",
            "existing": _rel(live),
            "trashed_copy": str(src.relative_to(root)),
        }
    live.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, live)
    return {"name": _rel(live), "restored": True}


# --- Turn-start digest --------------------------------------------------------


def digest() -> str | None:
    """The capped, always-derived vault overview injected at every turn.

    Generated from files on every call, so it cannot go stale. Never
    truncates silently: overflow is reported, not dropped.
    """
    root = notes_dir()
    if not root.exists() or not _iter_notes():
        return None
    lines: list[str] = ["notes vault:"]
    notes = _iter_notes()
    shown, dropped = 0, 0
    for p in notes:
        line = f"- {_rel(p)} — {_preview(p.read_text(errors='replace'))}"
        lines.append(line)
        shown += 1
        if shown >= DIGEST_MAX_LINES:
            dropped = len(notes) - shown
            break
    if dropped > 0:
        lines.append(f"(+{dropped} more notes — search find_notes)")
    todo = root / "todo.md"
    if todo.exists():
        body = _strip_frontmatter(todo.read_text(errors="replace"))
        todo_lines = [l for l in body.splitlines() if l.strip()][:8]
        lines.append("todo.md:")
        lines.extend(f"  {l}" for l in todo_lines)
    text = "\n".join(lines)
    if len(text) > DIGEST_MAX_CHARS:
        text = text[:DIGEST_MAX_CHARS] + "\n(notes digest truncated — search find_notes)"
    return text
