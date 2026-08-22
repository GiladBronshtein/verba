"""Capture the live system: screenshots plus a structured UI inventory.

A capture is not just images. Every screen also yields the labels the UI
actually shows (table headers, form fields, buttons, tabs), which is what makes
drift detection possible: the document says a table has five columns, the
capture says it has six, and the difference lands in a review queue.

Three guarantees hold for every crawl:

* **Nothing is written.** A network guard aborts any non-read request once
  sign-in is done, so a stray click cannot change platform data.
* **Real names do not reach the document.** Entity names and identifiers are
  replaced in the DOM immediately before each screenshot, and in the extracted
  labels afterwards.
* **Routes are remembered.** The URL each screen actually resolved to is
  recorded, so a single section can be re-crawled later by going straight there.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from . import forms
from .healing import Healer
from .masking import Masker
from .readonly import Guard, check_step

VIEWPORT = {"width": 1440, "height": 768}
DEFAULT_TIMEOUT = 20000


@dataclass
class Screen:
    id: str
    title: str = ""
    sections: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    shot: str | None = None
    extract: dict = field(default_factory=dict)
    settle_ms: int = 900
    skip: bool = False
    url: str | None = None          # remembered from the last successful crawl
    mask: bool = True
    signed_out: bool = False      # capture in a clean context, e.g. the sign-in page
    elements: list = field(default_factory=list)   # named crops, by selector

    @classmethod
    def from_dict(cls, d: dict) -> "Screen":
        return cls(
            id=d["id"], title=d.get("title", ""),
            sections=d.get("sections", []) or [],
            steps=d.get("steps", []) or [],
            shot=d.get("shot"), extract=d.get("extract", {}) or {},
            settle_ms=int(d.get("settle_ms", 900)), skip=bool(d.get("skip", False)),
            url=d.get("url"), mask=bool(d.get("mask", True)),
            signed_out=bool(d.get("signed_out", False)),
            elements=d.get("elements", []) or [],
        )


def load_screens(path: Path) -> tuple[dict, list[Screen]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    screens = [Screen.from_dict(s) for s in data.get("screens", [])]
    routes = load_routes(Path(path).parent / "routes.yaml")
    for s in screens:
        if not s.url and s.id in routes:
            s.url = routes[s.id].get("url")
    return data.get("site", {}) or {}, screens


# ---------------------------------------------------------------- routes


def load_routes(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("routes", {}) or {}


def save_routes(path: Path, routes: dict):
    """Remember where each screen lives, so one section can be re-crawled fast."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Learned routes. Written by `verba capture`: the URL each screen\n"
        "# actually resolved to, plus how long it took and when it was last seen.\n"
        "# A per-section recrawl navigates straight here and falls back to the\n"
        "# screen's steps if the URL no longer resolves. Safe to delete: the next\n"
        "# capture rebuilds it.\n"
    )
    path.write_text(
        header + yaml.safe_dump({"routes": routes}, sort_keys=True, allow_unicode=True),
        encoding="utf-8")


# ------------------------------------------------------------------ extraction

EXTRACT_JS = """
(sel) => {
  const seen = new Set();
  const out = [];
  document.querySelectorAll(sel).forEach(el => {
    if (!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)) return;
    let t = (el.getAttribute('aria-label') || el.innerText || el.value ||
             el.placeholder || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 90) return;
    if (seen.has(t)) return;
    seen.add(t);
    out.push(t);
  });
  return out;
}
"""


