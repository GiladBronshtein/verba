"""Starting a new document, without a blank page.

The hardest part of a pipeline like this has never been the pipeline. It is that
a new project starts as six empty YAML files whose schemas you have to learn
before anything runs at all, and the first thing you see is an error about a key
you have not heard of yet.

So `verba new` asks six questions and writes a project that builds. Not a
skeleton that builds once the gaps are filled: a real document, with a real
first section, a real screen registry and a theme, which renders to a PDF before
you have typed anything else. Every answer has a default, so the whole thing can
be held down through the Return key and still produce something to look at.

What it writes is ordinary project files. There is nothing generated-looking
about them, no markers to replace, and no step that has to be run again later:
from here on it is the same project any other command works on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .system import System
from .theme import available as themes_available

AUTH_KINDS = {
    "form": "a username and password typed into the product's own sign-in page",
    "sso": "single sign-on, where you sign in once in a real browser",
    "none": "no sign-in needed",
}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-")
    return s or "product"


@dataclass
class Answers:
    product: str = "My Product"
    vendor: str = ""
    about: str = ""
    base_url: str = "https://example.com"
    auth: str = "form"
    user: str = ""
    theme: str = "slate"
    audience: str = "operator"

    def __post_init__(self):
        self.vendor = self.vendor or self.product
        if self.auth not in AUTH_KINDS:
            raise ValueError(f"sign-in must be one of: {', '.join(AUTH_KINDS)}")
        if self.theme not in themes_available():
            raise ValueError(f"no such theme: {self.theme}. "
                             f"try one of: {', '.join(themes_available())}")


@dataclass
class Scaffold:
    root: Path
    a: Answers
    written: list[str] = field(default_factory=list)

    def _put(self, rel: str, text: str):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.lstrip("\n"), encoding="utf-8")
        self.written.append(rel)

    # ------------------------------------------------------------------
    def build(self) -> list[str]:
        """Write a project that builds, and return what was written."""
        a = self.a
        first = f"{slug(a.product)}-overview"

        self._put("content/doc.yaml", f"""
# The outline: the single source of order and numbering for the whole document.
#
# Section files never carry a number. Insert an entry here and everything below
# it renumbers, in the body and on the contents page together.

product:
  name: {a.product}
  vendor: {a.vendor}
  platform_version: "1.0"

document:
  title: Technical Documentation
  subtitle: User Guide
  confidentiality: ""

defaults:
  profile: default
  audience: {a.audience}

build:
  # The sheet and the margins are page setup and live in
  # content/typography.yaml, so the PDF and the DOCX read one setting.
  screenshot_width_cm: 15.0     # how wide a figure prints
  toc_depth: 3                  # deepest level listed on the contents page

outline:
  - id: introduction
    children:
      - id: introduction.{first}

lint:
  # Documented exceptions. Every suppression names its rule and what it covers,
  # so the list itself stays reviewable.
  allow: []
""")

        System(root=self.root).write(
            product=a.product, vendor=a.vendor, audience=a.audience,
            about=a.about or f"{a.product} is the system this document describes. "
                             "Replace this paragraph with what it does and who it "
                             "does it for, in the terms the company itself uses.")
        self.written.append("content/system.md")

        self._put("content/theme.yaml", f"""
# How the document looks.
#
#   verba themes            what is available, and what each is for
#   verba themes --use ink  pick a different one
#
# `tokens` overrides single values without forking a whole theme, which is the
# common case: a company has one brand colour and no opinion about the other
# nineteen. Every built-in theme is checked for contrast, so an override is the
# one place a document can be made unreadable. `verba themes --check` measures
# whatever is set here.

use: {a.theme}

tokens: {{}}
  # brand_blue: "3137DB"
""")

        self._put("content/typography.yaml", """
# The typefaces the outputs are set in, and the page they are set on.
#
#   verba fonts             what is installed, and what is served
#   verba layout            the sheet, the margins, how text is set

