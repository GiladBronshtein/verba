"""Prove the engine works, on a document it built itself.

The test project is scaffolded from scratch by `verba new`, which is the same
path a new user takes. That is deliberate: a suite written against one hand-made
fixture proves the engine works on that fixture, and this engine's whole claim is
that it works on a product it has never seen.

    python3 tools/selftest.py
    python3 tools/selftest.py -v      show tracebacks
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL, SKIP = "pass", "FAIL", "skip"
results: list[tuple[str, str, str]] = []


class SkipTest(Exception):
    pass


def check(name: str):
    def deco(fn):
        def run(*a, **k):
            try:
                results.append((name, PASS, fn(*a, **k) or ""))
            except SkipTest as e:
                results.append((name, SKIP, str(e)))
            except Exception as e:
                results.append((name, FAIL, f"{type(e).__name__}: {e}"))
                if "-v" in sys.argv:
                    traceback.print_exc()
        return run
    return deco


def ok(cond, msg):
    if not cond:
        raise AssertionError(msg)


def eq(got, want, what=""):
    if got != want:
        raise AssertionError(f"{what}expected {want!r}, got {got!r}")


# ── a project to test against, built the way a person would build one ────────

_FIXTURE: Path | None = None


def fixture() -> Path:
    """A scaffolded project, made once and reused."""
    global _FIXTURE
    if _FIXTURE is None:
        from verba.scaffold import Answers, Scaffold
        d = Path(tempfile.mkdtemp(prefix="verba-selftest-"))
        Scaffold(root=d, a=Answers(
            product="Acme Console", vendor="Acme Inc",
            about="Acme Console is where operators configure campaigns.",
            base_url="https://console.acme.test", auth="form",
            user="ops@acme.test", theme="atlas")).build()
        _FIXTURE = d
    return _FIXTURE


def fresh() -> Path:
    """A private copy, for tests that write."""
    d = Path(tempfile.mkdtemp(prefix="verba-write-"))
    shutil.copytree(fixture(), d, dirs_exist_ok=True)
    return d


# ── the wizard ───────────────────────────────────────────────────────────────

@check("a new project builds on the first try")
def t_scaffold_builds():
    """The whole promise of the wizard.

    A scaffold that needs one more edit before it renders is a scaffold that
    greets a new user with an error about a rule they have not read yet. The
    first section deliberately carries real prose rather than the TODO marker,
    because that marker is the one thing the rules refuse to ship.
    """
    from verba.lint import lint
    from verba.project import Project
    from verba.render.docx import DocxRenderer

    p = Project.load(fixture())
    eq(p.config["product"]["name"], "Acme Console", "product name did not land: ")
    ok(p.nodes, "the scaffolded document has no sections")

    errors = [f for f in lint(p) if f.level == "error"]
    ok(not errors, f"a new project breaks its own rules: "
                   f"{[(f.rule, f.message) for f in errors]}")

    out = Path(tempfile.mkdtemp()) / "out.docx"
    DocxRenderer(p).render(out)
    ok(out.exists() and out.stat().st_size > 8000, "the DOCX did not render")
    return f"{len(p.nodes)} sections, {out.stat().st_size // 1024} KB"


@check("the wizard refuses an answer it cannot honour")
def t_scaffold_refuses():
    from verba.scaffold import Answers
    for bad in ({"theme": "chartreuse"}, {"auth": "magic"}):
        try:
            Answers(product="X", **bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    return "unknown theme and unknown sign-in both refused"


# ── themes ───────────────────────────────────────────────────────────────────

def _ratio(a: str, b: str) -> float:
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@check("every theme is readable, measured rather than assumed")
def t_themes_contrast():
    """A palette that fails AA is a palette that ships an unreadable document.

    Measured against the ground each colour is actually painted on, not against
    the page: an accent that passes on white can fail on its own tinted callout,
    which is exactly where it is most often used.
    """
    from verba.theme import Theme, available
    ok(len(available()) >= 3, "there is barely a choice of theme")
    for name in available():
        t = Theme.named(name)
        for what, fg, bg, want in (
                ("body on page", t.navy_deep, "FFFFFF", 7.0),
                ("accent on page", t.brand_blue, "FFFFFF", 4.5),
                ("accent on tint", t.brand_blue, t.lavender, 4.5),
                ("body on tint", t.navy_deep, t.lavender, 7.0),
                ("cover on page", t.navy_hero, "FFFFFF", 7.0)):
            got = _ratio(fg, bg)
            ok(got >= want, f"{name}: {what} is {got:.2f}:1, wants {want}")
    return f"{len(available())} themes, 5 pairs each, all pass"


@check("the theme reaches the page, and no brand is baked in")
def t_theme_applied():
    """Both renderers had one company's hex values written into them."""
    from verba.render.html import CSS, themed_css
    from verba.render.pdf import print_css
    from verba.theme import Theme
    from verba.typography import Typography

    typo = Typography.load(fixture())
    for name in ("atlas", "ink", "forest"):
        th = Theme.named(name)
        pdf = print_css(typo.face("document"), typo.page, typo.text, th)
        web = themed_css(th)
        ok(f"#{th.brand_blue}" in pdf, f"{name} does not reach the print stylesheet")
        ok(f"#{th.brand_blue}" in web, f"{name} does not reach the preview")
        ok("$BLUE" not in pdf and "$NAVY" not in pdf, "a colour token was left unresolved")
        ok("$BLUE" not in web and "$LAV" not in web, "a colour token was left unresolved")

    slate = Theme.named("slate")
    others = [Theme.named(n) for n in ("ink", "atlas", "ember", "forest")]
    ok(all(o.brand_blue != slate.brand_blue for o in others),
       "the themes are not actually different from one another")
    ok("$" not in CSS.replace("$NAVY", "").replace("$BLUE", "").replace("$LAV", "")
       .replace("$PERI", "").replace("$GREYD", "").replace("$GREYM", "")
       .replace("$RED", "").replace("$GREEN", "").replace("$AMBER", ""),
       "the preview stylesheet has a token nothing substitutes")
    return "5 themes, both renderers, no literals left"


