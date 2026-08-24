"""Asset registry: deduplicated, canonically named screenshots and icons.

The legacy ``screenshots/`` folder holds 246 files with large groups of
byte-identical duplicates and opaque names (``dd_pub_ssp_saas_expanded.png``).
The content tree instead references stable names derived from the section that
uses the image, and a registry records where each one came from.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .atomic import write_json
from .imaging import auto_crop_image, distance, fingerprint


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def _rank(name: str) -> tuple:
    """Canonical-name preference: v2_ prefixed first, then shortest, then A-Z."""
    return (0 if name.startswith("v2_") else 1, len(name), name)


@dataclass
class Library:
    """Content-deduplicated view over a folder of screenshots."""
    root: Path
    by_hash: dict[str, list[str]] = field(default_factory=dict)
    canonical: dict[str, str] = field(default_factory=dict)   # hash -> best name
    prints: list = field(default_factory=list)                # (name, fp, size)

    @classmethod
    def load(cls, root: Path) -> "Library":
        lib = cls(root=Path(root))
        for p in sorted(lib.root.glob("*.png")):
            try:
                h = sha(p)
                Image.open(p).size
            except Exception:
                continue
            lib.by_hash.setdefault(h, []).append(p.name)
        for h, names in lib.by_hash.items():
            lib.canonical[h] = sorted(names, key=_rank)[0]
        for name in lib.canonical.values():
            try:
                cropped = auto_crop_image(Image.open(lib.root / name))
                lib.prints.append((name, fingerprint(cropped), cropped.size))
            except Exception:
                continue
        return lib

    def stats(self) -> dict:
        total = sum(len(v) for v in self.by_hash.values())
        return {"files": total, "unique": len(self.by_hash),
                "duplicates": total - len(self.by_hash)}

    def match(self, blob_img: Image.Image, tol: float = 0.45):
        """Best library file for an embedded image.

        Exact cropped-size agreement is the primary discriminator; the
        fingerprint breaks ties. Screenshots of one app share so much chrome
        that appearance alone is not decisive.
        """
        fp = fingerprint(blob_img)
        size = blob_img.size
        scored = []
        for name, lfp, lsize in self.prints:
            scored.append((0 if lsize == size else 1, distance(fp, lfp),
                           abs(lsize[0] - size[0]) + abs(lsize[1] - size[1]), name))
        if not scored:
            return None, 999.0
        scored.sort()
        exact, d, _, name = scored[0]
        if exact == 0 and d <= tol:
            return name, d
        if d <= 0.10:
            return name, d
        return None, d


def _read_registry(path: Path) -> tuple[dict, str]:
    """The registry, and in plain words whatever stopped it being read.

    The registry says where each picture came from. It is provenance, not
    content: without it every picture is still on disk and the document still
    builds. But it was read inside Project.load, so a file left half written by
    a killed capture stopped every command in the tool, including `status` and
    `lint`, whose entire job is to tell somebody what state the document is in.
    Refusing to say anything at all is the least useful moment to refuse.
    """
    if not path.exists():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        # A fault we recovered from still had a cause, and VERBA_TRACEBACK is
        # the one switch this tool tells people to reach for when they want the
        # cause. Swallowing it here would make that switch lie.
        if os.environ.get("VERBA_TRACEBACK"):
            traceback.print_exc()
        if isinstance(e, json.JSONDecodeError):
            return {}, f"{path.name} is not valid JSON: {e.msg} at line {e.lineno}"
        return {}, f"{path.name} could not be read: {e}"
    if not isinstance(data, dict):
        return {}, (f"{path.name} holds a {type(data).__name__} where a set of "
                    f"named entries belongs")
    return data, ""


@dataclass
class AssetStore:
    """Where the content tree keeps its images."""
    root: Path

    def __post_init__(self):
        self.root = Path(self.root)
        (self.root / "screenshots").mkdir(parents=True, exist_ok=True)
        (self.root / "icons").mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "registry.json"
        self.registry, self.registry_error = _read_registry(self.registry_path)
        if self.registry_error:
            print(f"the asset registry could not be read: {self.registry_error}.\n"
                  f"Carrying on without it. Every picture is still there and the "
                  f"document still builds; what is missing is the record of where "
                  f"each one came from, so rules that ask that question will say "
                  f"they do not know. The next thing that stores a picture keeps "
                  f"the unreadable file beside the new one.")

    def path_for(self, name: str) -> Path:
        sub = "icons" if name.startswith("icon-") else "screenshots"
        return self.root / sub / name

    def put_file(self, name: str, src: Path, **meta) -> str:
        shutil.copyfile(src, self.path_for(name))
        self.registry[name] = {"source": str(src), "sha": sha(self.path_for(name)), **meta}
        return name

    def put_blob(self, name: str, blob: bytes, **meta) -> str:
        self.path_for(name).write_bytes(blob)
        self.registry[name] = {"source": "embedded", "sha": sha(self.path_for(name)), **meta}
        return name

    def save(self):
        # A registry nothing could parse is still the only copy of what it
        # held, and a person reading it can often see what a parser cannot.
        # Writing straight over it would trade that for a file holding one
        # entry and no history, so it is kept beside the new one instead.
        if getattr(self, "registry_error", "") and self.registry_path.exists():
            spare = self.registry_path.with_suffix(".json.unreadable")
            self.registry_path.replace(spare)
            print(f"the unreadable asset registry was kept as {spare.name}, and a "
                  f"new one written in its place. Delete it once you have looked.")
            self.registry_error = ""
        write_json(self.registry_path, self.registry, sort_keys=True)

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def all_names(self) -> list[str]:
        return sorted([p.name for p in (self.root / "screenshots").glob("*.png")]
                      + [p.name for p in (self.root / "icons").glob("*.png")])

    def duplicate_groups(self) -> dict:
        by_hash: dict = {}
        for name in self.all_names():
            by_hash.setdefault(sha(self.path_for(name)), []).append(name)
        return {h: v for h, v in by_hash.items() if len(v) > 1}


def refresh_derived(store: "AssetStore", parent: str, capture_dir=None,
                    log=None) -> dict:
    """Refresh the inline elements that belong to a screenshot just replaced.

    Two mechanisms, in order of trust:

    1. **A freshly captured element.** The crawl photographed the control by CSS
       selector, so it is the right control whatever the layout did.
    2. **Re-cutting a stored rectangle.** Legacy crops carry percentages of the
       old layout. Re-cutting keeps them roughly right, but a column added to a
       table moves the rectangle onto the wrong control, so these are reported
       as needing a look rather than treated as correct.
    """
    from PIL import Image

    from .imaging import crop_by_rect

    src = store.path_for(parent)
    if not src.exists():
        return {"captured": [], "recut": [], "unverified": []}
    base = None
    captured, recut = [], []

    for name, meta in list(store.registry.items()):
        if meta.get("derived_from") != parent:
            continue
        fresh = Path(capture_dir) / "screenshots" / name if capture_dir else None
        if fresh and fresh.exists():
            shutil.copyfile(fresh, store.path_for(name))
            meta.update({"sha": sha(store.path_for(name)), "source": str(fresh),
                         "captured_by": "selector"})
            captured.append(name)
            if log:
                log(f"    refreshed {name} from the captured element")
            continue
        if not meta.get("crop"):
            continue
        try:
            if base is None:
                base = Image.open(src)
            crop_by_rect(base, meta["crop"]).save(store.path_for(name), "PNG")
        except Exception as e:
            if log:
                log(f"    could not re-cut {name}: {e}")
            continue
        meta.update({"sha": sha(store.path_for(name)), "captured_by": "rectangle",
                     "needs_check": True})
        recut.append(name)
        if log:
            log(f"    re-cut {name} from a stored rectangle, please check it")
    if captured or recut:
        store.save()
    return {"captured": captured, "recut": recut, "unverified": recut}


# Kept so older call sites keep working.
def recut_derived(store: "AssetStore", parent: str, log=None) -> list[str]:
    r = refresh_derived(store, parent, capture_dir=None, log=log)
    return r["captured"] + r["recut"]
