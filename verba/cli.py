"""verba command line.

    verba status                 what exists, how fresh it is, what is flagged
    verba lint                   run the content rules
    verba build                  render DOCX and HTML preview
    verba capture                crawl the live system, write a capture run
    verba capture --section ID   re-crawl only the screens one section uses
verba capture --wait-for-signin   wait while you sign in, second factor and all
    verba sweep                  review the crawl and propose the gaps filled
    verba fonts                  which typefaces the outputs are set in
    verba forms                  every form, field and rule the crawl read
    verba fix                    settle everything the system can, and say what is left
    verba fix --full             photograph every screen first, then do that
    verba new                    start a new document, without a blank page
    verba themes                 how the document looks
    verba design                 what was decided about how this looks, and why
    verba layout                 the sheet, the margins, how text is set
    verba edition                which sections this edition carries
    verba survey                 what the document is missing, before you crawl
    verba tidy                   fix the writing across the document, as one decision
    verba accept                 read the unsigned sections and sign them, one at a time
verba note "..."             write down something you noticed
    verba auto                   run the whole loop and only stop where you are needed
    verba env list|use|verify|signin|password   connection profiles
    verba capture --heal         let the model repair selectors that break
    verba heal [--apply]         review, and apply, those repairs
    verba routes                 the remembered address of every screen
    verba masking                the real-to-placeholder mapping
    verba drift                  compare the newest capture to the document
    verba section new|show|set   manage one section
    verba release                cut a version, never overwriting an output
    verba changelog              print the derived changelog
    verba history [section]      every recorded change, and restore one
    verba console                open the management console in a browser
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from .capture import Capture, latest_capture, load_routes, load_screens, merged_inventory
from .decisions import Decisions
from .drift import analyse, to_markdown
from .environments import Environments
from .healing import Healer, apply_repairs
from .history import History
from .incidents import Incidents
from .knowledge import Knowledge
from .lint import ERROR, lint, summarise
from .masking import Masker
from .model import Block, Section
from .project import Project
from .readonly import lint_screens
from .render.docx import DocxRenderer
from .render.html import HtmlRenderer
from .sweep import Sweep
from .version import ReleaseStore, output_name


def find_root(start: Path | None = None) -> Path:
    """The project you are standing in.

    Walks up from the working directory looking for content/doc.yaml, the way
    git looks for .git, so any command works from anywhere inside a project.

    This used to be the package's own parent directory, which was right for
    exactly as long as the engine lived inside the single project it served.
    Installed from a package it pointed at site-packages, so `verba build` in
    your own project went looking for someone else's document.
    """
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "content" / "doc.yaml").exists():
            return d
    return here


ROOT = find_root()


def _project(args) -> Project:
    return Project.load(args.root, profile=args.profile)


def _drift_report(project, root: Path):
    run = latest_capture(Path(root) / "capture")
    if not run:
        return None, None
    try:
        site, screens = load_screens(Path(root) / "content" / "screens.yaml")
        base = (site.get("base_url") or "").rstrip("/")
        aim = {sc.id: (g if g.startswith("http") else base + g)
               for sc in screens
               for g in [next((st["goto"] for st in sc.steps if "goto" in st), None)]
               if g}
    except Exception:
        aim = {}
    merged, newest = merged_inventory(Path(root) / "capture")
    merged["_dir"] = str(newest)
    return analyse(project, merged, screens_cfg=aim), newest


# ------------------------------------------------------------------ commands


def cmd_status(args):
    p = _project(args)
    rep, run = _drift_report(p, args.root)
    drift_by = rep.by_section() if rep else {}
    store = ReleaseStore(args.root)
    last = store.latest(p.profile.name)

    print(f"{p.config['product']['name']} {p.title()}   profile={p.profile.name}")
    print(f"sections {len(p.nodes)}   assets {len(p.assets.all_names())}   "
          f"latest release {last['version'] if last else 'none'}")
    print(f"capture  {run.name if run else 'none'}\n")
    print(f"{'NUM':<8} {'STATUS':<9} {'VERIFIED':<12} {'DRIFT':<6} SECTION")
    for node in p.nodes:
        sec = node.section
        if sec is None:
            continue
        d = len(drift_by.get(sec.id, []))
        print(f"{node.number:<8} {sec.status:<9} {sec.last_verified or '-':<12} "
              f"{(str(d) if d else '-'):<6} {'  ' * (node.level - 1)}{sec.title}")

    findings = lint(p)
    s = summarise(findings)
    print(f"\nlint: {s['error']} error  {s['warning']} warning  {s['info']} info")
    if rep:
        print(f"drift: {json.dumps(rep.summary())}")
    return 0


def cmd_lint(args):
    p = _project(args)
    findings = lint(p)
    for f in findings:
        if args.level == "all" or f.level == args.level:
            print(f)
    s = summarise(findings)
    print(f"\n{s['error']} error  {s['warning']} warning  {s['info']} info")
    return 1 if s["error"] and args.strict else 0


def cmd_build(args):
    p = _project(args)
    findings = lint(p)
    s = summarise(findings)
    if s["error"] and not args.force:
        print(f"build refused: {s['error']} error-level finding(s). "
              f"Run 'verba lint' to see them, or pass --force.")
        for f in findings:
            if f.level == ERROR:
                print(f"  {f}")
        return 1

    label = args.label or f"draft {date.today().isoformat()}"
    p.config["_release_label"] = label
    store = ReleaseStore(args.root)
    history = store.history(p.profile.name) if args.history else None

    out = Path(args.root) / "dist" / (args.out or
                                      f"preview_{p.profile.name}.docx")
    DocxRenderer(p).render(out, history=history)
    print(f"docx     {out}  ({out.stat().st_size // 1024} KB)")

    if args.pdf:
        from .render.pdf import PdfRenderer
        pdf = out.with_suffix(".pdf")
        PdfRenderer(p, history).render(pdf, work_dir=out.parent / "_print")
        print(f"pdf      {pdf}  ({pdf.stat().st_size // 1024} KB)")

    rep, _ = _drift_report(p, args.root)
    html = HtmlRenderer(p, rep).render(
        Path(args.root) / "dist" / "preview" / p.profile.name / "index.html")
    print(f"preview  {html}")
    print(f"lint     {s['error']} error  {s['warning']} warning  {s['info']} info")
    return 0


def cmd_capture(args):
    root = Path(args.root)
    content = root / "content"
    site, screens = load_screens(content / "screens.yaml")
    envs = Environments.load(root)
    env = envs.current()
    if env is not None:
        ok, why = env.ready(root)
        if not ok:
            print(f"{env.label or env.id}: {why}")
            print(f"fix it with: python3 -m verba env "
                  f"{'signin' if env.auth == 'sso' else 'password'} {env.id}")
            print("or, if this product asks for a code: python3 -m verba capture "
                  "--wait-for-signin")
            return 1
        site = {**site, **envs.as_site(env, fallback_login=site.get("login"))}
        if not env.export_credentials():
            print(f"{env.label or env.id}: the sign-in could not be read from the "
                  f"keychain. Run: python3 -m verba env password {env.id}")
            return 1
        print(f"connection: {env.label or env.id} ({env.auth}) {env.base_url}")

    only = args.screens.split(",") if args.screens else None
    if args.section:
        p = _project(args)
        sec = p.sections.get(args.section)
        if not sec:
            print(f"no section {args.section!r}")
            return 1
        only = sec.screens or [s.id for s in screens if args.section in s.sections]
        if not only:
            print(f"section {args.section!r} is not bound to any screen. Add one under "
                  f"`screens:` in its front matter and define it in content/screens.yaml.")
            return 1
        print(f"section {args.section}: {', '.join(only)}")

    for warning in lint_screens([s for s in screens if not only or s.id in only]):
        print(f"  registry warning: {warning}")

    masker = Masker.load(content / "masking.yaml", content / "masking-map.json")
    masker.required = bool(env is not None and env.mask_required)
    if args.no_mask:
        if masker.required:
            print(f"{env.label or env.id} holds real data, so it cannot be captured "
                  f"unmasked.")
            return 1
        masker.enabled = False
    # Masking that is on and empty is masking that is off. This used to be
    # checked only against --no-mask, so a connection marked as holding real
    # data was crawled with no rules at all and reported masking as on.
    if masker.required and not masker.active():
        print(f"{env.label or env.id} is marked as holding real data, and "
              f"content/masking.yaml has no columns, patterns or literals in it.")
        print("Masking would do nothing, so this crawl is refused. Add a rule, or "
              "take mask_required off the connection if the data really is safe.")
        return 1
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    out = root / "capture" / stamp
    healer = Healer(enabled=bool(args.heal))
    handoff = True if getattr(args, "wait_for_signin", False) else None
    if handoff:
        # Asked for by hand, so it applies whatever the connection says. This is
        # the flag for the morning a product starts asking for a code.
        site = {**site, "handoff": True}
    cap = Capture(site, screens, out, headless=not args.headed, masker=masker,
                  routes_path=content / "routes.yaml", healer=healer,
                  handoff=handoff)
    if cap.handoff:
        print("this crawl will wait for you to sign in if it needs to")
    print(f"capturing {len(only or screens)} screen(s) from {site.get('base_url')}")
    print(f"masking {'on' if masker.active() else 'off'}, "
          f"writes blocked, output capture/{stamp}")
    inc = Incidents.load(root)
    try:
        manifest = cap.run(only=only, log=print, prefer_url=not args.replay_steps)
    except Exception as e:
        inc.record(f"capture ({', '.join(only or ['all'])})", e,
                   context={"base_url": site.get("base_url"),
                            "connection": env.id if env else None,
                            "masking": masker.active()})
        print(f"\ncapture failed: {e}")
        print("recorded. see: python3 -m verba incidents")
        return 1
    if getattr(args, "sweep", True):
        print()
        touched = {sid for scr in screens if (not only or scr.id in only)
                   for sid in scr.sections}
        sw = Sweep(p if (p := _project(args)) else None, root,
                   Decisions.load(root), Knowledge.load(root))
        sw.run(sorted(touched) or None, log=print)

        # and the rule findings the new labels brought with them
        from .lint import lint as _lint
        from .tidy import Tidy
        p2 = _project(args)
        fixable = sorted({(f.section or "").split(" ", 1)[-1]
                          for f in _lint(p2) if f.level == "error"
                          and f.rule in ("CONTENT-03", "STYLE-06")})
        if fixable:
            print()
            print("checking what the crawl did to the rules ...")
            Tidy(p2, root).run(fixable, log=print)

    for e in manifest.get("errors", []):
        inc.record(f"capture {e.get('screen','?')}", None,
                   message=str(e.get("error", ""))[:400],
                   context={k: v for k, v in e.items() if k != "error"})
    ro = manifest["readonly"]
    print(f"captured {len(manifest['screens'])} screen(s), "
          f"{len(manifest['errors'])} error(s)")
    print(f"read-only: {ro['blocked_writes']} write attempt(s) blocked, "
          f"{ro['sign_in_requests']} sign-in request(s) allowed")
    mk = manifest["masking"]
    print(f"masking: {mk['known_values']} value(s) masked, "
          f"{mk['new_values']} newly learned")
    heal = manifest.get("healing", {})
    if heal.get("attempted"):
        print(f"healing: {heal['verified']} of {heal['attempted']} broken selector(s) "
              f"repaired and verified in the page")
        for r in heal.get("proposals", []):
            print(f"  {r['screen']}.{r['key']}")
            print(f"    {r['old']}  ->  {r['new']}   ({r['matches']} matches, "
                  f"{r['confidence']:.0%})")
        if heal.get("proposals"):
            print("  apply them with: python3 -m verba heal --apply")
        healer.save(root / "review" / "repairs.json")
    for e in manifest["errors"]:
        print(f"  ! {e.get('screen','?')}: {e.get('error','')[:120]}")
    return 0


def cmd_env(args):
    envs = Environments.load(args.root)
    if args.action == "list":
        if not envs.items:
            print("no connection profiles yet, see content/environments.yaml")
            return 0
        print(f"{'':3} {'ID':14} {'AUTH':6} {'ADDRESS':44} STATUS")
        for e in envs.summary():
            print(f"{'*' if e['active'] else ' ':3} {e['id']:14} {e['auth']:6} "
                  f"{e['base_url']:44} {e['status']}")
        return 0

    if args.action == "use":
        try:
            envs.activate(args.id)
        except KeyError:
            print(f"no profile {args.id!r}")
            return 1
        print(f"now using {args.id}")
        return 0

    env = envs.items.get(args.id)
    if env is None:
        print(f"no profile {args.id!r}")
        return 1

    if args.action == "verify":
        from .signin import verify
        r = verify(env, Path(args.root), log=print)
        return 0 if r.get("ok") else 1

    if args.action == "signin":
        if env.auth not in ("sso", "handoff"):
            print("interactive sign-in is for single sign-on and hand-over "
                  "profiles. A form profile just needs its password saved.")
            return 1
        if env.auth == "handoff":
            # Doing it now rather than in the middle of a crawl. The crawl would
            # ask on its own, so this is a convenience, not a prerequisite.
            print("signing in now, so the next crawl does not have to ask.")
        from .signin import interactive_signin
        interactive_signin(env, Path(args.root), log=print)
        return 0

    if args.action == "password":
        import getpass
        user = args.user or env.user or input("username: ").strip()
        pw = getpass.getpass(f"password for {user}: ")
        env.set_password(user, pw)
        envs.save()
        print(f"saved to the login keychain as {env.keychain_service}")
        return 0
    return 1


def cmd_heal(args):
    """Show, or apply, the selector repairs from the last crawl."""
    path = Path(args.root) / "review" / "repairs.json"
    if not path.exists():
        print("no repairs recorded. run: python3 -m verba capture --heal")
        return 0
    repairs = json.loads(path.read_text())
    good = [r for r in repairs if r.get("verified")]
    if not good:
        print(f"{len(repairs)} repair attempt(s), none verified in the page")
        for r in repairs:
            print(f"  {r['screen']}.{r['key']}: {r.get('error','')[:90]}")
        return 0
    for r in good:
        print(f"{r['screen']}.{r['key']}  ({r['matches']} matches, "
              f"{r['confidence']:.0%} confidence)")
        print(f"  was : {r['old']}")
        print(f"  now : {r['new']}")
        print(f"  why : {r['reasoning']}")
    if args.apply:
        applied = apply_repairs(Path(args.root) / "content" / "screens.yaml", good)
        for a in applied:
            print(f"applied: {a}")
        print(f"{len(applied)} repair(s) written to content/screens.yaml")
    else:
        print(f"\n{len(good)} verified repair(s). Apply with --apply.")
    return 0


def cmd_routes(args):
    routes = load_routes(Path(args.root) / "content" / "routes.yaml")
    if not routes:
        print("no routes remembered yet. run a capture first.")
        return 0
    print(f"{'SCREEN':34} {'LAST SEEN':20} {'VIA':7} URL")
    for sid, r in sorted(routes.items()):
        print(f"{sid:34} {r.get('last_seen','-'):20} {r.get('reached_by','-'):7} "
              f"{r.get('url','-')}")
    return 0


def cmd_masking(args):
    content = Path(args.root) / "content"
    m = Masker.load(content / "masking.yaml", content / "masking-map.json")
    print(f"masking {'enabled' if m.active() else 'disabled'}: "
          f"{len(m.columns)} column rule(s), {len(m.patterns)} pattern(s), "
          f"{len(m.literals)} literal(s)")
    rows = m.table()
    if not rows:
        print("no values learned yet. run a capture.")
        return 0
    print(f"\n{'RULE':22} {'REAL VALUE':34} PLACEHOLDER")
    for r in rows:
        print(f"{r['rule']:22} {r['from'][:33]:34} {r['to']}")
    return 0


def cmd_note(args):
    """Write down something you noticed. The next run deals with it."""
    from .notes import FIXED, OPEN, STUCK, Notes
    n = Notes.load(args.root)

    if args.text:
        note = n.add(" ".join(args.text), section=args.section or "",
                     figure=args.figure or "")
        print(f"noted: {note.text}")
        if note.section:
            print(f"  against {note.section}")
        print("\nit will be dealt with on the next run:")
        print("  python3 -m verba auto")
        return 0

    if args.reopen:
        print("reopened" if n.reopen(args.reopen) else "no such note")
        return 0
    if args.drop:
        print("removed" if n.drop(args.drop) else "no such note")
        return 0

    if not n.items:
        print("nothing noted yet. write something down with:")
        print('  python3 -m verba note "figure 4.3 shows a real customer name"')
        return 0

    s = n.summary()
    print(f"{s['open']} open, {s['fixed']} done, {s['stuck']} handed back\n")
    for note in n.items:
        mark = {OPEN: "open ", FIXED: "done ", STUCK: "stuck"}.get(note.status, "?")
        print(f"  [{mark}] {note.id}")
        print(f"          {note.text}")
        if note.section:
            print(f"          section: {note.section}")
        if note.outcome:
            print(f"          {note.outcome}")
    return 0


def cmd_auto(args):
    """Run the whole loop, and stop only where a person is needed."""
    from .auto import Auto

    print("running the whole pipeline. nothing is written to the platform, and")
    print("every change is recorded, so any of it can be put back.\n")
    a = Auto(Path(args.root))
    out = a.run(rounds=args.rounds, crawl=not args.no_crawl, log=print)

    if out["for_you"]:
        print()
        print(f"{len(out['for_you'])} thing(s) still yours to decide:\n")
        seen = set()
        for item in out["for_you"]:
            key = item["what"][:80]
            if key in seen:
                continue
            seen.add(key)
            print(f"  {item['what'][:96]}")
            print(f"      why: {item['why'][:88]}")
            print(f"      do : {item['do'][:88]}")
        print()

    if out["errors_after"] == 0:
        print("the document breaks no rules. build it with:")
        print("  python3 -m verba build --pdf")
    return 0


def cmd_tidy(args):
    """Fix the writing across the whole document, as one decision."""
    from .history import History
    from .knowledge import Knowledge
    from .tidy import Tidy

    p = _project(args)
    root = Path(args.root)

    if args.apply:
        out = Tidy.apply(root, p, History(root), Knowledge.load(root), log=print)
        if out["failed"]:
            for f in out["failed"]:
                print(f"  not written: {f}")
        print(f"\n{len(out['written'])} section(s) written. "
              f"Undo any of them from history.")
        return 0

    t = Tidy(p, root)
    edits = t.run(args.section.split(",") if args.section else None, log=print)
    if not edits:
        if t.skipped:
            for line in t.skipped:
                print(f"  {line}")
        return 0

    print()
    for e in edits:
        print(f"{e.number} {e.title}")
        for note in e.notes:
            print(f"    {note}")
    print("\nreview the diffs in the console, or write all of them with:")
    print("  python3 -m verba tidy --apply")
    return 0


def cmd_survey(args):
    """What the document is missing, before anyone opens a browser."""
    from .survey import Survey

    p = _project(args)
    sv = Survey.run(p, args.root)
    sv.save()
    s = sv.summary()

    if args.json:
        import json as _json
        print(_json.dumps(sv.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if not sv.gaps:
        print("nothing outstanding: every section is written, every picture is "
              "of something, and every screen has a section")
        return 0

    print(f"{s['gaps']} gap(s) in the document as it stands\n")
    titles = {
        "unwritten":    "descriptions never written",
        "image":        "pictures missing or not of a screen",
        "undocumented": "parts of the platform nothing describes",
        "stale":        "sections nobody has checked lately",
        "evidence":     "already answerable from the last crawl",
        "redirects":    "screens that are not screens",
    }
    for kind, items in sv.by_kind().items():
        print(f"{titles.get(kind, kind).upper()}  ({len(items)})")
        for g in items[:12]:
            mark = "crawl" if g.fixable_by_crawl else "     "
            print(f"  [{mark}] {g.where[:38]:40} {g.what[:78]}")
        if len(items) > 12:
            print(f"          ... and {len(items) - 12} more")
        print()

    worth = sv.screens_worth_crawling()
    if s["answerable_now"]:
        print(f"{s['answerable_now']} section(s) can be finished from evidence "
              f"already captured:")
        print("  python3 -m verba sweep\n")
    if worth:
        print(f"{len(worth)} screen(s) would need a fresh look:")
        print("  " + ", ".join(worth))
        print("\n  python3 -m verba survey --crawl")
    else:
        print("no crawl would tell us anything the last one did not.")

    if args.crawl:
        if not worth:
            print("\nnothing to crawl.")
            return 0
        print(f"\ncrawling {len(worth)} screen(s) ...\n")
        args.screens = ",".join(worth)
        args.section = None
        for flag, default in (("headed", False), ("mask", True),
                              ("replay_steps", False), ("heal", True),
                              ("sweep", True), ("no_mask", False)):
            if not hasattr(args, flag):
                setattr(args, flag, default)
        return cmd_capture(args)
    return 0


def cmd_design(args):
    """What was decided about how this looks, and what holds us to it."""
    from .design import Design
    d = Design.load(args.root)

    if args.add:
        if not args.because:
            print("a decision needs its reason: pass --because")
            return 1
        rec = d.add(args.area or "general", args.add, args.because,
                    rule=args.rule or "", enforced_by=args.enforced_by or "")
        print(f"recorded {rec.id} under {rec.area}")
        if rec.held_by == "nothing yet":
            print("nothing enforces it yet. give it --rule or --enforced-by, "
                  "or it is a note rather than a decision.")
        return 0

    if args.check:
        p = _project(args)
        found = d.check(p)
        if not found:
            print(f"the project holds against all {len(d.decisions)} decision(s)")
            return 0
        print(f"{len(found)} finding(s):\n")
        for f in found:
            print(f"  [{f['level'].upper():7}] {f['rule']}  {f['message']}")
            if f.get("detail"):
                print(f"            {f['detail']}")
        return 1 if any(f["level"] == "error" for f in found) else 0

    if args.find:
        hits = d.find(args.find)
        print(f"{len(hits)} decision(s) matching {args.find!r}\n")
        for x in hits:
            print(f"  {x.id}  ({x.area})")
            print(f"    {x.decided.strip()}")
            if x.because:
                print(f"    because: {x.because.strip()}")
            print(f"    held by: {x.held_by}\n")
        return 0

    s = d.summary()
    print(f"{s['decisions']} decision(s) across {len(s['areas'])} area(s), "
          f"{s['traps']} recorded trap(s)")
    if s["unenforced"]:
        print(f"not held by anything: {', '.join(s['unenforced'])}")
    print()
    for area, items in sorted(d.by_area().items()):
        print(f"{area.upper()}")
        for x in items:
            print(f"  {x.decided.strip()}")
            print(f"      held by {x.held_by}")
        print()
    print("why any of them:  python3 -m verba design --find <word>")
    print("hold the project: python3 -m verba design --check")
    return 0


def _ask(prompt: str, default: str = "", options: dict | None = None) -> str:
    """One question, with a default you can take by pressing Return."""
    if options:
        print(f"\n{prompt}")
        keys = list(options)
        for i, k in enumerate(keys, 1):
            mark = " (default)" if k == default else ""
            print(f"  {i}. {k}{mark} : {options[k]}")
        raw = input(f"  choose 1-{len(keys)} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        return raw if raw in options else default
    raw = input(f"{prompt} [{default}]: ").strip() if default else input(f"{prompt}: ").strip()
    return raw or default


def cmd_new(args):
    """Start a new document, without a blank page."""
    from .scaffold import AUTH_KINDS, Answers, Scaffold
    from .theme import Theme
    from .theme import available as themes_available

    dest = Path(args.dir or ".").resolve()
    if (dest / "content" / "doc.yaml").exists():
        print(f"there is already a document in {dest}")
        print("start a new one somewhere else, or work on this one: verba status")
        return 1

    given = {k: getattr(args, k, None) for k in
             ("product", "vendor", "about", "base_url", "auth", "user",
              "theme", "audience")}
    given = {k: v for k, v in given.items() if v}

    if not args.yes and not given.get("product"):
        print("\nA few questions, then you will have a document that builds.")
        print("Press Return to take the default on any of them.\n")
        given["product"] = _ask("What is the product called?", "My Product")
        given["vendor"] = _ask("Who makes it?", given["product"])
        given["about"] = _ask("What does it do, in one sentence?", "")
        given["base_url"] = _ask("Where does it live?", "https://example.com")
        given["auth"] = _ask("How do you sign in?", "form", AUTH_KINDS)
        if given["auth"] in ("form", "handoff"):
            given["user"] = _ask("Which account will the crawl use?", "")
        looks = {n: Theme.named(n).about.strip().split(".")[0] + "."
                 for n in themes_available()}
        given["theme"] = _ask("Which look?", "slate", looks)

    try:
        answers = Answers(**given)
    except (ValueError, TypeError) as e:
        print(f"refused: {e}")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    written = Scaffold(root=dest, a=answers).build()

    print(f"\nwrote {len(written)} files into {dest}")
    print(f"  {answers.product}, set in {Theme.named(answers.theme).label}, "
          f"signing in by {answers.auth}")
    print("\nIt already builds. Try it:\n")
    where = "" if dest == Path.cwd() else f"cd {dest} && "
    print(f"  {where}verba build --pdf\n")
    print("Then, in the order you will actually want them:")
    print("  verba console              the management interface, and the easiest way in")
    print("  content/system.md          say what this product is: the writer reads it")
    print("  content/screens.yaml       add the screens worth documenting")
    print("  verba capture              photograph them, and read the labels off the page")
    return 0


def cmd_fix(args):
    """Settle everything the system can settle, and say what is left."""
    from . import fixer
    from .history import History
    from .knowledge import Knowledge

    root = Path(args.root)

    def _crawl(*more):
        """Run this command's own capture, streaming it where the person is."""
        import subprocess
        import sys
        r = subprocess.run(
            [sys.executable, "-m", "verba", "--root", str(root), "capture", *more],
            capture_output=True, text=True)
        for line in (r.stdout or "").splitlines():
            print("    " + line)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "capture failed").strip()[:200])

    out = fixer.run(root, lambda: _project(args), History(root),
                    Knowledge.load(root), log=print,
                    rounds=int(args.rounds or 2),
                    allow_crawl=not args.no_crawl,
                    full=args.full and not args.no_crawl,
                    capture=lambda sid, log: _crawl("--section", sid),
                    capture_all=lambda log: _crawl())
    return 1 if out["after"]["error"] else 0