document: inter
console: inter

# Page setup. `paper` is the sheet; everything else is in millimetres.
# Paper may be A4, A5, Letter or Legal. It sets the sheet for the PDF and the
# DOCX together, so the two cannot disagree about what they are printed on.
#
#   edge         white space from the paper edge to the header and footer text
#   header_band  the height the header occupies, its rule included
#   footer_band  the same for the footer
#   gap          air between the header rule and the first line of body text

page:
  paper: A4
  side: 18
  edge: 12
  header_band: 8
  footer_band: 7
  gap: 9

# How body text is set. align is left or justify; hyphens is on or off.
text:
  align: left
  hyphens: "on"

faces:

  inter:
    label: Inter
    body: ["Inter", "Helvetica Neue", "sans-serif"]
    mono: ["JetBrains Mono", "SF Mono", "Menlo", "monospace"]
    docx: Inter
    docx_fallback: Calibri
    body_pt: 10.2
    line: 1.6
    tighten: -0.011
    webfont: "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
    note: Very large x-height, so it is set smaller and tracked in.

  source-sans:
    label: Source Sans 3
    body: ["Source Sans 3", "Helvetica Neue", "sans-serif"]
    mono: ["Source Code Pro", "SF Mono", "Menlo", "monospace"]
    docx: Source Sans 3
    docx_fallback: Calibri
    body_pt: 10.8
    line: 1.55
    tighten: 0
    webfont: "https://fonts.googleapis.com/css2?family=Source+Code+Pro:wght@400;500&family=Source+Sans+3:wght@400;500;600;700&display=swap"
    note: Adobe's screen-and-print workhorse. Slightly small on the body, so it is set larger.

  ibm-plex:
    label: IBM Plex Sans
    body: ["IBM Plex Sans", "Helvetica Neue", "sans-serif"]
    mono: ["IBM Plex Mono", "SF Mono", "Menlo", "monospace"]
    docx: IBM Plex Sans
    docx_fallback: Calibri
    body_pt: 10.2
    line: 1.58
    tighten: -0.004
    webfont: "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap"
    note: Drawn for technical documentation. Unmistakable digits, a true mono companion.

  system:
    label: System default
    body: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"]
    mono: ["SF Mono", "Menlo", "Consolas", "monospace"]
    docx: Calibri
    docx_fallback: Arial
    body_pt: 10.5
    line: 1.55
    tighten: 0
    note: Whatever the machine already has. Never missing, never distinctive.
""")

        self._put("content/screens.yaml", self._screens(first))
        self._put("content/masking.yaml", self._masking())
        self._put("content/environments.yaml", self._environments())

        self._put("content/profiles/default.yaml", f"""
# An edition. Section text writes {{{{ operator.name }}}} rather than naming a
# company, so one content tree renders a neutral manual and a branded one.
#
#   verba edition                  what this edition carries
#   verba edition drop <id>        leave a section out of it

name: default
audience: {a.audience}
title_suffix: ""
vars:
  operator:
    name: your organization
    role: {a.audience}
    possessive: your organization's
""")

        self._put("content/sections/introduction.md", """
---
id: introduction
title: Introduction
status: draft
screens: []
---

This document describes {{ product.name }} as it behaves today. Every screen in
it was photographed from the running system rather than drawn, and every field
list was read off the page rather than remembered.
""")

        # Deliberately not `TODO: describe this.`, which is the marker the rules
        # refuse to ship. A new project has to build on the first try or the
        # first thing anyone meets is an error about a rule they have not read
        # yet. This is honest placeholder prose instead: true of every product,
        # and replaced the moment there is a capture to write from.
        self._put(f"content/sections/introduction/{first}.md", f"""
---
id: introduction.{first}
title: {a.product} Overview
status: draft
screens: [home]
---

This section describes the main screen of {{{{ product.name }}}} and the work it
is used for. Once a capture has run, the screenshot and the field lists below
come from the running system rather than from memory, and any difference between
the two is raised for review.

