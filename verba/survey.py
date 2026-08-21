"""What the document is missing, worked out before anyone opens a browser.

A crawl is the expensive step: minutes of waiting, a sign-in, a lot of traffic
against a live platform. Running one and then discovering what it should have
looked at is the wrong order. This reads the document as it stands and answers
three questions without a browser:

* what is unfinished, and which screen would finish it;
* which pictures are missing, blank, or no longer of anything;
* which parts of the platform have no documentation at all.

The result is a plan rather than a report. Every gap that a crawl could close
names the screen that would close it, so `survey --crawl` visits exactly those
and nothing else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

TODO = re.compile(r"TODO:\s*describe this", re.I)

# Below this an image is a cropped control rather than a picture of a screen.
FIGURE_MIN_H = 200


@dataclass
class Gap:
    kind: str                 # unwritten | image | undocumented | stale | evidence
    where: str                # section number and title, or the screen id
    what: str
    screen: str = ""          # the screen a crawl would need to visit
    section: str = ""
    count: int = 1
    fixable_by_crawl: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Survey:
    root: Path
    gaps: list = field(default_factory=list)
    crawled: set = field(default_factory=set)

    # ------------------------------------------------------------------
    @classmethod
    def run(cls, project, root: Path | str = ".") -> "Survey":
        root = Path(root)
        s = cls(root=root)
        s.crawled = s._already_crawled()
        s._unfinished(project)
        s._pictures(project)
        s._undocumented(project)
        s._staleness(project)
        s._redirects(project)
        return s

    def _already_crawled(self) -> set:
        try:
            from .capture import merged_inventory
            merged, _ = merged_inventory(self.root / "capture")
            return set(merged.get("screens", {}))
        except Exception:
            return set()

    # -- what is unfinished ---------------------------------------------
    def _unfinished(self, project):
        for node in project.nodes:
            sec = node.section
            if sec is None:
                continue
            names = _unwritten(sec)
            if not names:
                continue
            screen = sec.screens[0] if sec.screens else ""
            self.gaps.append(Gap(
                kind="unwritten",
                where=f"{node.number} {sec.title}",
                what=f"{len(names)} description(s) never written: "
                     + ", ".join(names[:4]) + ("..." if len(names) > 4 else ""),
                screen=screen, section=sec.id, count=len(names),
                # only worth crawling if the evidence is not already in hand
                fixable_by_crawl=bool(screen) and screen not in self.crawled))
            if screen and screen in self.crawled:
                self.gaps.append(Gap(
                    kind="evidence",
                    where=f"{node.number} {sec.title}",
                    what="the evidence for these is already captured, so the "
                         "writer can answer them without another crawl",
                    screen=screen, section=sec.id, count=len(names)))

    # -- pictures --------------------------------------------------------
    def _pictures(self, project):
        for node in project.nodes:
            sec = node.section
            if sec is None:
                continue
            screen = sec.screens[0] if sec.screens else ""
            shots = sec.screenshots()

            # A captionless crop renders as a detail at its own size and is
            # not a fault. Only something presented as a figure has to be one:
            # the same rule the renderer applies, so the survey does not report
            # problems the document does not have.
            captioned = {b.attrs.get("file", "") for b in sec.blocks
                         if b.kind == "screenshot" and b.attrs.get("caption")}

            for name in shots:
                path = project.asset_path(name)
                if not path.exists():
                    self.gaps.append(Gap(
                        kind="image", where=f"{node.number} {sec.title}",
                        what=f"the file behind a figure is not in the library: {name}",
                        screen=screen, section=sec.id, fixable_by_crawl=bool(screen)))
                    continue
                verdict = _picture_problem(path, presented_as_figure=name in captioned)
                if verdict:
                    self.gaps.append(Gap(
                        kind="image", where=f"{node.number} {sec.title}",
                        what=f"{name}: {verdict}",
                        screen=screen, section=sec.id, fixable_by_crawl=bool(screen)))

            if screen and not shots:
                self.gaps.append(Gap(
                    kind="image", where=f"{node.number} {sec.title}",
                    what="this section maps to a screen but shows no picture of it",
                    screen=screen, section=sec.id, fixable_by_crawl=True))

    # -- parts of the platform nobody has written about -------------------
    def _undocumented(self, project):
        documented = set()
        for node in project.nodes:
            if node.section is not None:
                documented.update(node.section.screens)

        for screen in _registered_screens(self.root):
            sid = screen.get("id", "")
            if not sid or sid in documented:
                continue
            self.gaps.append(Gap(
                kind="undocumented", where=sid,
                what=f"{screen.get('title') or sid} is registered as a screen of "
                     f"the platform and no section describes it",
                screen=sid, fixable_by_crawl=sid not in self.crawled))

        # addresses the crawler has reached that no screen in the registry
        # accounts for: places the product has that we have never named
        for sid, entry in _remembered_routes(self.root).items():
            if sid in documented or any(
                    g.kind == "undocumented" and g.screen == sid for g in self.gaps):
                continue
            if not entry.get("sections"):
                self.gaps.append(Gap(
                    kind="undocumented", where=sid,
                    what="the crawler has reached this and it belongs to no section",
                    screen=sid))

    # -- screens that are not screens --------------------------------------
    def _redirects(self, project):
        """Two screens that produce the same picture are one screen.

        `dashboard.main` is registered, is reached by steps rather than an
        address, and lands on the supply page: its capture is byte for byte the
        publishers list. Comparing the landed address cannot catch that, because
        a screen reached by clicking has no address to compare. Comparing the
        pictures can, and it is the fact that actually matters: a section mapped
        to such a screen can never be given a correct figure, and any figure it
        is given is of somewhere else.
        """
        import hashlib
        try:
            from .capture import merged_inventory
            merged, _ = merged_inventory(self.root / "capture")
        except Exception:
            return
        runs = merged.get("_runs", {})

        owners: dict[str, list] = {}
        for node in project.nodes:
            if node.section is None:
                continue
            for sid in node.section.screens:
                owners.setdefault(sid, []).append(f"{node.number} {node.section.title}")

        by_hash: dict[str, list] = {}
        for sid, record in (merged.get("screens") or {}).items():
            shot, run = record.get("shot"), runs.get(sid)
            if not shot or not run:
                continue
            path = self.root / "capture" / run / "screenshots" / shot
            if not path.exists():
                continue
            try:
                h = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            by_hash.setdefault(h, []).append(sid)

        for sids in by_hash.values():
            if len(sids) < 2:
                continue
            named = ", ".join(sids)
            for sid in sids:
                who = owners.get(sid) or []
                self.gaps.append(Gap(
                    kind="redirects", where=sid,
                    what=f"this and {len([x for x in sids if x != sid])} other "
                         f"screen produce the same picture ({named}), so one of "
                         f"them is not a distinct screen"
                         + (f". Documented by {', '.join(who[:2])}" if who else
                            ". Nothing documents it"),
                    screen=sid, count=len(who), fixable_by_crawl=False))

    # -- age --------------------------------------------------------------
    def _staleness(self, project, days: int = 120):
        today = date.today()
        for node in project.nodes:
            sec = node.section
            if sec is None:
                continue
            when = getattr(sec, "last_verified", "") or ""
            if not when:
                continue
            try:
                age = (today - date.fromisoformat(str(when)[:10])).days
            except ValueError:
                continue
            if age > days:
                self.gaps.append(Gap(
                    kind="stale", where=f"{node.number} {sec.title}",
                    what=f"last checked against the live product {age} days ago",
                    screen=sec.screens[0] if sec.screens else "",
                    section=sec.id, count=age,
                    fixable_by_crawl=bool(sec.screens)))

    # ------------------------------------------------------------------
    def screens_worth_crawling(self) -> list[str]:
        """Exactly the screens that would close a gap, in document order."""
        out = []
        for g in self.gaps:
            if g.fixable_by_crawl and g.screen and g.screen not in out:
                out.append(g.screen)
        return out

    def by_kind(self) -> dict:
        out: dict[str, list] = {}
        for g in self.gaps:
            out.setdefault(g.kind, []).append(g)
        return out

    def summary(self) -> dict:
        kinds = self.by_kind()
        return {
            "at": datetime.now().isoformat(timespec="seconds"),
            "gaps": len(self.gaps),
            "unwritten": sum(g.count for g in kinds.get("unwritten", [])),
            "images": len(kinds.get("image", [])),
            "undocumented": len(kinds.get("undocumented", [])),
            "stale": len(kinds.get("stale", [])),
            "redirects": len(kinds.get("redirects", [])),
            "answerable_now": len(kinds.get("evidence", [])),
            "screens_worth_crawling": self.screens_worth_crawling(),
        }

    def to_dict(self) -> dict:
        return {"summary": self.summary(),
                "gaps": [g.to_dict() for g in self.gaps]}

    def save(self):
        import json
        path = self.root / "review" / "survey.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
def _unwritten(section) -> list[str]:
    out = []
    for b in section.blocks:
        if TODO.search(b.text or ""):
            out.append(b.kind)
        for it in (b.items or []):
            if isinstance(it, dict):
                for key, value in it.items():
                    if isinstance(value, str) and TODO.search(value):
                        out.append(str(it.get("field") or it.get("name")
                                       or it.get("action") or it.get("column")
                                       or key))
                        break
            elif TODO.search(str(it)):
                out.append(str(it)[:30])
    return out


def _picture_problem(path: Path, presented_as_figure: bool = True) -> str:
    """Why this image would not do, or empty if it is fine."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            lo, hi = im.convert("L").getextrema()
    except Exception as e:
        return f"cannot be read ({e})"
    if hi - lo < 12:
        return "the capture came back blank"
    if presented_as_figure and h < FIGURE_MIN_H:
        return (f"only {w}x{h}, a cropped control under a figure caption")
    return ""


def _registered_screens(root: Path) -> list[dict]:
    path = root / "content" / "screens.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    screens = raw.get("screens", raw) if isinstance(raw, dict) else raw
    return [s for s in screens if isinstance(s, dict)] if screens else []


def _remembered_routes(root: Path) -> dict:
    path = root / "content" / "routes.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    routes = raw.get("routes", raw) if isinstance(raw, dict) else {}
    return routes if isinstance(routes, dict) else {}