def cmd_themes(args):
    """How the document looks."""
    from .theme import Theme, available, table

    if args.use:
        if args.use not in available(args.root):
            print(f"no such theme: {args.use}. "
                  f"try one of: {', '.join(available(args.root))}")
            return 1
        path = Path(args.root) / "content" / "theme.yaml"
        if path.exists():
            text = path.read_text(encoding="utf-8")
            import re as _re
            text = _re.sub(r"^use:.*$", f"use: {args.use}", text, count=1, flags=_re.M)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = f"use: {args.use}\ntokens: {{}}\n"
        path.write_text(text, encoding="utf-8")
        print(f"set in {Theme.named(args.use, args.root).label}")
        print("rebuild to see it: verba build --pdf")
        return 0

    if args.check:
        return _theme_contrast(Theme.load(args.root))

    if args.show:
        t = Theme.load(args.root)
        print(f"{t.label}  ({t.name})\n")
        for token in ("navy_hero", "navy_deep", "brand_blue", "lavender",
                      "periwinkle", "grey_mid", "grey_dark"):
            print(f"  {token:12} #{getattr(t, token)}")
        return 0

    current = Theme.load(args.root)
    for row in table():
        mark = " *" if row["name"] == current.name else "  "
        print(f"{mark}{row['label']:8} {' '.join('#' + s for s in row['swatch'][:3])}")
        print(f"   {row['about'].strip()}\n")
    print(f"in use: {current.label}")
    print("change it: verba themes --use ink")
    return 0


