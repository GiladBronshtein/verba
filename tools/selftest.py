"""Prove the engine works, on a document it built itself.

The test project is scaffolded from scratch by `verba new`, which is the same
path a new user takes. That is deliberate: a suite written against one hand-made
fixture proves the engine works on that fixture, and this engine's whole claim is
that it works on a product it has never seen.

    python3 tools/selftest.py
    python3 tools/selftest.py -v      show tracebacks
"""
from __future__ import annotations

import base64
import json
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


# The smallest valid PNG. Several rules only care that a file is there and
# readable, not what is in it.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

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


@check("a command finds the project you are standing in")
def t_find_root():
    """The default project root was the package's own parent directory.

    Correct for exactly as long as the engine lived inside the single project it
    served. Installed from a package it points at site-packages, so `verba
    build` run in your own project goes looking for someone else's document.
    """
    from verba.cli import find_root

    d = fresh()
    eq(find_root(d), d.resolve(), "the project root was not found from its own root: ")
    deep = d / "content" / "sections"
    eq(find_root(deep), d.resolve(), "not found from a subdirectory: ")

    # nowhere near a project: fall back to where you are, not to the package
    bare = Path(tempfile.mkdtemp()).resolve()
    eq(find_root(bare), bare, "outside a project the answer should be here: ")
    ok(Path(__file__).resolve().parent.parent != find_root(deep),
       "the engine's own directory is being used as a project root")
    return "found from the root, from a subdirectory, and outside one"


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
    from verba import layout
    from verba.render.pdf import print_css
    from verba.typography import PAPERS, Typography

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
    was = {f: [line for line in (d / "content" / f).read_text().splitlines()
               if line.strip().startswith("#")]
           for f in ("typography.yaml", "doc.yaml")}
    layout.apply(d, paper="Letter", side=20, align="justify", hyphens="off",
                 screenshot_width_cm=12, toc_depth=2)
    for f, before in was.items():
        now = [line for line in (d / "content" / f).read_text().splitlines()
               if line.strip().startswith("#")]
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

    # a hand-over puts a person at the keyboard inside the sign-in phase, where
    # writes are permitted. The moment the product is on screen that stops being
    # true, before `lock()` runs, so their next click cannot reach the product.
    h = Guard()
    r = Route(); h._handle(r, Req("POST", "https://idp.example.test/verify"))
    eq(r.acted, "continue", "the second factor was blocked: ")
    h.reached_product()
    r = Route(); h._handle(r, Req("PUT"))
    eq(r.acted, "abort", "a click after the sign-in landed reached the product: ")
    r = Route(); h._handle(r, Req("GET"))
    eq(r.acted, "continue", "reading was blocked after the hand-over: ")

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
    return ("reads pass, writes abort, sign-in is the one logged exception, "
            "and it closes the moment the product appears")


@check("a rewrite can never drop a figure")
def t_rewrites_keep_figures():
    """A model asked to reconcile a section is being asked about labels and
    sentences, not about whether the section should have pictures.

    It answered that question anyway. One rewrite took a section from thirteen
    figures to two, and because a missing figure is only an INFO finding, the
    measurement guarding every other step waved it through: errors before,
    errors after, unchanged, keep it. Fourteen pictures left a real document
    that way and had to be restored from history.
    """
    import inspect as _i

    from verba.auto import Auto, _figures_of, _keeps_every_figure

    had = "t\n![One](a.png)\n![Two](b.png =14cm)\nx"
    eq(_figures_of(had), ["a.png", "b.png"], "figures not found: ")
    ok(_keeps_every_figure(had, had), "an identical rewrite was rejected")
    ok(not _keeps_every_figure(had, "t\n![One](a.png)\nx"),
       "a rewrite that drops a figure was allowed")
    ok(_keeps_every_figure(had, had + "\n![Three](c.png)"),
       "adding a figure was treated as losing one")

    # and every path that writes a whole section back is guarded
    for fn in (Auto._review_against_evidence, Auto._assist):
        ok("_keeps_every_figure" in _i.getsource(fn),
           f"{fn.__name__} can write a rewrite that drops a figure")
    return "no whole-section rewrite can lose a picture"


@check("no two steps can undo each other forever")
def t_no_tug_of_war():
    """Two steps with opposite goals and no knowledge of each other.

    In the real document the decider removed a figure because it showed the
    wrong screen, and the sweep offered the same figure back because the section
    then had none. Four rounds of it are in that project's history, and the
    finding never cleared however many times the button was pressed. Whatever
    one step retires, another must not reinstate.
    """
    import inspect as _i

    from verba import auto, sweep

    settle = _i.getsource(auto.Auto._settle_the_rest)
    ok('"retired"' in settle,
       "the decider removes a figure without recording that it was on purpose")

    offer = _i.getsource(sweep.Sweep)
    ok('retired' in offer,
       "the sweep can offer back a figure the decider deliberately removed")

    # and the rules stop counting the consequences as new work
    from verba import lint as lintmod
    src = _i.getsource(lintmod)
    ok(src.count('"retired"') >= 2,
       "a retired picture is still reported as unreferenced, or its section as "
       "having no figure, which turns one settled finding into two new ones")
    return "retirement is recorded, honoured, and not reported back"