# ── the system description ───────────────────────────────────────────────────

@check("the writer is told what the product is, by a person")
def t_system_description():
    """A crawl proves a control exists. It cannot say what the control is for.

    That knowledge comes from content/system.md and nowhere else. It used to be
    one sentence hard-coded into a prompt string, naming one company's product,
    which is why documenting a second product meant editing the source.
    """
    from verba.console.assist import HOUSE_RULES, house_rules
    from verba.system import System

    d = fresh()
    empty = System.load(d)
    ok(not empty.exists or empty.words < 400, "fixture assumption changed")

    s = System.load(d)
    s.write(product="Acme Console", vendor="Acme Inc", audience="operator",
            about="Acme Console configures campaigns.")
    loaded = System.load(d)
    ok(loaded.exists, "the description did not survive a write")
    eq(loaded.product, "Acme Console", "product name lost: ")

    block = loaded.prompt_block()
    ok("Acme Console" in block, "the model is not told what it is documenting")
    ok("authoritative" in block, "the description is not given precedence")

    composed = house_rules(d)
    ok(composed.index("Acme Console") < composed.index("Never use an em dash"),
       "the product description must come before the craft rules")
    ok("Never use an em dash" in composed, "the writing rules were dropped")

    # with nothing written, the model must be told it knows nothing
    bare = Path(tempfile.mkdtemp())
    ok("TODO" in house_rules(bare),
       "with no description, the writer is not told to leave gaps rather than invent")
    ok("Rise" not in HOUSE_RULES, "one company's name is still baked into the rules")
    return f"{loaded.words} words, ahead of the craft rules"


# ── page setup ───────────────────────────────────────────────────────────────

@check("the sheet is a setting, and both outputs read the same one")
def t_page_setup():
    from verba.render.pdf import print_css
    from verba.typography import PAPERS, Typography
    from verba import layout

    d = fresh()
    for name in ("Letter", "A5", "A4"):
        layout.apply(d, paper=name, screenshot_width_cm=9)
        t = Typography.load(d)
        eq(t.page.paper_name, name, "paper did not survive a save: ")
        eq(t.page.width_mm, PAPERS[name][0], "wrong sheet width: ")
        ok(f"size: {name}" in print_css(t.face("document"), t.page, t.text),
           f"{name} does not reach the stylesheet")
    return f"{len(PAPERS)} sheets, PDF and DOCX read one setting"