def _theme_contrast(t) -> int:
    """Measure the theme rather than trusting it.

    A built-in theme is checked before it ships. An override in a project's own
    theme.yaml is the one place a document can be made unreadable, so this
    measures whatever is actually set.
    """
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def ratio(a, b):
        la, lb = lum(a), lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    checks = [
        ("body text on the page", t.navy_deep, "FFFFFF", 7.0),
        ("accent on the page", t.brand_blue, "FFFFFF", 4.5),
        ("accent on its own tint", t.brand_blue, t.lavender, 4.5),
        ("body text on a tint", t.navy_deep, t.lavender, 7.0),
        ("cover text on the page", t.navy_hero, "FFFFFF", 7.0),
    ]
    bad = 0
    print(f"{t.label}\n")
    for what, fg, bg, want in checks:
        got = ratio(fg, bg)
        ok = got >= want
        bad += 0 if ok else 1
        print(f"  {'ok ' if ok else 'FAIL'}  {what:24} {got:5.2f}:1  (wants {want})")
    print()
    if bad:
        print(f"{bad} failing. an override in content/theme.yaml is usually the cause.")
        return 1
    print("every measured pair passes")
    return 0


def cmd_layout(args):
    """How the document is laid out: the sheet, the margins, how text is set."""
    from . import layout

    changes = {k: getattr(args, k, None) for k in
               ("paper", "side", "edge", "header_band", "footer_band", "gap",
                "align", "hyphens", "screenshot_width_cm", "toc_depth")}
    changes = {k: v for k, v in changes.items() if v is not None}
    if changes:
        try:
            touched = layout.apply(args.root, **changes)
        except ValueError as e:
            print(f"refused: {e}")
            return 1
        print("nothing to change" if not touched
              else f"changed: {', '.join(touched)}")
        print("rebuild to see it: python3 -m verba build --pdf")
        return 0

    d = layout.read(args.root)
    print(f"sheet          {d['paper']}  ({d['sheet_mm']} mm)")
    print(f"side margins   {d['side']:g} mm")
    print(f"top / bottom   {d['margin_top']:g} / {d['margin_bottom']:g} mm  "
          f"(edge {d['edge']:g} + band {d['header_band']:g} + gap {d['gap']:g})")
    print(f"column         {d['text_width_cm']:g} cm of text")
    print(f"body text      {d['align']}, hyphens {d['hyphens']}")
    print(f"figures        {d['screenshot_width_cm']:g} cm wide")
    print(f"contents       down to level {d['toc_depth']}")
    if d["figure_overflows"]:
        print(f"\n  a {d['screenshot_width_cm']:g} cm figure runs off a "
              f"{d['text_width_cm']:g} cm column")
    print(f"\npaper sizes: {', '.join(x['name'] for x in d['papers'])}")
    print("change one:  python3 -m verba layout --paper Letter --side 20")
    return 0