@check("two writers cannot lose each other's work")
def t_atomic_writes():
    """Every store here is read whole, changed, and written whole. That is the
    right shape for files a person can open and read, and it has exactly one
    failure: two writers at once, where the second to finish wins and the
    first's work is gone with nothing saying so.

    Theoretical while one console served one project. Not theoretical once the
    console could switch documents and the command line grew a `fix` that
    writes while you watch the same document in a browser.
    """
    import json
    import threading

    from verba.atomic import update_json

    root = Path(tempfile.mkdtemp(prefix="verba-lock-"))
    store = root / "decisions.json"

    def bump():
        for _ in range(150):
            with update_json(store) as box:
                box[0]["n"] = box[0].get("n", 0) + 1

    store.write_text(json.dumps({"n": 0}))
    threads = [threading.Thread(target=bump) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    got = json.loads(store.read_text())["n"]
    eq(got, 600, "writes were lost under concurrency: ")

    # and every store actually goes through it, or the guarantee is decorative
    import inspect as _i

    import verba.assets
    import verba.decisions
    import verba.incidents
    import verba.knowledge
    import verba.masking
    import verba.notes
    import verba.version
    import verba.workspaces
    for mod in (verba.decisions, verba.knowledge, verba.notes, verba.incidents,
                verba.assets, verba.masking, verba.version, verba.workspaces):
        src = _i.getsource(mod)
        ok("write_json" in src,
           f"{mod.__name__.split('.')[-1]} still writes its store unguarded")
    return "600/600 concurrent writes kept, 8 stores locked"


@check("an approval is permission, not a record that it was applied")
def t_approval_is_permission():
    """A change approved but never landed must not be skipped forever.

    One in the real document was approved by a step that was then undone, so
    the record said yes and the document said nothing, and every run since had
    skipped it. Only a decline stops a change being made.
    """
    import inspect as _i

    from verba.auto import Auto
    from verba.decisions import Decisions

    root = fresh()
    d = Decisions.load(root)
    change = {"section": "s", "kind": "fields", "change": "added",
              "label": "Widget", "screen": "x"}
    d.record(change, "approved", "")
    v = Decisions.load(root).verdict_for(change)
    ok(v is not None, "the approval was not stored")
    eq(v.verdict, "approved", "wrong verdict: ")

    src = _i.getsource(Auto._drift)
    ok('verdict.verdict == "declined"' in src,
       "the loop still skips a change merely because somebody approved it")
    return "approved but unlanded changes are applied"


@check("the system's own retreat is not a person's ruling")
def t_auto_decline_is_not_binding():
    """A decline the machine made under yesterday's abilities is reconsidered
    when those change. A person's decline is not."""
    from verba.decisions import Decisions

    root = fresh()
    d = Decisions.load(root)
    mine = {"section": "s", "kind": "fields", "change": "added",
            "label": "Mine", "screen": "x", "line": "added field `Mine`"}
    theirs = {"section": "s", "kind": "fields", "change": "added",
              "label": "Theirs", "screen": "x", "line": "added field `Theirs`"}
    d.record(mine, "declined", "applying this added a rule finding", by="auto")
    d.record(theirs, "declined", "we do not document this", by="human")

    again = Decisions.load(root)
    ok(not again.verdict_for(mine).binding,
       "the machine's own decline is being treated as binding")
    ok(again.verdict_for(theirs).binding,
       "a person's decline stopped being binding")

    notes = again.notes_for("s")
    ok("Theirs" in notes, "the person's decision is not passed to the writer")
    ok("Mine" not in notes,
       "the machine's own retreat is quoted back as a human ruling")
    return "auto declines are reconsidered, human declines bind"


@check("a difference and the description it needs are judged together")
def t_apply_and_describe_are_one_step():
    """Applying a difference that adds a control creates an entry with no
    description, and an unwritten description is itself a finding. Measured on
    its own, the change that is exactly right looks worse than not making it."""
    import inspect as _i

    from verba.auto import Auto

    src = _i.getsource(Auto._drift)
    ok("_describe(" in src,
       "an applied difference is judged before what it added is described")
    desc = _i.getsource(Auto._describe) + _i.getsource(Auto._assist)
    ok("fill_todos" in desc,
       "describing runs something other than the task that fills TODOs")
    ok("available()" in desc,
       "a missing model is not reported, so the refusal has no reason")

    # and every finding that names a rewrite as its fix gets one, or "fix what
    # can be fixed" leaves standing exactly the findings whose remedy the
    # system is holding in its hand
    pol = _i.getsource(Auto._polish)
    ok("assist:" in pol, "the loop ignores findings whose remedy is a rewrite")
    ok("_polish" in _i.getsource(Auto.run), "the rewrite step is never run")
    return "apply, describe, rewrite, then measure"


@check("a real click on Save never reaches a real server")
def t_readonly_live():
    """The guarantee, proved against something that records what it receives.

    Checking the guard's own bookkeeping proves the guard agrees with itself.
    The claim people actually care about is that the product never sees the
    request, and only a server can answer that, so this stands one up, drives a
    real browser at it with the guard armed, clicks a button wired to a PUT, and
    then asks the server what it got.
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received: list[str] = []

    PAGE = b"""<!doctype html><html><body>
    <h1>Account</h1>
    <button id="save">Save</button>
    <script>
      document.getElementById('save').onclick = () => {
        fetch('/api/accounts/1', {method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: 'changed by a stray click'})});
      };
    </script></body></html>"""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def _write(self):
            received.append(f"{self.command} {self.path}")
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_PUT = do_POST = do_PATCH = do_DELETE = _write

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        from playwright.sync_api import sync_playwright

        from verba.readonly import Guard
        guard = Guard()
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page()
            guard.attach(page)
            guard.lock()                      # sign-in is over; nothing may write
            page.goto(f"http://127.0.0.1:{port}/accounts/1")
            page.click("#save")
            page.wait_for_timeout(700)
            b.close()
    except ImportError:
        raise SkipTest("playwright is not installed")
    finally:
        srv.shutdown()

    eq(received, [], "the server was written to: ")
    ok(guard.blocked, "the write was neither delivered nor recorded as blocked")
    ok(any("PUT" in x for x in guard.blocked),
       f"the blocked write was not the PUT: {guard.blocked}")
    ok(json.dumps(guard.report()), "the guard cannot report what it did")
    return f"clicked Save; server received nothing; {guard.blocked[0][:44]}..."


@check("a sign-in a machine cannot finish is handed to a person")
def t_handoff_waits_for_the_person():
    """Two-factor sign-in, proved against a server that insists on the code.

    The interesting case is not "does it wait": anything can wait. It is that
    the crawl fills in what it knows, stops at the wall, carries on by itself
    once the wall is gone, saves the session so nobody is asked twice, and is
    read-only again the moment the product appears.

    The person is played by the `on_wait` hook, which is the same seam the
    console uses to stream progress. Same thread, no timing games.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    writes: list[str] = []
    CODE = "314159"

    LOGIN = b"""<!doctype html><html><body><h1>Sign in</h1>
      <form method="POST" action="/login">
        <input type="email" name="u" autocomplete="username">
        <input type="password" name="p" autocomplete="current-password">
        <button type="submit">Continue</button>
      </form></body></html>"""

    # Same path, new page. An address check alone reports this as signed in.
    CODEPAGE = b"""<!doctype html><html><body><h1>Check your phone</h1>
      <form method="POST" action="/code">
        <input autocomplete="one-time-code" name="code" id="code">
        <button type="submit" id="go">Verify</button>
      </form></body></html>"""

    PRODUCT = b"""<!doctype html><html><body>
      <nav><a href="/">Home</a></nav>
      <h1>Accounts</h1>
      <table><thead><tr><th>NAME</th><th>PLAN</th></tr></thead>
      <tbody><tr><td>Example Account 1</td><td>Pro</td></tr></tbody></table>
      <button id="save">Save</button>
      <script>document.getElementById('save').onclick = () =>
        fetch('/api/accounts/1', {method: 'PUT'});</script>
      </body></html>"""

    state = {"password": False, "code": False}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not state["password"]:
                return self._send(LOGIN)
            if not state["code"]:
                return self._send(CODEPAGE)
            return self._send(PRODUCT)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n).decode()
            if self.path == "/login":
                state["password"] = True
            elif self.path == "/code" and CODE in body:
                state["code"] = True
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _write(self):
            writes.append(f"{self.command} {self.path}")
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_PUT = do_PATCH = do_DELETE = _write

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    typed = {"n": 0}

    def be_the_person(page, seconds_left):
        """What a human does: reads the code off their phone and types it."""
        if typed["n"] or not page.query_selector("#code"):
            return
        page.fill("#code", CODE)
        page.click("#go")
        typed["n"] += 1

    try:
        from verba.capture import Capture, Screen
    except ImportError:
        srv.shutdown()
        raise SkipTest("playwright is not installed")

    root = Path(tempfile.mkdtemp(prefix="verba-handoff-"))
    session = root / ".verba" / "sessions" / "t.json"
    site = {
        "base_url": base,
        "signed_in_when": "table",
        "handoff": True,
        "handoff_timeout_s": 60,
        "storage_state": str(session),
        "login": [
            {"goto": "/"},
            {"wait_for": "input"},
            {"fill": 'input[autocomplete="username"]', "value": "ops@example.test"},
            {"fill": 'input[autocomplete="current-password"]', "value": "hunter2"},
            {"click": 'button[type="submit"]'},
        ],
    }
    screens = [Screen(id="accounts", title="Accounts", sections=["accounts"],
                      shot="accounts-1.png",
                      steps=[{"goto": "/"}, {"wait_for": "table"}],
                      extract={"columns": "table thead th"})]
    cap = Capture(site, screens, root / "capture" / "run",
                  headless=True, on_wait=be_the_person)
    try:
        manifest = cap.run(log=lambda *a: None)
    finally:
        srv.shutdown()

    ok(cap.handed_over, "the crawl did not hand over, so it never waited")
    eq(typed["n"], 1, "the person was asked for a code this many times: ")
    cols = (manifest.get("screens") or {}).get("accounts", {}) \
        .get("elements", {}).get("columns", [])
    ok("NAME" in cols, f"the crawl never reached the product: {cols}")
    ok(session.exists(), "the session was not saved, so it would ask again")
    eq(writes, [], "the product was written to during the sign-in: ")
    ok(cap.guard.phase == "readonly",
       "the guard was left in its sign-in phase after the hand-over")
    return (f"filled the password, waited, took the code, "
            f"read {len(cols)} columns, saved the session")