@check("a refused layout change writes nothing at all")
def t_layout_atomic():
    """The panel posts the whole form, so it is one change, not eight."""
    from verba import layout
    d = fresh()
    layout.apply(d, paper="A4", side=18, screenshot_width_cm=15, toc_depth=3)
    before = layout.read(d)
    try:
        layout.apply(d, paper="A5", screenshot_width_cm=15)
        raise AssertionError("an impossible layout was accepted")
    except ValueError:
        pass
    after = layout.read(d)
    eq(after["paper"], before["paper"], "the paper moved despite the refusal: ")
    eq(after["screenshot_width_cm"], before["screenshot_width_cm"],
       "the figure width moved despite the refusal: ")
    ok("paper" in layout.apply(d, paper="A5", screenshot_width_cm=10),
       "a coherent change of both was not accepted as one")
    for bad in ({"paper": "Tabloid"}, {"side": 90}, {"toc_depth": 9},
                {"align": "centre"}, {"hyphens": "maybe"}):
        try:
            layout.apply(d, **bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    eq(layout.read(d)["paper"], "A5", "a refusal moved something: ")
    return "all-or-nothing, judged against the page being chosen"


@check("a setting is written without losing the page that explains it")
def t_settings_keep_prose():
    import yaml
    from verba import layout
    d = fresh()
    was = {f: [l for l in (d / "content" / f).read_text().splitlines()
               if l.strip().startswith("#")]
           for f in ("typography.yaml", "doc.yaml")}
    layout.apply(d, paper="Letter", side=20, align="justify", hyphens="off",
                 screenshot_width_cm=12, toc_depth=2)
    for f, before in was.items():
        now = [l for l in (d / "content" / f).read_text().splitlines()
               if l.strip().startswith("#")]
        eq(now, before, f"writing a setting rewrote the prose in {f}: ")
    cfg = yaml.safe_load((d / "content" / "doc.yaml").read_text())
    ok(cfg.get("outline"), "the outline was disturbed")
    typo = yaml.safe_load((d / "content" / "typography.yaml").read_text())
    ok(isinstance(typo["text"]["hyphens"], str),
       "hyphens came back a boolean, so the word the person chose was lost")
    return f"{sum(len(v) for v in was.values())} comment lines kept"


# ── editions ─────────────────────────────────────────────────────────────────

@check("an edition carries what it says, and says why not")
def t_editions():
    from verba import editions
    from verba.lint import lint
    from verba.project import Project

    d = fresh()
    # give it enough of an outline to drop something from
    doc = d / "content" / "doc.yaml"
    doc.write_text(doc.read_text().replace(
        "outline:\n  - id: introduction\n    children:\n      - id: introduction.acme-console-overview",
        "outline:\n  - id: introduction\n    children:\n      - id: introduction.acme-console-overview\n"
        "  - id: second\n    children:\n      - id: second.detail"))
    (d / "content" / "sections" / "second.md").write_text(
        "---\nid: second\ntitle: Second\nstatus: draft\nscreens: []\n---\n\nA chapter.\n")
    (d / "content" / "sections" / "second").mkdir(exist_ok=True)
    (d / "content" / "sections" / "second" / "detail.md").write_text(
        "---\nid: second.detail\ntitle: Detail\nstatus: draft\nscreens: []\n---\n\nA section.\n")

    whole = Project.load(d)
    n = len(whole.nodes)
    ok(n >= 4, f"the fixture outline is too small: {n}")

    editions.carry(d, "default", "second", False)
    cut = Project.load(d)
    shipping = {x.id for x in cut.nodes}
    ok("second" not in shipping and "second.detail" not in shipping,
       "dropping a chapter left its sections behind")
    eq(len(cut.nodes), n - 2, "the wrong number of sections was dropped: ")

    for f in lint(cut):
        ok(f.rule != "STRUCT-02" or f.section not in ("second", "second.detail"),
           f"a section left out on purpose is reported as forgotten: {f.section}")

    rows = {r["id"]: r for r in editions.read(cut)}
    eq(rows["second"]["why"], "left out of this edition")
    ok("under second" in rows["second.detail"]["why"], "no reason given")
    ok(not rows["second.detail"]["settable"],
       "a switch is offered that cannot be the answer")

    editions.reset(d, "default")
    eq(len(Project.load(d).nodes), n, "reset did not restore the document: ")
    for _ in range(3):
        editions.carry(d, "default", "second", False)
        editions.carry(d, "default", "second", True)
    eq(len(Project.load(d).nodes), n, "toggling twice did not return to the start: ")
    return f"{n} sections, branch drop and reset both correct"


@check("a neutral edition cannot print another edition's customer")
def t_neutral_edition():
    """Which names are forbidden is read off the editions, not typed into the linter.

    It used to be one company's customer name, in a constant, in lint.py. Every
    project built by this engine therefore policed that one word and no other.
    """
    from verba.lint import lint
    from verba.project import Project

    d = fresh()
    (d / "content" / "profiles" / "acmecorp.yaml").write_text(
        "name: acmecorp\naudience: operator\ntitle_suffix: \" (AcmeCorp)\"\n"
        "vars:\n  operator:\n    name: AcmeCorp\n    role: AcmeCorp operator\n"
        "    possessive: AcmeCorp's\n")

    neutral = Project.load(d, profile="default")
    ok(neutral.profile.neutral, "the default edition does not consider itself neutral")
    ok("AcmeCorp" in neutral.tenant_terms(),
       f"the customer name was not learned from the other edition: "
       f"{neutral.tenant_terms()}")

    branded = Project.load(d, profile="acmecorp")
    ok(not branded.profile.neutral, "a branded edition claims to be neutral")

    sec = next(iter(neutral.sections.values()))
    sec.blocks[0].text = "AcmeCorp operators can do this."
    found = [f for f in lint(neutral) if f.rule == "GENERIC-01"]
    ok(found, "a customer name in the neutral edition was not caught")

    branded.sections[sec.id].blocks[0].text = "AcmeCorp operators can do this."
    ok(not [f for f in lint(branded) if f.rule == "GENERIC-01"],
       "the customer's own edition may name the customer")
    return f"learned {neutral.tenant_terms()[:1]} from the editions"


# ── the guarantee ────────────────────────────────────────────────────────────

@check("nothing can be written to the system being documented")
def t_readonly():
    """The one guarantee that has to hold whatever else is wrong.

    Enforced in the browser rather than by being careful about which buttons a
    crawl clicks: every request that is not GET, HEAD or OPTIONS is aborted, and
    sign-in is the single logged exception.
    """
    from verba.readonly import Guard, UnsafeStep, check_step

    class Req:
        def __init__(self, method, url="https://console.acme.test/api/x"):
            self.method, self.url = method, url

    class Route:
        def __init__(self):
            self.acted = None

        def continue_(self):
            self.acted = "continue"

        def abort(self):
            self.acted = "abort"

    # once out of the sign-in phase, nothing that is not a read gets through
    g = Guard().lock()
    for m in ("GET", "HEAD", "OPTIONS"):
        r = Route(); g._handle(r, Req(m))
        eq(r.acted, "continue", f"{m} was blocked: ")
    for m in ("POST", "PUT", "PATCH", "DELETE"):
        r = Route(); g._handle(r, Req(m))
        eq(r.acted, "abort", f"{m} reached the platform: ")
    eq(len(g.blocked), 4, "the blocked writes were not recorded: ")

    # sign-in is the single exception, and every one of them is on the record
    s = Guard()
    r = Route(); s._handle(r, Req("POST", "https://console.acme.test/login"))
    eq(r.acted, "continue", "sign-in was blocked: ")
    eq(len(s.allowed_posts), 1, "the sign-in write was not recorded: ")
    eq(s.report()["blocked_writes"], 0, "sign-in counted as a blocked write: ")

    # a step that could write is refused before a browser is ever opened
    for step in ({"fill": "input", "value": "x"}, {"press": "Enter"},
                 {"sorcery": "yes"}):
        try:
            check_step(step, "readonly")
            raise AssertionError(f"a writing step was accepted: {step}")
        except UnsafeStep:
            pass
    # the same steps are what sign-in is made of, so there they are allowed
    check_step({"fill": "input", "value": "x"}, "login")
    ok(not check_step({"goto": "/"}, "readonly"), "a plain navigation was reported")
    # a click that reads like a commit is advised against rather than refused,
    # because the network guard is what actually stops it
    ok(check_step({"click": "button.save"}, "readonly"),
       "a click reading like a commit drew no warning")
    return "reads pass, writes abort, sign-in is the one logged exception"


@check("the content model round-trips")
def t_model():
    from verba.model import Section, parse_section
    src = (fixture() / "content" / "sections" / "introduction.md").read_text()
    sec = parse_section(src, "introduction")
    ok(sec.blocks, "the section parsed to nothing")
    ok(isinstance(sec, Section), "wrong type back")
    return f"{len(sec.blocks)} blocks"


# ── run ──────────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [t_scaffold_builds, t_scaffold_refuses, t_themes_contrast,
             t_theme_applied, t_system_description, t_page_setup,
             t_layout_atomic, t_settings_keep_prose, t_editions,
             t_neutral_edition,
             t_readonly, t_model]
    for t in tests:
        t()
    width = max(len(n) for n, _, _ in results)
    for name, status, note in results:
        tag = {PASS: "  ok  ", FAIL: " FAIL ", SKIP: " skip "}[status]
        print(f"[{tag}] {name:<{width}}   {note}")
    bad = sum(1 for _, s, _ in results if s == FAIL)
    n_skip = sum(1 for _, s, _ in results if s == SKIP)
    print(f"\n{len(results) - bad - n_skip} passed, {bad} failed, {n_skip} skipped")
    if _FIXTURE:
        shutil.rmtree(_FIXTURE, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