def cmd_edition(args):
    """Which sections this edition carries."""
    from . import editions

    if args.action == "reset":
        print(editions.reset(args.root, args.profile or _default_profile(args.root)))
        return 0

    name = args.profile or _default_profile(args.root)
    if args.action in ("add", "drop"):
        if not args.id:
            print(f"which section? python3 -m verba --profile {name} "
                  f"edition {args.action} <section-id>")
            return 1
        try:
            print(editions.carry(args.root, name, args.id, args.action == "add"))
        except ValueError as e:
            print(f"refused: {e}")
            return 1
        return 0

    p = _project(args)
    rows = editions.read(p)
    carried = [r for r in rows if r["carried"]]
    print(f"{p.profile.name}: {len(carried)} of {len(rows)} sections\n")
    for r in rows:
        mark = "  " if r["carried"] else "- "
        num = (r["number"] or "").ljust(8)
        print(f"{mark}{num}{'  ' * r['depth']}{r['title']}")
        if r["why"]:
            print(f"          {'  ' * r['depth']}{r['why']}")
    print(f"\ndrop one:  python3 -m verba --profile {p.profile.name} "
          f"edition drop <section-id>")
    print(f"put back:  python3 -m verba --profile {p.profile.name} "
          f"edition add <section-id>")
    return 0