@check("a finding nothing can act on is not put in front of a person")
def t_only_actionable_work_is_reported():
    """Three ways the To fix list stayed full no matter how often it was run.

    All three were invisible to the rule count, which is what the loop measures
    itself by, so every round reported success while the list did not move.
    """
    import json

    from verba.auto import _worth_deciding
    from verba.lint import INFO, Finding, lint
    from verba.project import Project

    root = fresh()

    # 1. The decider only ever looked at errors and warnings, so every INFO was
    #    structurally unreachable by the one step whose job is settling things.
    ok(_worth_deciding(Finding("ASSET-06", INFO, "s", "x")),
       "an INFO the system can act on is still invisible to the decider")
    ok(not _worth_deciding(Finding("META-01", INFO, "s", "x")),
       "an INFO only a person can settle is being sent to the decider")

    # 2. An unreferenced picture that no screen produces cannot be reached by
    #    any step: no crawl replaces it, nothing adopts it. Reporting it is
    #    asking for work that cannot be done.
    assets = root / "content" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "orphan-from-an-old-import.png").write_bytes(PNG)
    reg = json.loads((assets / "registry.json").read_text())
    reg["orphan-from-an-old-import.png"] = {"legacy_name": "old_doc_fig_12.png"}
    (assets / "registry.json").write_text(json.dumps(reg))
    stray = [f for f in lint(Project.load(root))
             if f.rule == "ASSET-05" and "orphan" in f.message]
    eq(stray, [], "a picture no screen produces was reported as work: ")

    # 3. ASSET-07 asks a section to adopt its screen's capture. ASSET-12 rules
    #    that capture is of something else. Each is right; together they took
    #    turns forever, and the rule count never moved so nothing noticed.
    proj = Project.load(root)
    sec = next(s for s in proj.sections.values() if s.screens)
    screen = sec.screens[0]
    import yaml
    reg_path = root / "content" / "screens.yaml"
    data = yaml.safe_load(reg_path.read_text())
    shot = next(s["shot"] for s in data["screens"] if s["id"] == screen)

    body = sec.path.read_text(encoding="utf-8")
    other = "a-different-picture.png"
    (assets / other).write_bytes(PNG)
    sec.path.write_text(body + f"\n\n![Something else]({other})\n", encoding="utf-8")

    def asset07():
        return [f for f in lint(Project.load(root)) if f.rule == "ASSET-07"]

    ok(asset07(), "ASSET-07 did not fire, so this test proves nothing")

    (root / "review").mkdir(exist_ok=True)
    (root / "review" / "picture-match.json").write_text(json.dumps({
        f"{sec.id}|{shot}": {"fits": False, "what": "shows a different screen",
                             "when": "2026-08-23"}}), encoding="utf-8")
    eq(asset07(), [],
       "ASSET-07 still asks for a picture already ruled to be of something else: ")
    # 4. Removing a crop from the registry must not take the registry's prose
    #    with it. Loading and dumping the YAML is four lines and loses every
    #    comment in the file, the block about credentials included.
    import yaml as _yaml

    from verba.auto import Auto
    reg_text = reg_path.read_text(encoding="utf-8")
    comments = [ln for ln in reg_text.splitlines() if ln.strip().startswith("#")]
    ok(comments, "the scaffolded registry has no prose, so this proves nothing")
    data = _yaml.safe_load(reg_text)
    target = data["screens"][0]
    target.setdefault("elements", []).append(
        {"name": "icon-nothing-shows.png", "selector": ".badge"})
    reg_path.write_text(_yaml.safe_dump(data, sort_keys=False)
                        + "\n" + "\n".join(comments), encoding="utf-8")
    kept = [ln for ln in reg_path.read_text().splitlines()
            if ln.strip().startswith("#")]

    ok(Auto(root)._stop_capturing("icon-nothing-shows.png", "nothing shows it",
                                  lambda *a: None),
       "the loop could not take an unused crop out of the registry")
    now = reg_path.read_text(encoding="utf-8")
    eq([ln for ln in now.splitlines() if ln.strip().startswith("#")], kept,
       "taking a crop out of the registry rewrote its prose: ")
    after = _yaml.safe_load(now)
    eq(len(after["screens"]), len(data["screens"]), "screens were lost: ")
    ok("icon-nothing-shows.png" not in now, "the crop is still in the registry")

    # 5. A verdict is about an image, not a filename. Two rules read these
    #    now, so one that never expired would silence a rule on evidence about
    #    a picture that has since been replaced.
    from verba.auto import _picture_digest, _verdict_still_about
    shot_path = assets / other
    digest = _picture_digest(root, other)
    ok(digest, "a picture on disk has no fingerprint")
    fresh_verdict = {"fits": False, "of": digest}
    ok(_verdict_still_about(root, other, fresh_verdict),
       "a verdict about the picture that is there was called stale")
    shot_path.write_bytes(PNG + b"\n")          # the screen was photographed again
    ok(not _verdict_still_about(root, other, fresh_verdict),
       "a verdict about a replaced picture is still believed")
    ok(_verdict_still_about(root, other, {"fits": False}),
       "a verdict from before fingerprints were kept was thrown away")

    return ("unreachable work is not reported, the two rules no longer fight, "
            "the registry keeps its prose, and a verdict expires with its picture")