Replace this paragraph with what an operator actually does here.
""")

        (self.root / "content" / "assets").mkdir(parents=True, exist_ok=True)
        self._put("content/assets/registry.json", "{}\n")
        self._put(".gitignore", """
capture/
dist/
.verba/sessions/
content/masking-map.json
__pycache__/
""")
        return self.written

    # ------------------------------------------------------------------
    def _screens(self, first: str) -> str:
        a = self.a
        if a.auth == "form":
            login = """  login:
    - goto: /login
    - wait_for: "input"
    - wait_ms: 800
    - fill: 'input[autocomplete="username"], input[name="email"], input[type="email"]'
      value: "${VERBA_USER}"
    - fill: 'input[autocomplete="current-password"], input[name="password"], input[type="password"]'
      value: "${VERBA_PASSWORD}"
    - click: 'button[type="submit"]'
    - wait_ms: 2500"""
        elif a.auth == "sso":
            login = """  # Single sign-on: nothing is typed by automation. You sign in once in a real
  # browser (`verba env signin <profile>`) and the session is reused.
  login: []"""
        else:
            login = "  login: []"

        return f"""
# Screen registry: how to reach each documented screen, and what to read off it.
#
# `sections` binds a screen to the sections it evidences. After a capture the
# labels read by `extract` are compared with what those sections claim, and every
# difference lands in the review queue.
#
# Credentials come from the environment, never from this file:
#   export VERBA_USER=... VERBA_PASSWORD=...

site:
  base_url: {a.base_url}
{login}

  # If reads need POST anywhere (a GraphQL endpoint, say), name them here.
  # Nothing else is ever allowed through: see the read-only guarantee.
  readonly:
    allow_post_matching: []

screens:
  - id: home
    title: Home
    sections: [introduction.{first}]
    shot: introduction-{first}-1.png
    steps:
      - goto: /
      - wait_for: "body"
    extract:
      # What to read off the page. Each key becomes a list of labels the
      # document is then held against.
      tabs: "[role=tab]"
      columns: "table thead th, [role=columnheader]"
      actions: "main button, main a[role=button]"
"""

    def _masking(self) -> str:
        return """
# Screenshot masking.
#
# Real names and identifiers are replaced in the page's DOM immediately before
# each screenshot is taken, and in the labels read off the page afterwards.
# Nothing is ever submitted: the substitution exists only in the captured pixels.
#
# This matters the moment a document leaves the building. A screenshot of a live
# account carries one customer's data into another customer's documentation.
#
# The mapping is stored in content/masking-map.json, so a given real value always
# becomes the same placeholder, in this crawl and in crawls months from now.

enabled: true

# Values under a table header, replaced row by row. This is the main rule: it
# catches every name in a list view without knowing the names in advance, which
# matters because the data changes between crawls.
columns: []
  # - header: NAME
  #   with: "Example Account {n}"

# Anything matching the pattern, anywhere on the page.
patterns: []
  # - name: entity-id
  #   pattern: "\\\\b[0-9a-f]{24}\\\\b"
  #   with: "6a000000000000000000{n:04d}"

# One exact string, always replaced with the same thing.
literals: []
  # - match: "Acme Corp"
  #   with: "Example Account 1"
"""

    def _environments(self) -> str:
        a = self.a
        user = f"\n  user: {a.user}" if (a.user and a.auth == "form") else ""
        return f"""
# Connections. Which system a crawl talks to, and how it gets in.
#
# Passwords are never stored here. A form login keeps its password in the login
# keychain (`verba env password <id>`), and single sign-on keeps a browser
# session under .verba/sessions instead of a password at all.
#
# `mask_required: true` refuses an unmasked crawl outright. Set it on anything
# holding real customer data.

active: default
environments:
- id: default
  label: {a.product}
  base_url: {a.base_url}
  auth: {a.auth}{user}
  signed_in_when: "body"
  mask_required: false
"""