def _default_profile(root) -> str:
    import yaml
    cfg = yaml.safe_load((Path(root) / "content" / "doc.yaml").read_text(
        encoding="utf-8")) or {}
    return cfg.get("defaults", {}).get("profile", "generic")


def cmd_forms(args):
    """Every form, field and rule the last crawl read, and what the document says."""
    from . import forms as F
    from .capture import merged_inventory

    root = Path(args.root)
    merged, _ = merged_inventory(root / "capture")
    screens = merged.get("screens", {})
    if not screens:
        print("no capture yet. run: python3 -m verba capture")
        return 1

    p = _project(args)
    wanted = None
    if args.section:
        node = next((n for n in p.nodes if n.id == args.section), None)
        if node is None:
            print(f"no section {args.section}")
            return 1
        wanted = set(node.section.screens)

    seen = shown = 0
    for sid, rec in sorted(screens.items()):
        if wanted and sid not in wanted:
            continue
        data = rec.get("forms")
        if not data:
            continue
        seen += 1
        counts = rec.get("form_counts", {})
        print(f"\n{sid}  {counts.get('fields', 0)} field(s), "
              f"{counts.get('required', 0)} required")
        for form in data.get("forms", []):
            title = form.get("name") or "(controls not inside a form)"
            print(f"  {title}")
            for fl in form.get("fields", []):
                r = fl.get("rules", {})
                flags = [k.replace('_', ' ') for k in
                         ("required", "read_only", "disabled") if r.get(k)]
                extra = []
                if r.get("max_length"):
                    extra.append(f"max {r['max_length']}")
                if fl.get("options"):
                    extra.append(f"choices: {', '.join(fl['options'][:5])}")
                shown += 1
                print(f"    {(fl.get('name') or '(unnamed)')[:34]:36} "
                      f"{fl.get('kind',''):11} {' '.join(flags):22} {'; '.join(extra)}")
                if args.all:
                    for note in fl.get("findings", []):
                        print(f"      ! {note}")

    if not seen:
        print("the last crawl read no forms. every screen it visited was a list or a view.")
        return 0

    print(f"\n{shown} field(s) across {seen} screen(s)")

    # what the document says, against what the screen shows
    issues = []
    for node in p.nodes:
        if node.section is None:
            continue
        for sid in node.section.screens:
            rec = screens.get(sid) or {}
            if rec.get("forms"):
                issues += F.compare(node.section, rec["forms"])
    if issues:
        print(f"\n{len(issues)} constraint difference(s):")
        for i in issues:
            print(f"  {i['section']}: {i['line']}")
    else:
        print("\nno constraint differences: the document matches what the screens declare")

    if args.all:
        a11y = [a for rec in screens.values() for a in (rec.get("a11y") or [])]
        if a11y:
            print(f"\n{len(a11y)} accessibility observation(s) about the platform:")
            for a in a11y[:30]:
                print(f"  {a['screen']}: {a['field']} ({a['kind']}) {a['issue']}")
    return 0


def cmd_fonts(args):
    from .typography import Typography
    t = Typography.load(args.root)

    if args.document or args.console:
        for which, key in (("document", args.document), ("console", args.console)):
            if key:
                t.choose(which, key)
                print(f"{which} is now set in {t.faces[key].label}")
        print("\nrebuild to see it: python3 -m verba build --pdf")
        return 0

    if args.verify:
        print("asking Chromium what it can resolve, which is what prints the PDF\n")
        rows = t.verify(log=print)
        missing = [r for r in rows if not r["ok"]]
        if missing:
            print(f"\n{len(missing)} face(s) would fall back to something else:")
            for r in missing:
                print(f"  {r['label']}: {r['primary']} is not on this machine")
        return 0

    print(f"document: {t.face('document').label}     console: {t.face('console').label}\n")
    print(f"{'':3}{'KEY':14} {'TYPEFACE':18} {'FIRST FAMILY':24} WHERE")
    for r in t.table():
        mark = ("D" if r["is_document"] else " ") + ("C" if r["is_console"] else " ")
        state = "webfont" if r["webfont"] else ("installed" if r["available"] else "MISSING")
        print(f"{mark:3}{r['key']:14} {r['label']:18} {r['primary']:24} {state}")
    print("\n  D = the document is set in it, C = the console is")
    print("\nchange it with:  python3 -m verba fonts --document google-sans")
    print("prove it with:   python3 -m verba fonts --verify")
    return 0


