#!/usr/bin/env python3
"""Every link in the README and the wiki, checked.

A README is the first thing anyone reads, and a dead link in it is the first
thing they learn about the project. The wiki is worse: its pages link to each
other by a name GitHub derives from the filename, so renaming one page breaks
every link to it silently, and nothing in a normal build would ever notice.

    python3 tools/check_links.py            everything, network included
    python3 tools/check_links.py --offline  files and anchors only
"""
from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "docs" / "wiki"
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMG_HTML = re.compile(r'<img[^>]+src="([^"]+)"')
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)


def slug(text: str) -> str:
    """GitHub's own anchor rules: lowercase, punctuation dropped, spaces to hyphens."""
    t = re.sub(r"<[^>]+>", "", text)
    t = re.sub(r"[^\w\s-]", "", t.lower())
    return re.sub(r"\s+", "-", t.strip())


def anchors(text: str) -> set:
    return {slug(h) for h in HEADING.findall(text)}


def without_code(text: str) -> str:
    """Drop fenced blocks before looking for links.

    A page that documents the block syntax shows `![caption](file.png)` as an
    example of what to type. That is not a link to anything and reporting it as
    broken is the checker being wrong, which is worse than not checking.
    Handles four-backtick fences too, since a page showing a fenced example
    inside a fenced example needs them.
    """
    text = re.sub(r"^(`{3,})[^\n]*\n.*?^\1`*\s*$", "", text, flags=re.S | re.M)
    # And inline spans, which is how a table row shows the syntax for a figure.
    return re.sub(r"`[^`\n]+`", "", text)


_WIKI_SEEN = {}


def _wiki_published(repo_url: str) -> bool:
    """Does this repository's wiki actually have anything in it?

    A status code cannot answer this. GitHub serves /wiki/AnyPage with a 200
    for a repository whose wiki was never created, redirecting quietly to the
    repository home, so every wiki link in a README can be green and every one
    of them land nowhere. The wiki is its own git repository and only exists
    once a page has been saved, so asking git is the honest question.
    """
    if repo_url in _WIKI_SEEN:
        return _WIKI_SEEN[repo_url]
    probe = f"{repo_url}.wiki.git/info/refs?service=git-upload-pack"
    try:
        urllib.request.urlopen(urllib.request.Request(
            probe, headers={"User-Agent": "verba-link-check"}), timeout=12)
        _WIKI_SEEN[repo_url] = True
    except Exception:
        _WIKI_SEEN[repo_url] = False
    return _WIKI_SEEN[repo_url]


def check(offline: bool = False) -> int:
    pages = {p.stem for p in WIKI.glob("*.md")}
    files = [ROOT / "README.md", ROOT / "CONTRIBUTING.md"] + sorted(WIKI.glob("*.md"))
    bad = []
    urls = {}
    counted = 0

    for path in files:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        text = without_code(raw)
        # Anchors from the prose only. A page showing an example of a settings
        # file has "## Vocabulary" inside a fence, which is code and not a
        # heading, and counting it would let a link to a heading that does not
        # exist pass.
        here = anchors(text)
        rel = path.relative_to(ROOT)
        in_wiki = path.parent == WIKI

        for target in IMG_HTML.findall(text):
            counted += 1
            if target.startswith("http"):
                urls.setdefault(target, []).append(str(rel))
            elif not (ROOT / target.lstrip("/")).exists():
                bad.append(f"{rel}: image not on disk: {target}")

        for _label, target in LINK.findall(text):
            counted += 1
            if target.startswith("#"):
                if slug(target[1:]) not in here:
                    bad.append(f"{rel}: no heading for anchor {target}")
            elif target.startswith("http"):
                urls.setdefault(target, []).append(str(rel))
            elif target.startswith("mailto:"):
                pass
            elif in_wiki and "/" not in target and not target.endswith(".md"):
                # a wiki page link, which GitHub resolves by filename
                if target not in pages:
                    bad.append(f"{rel}: no wiki page named {target!r}")
            else:
                spot = target.split("#")[0].lstrip("/")
                if spot and not (ROOT / spot).exists() and not (path.parent / spot).exists():
                    bad.append(f"{rel}: not on disk: {target}")

    if not offline:
        for url, where in sorted(urls.items()):
            # A wiki link is the one case a status code cannot answer. GitHub
            # serves "create the first page" with a 200 for every page of a
            # wiki nobody has published, so nineteen links in a README can all
            # be green and all lead to an empty tab.
            m = re.match(r"(https://github\.com/[^/]+/[^/]+)/wiki", url)
            if m:
                if not _wiki_published(m.group(1)):
                    bad.append(f"{where[0]}: the wiki has no pages, so GitHub "
                               f"redirects this to the repository home: {url}")
                continue

            probe = urllib.request.Request(
                url, method="HEAD", headers={"User-Agent": "verba-link-check"})
            try:
                urllib.request.urlopen(probe, timeout=12)
            except urllib.error.HTTPError as e:
                # A wiki nobody has created yet answers 404, and that is a real
                # broken link in a README, so it is reported like any other.
                # 403/405/429 are the host declining the probe, not the link.
                if e.code not in (403, 405, 429):
                    bad.append(f"{where[0]}: {e.code} on {url}")
            except Exception as e:
                bad.append(f"{where[0]}: {type(e).__name__} on {url}")

    print(f"{counted} link(s) across {len(files)} file(s), "
          f"{len(urls)} distinct address(es)")
    if bad:
        print(f"\n{len(bad)} broken:")
        for b in bad:
            print(f"  {b}")
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    raise SystemExit(check(offline="--offline" in sys.argv))
