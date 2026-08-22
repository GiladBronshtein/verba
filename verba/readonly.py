"""Read-only enforcement for every crawl.

The documentation crawler must never change anything in the platform. That
guarantee is enforced at the network layer rather than by being careful about
which buttons get clicked: after sign-in, any request whose method is not a
read method is aborted before it leaves the browser. A misdirected click on
Save therefore cannot write, because the request never reaches the server.

Two further layers sit on top:

* the step interpreter refuses to type into fields outside sign-in, so no form
  can be filled in the first place;
* the screen registry is linted for steps that look like commits, which are
  reported so the registry gets cleaned up rather than silently relied upon.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# Step verbs that can only ever read.
SAFE_STEPS = {"goto", "click", "click_text", "wait_for", "wait_ms", "press",
              "scroll", "expand_all", "hover", "mask"}

# Steps that can put data into the page. Permitted during sign-in only.
WRITING_STEPS = {"fill", "select", "check", "upload"}

# Labels that usually commit a change. Advisory: the network guard is what
# actually prevents the write.
COMMIT_WORDS = re.compile(
    r"\b(save|submit|delete|remove|archive|duplicate|confirm|apply|publish|"
    r"activate|deactivate|disable|enable|pause|resume|update|overwrite|"
    r"create\s+(publisher|partner|deal|connection|list|user))\b", re.I)

# Keys that could commit a focused form.
UNSAFE_KEYS = {"Enter", "NumpadEnter"}


@dataclass
class Guard:
    """Installed on a Playwright page. Blocks writes and keeps a record."""
    allow_post_matching: list = field(default_factory=list)
    phase: str = "login"                 # login | readonly
    blocked: list = field(default_factory=list)
    allowed_posts: list = field(default_factory=list)
    # Set the moment a hand-over reaches the product, before `lock()` runs. A
    # person driving the browser through a second factor is inside the sign-in
    # phase, where writes are permitted, and they have a mouse. Narrowing the
    # phase the instant the product appears keeps that window to one poll.
    at_product: bool = False
    _log = None

    def attach(self, page, log=None):
        self._log = log
        page.route("**/*", self._handle)
        return self

    # ------------------------------------------------------------------
    def _post_allowed(self, url: str) -> bool:
        return any(fnmatch.fnmatch(url, pat) for pat in self.allow_post_matching)

    def _handle(self, route, request):
        method = (request.method or "GET").upper()
        if method in READ_METHODS:
            return route.continue_()

        # Sign-in is the one write the crawler is allowed to perform, and only
        # while the login steps are running. Every one is recorded and reported,
        # so the single permitted exception stays auditable.
        if self.phase == "login" and not self.at_product:
            entry = f"{method} {request.url}"
            self.allowed_posts.append(entry)
            if self._log:
                self._log(f"    sign-in request allowed: {entry[:150]}")
            return route.continue_()

        if self._post_allowed(request.url):
            self.allowed_posts.append(f"{method} {request.url} (allowlisted read)")
            return route.continue_()

        entry = f"{method} {request.url}"
        self.blocked.append(entry)
        if self._log:
            self._log(f"    blocked write: {entry[:150]}")
        return route.abort()

    def reached_product(self):
        """The sign-in landed. Stop permitting writes, before `lock()` runs."""
        self.at_product = True
        return self

    def lock(self):
        """Leave the sign-in phase. From here nothing may write."""
        self.phase = "readonly"
        self.at_product = True
        return self

    def report(self) -> dict:
        return {"blocked_writes": len(self.blocked),
                "sign_in_writes": len(self.allowed_posts),
                "blocked": self.blocked[:50],
                "sign_in_requests": len(self.allowed_posts),
                "sign_in_detail": self.allowed_posts[:20],
                "phase": self.phase}


class UnsafeStep(RuntimeError):
    pass


def check_step(step: dict, phase: str) -> list[str]:
    """Reject a step that could write. Returns advisory warnings."""
    warnings: list[str] = []
    opens_form = bool(step.get("opens_form"))
    for key in step:
        if key in ("value", "intent", "note", "opens_form"):
            continue
        if key in WRITING_STEPS:
            if phase != "login":
                raise UnsafeStep(
                    f"step {key!r} types into the page and is only permitted during "
                    f"sign-in. Remove it from the screen definition.")
            continue
        if key not in SAFE_STEPS:
            raise UnsafeStep(f"unknown capture step {key!r}")

        if key == "press" and str(step[key]) in UNSAFE_KEYS and phase != "login":
            raise UnsafeStep(
                f"pressing {step[key]!r} can submit a focused form. Use an explicit "
                f"click on a navigation control instead.")

        if key in ("click", "click_text"):
            m = COMMIT_WORDS.search(str(step[key]))
            # `opens_form: true` records that this control opens a form rather
            # than committing one. It silences the advisory only: the network
            # guard still blocks anything the click actually tries to write.
            if m and phase != "login" and not opens_form:
                warnings.append(
                    f"step clicks {str(step[key])[:60]!r}, which reads like a commit "
                    f"({m.group(0)}). The network guard will block any write it "
                    f"attempts, but the step should be removed.")
    return warnings


def lint_screens(screens) -> list[str]:
    """Advisory pass over the whole registry, surfaced before a crawl runs."""
    out: list[str] = []
    for screen in screens:
        for step in screen.steps:
            try:
                for w in check_step(step, "readonly"):
                    out.append(f"{screen.id}: {w}")
            except UnsafeStep as e:
                out.append(f"{screen.id}: REFUSED {e}")
    return out