@check("verified means a person checked it, not that somebody typed it")
def t_verified_costs_something():
    """The signal the whole system's credibility rests on.

    On the first real document built with this engine, all thirty-eight
    sections said verified, thirty-five of them stamped with the same date,
    while History recorded 2.8% of the changes as having a human behind them.
    The rule meant to catch that stayed quiet because a date was present.
    """
    from verba.attest import attest, demote, is_attested
    from verba.history import History
    from verba.lint import lint
    from verba.project import Project

    root = fresh()
    (root / "capture" / "2026-08-23T000000").mkdir(parents=True, exist_ok=True)
    (root / "capture" / "2026-08-23T000000" / "inventory.json").write_text("{}")

    proj = Project.load(root)
    sec = next(iter(proj.sections.values()))

    # a stamp with nothing behind it is reported, where it used to pass
    sec.meta["status"] = "verified"
    sec.meta["last_verified"] = "2026-07-01"
    sec.save(sec.path)
    fired = [f for f in lint(Project.load(root)) if f.rule == "FRESH-04"]
    ok(fired, "a section claiming verified with nobody named passed the rules")
    eq(len(fired), 1,
       "one migration state was reported once per section rather than once: ")

    # a real acceptance carries who and against what, and clears it
    sec.meta = attest(sec.meta, "gilad", "2026-08-23T000000", "2026-08-23")
    sec.save(sec.path)
    ok(is_attested(sec.meta), "the acceptance did not record its evidence")
    # one fewer unsigned section than before, and the summary says so
    after = [f for f in lint(Project.load(root)) if f.rule == "FRESH-04"]
    before_n = int(fired[0].message.split()[0])
    if after:
        eq(int(after[0].message.split()[0]), before_n - 1,
           "signing a section did not shorten the count: ")
    else:
        eq(before_n, 1, "the rule went quiet with sections still unsigned: ")

    # putting a section back is not authoring it: the acceptance returns with
    # the text, because it was that text a person accepted. Without this one
    # reverted step stripped the badge off eighteen sections whose content was
    # fully restored, and the finding count going down read as progress.
    from verba.attest import demote as _dm
    signed = "---\nstatus: verified\nverified_by: g\n---\nx"
    ok("verified" in _dm(signed, "auto", "put back"),
       "putting a section back stripped the acceptance off the text it restored")
    ok("review" in _dm(signed, "auto", "review"),
       "a machine rewrite kept the acceptance")

    # and a machine touching it afterwards takes the badge away, at the choke
    # point every machine write in the engine goes through
    text = sec.path.read_text(encoding="utf-8")
    History(root).record(sec.id, sec.path, text, text + "\n\nAdded by a model.\n",
                         actor="auto", action="edit")
    after = sec.path.read_text(encoding="utf-8")
    ok("status: review" in after,
       "a model rewrote a verified section and it stayed verified")
    ok("verified_by" not in after,
       "the acceptance outlived the text it was an acceptance of")

    # a person editing it does not lose their own badge
    ok(demote("---\nstatus: verified\n---\nx", "human") ==
       "---\nstatus: verified\n---\nx",
       "a person's own edit dropped their acceptance")
    # and the loop must never be able to sign one itself, which is the whole
    # reason the signature is worth anything
    from verba.auto import _is_a_persons_signature
    from verba.lint import WARN, Finding
    ok(_is_a_persons_signature(Finding("FRESH-04", WARN, "s", "x")),
       "the decider is allowed to consider marking a section verified")
    ok(not _is_a_persons_signature(Finding("ASSET-03", WARN, "s", "x")),
       "an ordinary finding was routed away from the decider")
    src = (Path(__file__).resolve().parents[1] / "verba" / "auto.py").read_text()
    ok('"verified"' not in src and "'verified'" not in src,
       "the loop names the verified status, so it can reach for it")
    return "a claim carries who and against what, and no machine can sign one"


