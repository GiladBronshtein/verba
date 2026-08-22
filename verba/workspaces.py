"""Every document this machine knows about.

The console served one directory, decided when the process started. That is the
right shape for a tool built inside the single project it serves, and the wrong
shape for one that documents whatever you point it at: documenting a second
system meant a second terminal, a second port, and remembering which tab was
which.

A document is still just a folder with a `content/doc.yaml` in it. Nothing about
the format changes and nothing is centralised. This is only a list of where they
are, so the console can offer them and switch between them, kept in
`~/.verba/workspaces.json`.

An entry that no longer exists on disk is reported as missing rather than
quietly dropped: a document on an unmounted drive has not been deleted, and
removing it from the list would lose the only record of where it was.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from .atomic import write_json

REGISTRY = Path.home() / ".verba" / "workspaces.json"


def _load() -> dict:
    if not REGISTRY.exists():
        return {"documents": []}
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8")) or {"documents": []}
    except json.JSONDecodeError:
        return {"documents": []}


def _save(data: dict):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    write_json(REGISTRY, data)


def is_document(path: Path | str) -> bool:
    return (Path(path) / "content" / "doc.yaml").exists()


def product_of(path: Path | str) -> str:
    """What the document at this path is about, read from its own manifest."""
    try:
        cfg = yaml.safe_load(
            (Path(path) / "content" / "doc.yaml").read_text(encoding="utf-8")) or {}
        return str((cfg.get("product") or {}).get("name") or Path(path).name)
    except Exception:
        return Path(path).name


def remember(path: Path | str) -> dict:
    """Add a document to the list, or move it to the front if it is already on it."""
    path = str(Path(path).resolve())
    data = _load()
    docs = [d for d in data["documents"] if d.get("path") != path]
    entry = {"path": path, "product": product_of(path),
             "opened": datetime.now().isoformat(timespec="seconds")}
    data["documents"] = [entry] + docs
    _save(data)
    return entry


def forget(path: Path | str):
    """Take a document off the list. The folder itself is never touched."""
    path = str(Path(path).resolve())
    data = _load()
    data["documents"] = [d for d in data["documents"] if d.get("path") != path]
    _save(data)


def listing(current: Path | str | None = None) -> list[dict]:
    """Every remembered document, most recently opened first."""
    data = _load()
    now = str(Path(current).resolve()) if current else None
    out = []
    for d in data["documents"]:
        p = Path(d["path"])
        exists = is_document(p)
        out.append({
            "path": d["path"],
            "name": p.name,
            # Re-read the product name: a document that was renamed should not
            # keep answering to what it was called when it was first opened.
            "product": product_of(p) if exists else d.get("product", p.name),
            "opened": d.get("opened", ""),
            "exists": exists,
            "current": d["path"] == now,
        })
    if now and not any(d["current"] for d in out) and is_document(now):
        out.insert(0, {"path": now, "name": Path(now).name,
                       "product": product_of(now), "opened": "",
                       "exists": True, "current": True})
    return out


def default_home() -> Path:
    """Where a new document goes when nobody says otherwise."""
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "Verba"
