"""Release management.

A release is a snapshot: the version number, which sections it contained, and
the hash of each one. The next release diffs against that snapshot, so the
changelog is derived from what actually changed rather than remembered by hand.
Output files are never overwritten.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .atomic import write_json

STATE = ".verba/releases.json"


def section_hash(section) -> str:
    payload = json.dumps({
        "title": section.title,
        "blocks": [[b.kind, b.text, b.items, b.attrs] for b in section.blocks],
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass
class Release:
    version: str
    date: str
    profile: str
    outputs: list = field(default_factory=list)
    sections: dict = field(default_factory=dict)   # id -> {hash, title, number}
    assets: dict = field(default_factory=dict)     # name -> sha
    summary: str = ""
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class ReleaseStore:
    def __init__(self, root: Path):
        self.path = Path(root) / STATE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.path.read_text()) if self.path.exists() \
            else {"releases": []}

    @property
    def releases(self) -> list[dict]:
        return self.data["releases"]

    def latest(self, profile: str | None = None) -> dict | None:
        for r in reversed(self.releases):
            if profile is None or r.get("profile") == profile:
                return r
        return None

    def find(self, version: str, profile: str | None = None) -> dict | None:
        """One release by name, however the person wrote the number.

        `diff` has always taken any previous release, so comparing against a
        named one needed nothing but a way to name it. Until this existed the
        only comparison anybody could reach was against the newest release, and
        "what changed since v30" had no answer at all, on a tool whose whole
        subject is what changed.
        """
        want = str(version or "").strip().lstrip("vV")
        for r in reversed(self.releases):
            if profile is not None and r.get("profile") != profile:
                continue
            if str(r.get("version", "")).lstrip("vV") == want:
                return r
        return None

    def versions(self, profile: str | None = None) -> list:
        return [r["version"] for r in self.releases
                if profile is None or r.get("profile") == profile]

    def next_version(self, profile: str | None = None) -> str:
        nums = [int(str(r["version"]).lstrip("v").split(".")[0])
                for r in self.releases if str(r["version"]).lstrip("v").split(".")[0].isdigit()]
        # A project with no releases yet starts at v1. This used to fall back to
        # 25, which was the number one particular document happened to have
        # reached when the line was written.
        return f"v{max(nums) + 1 if nums else 1}"

    def snapshot(self, project, version: str) -> Release:
        rel = Release(version=version, date=date.today().isoformat(),
                      profile=project.profile.name)
        for node in project.nodes:
            if node.section is None:
                continue
            rel.sections[node.id] = {
                "hash": section_hash(node.section),
                "title": node.section.title,
                "number": node.number,
                "status": node.section.status,
                "last_verified": node.section.last_verified,
            }
        rel.assets = {n: project.assets.registry.get(n, {}).get("sha", "")
                      for n in project.assets.all_names()}
        return rel

    def diff(self, project, previous: dict | None) -> dict:
        current = self.snapshot(project, "pending")
        prev_secs = (previous or {}).get("sections", {})
        added = [s for s in current.sections if s not in prev_secs]
        removed = [s for s in prev_secs if s not in current.sections]
        changed = [s for s in current.sections
                   if s in prev_secs and prev_secs[s]["hash"] != current.sections[s]["hash"]]
        renumbered = [s for s in current.sections
                      if s in prev_secs and s not in changed
                      and prev_secs[s].get("number") != current.sections[s]["number"]]
        prev_assets = (previous or {}).get("assets", {})
        new_assets = [a for a in current.assets if a not in prev_assets]
        changed_assets = [a for a in current.assets
                          if a in prev_assets and prev_assets[a] != current.assets[a]]
        return {"added": added, "removed": removed, "changed": changed,
                "renumbered": renumbered, "new_assets": new_assets,
                "changed_assets": changed_assets}

    def describe(self, project, d: dict) -> str:
        titles = {n.id: f"{n.number} {n.title}" for n in project.nodes}
        bits = []
        if d["added"]:
            bits.append(f"{len(d['added'])} new section(s): " +
                        ", ".join(titles.get(s, s) for s in d["added"][:4]))
        if d["changed"]:
            bits.append(f"{len(d['changed'])} section(s) revised: " +
                        ", ".join(titles.get(s, s) for s in d["changed"][:4]))
        if d["removed"]:
            bits.append(f"{len(d['removed'])} section(s) removed")
        if d["changed_assets"]:
            bits.append(f"{len(d['changed_assets'])} screenshot(s) replaced")
        if d["new_assets"]:
            bits.append(f"{len(d['new_assets'])} screenshot(s) added")
        if d["renumbered"]:
            bits.append(f"{len(d['renumbered'])} section(s) renumbered")
        return "; ".join(bits) or "No content changes."

    def record(self, rel: Release):
        self.releases.append(rel.to_dict())
        write_json(self.path, self.data)

    def history(self, profile: str | None = None, limit: int = 12) -> list[dict]:
        rs = [r for r in self.releases if profile is None or r["profile"] == profile]
        return list(reversed(rs))[:limit]

    def changelog_markdown(self) -> str:
        lines = ["# Changelog", ""]
        for r in reversed(self.releases):
            lines += [f"## {r['version']} ({r['date']}) profile: {r['profile']}", "",
                      r.get("summary", ""), ""]
            for note in r.get("notes", []):
                lines.append(f"- {note}")
            if r.get("outputs"):
                lines.append("")
                for o in r["outputs"]:
                    lines.append(f"- output: `{o}`")
            lines.append("")
        return "\n".join(lines)


def output_name(project, version: str) -> str:
    prod = project.config["product"]["name"].replace(" ", "_")
    doc = project.config["document"]["title"].replace(" ", "_")
    prof = project.profile.name
    return f"{prod}_{doc}_{version}_{prof}.docx"