@check("a step cannot damage what no rule measures")
def t_invariants_catch_what_counting_missed():
    """Three separate steps did this in one session, at a flat rule count.

    Each was fixed with a guard against that specific pair of steps. This is
    the property instead of the patch.
    """
    from verba.invariants import Shape, broken, tug_of_war

    was = Shape(sections={"s": {"figures": {"a.png", "b.png", "c.png"},
                                "blocks": {"fields", "columns"}, "words": 400}})

    keep = Shape(sections={"s": {"figures": {"a.png", "b.png", "c.png"},
                                 "blocks": {"fields", "columns"}, "words": 380}})
    eq(broken(was, keep), [], "an ordinary tightening was called damage: ")

    lost = Shape(sections={"s": {"figures": {"a.png"},
                                 "blocks": {"fields", "columns"}, "words": 400}})
    ok(any("figure" in x for x in broken(was, lost)),
       "a rewrite dropping two figures was not caught")

    gutted = Shape(sections={"s": {"figures": {"a.png", "b.png", "c.png"},
                                   "blocks": {"fields", "columns"}, "words": 90}})
    ok(broken(was, gutted), "a section cut to a quarter of itself was not caught")

    blocks = Shape(sections={"s": {"figures": {"a.png", "b.png", "c.png"},
                                   "blocks": {"fields"}, "words": 400}})
    ok(any("columns" in x for x in broken(was, blocks)),
       "a lost table block was not caught")

    eq(broken(was, Shape(sections={})),
       ["s stopped existing"], "a vanished section was not caught: ")

    # and every fault is attributed, so a step that damages one section of
    # five loses that one rather than all five
    from verba.invariants import faults
    two = Shape(sections={"good": {"figures": {"a.png"}, "blocks": set(), "words": 100},
                          "bad": {"figures": {"b.png"}, "blocks": set(), "words": 100}})
    late = Shape(sections={"good": {"figures": {"a.png"}, "blocks": set(), "words": 98},
                           "bad": {"figures": set(), "blocks": set(), "words": 100}})
    eq(sorted(faults(two, late)), ["bad"],
       "the fault was not attributed to the section that caused it: ")

    # two steps taking turns, at a constant count, over two rounds
    rounds = [{"writes": {"a.md": ["decide", "look"]}},
              {"writes": {"a.md": ["look", "decide"]}}]
    ok(tug_of_war(rounds), "two steps undoing each other went unnoticed")
    # and the loop must actually call it. It was written, tested in isolation,
    # and never wired in, which is a detector that detects nothing.
    src = (Path(__file__).resolve().parents[1] / "verba" / "auto.py").read_text()
    ok("tug_of_war(" in src and "round_writes" in src,
       "the tug-of-war detector is not called by the loop")
    eq(tug_of_war([{"writes": {"a.md": ["decide"]}}] * 2), [],
       "one step writing one file twice was called a fight: ")
    return "figures, blocks, word floor, whole sections, and steps taking turns"