def cmd_drift(args):
    p = _project(args)
    run = Path(args.capture) if args.capture else latest_capture(Path(args.root) / "capture")
    if not run:
        print("no capture found. run 'verba capture' first.")
        return 1
    rep, _ = _drift_report(p, args.root)
    md = to_markdown(rep, p)
    out = Path(args.root) / "review" / "DRIFT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md if args.print_report else f"wrote {out}\n{json.dumps(rep.summary(), indent=2)}")
    return 0


def cmd_section(args):
    p = _project(args)
    if args.action == "show":
        sec = p.sections.get(args.id)
        if not sec:
            print(f"no section {args.id!r}")
            return 1
        print(sec.path)
        print(sec.to_markdown())
        return 0

    if args.action == "new":
        sid = args.id
        chapter = sid.split(".")[0]
        title = args.title or sid.split(".")[-1].replace("-", " ").title()
        d = Path(args.root) / "content" / "sections" / chapter
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("*.md"))) + 1
        sec = Section(id=sid, title=title, meta={
            "id": sid, "title": title, "status": "draft",
            "last_verified": "", "screens": [args.screen] if args.screen else [],
            "sources": [],
        }, blocks=[Block("paragraph", "TODO: describe this screen.")])
        path = sec.save(d / f"{n:03d}-{sid.split('.')[-1]}.md")
        print(f"created {path}")
        print("add it to content/doc.yaml under the right parent so it ships.")
        return 0

    if args.action == "set":
        sec = p.sections.get(args.id)
        if not sec:
            print(f"no section {args.id!r}")
            return 1
        for pair in args.values:
            k, _, v = pair.partition("=")
            sec.meta[k] = v
        sec.save(sec.path)
        print(f"updated {sec.path}: {', '.join(args.values)}")
        return 0

    if args.action == "verify":
        from .attest import attest, latest_capture, whoami
        who = (getattr(args, "who", "") or "").strip() or whoami()
        if not who:
            print("who is accepting this? Nothing here can answer that for you.")
            print("  python3 -m verba section verify <id> --who \"your name\"")
            print("  or set VERBA_WHO, or git config user.name")
            return 1
        stamp = args.date or date.today().isoformat()
        against = latest_capture(args.root)
        if not against:
            print("nothing has been captured yet, so there is nothing to have "
                  "checked this against. Run a capture first.")
            return 1
        ids = args.id.split(",") if args.id else [n.id for n in p.nodes]
        n = 0
        for sid in ids:
            sec = p.sections.get(sid)
            if not sec:
                continue
            sec.meta = attest(sec.meta, who, against, stamp)
            sec.save(sec.path)
            n += 1
        print(f"{who} accepted {n} section(s) on {stamp}, against capture {against}")
        print("Any change with a machine behind it drops the badge again.")
        return 0
    return 1


def cmd_accept(args):
    """Walk the sections nobody has signed, one at a time."""
    from .accept import outstanding, sign
    from .attest import latest_capture, whoami
    from .history import History

    root = Path(args.root)
    p = _project(args)
    who = (args.who or "").strip() or whoami()
    if not who:
        print("Who is accepting these? Nothing here can answer that for you.")
        print('  python3 -m verba accept --who "your name"')
        return 1
    against = latest_capture(root)
    if not against:
        print("Nothing has been captured yet, so there is nothing to check "
              "these against. Run a capture first.")
        return 1

    cards = outstanding(p, root)
    if args.id:
        wanted = set(args.id.split(","))
        cards = [c for c in cards if c.id in wanted]
    if not cards:
        print("Every section carries a signature. Nothing to accept.")
        return 0

    print(f"{len(cards)} section(s) nobody has signed.")
    print(f"Signing as {who}, against capture {against}.\n")
    print("  y = yes, I have read this and it is right")
    print("  n = no, leave it unsigned and tell me why")
    print("  o = show me the whole section")
    print("  q = stop here\n")

    signed = skipped = 0
    for i, card in enumerate(cards, 1):
        print("=" * 72)
        print(f"[{i}/{len(cards)}]  {card.number}  {card.title}")
        print(f"       {card.id}  ({card.words} words, "
              f"{len(card.figures)} figure(s), status {card.status})")
        if card.last:
            print(f"       last stamped {card.last}, by nobody")
        diffs = card.differences()
        if diffs:
            print("\n  The crawl and the text do not agree:")
            for d in diffs:
                print(f"    {d}")
        else:
            print("\n  The crawl found nothing the text does not already say.")
        if card.figures:
            print(f"\n  Figures: {', '.join(card.figures)}")

        while True:
            answer = input("\n  read it and accept? [y/n/o/q] ").strip().lower()
            if answer == "o":
                sec = p.sections.get(card.id)
                print("\n" + "-" * 72)
                print(sec.path.read_text(encoding="utf-8"))
                print("-" * 72)
                continue
            break

        if answer == "q":
            print("\nstopped.")
            break
        if answer != "y":
            # An empty answer is a skip, never a yes. Holding down Return is
            # exactly the behaviour this whole mechanism exists to prevent.
            skipped += 1
            why = input("  why not? (optional) ").strip()
            if why:
                from .notes import Notes
                Notes.load(root).add(why, section=card.id)
                print("  noted, the loop will pick it up")
            continue

        sec = p.sections.get(card.id)
        before = sec.path.read_text(encoding="utf-8")
        msg = sign(p, root, card.id, who=who, when=args.date or "")
        History(root).record(card.id, sec.path, before,
                             sec.path.read_text(encoding="utf-8"),
                             actor="human", action="accept", note=msg)
        signed += 1
        print(f"  {msg}")

    print(f"\n{signed} accepted, {skipped} left unsigned, "
          f"{len(cards) - signed - skipped} not reached.")
    if signed:
        print("Any change with a machine behind it drops those badges again.")
    return 0


def cmd_release(args):
    p = _project(args)
    findings = lint(p)
    s = summarise(findings)
    if s["error"] and not args.force:
        print(f"release refused: {s['error']} error-level finding(s).")
        for f in findings:
            if f.level == ERROR:
                print(f"  {f}")
        return 1

    store = ReleaseStore(args.root)
    version = args.version or store.next_version()
    prev = store.latest(p.profile.name)
    diff = store.diff(p, prev)
    summary = args.summary or store.describe(p, diff)

    p.config["_release_label"] = version
    out = Path(args.root) / "dist" / output_name(p, version)
    if out.exists():
        print(f"release refused: {out.name} already exists. Bump the version.")
        return 1

    DocxRenderer(p).render(out, history=store.history(p.profile.name))
    from .render.pdf import PdfRenderer
    pdf = out.with_suffix(".pdf")
    PdfRenderer(p, store.history(p.profile.name)).render(pdf, work_dir=out.parent / "_print")
    html = HtmlRenderer(p, _drift_report(p, args.root)[0]).render(
        Path(args.root) / "dist" / "preview" / f"{version}-{p.profile.name}" / "index.html")

    rel = store.snapshot(p, version)
    rel.summary = summary
    rel.outputs = [str(out.relative_to(args.root)), str(pdf.relative_to(args.root)),
                   str(html.relative_to(args.root))]
    notes = ([f"new: {sid}" for sid in diff["added"]]
             + [f"revised: {sid}" for sid in diff["changed"]]
             + [f"removed: {sid}" for sid in diff["removed"]]
             + [f"screenshot replaced: {a}" for a in diff["changed_assets"]])
    # A first release lists the whole document, which is noise in a changelog.
    if len(notes) > 20:
        notes = notes[:20] + [f"... and {len(notes) - 20} more"]
    rel.notes = notes
    store.record(rel)
    (Path(args.root) / "CHANGELOG.md").write_text(store.changelog_markdown(),
                                                  encoding="utf-8")
    print(f"released {version} ({p.profile.name})")
    print(f"  {out}")
    print(f"  {pdf}")
    print(f"  {html}")
    print(f"  {summary}")
    return 0