# Some screens render form controls with no <label> element at all: the product
# is Material UI and the field name is sibling text. A CSS selector cannot express
# "the text that names this control", so these strategies do it in the page.
STRATEGY_JS = {
  "@controls": """
  () => {
    const out = [], seen = new Set();
    const sel = 'input, textarea, select, [role=combobox], [role=switch]';
    document.querySelectorAll(sel).forEach(el => {
      if (!(el.offsetWidth || el.offsetHeight)) return;
      let label = '', node = el.parentElement, hops = 0;
      while (node && hops < 4 && !label) {
        const own = [...node.childNodes].filter(c => c.nodeType === 3)
          .map(c => c.textContent.trim()).filter(Boolean).join(' ');
        if (own) label = own;
        if (!label && node.previousElementSibling)
          label = (node.previousElementSibling.innerText || '').trim().split('\\n')[0];
        node = node.parentElement; hops++;
      }
      label = (label || el.getAttribute('aria-label') || el.placeholder || '')
        .replace(/\\s+/g, ' ').trim();
      if (!label || label.length > 70 || seen.has(label)) return;
      seen.add(label); out.push(label);
    });
    return out;
  }""",
  "@nav": """
  () => {
    const out = [], seen = new Set();
    document.querySelectorAll(
      '.MuiListItemText-primary, nav a, aside a, [role=navigation] a').forEach(e => {
      const t = (e.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t && t.length < 60 && !seen.has(t)) { seen.add(t); out.push(t); }
    });
    return out;
  }""",
}


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