@check("a runaway loop stops instead of billing all night")
def t_model_calls_are_bounded_and_counted():
    """Twenty-one call sites, and until now no idea how many were made.

    The ceiling is not there to save money on a normal run. It is there so a
    loop stuck in a circle stops and says so, rather than continuing quietly
    until somebody finds out from an invoice.
    """
    from verba.budget import Budget, OverBudget

    b = Budget.for_run(3)
    for _ in range(3):
        b.check("decide")
        b.spend("decide", "x" * 4000, "y" * 800)
    ok("3 model call(s) of 3" in b.summary(), f"the tally is wrong: {b.summary()}")
    ok(b.tokens() > 0, "nothing was counted")
    try:
        b.check("decide")
        raise AssertionError("the ceiling did not stop the run")
    except OverBudget:
        pass

    # a picture costs more than a sentence, and is counted as such
    v = Budget.for_run(10)
    v.spend("look at a picture", "brief", "CLEAN", images=1)
    ok(v.tokens() > 1000, "a picture was counted as if it were a few words")

    # and the meter is at the door every call goes through
    src = (Path(__file__).resolve().parents[1] / "verba" / "console"
           / "assist.py").read_text()
    eq(src.count("_BUDGET.spend"), 3,
       "a model call site is not metered (run_model, look, match): ")

    root = fresh()
    b.record(root)
    ledger = json.loads((root / "review" / "model-usage.json").read_text())
    ok(ledger["runs"], "the run was not written to the ledger")
    return "ceiling enforced, tally kept, three call sites metered, ledger written"


@check("a missing theme cannot fail a publish")
def t_themes_ship_and_never_stop_a_build():
    """Two faults, one of which would have hit every real install.

    The themes lived beside the package rather than in it, and were not listed
    as package data, so `pip install verba-docs` shipped none of them and the
    first build would die on "no such theme: slate". It was invisible because
    every user so far ran from a checkout, where the directory happens to be
    where the lookup pointed.

    And a theme that cannot be found ended a publish in a traceback, which is
    the worst possible way to learn that the colour of your headings is wrong.
    """
    import subprocess
    import tomllib

    from verba.lint import lint
    from verba.project import Project
    from verba.theme import BUILTIN, Theme, available

    repo = Path(__file__).resolve().parents[1]
    pkg = repo / "verba"
    ok(BUILTIN.is_relative_to(pkg),
       f"the themes are outside the package, so an install ships none: {BUILTIN}")
    ok(available(), "no themes at all")
    data = tomllib.loads((repo / "pyproject.toml").read_text())
    globs = data["tool"]["setuptools"]["package-data"]["verba"]
    ok(any("themes" in g for g in globs),
       f"the themes are not declared as package data: {globs}")

    root = fresh()
    # a project may carry a palette of its own, and it wins
    (root / "themes").mkdir(exist_ok=True)
    (root / "themes" / "house.yaml").write_text(
        "label: House\nabout: The house palette.\nbrand_blue: '#123456'\n")
    ok("house" in available(root), "a project's own theme was not offered")
    eq(Theme.named("house", root).label, "House", "the project theme was not read: ")

    # and one that is not there renders in the default and says so
    (root / "content" / "theme.yaml").write_text("use: vanished\ntokens: {}\n")
    picked = Theme.load(root)
    eq(picked.missing, "vanished", "the substitution was made silently: ")
    ok(picked.name != "vanished", "a theme that does not exist was returned")
    flagged = [f for f in lint(Project.load(root)) if f.rule == "DESIGN-04"]
    ok(flagged, "rendering in the wrong palette was not reported")

    r = subprocess.run([sys.executable, "-m", "verba", "--root", str(root), "build"],
                       capture_output=True, text=True, cwd=str(repo))
    eq(r.returncode, 0,
       "a missing theme still fails a build:\n" + (r.stdout + r.stderr)[-400:])
    return "themes ship inside the package, a project may add its own, and a missing one falls back"