def cmd_history(args):
    p = _project(args)
    h = History(args.root)
    h.seed(p.sections)
    if args.restore:
        sec = p.sections.get(args.id)
        if not sec:
            print(f"no section {args.id!r}")
            return 1
        h.restore(args.id, args.restore, sec.path)
        print(f"restored {args.id} to {args.restore}")
        return 0
    entries = h.entries(args.id or None, limit=args.limit)
    if not entries:
        print("nothing recorded yet")
        return 0
    print(f"{'WHEN':20} {'SECTION':44} {'WHAT':10} {'SOURCE':9} NOTE")
    for e in entries:
        print(f"{e['at'].replace('T',' '):20} {e['section'][:43]:44} "
              f"{e['action'][:9]:10} {e['actor']:9} {(e.get('note') or '')[:44]}")
    print()
    print(json.dumps(h.stats(), indent=2))
    return 0


def cmd_selftest(args):
    import subprocess
    script = Path(args.root) / "tools" / "selftest.py"
    cmd = [sys.executable, str(script)] + (["--live"] if args.live else [])
    return subprocess.run(cmd).returncode


def cmd_incidents(args):
    inc = Incidents.load(Path(args.root).resolve())
    if args.resolve:
        ok_ = inc.resolve(args.resolve, args.note or "")
        print(f"{'closed' if ok_ else 'no such incident'}: {args.resolve}")
        return 0 if ok_ else 1
    if args.export:
        out = Path(args.root) / "review" / "incident-brief.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(inc.brief(args.signature), encoding="utf-8")
        print(out)
        print()
        print("Hand this to a coding agent, for example:")
        print(f"  claude 'read {out.relative_to(Path(args.root).resolve())} "
              f"and fix the cause of each incident, then run "
              f"python3 tools/selftest.py'")
        return 0
    opened = inc.open_items()
    if not opened:
        print("no open incidents")
        return 0
    print(f"{'SIGNATURE':14} {'SEEN':>4}  {'LAST':20} WHERE")
    for i in opened:
        print(f"{i.signature:14} {i.seen:>4}  {i.last_at:20} {i.where}")
        print(f"{'':14}       {i.kind}: {i.message[:96]}")
    print()
    print("export a brief for a coding agent with: verba incidents --export")
    return 0


def cmd_sweep(args):
    """Review the document against the newest crawl and propose the gaps filled."""
    p = _project(args)
    root = Path(args.root).resolve()
    ids = None
    if args.section:
        ids = [args.section] if args.section in p.sections else None
        if ids is None:
            print(f"no section {args.section!r}")
            return 1
    sw = Sweep(p, root, Decisions.load(root), Knowledge.load(root))
    props = sw.run(ids, log=print, write_text=not args.images_only)
    if not props:
        print("nothing to propose")
        return 0
    print()
    for pr in props:
        print(f"  [{pr.kind}] {pr.title}")
        print(f"          {pr.detail}")
    print()
    print("review them in the console, or apply the image ones with:")
    print("  python3 -m verba sweep --apply-images")
    if args.apply_images:
        from .assets import refresh_derived
        from .history import History
        h = History(root)
        n = 0
        for pr in props:
            if pr.kind != "image":
                continue
            src = root / "capture" / pr.run / "screenshots" / pr.asset
            if not src.exists():
                continue
            import shutil
            from datetime import date
            shutil.copyfile(src, p.asset_path(pr.asset))
            p.assets.registry.setdefault(pr.asset, {}).update(
                {"source": str(src), "replaced_on": date.today().isoformat()})
            p.assets.save()
            h.record_asset(pr.asset, f"{pr.run}/{pr.asset}", note="adopted by sweep")
            refresh_derived(p.assets, pr.asset, capture_dir=root / "capture" / pr.run)
            Sweep.drop(root, pr.id)
            n += 1
        print(f"\nadopted {n} image(s)")
    return 0


def cmd_knowledge(args):
    p = _project(args)
    k = Knowledge.load(Path(args.root).resolve())
    k.learn_vocabulary(p)
    s = k.summary()
    print(f"{s['terms']} house term(s), {s['phrasing_samples']} approved sample(s)")
    print(f"{'TERM':36} {'USED':>5}  SECTIONS")
    for t in s["top_terms"]:
        print(f"  {t['term'][:34]:34} {t['count']:>5}  {t['sections']}")
    return 0


def cmd_decisions(args):
    d = Decisions.load(Path(args.root).resolve())
    if not d.items:
        print("nothing decided yet")
        return 0
    print(json.dumps(d.summary(), indent=2))
    print()
    for item in d.items.values():
        print(f"{item.verdict:9} {item.section}")
        print(f"  {item.line}")
        if item.reason:
            print(f"  reason: {item.reason}")
    return 0


def cmd_console(args):
    from .console.server import serve
    return serve(Path(args.root), port=args.port, profile=args.profile,
                 open_browser=not args.no_open)