class Capture:
    """Drives Playwright over the screen registry, read-only and masked."""

    def __init__(self, site: dict, screens: list[Screen], out_dir: Path,
                 headless: bool = True, masker: Masker | None = None,
                 routes_path: Path | None = None, healer: Healer | None = None,
                 handoff: bool | None = None, on_wait=None):
        self.site = site
        # A hand-over is how a sign-in that a machine cannot finish gets
        # finished: the crawl fills what it knows, a person deals with the
        # second factor, and the run carries on. It forces a visible browser,
        # because waiting for somebody in a headless one is waiting forever.
        self.handoff = bool(site.get("handoff") if handoff is None else handoff)
        self.handoff_timeout_s = int(site.get("handoff_timeout_s", 300) or 300)
        self.on_wait = on_wait
        self.handed_over = False
        self.screens = screens
        self.out_dir = Path(out_dir)
        self.headless = headless
        self.shots_dir = self.out_dir / "screenshots"
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self.masker = masker or Masker(enabled=False)
        self.routes_path = routes_path
        self.routes: dict = load_routes(routes_path) if routes_path else {}
        self.guard = Guard(allow_post_matching=(site.get("readonly", {}) or {})
                           .get("allow_post_matching", []) or [])
        self.healer = healer or Healer(enabled=False)
        self.inventory: dict = {}
        self.errors: list[dict] = []

    def _live_frame(self, page, screen, stage: str):
        """Write a rolling frame of what the crawler is looking at.

        A crawl is otherwise a list of log lines, and a screen that loaded the
        wrong page reads exactly like one that loaded the right page. Seeing it
        makes that obvious in a second.
        """
        try:
            page.screenshot(path=str(self.out_dir / "live.png"), full_page=False)
            (self.out_dir / "live.json").write_text(json.dumps({
                "screen": screen.id, "title": screen.title, "stage": stage,
                "url": page.url, "at": datetime.now().isoformat(timespec="seconds"),
            }), encoding="utf-8")
        except Exception:
            pass   # a missing preview frame must never fail a crawl

    # -- step interpreter -------------------------------------------------
    def _run_step(self, page, step: dict, phase: str, log=None):
        for warning in check_step(step, phase):
            if log:
                log(f"    warning: {warning}")
        base = self.site.get("base_url", "").rstrip("/")
        if "goto" in step:
            target = step["goto"]
            page.goto(target if target.startswith("http") else base + target,
                      wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        elif "click" in step:
            page.click(step["click"], timeout=DEFAULT_TIMEOUT)
        elif "click_text" in step:
            page.get_by_text(step["click_text"], exact=False).first.click(
                timeout=DEFAULT_TIMEOUT)
        elif "fill" in step:
            page.fill(step["fill"], _expand_env(step.get("value", "")),
                      timeout=DEFAULT_TIMEOUT)
        elif "wait_for" in step:
            page.wait_for_selector(step["wait_for"], timeout=DEFAULT_TIMEOUT)
        elif "wait_ms" in step:
            page.wait_for_timeout(int(step["wait_ms"]))
        elif "press" in step:
            page.keyboard.press(step["press"])
        elif "scroll" in step:
            page.mouse.wheel(0, int(step["scroll"]))
        elif "hover" in step:
            page.hover(step["hover"], timeout=DEFAULT_TIMEOUT)
        elif "expand_all" in step:
            page.evaluate(
                "(sel) => document.querySelectorAll(sel).forEach(e => e.click())",
                step["expand_all"])
        else:
            raise ValueError(f"unknown capture step: {step}")

    def _session_still_works(self, page, emit) -> bool:
        """Does the saved session actually get us in, or has it lapsed?"""
        marker = self.site.get("signed_in_when") or "nav a, aside a, [role=tab], table"
        base = (self.site.get("base_url") or "").rstrip("/")
        try:
            page.goto(base or "/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector(marker, timeout=8000)
            return True
        except Exception:
            return False

    def login(self, page, log=None):
        emit = log or (lambda *_: None)
        for step in self.site.get("login", []) or []:
            try:
                self._run_step(page, step, phase="login", log=log)
            except Exception as e:
                if not self.handoff:
                    raise
                # A hand-over fills in what it can and no more. A product that
                # has just started asking for a code will fail on a step that
                # worked last week, and that is not a reason to stop: it is
                # exactly the case a person is here for.
                emit(f"    could not do that step, leaving it to you: "
                     f"{type(e).__name__}")
                break
        marker = self.site.get("signed_in_when") or "nav a, aside a, [role=tab], table"
        from .signin import await_signed_in, hand_over
        if await_signed_in(page, marker, timeout_ms=8000 if self.handoff else 30000,
                           log=log):
            self.guard.reached_product()
            emit("  signed in")
            return

        if self.handoff:
            emit("")
            emit("  over to you: finish signing in in the browser window,")
            emit("  including any code, prompt or key. The crawl carries on")
            emit("  by itself the moment the product is on screen.")
            ok = hand_over(page, marker, timeout_s=self.handoff_timeout_s,
                           log=emit, tick=self.on_wait)
            if ok:
                self.guard.reached_product()
                self.handed_over = True
                return
            raise RuntimeError(
                f"nobody finished signing in within "
                f"{self.handoff_timeout_s // 60} minutes, still on {page.url}.")

        # Failing here loudly beats twenty selector timeouts that each look
        # like a broken screen when the real fault is one sign-in.
        raise RuntimeError(
            f"sign-in did not reach the product, still on {page.url}. "
            f"Check the credentials for this connection.")

    # -- main -------------------------------------------------------------
    def run(self, only: list[str] | None = None, log=None, prefer_url: bool = True) -> dict:
        from playwright.sync_api import sync_playwright

        emit = log or (lambda *_: None)
        started = datetime.now().isoformat(timespec="seconds")

        state = self.site.get("storage_state")
        have_session = bool(state and Path(state).exists())
        # Waiting for a person in a browser they cannot see is waiting forever.
        # Unless the caller brought its own way of finishing the sign-in, which
        # is what `on_wait` is: the console's progress hook, or a test standing
        # in for the person. Then there is nobody to show a window to.
        needs_a_window = self.handoff and not have_session and self.on_wait is None
        headless = self.headless and not needs_a_window
        if needs_a_window and self.headless:
            emit("opening a visible browser: this connection asks you to sign in")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            ctx_args = {"viewport": VIEWPORT, "device_scale_factor": 1}
            if have_session:
                ctx_args["storage_state"] = state
            ctx = browser.new_context(**ctx_args)
            page = ctx.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT)
            self.guard.attach(page, log=emit)

            if have_session:
                # The session was captured interactively, so there is no form to
                # fill and no password anywhere in this process.
                emit(f"using the saved sign-in session ({Path(state).name})")
                if self.handoff and not self._session_still_works(page, emit):
                    # An expired session used to end the run. On a connection
                    # that already knows how to ask a person, ending the run is
                    # the one thing there is no reason to do.
                    emit("  that session has expired")
                    ctx.close()
                    if headless:
                        browser.close()
                        browser = pw.chromium.launch(headless=False)
                    ctx = browser.new_context(viewport=VIEWPORT,
                                              device_scale_factor=1)
                    page = ctx.new_page()
                    page.set_default_timeout(DEFAULT_TIMEOUT)
                    self.guard.attach(page, log=emit)
                    self.login(page, log=emit)
            else:
                emit("signing in ...")
                self.login(page, log=emit)

            if self.handed_over and state:
                # Nobody should be asked twice. Saving here is what turns a
                # hand-over into a one-off rather than a habit.
                try:
                    Path(state).parent.mkdir(parents=True, exist_ok=True)
                    ctx.storage_state(path=str(state))
                    emit(f"  session saved, the next crawl will not ask "
                         f"({Path(state).name})")
                except Exception as e:
                    emit(f"  could not save the session: {e}")

            self.guard.lock()
            emit("read-only guard armed: writes are blocked from here on")

            for screen in self.screens:
                if screen.skip or (only and screen.id not in only):
                    continue
                try:
                    if screen.signed_out:
                        # The sign-in page cannot be photographed from a signed-in
                        # browser: it redirects to the landing page, and the crawl
                        # then documents the wrong screen entirely.
                        emit(f"  {screen.id}: using a signed-out browser")
                        fresh = browser.new_context(viewport=VIEWPORT,
                                                    device_scale_factor=1)
                        fpage = fresh.new_page()
                        fpage.set_default_timeout(DEFAULT_TIMEOUT)
                        self.guard.attach(fpage, log=emit)
                        try:
                            self._capture_one(fpage, screen, emit, prefer_url=False)
                        finally:
                            fresh.close()
                    else:
                        self._capture_one(page, screen, emit, prefer_url)
                except Exception as e:
                    self.errors.append({"screen": screen.id, "error": str(e)})
                    emit(f"  ! {screen.id}: {str(e)[:180]}")
                # After every screen, not only at the end. A crawl of twenty
                # screens is minutes of someone's time and a lot of sign-in
                # traffic; if the process dies at screen nineteen, everything
                # already captured should still be usable rather than a folder
                # of orphaned images with nothing to read them by.
                self._write_manifest(started, partial=True)

            ctx.close()
            browser.close()

        if self.routes_path:
            save_routes(self.routes_path, self.routes)
        self.masker.save()

        return self._write_manifest(started, partial=False)

    def _write_manifest(self, started: str, partial: bool) -> dict:
        manifest = {
            "captured_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "partial": partial,
            "viewport": VIEWPORT,
            "base_url": self.site.get("base_url", ""),
            "screens": self.inventory,
            "errors": self.errors,
            "readonly": self.guard.report(),
            "signin": {"handoff": self.handoff, "handed_over": self.handed_over},
            "masking": self.masker.summary(),
            "healing": {**self.healer.summary(),
                        "proposals": self.healer.proposals()},
        }
        # written whole then moved, so a process killed mid-write leaves the
        # previous complete manifest rather than half a JSON file
        tmp = self.out_dir / "inventory.json.part"
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.out_dir / "inventory.json")
        return manifest

    # ------------------------------------------------------------------
    def _capture_one(self, page, screen: Screen, emit, prefer_url: bool):
        started = datetime.now()
        used_url = False
        remembered = (self.routes.get(screen.id) or {}).get("url") or screen.url

        if prefer_url and remembered and _is_direct(screen):
            emit(f"  {screen.id}: going straight to the remembered address")
            page.goto(remembered, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            used_url = True
            wait_for = next((s["wait_for"] for s in screen.steps if "wait_for" in s), None)
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=6000)
                except Exception:
                    emit("    remembered address did not settle, replaying the steps")
                    used_url = False
        if not used_url:
            for step in screen.steps:
                try:
                    self._run_step(page, step, phase="readonly", log=emit)
                except Exception:
                    key = next((k for k in ("click", "click_text", "wait_for", "hover")
                                if k in step), None)
                    if not (key and self.healer.enabled):
                        raise
                    emit(f"    step failed: {key}={str(step[key])[:60]}")
                    want = _describe_step(step, key, screen)
                    rep = self.healer.heal(page, screen.id, "step", key,
                                           str(step[key]), want, log=emit)
                    if not (rep and rep.verified):
                        raise
                    self._run_step(page, {**step, key: rep.new},
                                   phase="readonly", log=emit)
                    emit("    step recovered with the repaired selector")

        page.wait_for_timeout(screen.settle_ms)
        _await_quiet(page)
        self._live_frame(page, screen, "settled")

        masked = (self.masker.apply(page, log=emit, screen_id=screen.id)
                  if screen.mask else [])
        self._live_frame(page, screen, "masked")

        record = {
            "id": screen.id, "title": screen.title, "sections": screen.sections,
            "url": page.url, "reached_by": "url" if used_url else "steps",
            "elements": {}, "masked": len(masked),
        }
        for kind, sel in screen.extract.items():
            try:
                if isinstance(sel, str) and sel.startswith("@"):
                    strategy = STRATEGY_JS.get(sel)
                    if strategy is None:
                        raise ValueError(f"unknown extraction strategy {sel!r}")
                    values = page.evaluate(strategy)
                else:
                    values = page.evaluate(EXTRACT_JS, sel)
            except Exception as e:
                values = []
                self.errors.append({"screen": screen.id, "extract": kind, "error": str(e)})
            if not values and self.healer.enabled and not str(sel).startswith("@"):
                rep = self.healer.heal(
                    page, screen.id, "extract", kind, str(sel),
                    f"the {kind} shown on the {screen.title or screen.id} screen",
                    log=emit)
                if rep and rep.verified:
                    try:
                        values = page.evaluate(EXTRACT_JS, rep.new)
                    except Exception:
                        values = []
            record["elements"][kind] = [self.masker.scrub_text(v) for v in values]

        if screen.shot:
            target = self.shots_dir / screen.shot
            page.screenshot(path=str(target), full_page=False)
            record["shot"] = screen.shot

        # Named inline elements are photographed by selector, not by cropping the
        # full screenshot at fixed percentages. A percentage rectangle silently
        # captures the wrong control the moment a column is added or a row height
        # changes; a selector either resolves to the right element or fails loudly.
        captured_elements = []
        for spec in screen.elements:
            name, selector = spec.get("name"), spec.get("selector")
            if not (name and selector):
                continue
            try:
                loc = page.locator(selector).first
                loc.wait_for(state="visible", timeout=5000)
                loc.screenshot(path=str(self.shots_dir / name))
                captured_elements.append(name)
            except Exception as e:
                repaired = False
                if self.healer.enabled:
                    rep = self.healer.heal(
                        page, screen.id, "element", name, selector,
                        spec.get("describe") or f"the UI control named {name}",
                        log=emit)
                    if rep and rep.verified:
                        try:
                            loc = page.locator(rep.new).first
                            loc.wait_for(state="visible", timeout=4000)
                            loc.screenshot(path=str(self.shots_dir / name))
                            captured_elements.append(name)
                            repaired = True
                        except Exception:
                            repaired = False
                if not repaired:
                    self.errors.append({"screen": screen.id, "element": name,
                                        "error": str(e)[:200]})
                    emit(f"    ! element {name}: {str(e)[:120]}")
        if captured_elements:
            record["elements_captured"] = captured_elements
            emit(f"    captured {len(captured_elements)} inline element(s)")

        # Read the forms before the timings are closed. Purely a read: see the
        # header of forms.py for what this is not allowed to do.
        observed = forms.inspect(page, log=emit)
        if observed.get("forms"):
            record["forms"] = forms.scrub(observed, self.masker)
            record["form_counts"] = forms.summary(observed)
            a11y = forms.accessibility(record["forms"], screen.id)
            if a11y:
                record["a11y"] = a11y

        took = (datetime.now() - started).total_seconds()
        record["seconds"] = round(took, 1)
        self.inventory[screen.id] = record
        self.routes[screen.id] = {
            "url": page.url,
            "title": screen.title,
            "sections": list(screen.sections),
            "last_seen": datetime.now().isoformat(timespec="seconds"),
            "reached_by": record["reached_by"],
            "seconds": record["seconds"],
        }
        counts = ", ".join(f"{k}={len(v)}" for k, v in record["elements"].items())
        emit(f"  captured {screen.id} in {took:.1f}s via {record['reached_by']}  [{counts}]")