@check("the cover places its parts and nothing is said twice")
def t_cover_and_duplicate_content():
    """Two faults a reader sees before anything else.

    The cover ran the vendor at 64pt and the product under it at 32pt, so a
    document whose vendor and product share a word printed RISE and then Rise
    Hub: three competing titles and the same word twice, under a third of a
    page of nothing. And inside, one section explained Supply and Demand in a
    terms table and again in a tabs table, in identical words, which no rule
    noticed because the two blocks are different kinds.
    """
    from verba.lint import lint
    from verba.project import Project
    from verba.render.pdf import PdfRenderer, _revision_label

    eq(_revision_label("draft 2026-08-23"), "Draft",
       "the cover prints the date twice, once labelled Revision: ")
    eq(_revision_label("v33"), "v33", "a real version was rewritten: ")

    root = fresh()
    proj = Project.load(root)
    html = PdfRenderer(proj)._cover()
    ok('class="band"' in html and 'class="low"' in html,
       "the cover is not built in two parts")
    ok("64pt" not in html, "the old masthead is still in the cover")
    # vendor and product are the same word in the fixture's neighbourhood: the
    # eyebrow must not simply repeat the title
    name = proj.config["product"]["name"]
    ok(html.count(name) <= 2, f"the product name is printed too often: {html.count(name)}")

    sec = next(iter(proj.sections.values()))
    body = sec.path.read_text(encoding="utf-8")
    sec.path.write_text(body + """

```terms
- term: Region
  definition: Where events for this account are delivered.
```

```fields
- field: Region
  description: Where events for this account are delivered.
```
""", encoding="utf-8")
    said = [f for f in lint(Project.load(root)) if f.rule == "CONTENT-04"]
    ok(said, "the same control explained twice in one section was not reported")
    ok("region" in said[0].message.lower(), f"the wrong label was named: {said[0].message}")

    # and a shared label with different wording is left alone: a field called
    # Status and an action called Status are two different things
    sec2 = list(Project.load(root).sections.values())[1]
    b2 = sec2.path.read_text(encoding="utf-8")
    sec2.path.write_text(b2 + """

```fields
- field: Status
  description: Whether the account is live.
```

```actions
- action: Status
  description: Opens the health panel for this account.
```
""", encoding="utf-8")
    named = [f for f in lint(Project.load(root))
             if f.rule == "CONTENT-04" and "status" in f.message.lower()]
    eq(named, [], "two different things sharing a name were called a duplicate: ")
    return "cover is a band and a sheet, and one control cannot be explained twice"


@check("the sign-in window is guarded, and required masking cannot do nothing")
def t_the_doors_the_audit_found():
    """Two holes in the one guarantee everything else rests on.

    `verba env signin` opened a visible browser at the customer's live product
    and handed a person the keyboard for five minutes with no guard attached at
    all: the single path in the engine where a click reached the product. And
    `mask_required` was checked only against --no-mask, so masking that was
    enabled with no rules in it, which is what `verba new` writes, protected
    nothing while every report said masking was on.
    """
    import inspect

    from verba import capture as cap_mod
    from verba import signin as si
    from verba.masking import Masker, MaskingRequired

    src = inspect.getsource(si.interactive_signin)
    ok("Guard()" in src and "guard.attach" in src,
       "the interactive sign-in still opens an unguarded browser at the product")
    ok("on_product=guard.reached_product" in src,
       "the permitted window is not closed when the product appears")
    ok('ctx.on("page"' in src,
       "a popup during sign-in would be its own Page and inherit no guard")

    # every context in the crawl, not just the first page
    csrc = inspect.getsource(cap_mod.Capture.run)
    eq(csrc.count('ctx.on("page"') + csrc.count('fresh.on("page"'), 3,
       "a context in the crawl can still produce an unguarded page: ")
    ok("reached_product" in inspect.getsource(cap_mod.Capture._session_still_works),
       "a saved session still loads the product with writes permitted")

    # masking that is on and empty is masking that is off
    m = Masker(enabled=True)
    ok(not m.active(), "an empty masker reported itself active")
    m.required = True
    try:
        m.apply(None)
        raise AssertionError("required masking with no rules did not refuse")
    except MaskingRequired:
        pass
    m.required = False
    eq(m.apply(None), [], "masking that is not required refused anyway: ")
    # a Service Worker's requests are not routed unless the context blocks them
    for mod, n in ((cap_mod, 3), (si, 2)):
        src = inspect.getsource(mod)
        ok(src.count('service_workers') >= n,
           f"a browser context in {mod.__name__} does not block service workers")

    # the POST allowlist is for POST
    from verba.readonly import Guard
    g = Guard(allow_post_matching=["*/graphql"])
    class R:
        def __init__(s, m): s.method, s.url = m, "https://x.test/graphql"
    class Route:
        def __init__(s): s.acted = None
        def continue_(s): s.acted = "continue"
        def abort(s): s.acted = "abort"
    g.lock()
    r = Route(); g._handle(r, R("POST"))
    eq(r.acted, "continue", "an allowlisted POST was blocked: ")
    r = Route(); g._handle(r, R("DELETE"))
    eq(r.acted, "abort", "a DELETE to an allowlisted URL was permitted: ")

    return ("the sign-in browser is guarded, popups and service workers are guarded, "
            "empty masking refuses, and the POST allowlist is only for POST")