def cmd_changelog(args):
    print(ReleaseStore(args.root).changelog_markdown())
    return 0


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser("verba", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="project root")
    ap.add_argument("--profile", default=None, help="edition to render")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    lt = sub.add_parser("lint")
    lt.add_argument("--level", default="all", choices=["all", "error", "warning", "info"])
    lt.add_argument("--strict", action="store_true", help="exit non-zero on errors")
    lt.set_defaults(func=cmd_lint)

    b = sub.add_parser("build")
    b.add_argument("--out")
    b.add_argument("--label")
    b.add_argument("--force", action="store_true")
    b.add_argument("--history", action="store_true", help="include revision history page")
    b.add_argument("--pdf", action="store_true", help="also render a PDF")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("capture")
    c.add_argument("--screens", help="comma separated screen ids")
    c.add_argument("--section", help="capture only the screens this section uses")
    c.add_argument("--headed", action="store_true")
    c.add_argument("--no-mask", action="store_true",
                   help="capture real names, for local checking only")
    c.add_argument("--replay-steps", action="store_true",
                   help="ignore remembered routes and click through from scratch")
    c.add_argument("--heal", action="store_true",
                   help="let the model repair selectors that stop resolving")
    c.add_argument("--wait-for-signin", action="store_true",
                   help="open a browser and wait for you to sign in, including "
                        "any second factor, then carry on")
    c.add_argument("--no-sweep", dest="sweep", action="store_false",
                   help="skip the review pass over what the crawl produced")
    c.set_defaults(sweep=True)
    c.set_defaults(func=cmd_capture)

    ev = sub.add_parser("env")
    ev.add_argument("action", choices=["list", "use", "verify", "signin", "password"])
    ev.add_argument("id", nargs="?", default="")
    ev.add_argument("--user")
    ev.set_defaults(func=cmd_env)

    hl = sub.add_parser("heal")
    hl.add_argument("--apply", action="store_true")
    hl.set_defaults(func=cmd_heal)

    sub.add_parser("routes").set_defaults(func=cmd_routes)
    sub.add_parser("masking").set_defaults(func=cmd_masking)

    d = sub.add_parser("drift")
    d.add_argument("--capture")
    d.add_argument("--print-report", action="store_true")
    d.set_defaults(func=cmd_drift)

    s = sub.add_parser("section")
    s.add_argument("action", choices=["new", "show", "set", "verify"])
    s.add_argument("id", nargs="?", default="")
    s.add_argument("values", nargs="*")
    s.add_argument("--title")
    s.add_argument("--screen")
    s.add_argument("--date")
    s.add_argument("--who", help="who is accepting it")

    ac = sub.add_parser("accept")
    ac.add_argument("--id", help="comma separated section ids")
    ac.add_argument("--who", help="who is accepting them")
    ac.add_argument("--date")
    ac.set_defaults(func=cmd_accept)
    s.set_defaults(func=cmd_section)

    r = sub.add_parser("release")
    r.add_argument("--version")
    r.add_argument("--summary")
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_release)

    k = sub.add_parser("console")
    k.add_argument("--port", type=int, default=8800)
    k.add_argument("--no-open", action="store_true")
    k.set_defaults(func=cmd_console)

    hh = sub.add_parser("history")
    hh.add_argument("id", nargs="?", default="", help="limit to one section")
    hh.add_argument("--limit", type=int, default=40)
    hh.add_argument("--restore", help="revision id to restore")
    hh.set_defaults(func=cmd_history)

    ic = sub.add_parser("incidents")
    ic.add_argument("--export", action="store_true",
                    help="write a brief a coding agent can act on")
    ic.add_argument("--signature", help="limit to one incident")
    ic.add_argument("--resolve", help="close an incident by signature")
    ic.add_argument("--note", help="what fixed it")
    ic.set_defaults(func=cmd_incidents)

    stt = sub.add_parser("selftest")
    stt.add_argument("--live", action="store_true",
                     help="also sign in and crawl one screen")
    stt.set_defaults(func=cmd_selftest)

    nt = sub.add_parser("note")
    nt.add_argument("text", nargs="*", help="what you noticed, in a sentence")
    nt.add_argument("--section", help="if you know which one it is about")
    nt.add_argument("--figure", help="a picture, if that is what you mean")
    nt.add_argument("--reopen", help="put a note back on the list")
    nt.add_argument("--drop", help="remove a note")
    nt.set_defaults(func=cmd_note)

    au = sub.add_parser("auto")
    au.add_argument("--rounds", type=int, default=3,
                    help="how many times to go round before stopping")
    au.add_argument("--no-crawl", action="store_true",
                    help="work from the last capture instead of taking a new one")
    au.set_defaults(func=cmd_auto)

    td = sub.add_parser("tidy")
    td.add_argument("--section", help="comma separated section ids")
    td.add_argument("--apply", action="store_true",
                    help="write every prepared decision")
    td.set_defaults(func=cmd_tidy)

    sv = sub.add_parser("survey")
    sv.add_argument("--crawl", action="store_true",
                    help="then crawl exactly the screens that would close a gap")
    sv.add_argument("--json", action="store_true", help="machine readable")
    sv.set_defaults(func=cmd_survey)

    dg = sub.add_parser("design")
    dg.add_argument("--check", action="store_true",
                    help="hold the project against every decision")
    dg.add_argument("--find", help="search the decisions and their reasons")
    dg.add_argument("--add", help="record a decision, as a sentence")
    dg.add_argument("--because", help="why it was decided, required with --add")
    dg.add_argument("--area", help="typography, colour, console, content, figures")
    dg.add_argument("--rule", help="the lint rule that enforces it")
    dg.add_argument("--enforced-by", dest="enforced_by",
                    help="the module that applies it")
    dg.set_defaults(func=cmd_design)

    nw = sub.add_parser("new")
    nw.add_argument("dir", nargs="?", help="where to put it (default: here)")
    nw.add_argument("--product", help="what the product is called")
    nw.add_argument("--vendor", help="who makes it")
    nw.add_argument("--about", help="what it does, in one sentence")
    nw.add_argument("--url", dest="base_url", help="where it lives")
    nw.add_argument("--auth", help="form, sso or none")
    nw.add_argument("--user", help="the account a crawl signs in as")
    nw.add_argument("--theme", help="slate, ink, atlas, ember or forest")
    nw.add_argument("--audience", help="who the document is written for")
    nw.add_argument("-y", "--yes", action="store_true",
                    help="take every default, ask nothing")
    nw.set_defaults(func=cmd_new)

    fx = sub.add_parser("fix")
    fx.add_argument("--rounds", help="how many times to go round (default 2)")
    fx.add_argument("--no-crawl", action="store_true",
                    help="do not photograph anything, even when that is the fix")
    fx.add_argument("--full", action="store_true",
                    help="photograph every screen first, then fix against it")
    fx.set_defaults(func=cmd_fix)

    th = sub.add_parser("themes")
    th.add_argument("--use", help="pick one")
    th.add_argument("--show", action="store_true", help="the resolved values")
    th.add_argument("--check", action="store_true", help="measure its contrast")
    th.set_defaults(func=cmd_themes)

    ly = sub.add_parser("layout")
    ly.add_argument("--paper", help="A4, A5, Letter or Legal")
    ly.add_argument("--side", help="left and right margin, mm")
    ly.add_argument("--edge", help="paper edge to header and footer text, mm")
    ly.add_argument("--header-band", dest="header_band", help="header height, mm")
    ly.add_argument("--footer-band", dest="footer_band", help="footer height, mm")
    ly.add_argument("--gap", help="air under the header rule, mm")
    ly.add_argument("--align", help="left or justify")
    ly.add_argument("--hyphens", help="on or off")
    ly.add_argument("--figure-width", dest="screenshot_width_cm",
                    help="how wide a screenshot prints, cm")
    ly.add_argument("--toc-depth", dest="toc_depth",
                    help="deepest level on the contents page, 1 to 4")
    ly.set_defaults(func=cmd_layout)

    ed = sub.add_parser("edition")
    ed.add_argument("action", nargs="?", default="show",
                    choices=["show", "add", "drop", "reset"])
    ed.add_argument("id", nargs="?", help="the section to add or drop")
    ed.set_defaults(func=cmd_edition)

    fm = sub.add_parser("forms")
    fm.add_argument("--section", help="only the screens one section uses")
    fm.add_argument("--all", action="store_true",
                    help="include per-field findings and accessibility observations")
    fm.set_defaults(func=cmd_forms)

    ft = sub.add_parser("fonts")
    ft.add_argument("--document", help="set the typeface the PDF, DOCX and preview use")
    ft.add_argument("--console", help="set the typeface the management interface uses")
    ft.add_argument("--verify", action="store_true",
                    help="ask Chromium which faces actually resolve")
    ft.set_defaults(func=cmd_fonts)

    sw = sub.add_parser("sweep")
    sw.add_argument("--section", help="only this section")
    sw.add_argument("--images-only", action="store_true",
                    help="skip the writing pass")
    sw.add_argument("--apply-images", action="store_true",
                    help="adopt the changed images straight away")
    sw.set_defaults(func=cmd_sweep)

    sub.add_parser("knowledge").set_defaults(func=cmd_knowledge)
    sub.add_parser("decisions").set_defaults(func=cmd_decisions)
    sub.add_parser("changelog").set_defaults(func=cmd_changelog)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