def _is_direct(screen: Screen) -> bool:
    """True when a screen is reachable by address alone.

    A screen whose steps click through a modal or a row cannot be reached by
    navigating to a URL, so the remembered address is not a shortcut for it.
    """
    for step in screen.steps:
        if any(k in step for k in ("click", "click_text", "expand_all", "hover")):
            return False
    return True


def _await_quiet(page, budget_ms: int = 4000):
    """Wait out spinners so a loading state never becomes a documentation figure."""
    selectors = ["[class*=spinner]", "[class*=Spinner]", "[class*=loading]",
                 "[class*=Loading]", "[class*=skeleton]", "[aria-busy=true]"]
    try:
        page.wait_for_function(
            """(sels) => !sels.some(s => Array.from(document.querySelectorAll(s))
                 .some(e => e.offsetWidth || e.offsetHeight))""",
            arg=selectors, timeout=budget_ms)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=budget_ms)
    except Exception:
        pass


def _expand_env(value: str) -> str:
    """Allow ${ENV_VAR} in the registry so credentials stay out of the repo."""
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), str(value))


def latest_capture(capture_root: Path) -> Path | None:
    runs = sorted([p for p in Path(capture_root).glob("*") if (p / "inventory.json").exists()])
    return runs[-1] if runs else None


def merged_inventory(capture_root: Path) -> tuple[dict, Path | None]:
    """The newest capture of each screen, across runs.

    Re-crawling one section writes a run holding only that screen. Treating the
    newest run as the whole picture would then hide every other screen's drift,
    which reads as the queue mysteriously emptying. Merge per screen instead, so
    a targeted recrawl refreshes exactly what it captured and leaves the rest
    standing.
    """
    runs = sorted([p for p in Path(capture_root).glob("*")
                   if (p / "inventory.json").exists()])
    if not runs:
        return {}, None
    merged: dict = {"screens": {}, "errors": [], "captured_at": "",
                    "readonly": {}, "masking": {}, "_runs": {}}
    for run in runs:                      # oldest first, so newer overwrite
        try:
            data = json.loads((run / "inventory.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        for sid, rec in (data.get("screens") or {}).items():
            merged["screens"][sid] = rec
            merged["_runs"][sid] = run.name
        merged["captured_at"] = data.get("captured_at", merged["captured_at"])
        merged["readonly"] = data.get("readonly", merged["readonly"])
        merged["masking"] = data.get("masking", merged["masking"])
        merged["errors"] = data.get("errors", [])
    return merged, runs[-1]


def load_inventory(run_dir: Path) -> dict:
    return json.loads((Path(run_dir) / "inventory.json").read_text(encoding="utf-8"))


def _describe_step(step: dict, key: str, screen) -> str:
    """Say in words what a step was trying to reach, for the repair prompt."""
    target = str(step[key])
    where = screen.title or screen.id
    if key == "click_text":
        return f"the control labelled {target!r} on the {where} screen"
    if key == "wait_for":
        return f"the main content of the {where} screen (was waiting for {target!r})"
    if key == "hover":
        return f"the element to hover on the {where} screen"
    return f"the control matching {target!r} on the {where} screen"