@check("a mistake in a file the user was told to edit is a sentence, not a stack")
def t_failures_are_explained():
    """Fourteen distinct tracebacks were reproducible in a temp project.

    The engine is full of carefully worded refusals and none of them were
    reached by the faults people actually hit: no project yet, a colon inside
    an unquoted title, a registry.json left half written by a killed capture.
    Those arrived as Python internals, which tell a writer nothing except that
    the tool is broken.
    """
    import subprocess

    repo = Path(__file__).resolve().parents[1]

    def verba(args, **kw):
        return subprocess.run([sys.executable, "-m", "verba"] + args,
                              capture_output=True, text=True, cwd=str(repo), **kw)

    nothing = Path(tempfile.mkdtemp())
    r = verba(["--root", str(nothing), "status"])
    ok("Traceback" not in r.stderr, "no project at all is still a traceback")
    ok("no document" in r.stdout, f"the message does not say what is wrong: {r.stdout[:120]}")

    root = fresh()
    (root / "content" / "doc.yaml").write_text(
        (root / "content" / "doc.yaml").read_text() + "\nbroken: [unterminated\n")
    r = verba(["--root", str(root), "status"])
    ok("Traceback" not in r.stderr, "broken YAML is still a traceback")
    ok("YAML" in r.stdout and "line" in r.stdout,
       f"the message does not name the fault or the line: {r.stdout[:140]}")

    other = fresh()
    (other / "content" / "assets" / "registry.json").write_text('{"half":')
    r = verba(["--root", str(other), "status"])
    ok("Traceback" not in r.stderr, "a half-written JSON is still a traceback")
    ok("JSON" in r.stdout, f"the message does not name the fault: {r.stdout[:140]}")

    # and the escape hatch still exists for anyone debugging
    import os as _os
    env = dict(_os.environ, VERBA_TRACEBACK="1")
    r = verba(["--root", str(other), "status"], env=env)
    ok("Traceback" in r.stderr, "VERBA_TRACEBACK=1 no longer shows the traceback")

    # a brand colour pasted the way every design tool hands it over
    from verba.theme import Theme
    eq(Theme._hex("#3137DB"), "3137DB", "a hex with a hash was not accepted: ")
    eq(Theme._hex("#abc"), "AABBCC", "a three-digit hex was not expanded: ")
    eq(Theme._hex("notacolour"), "notacolour", "a non-colour was mangled: ")
    return "no project, broken YAML, half-written JSON and a hashed hex all explained"


@check("a rule cannot quietly stop reporting")
def t_rules_are_held_to_a_corpus():
    """The move that is always available when a list will not empty.

    Narrow the rule, and the findings go away, and it looks like progress. It
    is not caught by any test, because every test still passes: the rule just
    says less. So the corpus is checked in, and a change to what the rules say
    about it has to be accepted in the same commit a reviewer reads.
    """
    import subprocess
    r = subprocess.run([sys.executable, "tools/rule_baseline.py"],
                       capture_output=True, text=True,
                       cwd=str(Path(__file__).resolve().parents[1]))
    ok(r.returncode == 0,
       "the rules say something different about the corpus than the baseline "
       "records:\n" + (r.stdout or r.stderr))
    return (r.stdout or "").strip().splitlines()[-1][:80]


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
    tests = [t_scaffold_builds, t_scaffold_refuses, t_find_root,
             t_themes_contrast,
             t_theme_applied, t_system_description, t_page_setup,
             t_layout_atomic, t_settings_keep_prose, t_editions,
             t_neutral_edition,
             t_rewrites_keep_figures, t_no_tug_of_war, t_atomic_writes, t_approval_is_permission, t_auto_decline_is_not_binding,
             t_apply_and_describe_are_one_step,
             t_readonly, t_readonly_live, t_handoff_waits_for_the_person,
             t_only_actionable_work_is_reported,
             t_themes_ship_and_never_stop_a_build,
             t_cover_and_duplicate_content,
             t_the_doors_the_audit_found,
             t_failures_are_explained,
             t_rules_are_held_to_a_corpus,
             t_model_calls_are_bounded_and_counted,
             t_verified_costs_something,
             t_invariants_catch_what_counting_missed,
             t_model]
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
