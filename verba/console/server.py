"""The verba console: a local web app for managing the documentation.

Serves a JSON API over the same project objects the CLI uses, so the console and
the command line can never disagree about state. Runs on the standard library
alone: no framework to install, nothing to break when the environment moves.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import urllib.parse
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import forms as formlib
from .. import glyphs
from ..assets import refresh_derived
from ..capture import (
    Capture,
    _is_direct,
    latest_capture,
    load_routes,
    load_screens,
    merged_inventory,
)
from ..decisions import Decisions
from ..drift import analyse, to_markdown
from ..environments import Environment, Environments
from ..healing import Healer, apply_repairs
from ..history import History
from ..incidents import Incidents
from ..knowledge import Knowledge
from ..lint import lint, summarise
from ..lint import remedy as _lint_remedy
from ..masking import Masker
from ..model import parse_section
from ..project import Project
from ..readonly import lint_screens
from ..render.docx import DocxRenderer
from ..render.html import HtmlRenderer
from ..render.pdf import PdfRenderer
from ..sweep import Sweep
from ..typography import Typography
from ..version import ReleaseStore, output_name
from . import actions, assist
from .jobs import JobRunner

STATIC = Path(__file__).parent / "static"


class ConsoleState:
    """Owns the project and everything derived from it."""

    def __init__(self, root: Path, profile: str | None = None):
        self.root = Path(root).resolve()
        self.profile = profile
        self.incidents = Incidents.load(self.root)
        self.jobs = JobRunner(self.incidents)
        self.history = History(self.root)
        self.decisions = Decisions.load(self.root)
        self.knowledge = Knowledge.load(self.root)
        # The project has to exist before anything can be learned from it. This
        # ran the other way round and survived only because an established
        # project already had a vocabulary, so the branch never executed; on a
        # project's first run it did, and the console would not start at all.
        self.reload()
        if not self.knowledge.terms:
            self.knowledge.learn_vocabulary(self.project)
        self.history.seed(self.project.sections)

    def reload(self, profile: str | None = None):
        if profile:
            self.profile = profile
        self.project = Project.load(self.root, profile=self.profile)
        self.profile = self.project.profile.name
        return self.project

    # ------------------------------------------------------------------
    @property
    def capture_dir(self) -> Path | None:
        return latest_capture(self.root / "capture")

    def drift(self):
        run = self.capture_dir
        if not run:
            return None, None
        # what each screen was aimed at, so a crawl that landed elsewhere can be
        # recognised rather than mined for differences
        try:
            site, screens = self.screens()
            base = (site.get("base_url") or "").rstrip("/")
            aim = {}
            for sc in screens:
                goto = next((st["goto"] for st in sc.steps if "goto" in st), None)
                if goto:
                    aim[sc.id] = goto if goto.startswith("http") else base + goto
        except Exception:
            aim = {}
        merged, newest = merged_inventory(self.root / "capture")
        merged["_dir"] = str(newest)
        return analyse(self.project, merged, screens_cfg=aim), newest

    def profiles(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "content" / "profiles").glob("*.yaml"))

    def envs(self) -> Environments:
        return Environments.load(self.root)

    def screens(self):
        """The screen registry, with the active connection profile's address."""
        site, screens = load_screens(self.root / "content" / "screens.yaml")
        envs = self.envs()
        env = envs.current()
        if env is not None:
            override = envs.as_site(env, fallback_login=site.get("login"))
            site = {**site, **{k: v for k, v in override.items() if v or k == "login"}}
        return site, screens

    def routes(self) -> dict:
        return load_routes(self.root / "content" / "routes.yaml")

    KEYCHAIN = os.environ.get("VERBA_KEYCHAIN_SERVICE", "verba-staging")

    def credentials(self) -> dict:
        """Whether the active connection can sign in.

        Connection profiles own this. The older single-credential path is kept
        only as a fallback for a project with no profiles defined, because two
        sources of truth produced a console that claimed to be signed in on one
        panel and not on another.
        """
        env = self.envs().current()
        if env is not None:
            ok, why = env.ready(self.root)
            return {"ready": ok, "user": env.user or "", "source": env.auth,
                    "detail": why, "environment": env.label or env.id}
        user = os.environ.get("VERBA_USER", "")
        if user and os.environ.get("VERBA_PASSWORD"):
            return {"ready": True, "user": user, "source": "environment",
                    "detail": "from the environment"}
        try:
            acct = subprocess.run(
                ["security", "find-generic-password", "-s", self.KEYCHAIN],
                capture_output=True, text=True, timeout=10)
            pw = subprocess.run(
                ["security", "find-generic-password", "-s", self.KEYCHAIN, "-w"],
                capture_output=True, text=True, timeout=10)
        except Exception:
            return {"ready": False, "user": "", "source": "none"}
        if pw.returncode == 0 and pw.stdout.strip():
            name = ""
            for line in acct.stdout.splitlines():
                if '"acct"' in line and '="' in line:
                    name = line.split('="')[-1].rstrip('"')
            # make them available to this process, so a crawl started now works
            os.environ["VERBA_USER"] = name
            os.environ["VERBA_PASSWORD"] = pw.stdout.strip()
            return {"ready": True, "user": name, "source": "keychain",
                    "detail": "from the login keychain"}
        return {"ready": False, "user": "", "source": "none",
                "detail": "no connection profile set up"}

    def save_credentials(self, user: str, password: str) -> dict:
        """Store in the login keychain, never in a file, and use them right away."""
        if not user or not password:
            raise ValueError("both an email address and a password are needed")
        r = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", self.KEYCHAIN,
             "-a", user, "-w", password],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "the keychain refused the entry")
        os.environ["VERBA_USER"] = user
        os.environ["VERBA_PASSWORD"] = password
        return {"ready": True, "user": user, "source": "keychain"}

    def masker(self) -> Masker:
        content = self.root / "content"
        return Masker.load(content / "masking.yaml", content / "masking-map.json")

    # ------------------------------------------------------------------
    def state(self) -> dict:
        p = self.reload()
        rep, run = self.drift()
        drift_by = rep.by_section() if rep else {}
        findings = lint(p)
        # The remedy travels with the finding wherever it is shown. A finding
        # without one is a complaint, and the section view was showing exactly
        # that.
        from ..lint import remedy as _remedy
        by_section: dict[str, list] = {}
        for f in findings:
            key = f.section.split(" ", 1)[-1] if f.section else ""
            by_section.setdefault(key, []).append(
                {"rule": f.rule, "level": f.level, "message": f.message,
                 "detail": f.detail, "remedy": _remedy(f.rule)})

        site, screens = self.screens()
        screen_index = {s.id: s for s in screens}
        routes = self.routes()
        store = ReleaseStore(self.root)
        readonly = {}
        if run and (run / "inventory.json").exists():
            try:
                readonly = json.loads(
                    (run / "inventory.json").read_text()).get("readonly", {})
            except Exception:
                readonly = {}

        hist_index: dict = {}
        for e in self.history.entries(limit=5000):
            hist_index.setdefault(e.get("section", ""), []).append(e)

        sections = []
        for node in p.nodes:
            sec = node.section
            if sec is None:
                continue
            changes = drift_by.get(sec.id, [])
            sections.append({
                "id": sec.id, "number": node.number, "level": node.level,
                "title": sec.title, "icon": sec.icon, "status": sec.status,
                # the same drawn mark the document prints, so the interface and
                # the output do not disagree about what a section looks like
                "mark": glyphs.for_emoji(sec.icon, size="1em") if sec.icon else "",
                "last_verified": sec.last_verified, "screens": sec.screens,
                "capturable": [s for s in sec.screens if s in screen_index],
                "routes": [{"screen": s, "url": routes.get(s, {}).get("url"),
                            "last_seen": routes.get(s, {}).get("last_seen")}
                           for s in sec.screens],
                "notes": sec.meta.get("notes", ""),
                "words": sec.word_count(),
                "screenshots": sec.screenshots(),
                "blocks": [b.kind for b in sec.blocks],
                "drift": [self._change(c) for c in changes],
                "lint": by_section.get(sec.id, []),
                "path": str(sec.path.relative_to(self.root)) if sec.path else "",
                "changes": len([e for e in hist_index.get(sec.id, [])
                                if e.get("action") != "baseline"]),
                # Not "notes": that name already belongs to the section's own
                # front-matter note, and the second key in a dict literal wins
                # silently. A stale section's explanation was being replaced by
                # this list and never shown to anyone.
                "decided": [{"line": d.line, "reason": d.reason, "at": d.at,
                             "change": {**d.change, "section": d.section,
                                        "line": d.line}}
                            for d in self.decisions.declined_for(sec.id)],
            })

        return {
            "product": p.config.get("product", {}),
            "document": p.config.get("document", {}),
            "profile": p.profile.name,
            "profiles": self.profiles(),
            "title": p.title(),
            "sections": sections,
            "summary": {
                "sections": len(sections),
                "verified": sum(1 for s in sections if s["status"] == "verified"),
                "stale": sum(1 for s in sections if s["status"] == "stale"),
                "draft": sum(1 for s in sections if s["status"] == "draft"),
                # Only what is still outstanding. Counting decided items here
                # is why a settled queue still wore a badge and a red edge: the
                # number said there was work, and there was none.
                "drift_items": sum(
                    1 for s in sections for c in s["drift"] if not c.get("decided")),
                "drift_decided": sum(
                    1 for s in sections for c in s["drift"] if c.get("decided")),
                "assets": len(p.assets.all_names()),
                **summarise(findings),
            },
            "global_lint": [
                {"rule": f.rule, "level": f.level, "message": f.message, "detail": f.detail}
                for f in findings if not f.section],
            "capture": {
                "run": run.name if run else None,
                "at": rep.captured_at if rep else None,
                "unmapped_screens": rep.unmapped_screens if rep else [],
                "errors": rep.capture_errors if rep else [],
                "base_url": site.get("base_url", ""),
            },
            "screens": [{"id": s.id, "title": s.title, "sections": s.sections,
                         "shot": s.shot, "url": routes.get(s.id, {}).get("url") or s.url,
                         "last_seen": routes.get(s.id, {}).get("last_seen"),
                         "direct": _is_direct(s)} for s in screens],
            "assist": {"backends": assist.backends(),
                       "tasks": assist.TASKS,
                       "ready": assist.available()[0]},
            "masking": {**self.masker().summary(),
                        "active": self.masker().active(),
                        "map": self.masker().table()[:200]},
            "readonly": readonly,
            "credentials": self.credentials(),
            "environments": {"active": self.envs().active,
                             "items": self.envs().summary()},
            "history": self.history.stats(),
            "decisions": self.decisions.summary(),
            "knowledge": self.knowledge.summary(),
            "incidents": self.incidents.summary(),
            "proposals": Sweep.load(self.root),
            "releases": store.history(limit=20),
            "next_version": store.next_version(),
            # Whether a person has said what this product is. The first-run
            # panel asks, and stops asking once the file has words in it.
            "system": __import__("verba.system", fromlist=["System"])
                      .System.load(self.root).summary(),
            "outputs": self._outputs(),
            "jobs": self.jobs.recent(),
        }

    def _change(self, c) -> dict:
        base = {"section": c.section, "screen": c.screen, "kind": c.kind,
                "change": c.change, "label": c.label, "became": c.became,
                "confidence": c.confidence, "note": c.note, "line": c.line(),
                "applicable": c.change in ("renamed", "added", "removed",
                                          "image", "unmapped")}
        d = self.decisions.verdict_for(base)
        if d:
            base.update({"decided": d.verdict, "decided_reason": d.reason,
                         "decided_at": d.at})
        return base

    def _outputs(self) -> list[dict]:
        dist = self.root / "dist"
        out = []
        for f in sorted(dist.glob("*.docx")) + sorted(dist.glob("*.pdf")):
            out.append({"name": f.name, "size_kb": f.stat().st_size // 1024,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime)
                        .isoformat(timespec="minutes"),
                        "url": f"/files/dist/{f.name}"})
        return sorted(out, key=lambda x: x["modified"], reverse=True)

    # ------------------------------------------------------------------ jobs
    def job_capture(self, screen_ids: list[str] | None, section_id: str | None = None,
                    mask: bool = True, replay_steps: bool = False, heal: bool = True,
                    sweep: bool = True):
        # The work is a method rather than a closure so anything else that needs
        # a capture can have one synchronously. `fix` does: some rule findings
        # are cleared only by a fresh photograph, and refusing to take one meant
        # the loop always ended by handing back a job it could have done.
        def run(log):
            return self.capture_now(screen_ids, section_id, mask, replay_steps,
                                    heal, sweep, log)

        name = f"capture {section_id}" if section_id else "capture the live system"
        return self.jobs.start(name, run, detail=", ".join(screen_ids or ["all screens"]))

    def screens_for_section(self, section_id: str) -> list[str]:
        """Exactly the screens one section depends on.

        `capture_now(None, sid)` reads as "capture this section" and is not:
        the first argument is the screen list and None there means every screen
        in the registry. Recapturing one section therefore crawled the entire
        product, and a run that wanted two sections crawled it twice.
        """
        _, screens = self.screens()
        sec = self.reload().sections.get(section_id)
        want = list(getattr(sec, "screens", []) or []) if sec else []
        want += [s.id for s in screens if section_id in (getattr(s, "sections", []) or [])]
        return sorted(set(want))

    def capture_now(self, screen_ids: list[str] | None, section_id: str | None = None,
                    mask: bool = True, replay_steps: bool = False, heal: bool = True,
                    sweep: bool = True, log=None):
        """Crawl now, on this thread, and return the manifest summary."""
        log = log or (lambda *_: None)
        if True:
            site, screens = self.screens()
            content = self.root / "content"
            stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
            out = self.root / "capture" / stamp
            targets = [s for s in screens if not screen_ids or s.id in screen_ids]
            if not targets:
                raise RuntimeError("no matching screens in content/screens.yaml")

            envs = self.envs()
            env = envs.current()
            masker = self.masker()
            if not mask:
                if env is not None and env.mask_required:
                    raise RuntimeError(
                        f"{env.label or env.id} is marked as holding real data, so "
                        f"screenshots cannot be captured unmasked. Uncheck that on the "
                        f"connection only if the data really is safe to publish.")
                masker.enabled = False
            if env is not None:
                ok, why = env.ready(self.root)
                if not ok:
                    raise RuntimeError(f"{env.label or env.id}: {why}. "
                                       f"Fix it under Connections.")
                if not env.export_credentials():
                    raise RuntimeError(
                        f"{env.label or env.id}: the sign-in could not be read from "
                        f"the keychain. Re-enter it under Connections.")
                log(f"connection: {env.label or env.id} ({env.auth})")

            log(f"base url : {site.get('base_url')}")
            log(f"screens  : {', '.join(s.id for s in targets)}")
            log(f"output   : capture/{stamp}")
            log(f"masking  : {'on' if masker.active() else 'OFF, real names will be captured'}")
            log("writes   : blocked at the network layer once sign-in completes")
            for w in lint_screens(targets):
                log(f"  registry warning: {w}")
            log("launching chromium at 1440x768 ...")

            healer = Healer(enabled=heal)
            log(f"healing  : {'on, broken selectors get a repair proposal' if heal else 'off'}")
            cap = Capture(site, screens, out, headless=True, masker=masker,
                          routes_path=content / "routes.yaml", healer=healer)
            manifest = cap.run(only=[s.id for s in targets], log=log,
                               prefer_url=not replay_steps)

            if not manifest["screens"]:
                raise RuntimeError("no screen captured, see the errors above")
            ro = manifest["readonly"]
            log(f"read-only: {ro['blocked_writes']} write attempt(s) blocked, "
                f"{ro['sign_in_requests']} sign-in request(s) allowed")
            mk = manifest["masking"]
            log(f"masking  : {mk['known_values']} value(s) masked, "
                f"{mk['new_values']} newly learned")
            hz = manifest.get("healing", {})
            if hz.get("attempted"):
                log(f"healing  : {hz['verified']} of {hz['attempted']} broken "
                    f"selector(s) repaired and verified")
                healer.save(self.root / "review" / "repairs.json")
            log(f"done: {len(manifest['screens'])} screen(s), "
                f"{len(manifest['errors'])} error(s)")

            p = self.reload()
            sweep_count = tidy_count = 0
            before_errors = summarise(lint(p))["error"]
            if sweep:
                log("")
                log("reviewing what the crawl produced ...")
                touched = sorted({sid for sc in targets for sid in sc.sections})
                sw = Sweep(p, self.root, self.decisions, self.knowledge)
                sweep_count = len(sw.run(touched or None, log=log))

                # A crawl brings new labels, and new labels bring new rule
                # findings: a placeholder documented as a name, a control named
                # after one account's row. Leaving those for the next person to
                # discover in a lint run is the same as not looking.
                log("")
                log("checking what the crawl did to the rules ...")
                p = self.reload()
                findings = lint(p)
                after_errors = summarise(findings)["error"]
                fixable = sorted({(f.section or "").split(" ", 1)[-1]
                                  for f in findings if f.level == "error"
                                  and f.rule in ("CONTENT-03", "STYLE-06")})
                if after_errors > before_errors:
                    log(f"  the crawl added {after_errors - before_errors} "
                        f"rule finding(s)")
                if fixable:
                    from ..tidy import Tidy
                    log(f"  {len(fixable)} section(s) need the writing fixed, "
                        f"asking the writer")
                    tidy_count = len(Tidy(p, self.root).run(fixable, log=log))
                elif after_errors:
                    log(f"  {after_errors} finding(s) remain, none of them the "
                        f"kind the writer can fix")
                else:
                    log("  no rule findings")

            rep, _ = self.drift()
            changes = [self._change(c) for c in (rep.changes if rep else [])
                       if not section_id or c.section == section_id]
            return {"run": stamp, "screens": list(manifest["screens"]),
                    "proposals": sweep_count, "writing_fixes": tidy_count,
                    "lint_errors": summarise(lint(self.reload()))["error"],
                    "errors": manifest["errors"], "changes": changes,
                    "readonly": ro, "masking": manifest["masking"],
                    "healing": manifest.get("healing", {})}

    def job_publish(self, formats: list[str], version: str | None, summary: str,
                    force: bool):
        def run(log):
            p = self.reload()
            findings = lint(p)
            s = summarise(findings)
            log(f"lint: {s['error']} error, {s['warning']} warning, {s['info']} info")
            for f in findings:
                if f.level == "error":
                    log(f"  ERROR {f.rule} {f.section}: {f.message}")
            if s["error"] and not force:
                raise RuntimeError(
                    f"{s['error']} error-level finding(s). Fix them, or publish with "
                    f"'ignore lint errors' ticked.")

            store = ReleaseStore(self.root)
            label = version or f"draft-{date.today().isoformat()}"
            p.config["_release_label"] = label
            dist = self.root / "dist"
            outputs = []

            if version:
                prev = store.latest(p.profile.name)
                diff = store.diff(p, prev)
                text = summary or store.describe(p, diff)
                base = output_name(p, version).removesuffix(".docx")
            else:
                text = summary or "Working draft."
                base = f"preview_{p.profile.name}"

            history = store.history(p.profile.name)
            if "docx" in formats:
                out = dist / f"{base}.docx"
                if version and out.exists():
                    raise RuntimeError(f"{out.name} already exists, bump the version")
                log(f"rendering docx -> {out.name}")
                DocxRenderer(p).render(out, history=history if version else None)
                outputs.append(str(out.relative_to(self.root)))
                log(f"  {out.stat().st_size // 1024} KB")

            if "pdf" in formats:
                out = dist / f"{base}.pdf"
                if version and out.exists():
                    raise RuntimeError(f"{out.name} already exists, bump the version")
                log(f"rendering pdf via chromium -> {out.name}")
                PdfRenderer(p, history if version else None).render(
                    out, work_dir=dist / "_print")
                outputs.append(str(out.relative_to(self.root)))
                log(f"  {out.stat().st_size // 1024} KB")

            if "html" in formats:
                rep, _ = self.drift()
                out = HtmlRenderer(p, rep).render(
                    dist / "preview" / f"{label}-{p.profile.name}" / "index.html")
                outputs.append(str(out.relative_to(self.root)))
                log(f"rendering html preview -> {out.parent.name}/")

            if version:
                rel = store.snapshot(p, version)
                rel.summary = text
                rel.outputs = outputs
                rel.notes = [f"{k}: {v}" for k, v in
                             store.diff(p, store.latest(p.profile.name)).items() if v][:20]
                store.record(rel)
                (self.root / "CHANGELOG.md").write_text(store.changelog_markdown(),
                                                        encoding="utf-8")
                log(f"released {version}: {text}")
            log("done")
            return {"outputs": outputs, "version": version, "summary": text}

        return self.jobs.start("publish" if version else "build", run,
                               detail=f"{'+'.join(formats)}"
                                      f"{' ' + version if version else ''}")

    def job_assist(self, section_id: str, task: str):
        def run(log):
            p = self.reload()
            sec = p.sections.get(section_id)
            if sec is None:
                raise RuntimeError(f"no section {section_id!r}")
            rep, run_dir = self.drift()
            drift = [self._change(c) for c in (rep.changes if rep else [])
                     if c.section == section_id]
            # the newest run may hold only the screens of a targeted recrawl,
            # so take the newest capture of each screen across runs
            merged, _ = merged_inventory(self.root / "capture")
            inv = {sid: merged["screens"][sid] for sid in sec.screens
                   if sid in merged.get("screens", {})}
            findings = [
                {"rule": f.rule, "level": f.level, "message": f.message,
                 "detail": f.detail}
                for f in lint(p) if section_id in (f.section or "")]

            log(f"task     : {assist.TASKS.get(task, task)}")
            log(f"section  : {sec.title}")
            log(f"evidence : {len(inv)} screen(s), {len(drift)} difference(s), "
                f"{len(findings)} finding(s)")
            if not inv:
                log("note     : no crawl evidence for this section, the model will "
                    "work from the existing text alone")

            self.knowledge.learn_vocabulary(p)
            notes = self.knowledge.bundle_for(section_id, self.decisions)
            declined = len(self.decisions.declined_for(section_id))
            if declined:
                log(f"honouring {declined} earlier decision(s) on this section")
            if self.knowledge.terms:
                log(f"applying house vocabulary: {len(self.knowledge.terms)} term(s)")
            prompt = assist.build_prompt(task, p, sec, inv, drift, findings, notes)
            result = assist.run_model(prompt, log=log)
            if not result.ok:
                raise RuntimeError(result.error)
            log(f"answer   : {len(result.output)} characters via {result.backend}")

            if task == "review":
                log("review complete, nothing was changed")
                return {"task": task, "kind": "notes", "notes": result.output,
                        "section": section_id}

            proposed = assist.clean_output(result.output)
            # An empty answer parses into a section whose id falls back to the
            # file name, and the id check then reports a rename that never
            # happened. Say what actually went wrong.
            if not (result.output or "").strip():
                raise RuntimeError(
                    "the model returned nothing at all. Nothing was changed.")
            try:
                parsed = parse_section(proposed, sec.path)
            except Exception as e:
                raise RuntimeError(f"the model returned something that is not a valid "
                                   f"section file: {e}")
            if parsed.id != sec.id:
                # The id is front matter, ours, and the writer was asked about
                # content. Put it back rather than discarding a good rewrite.
                proposed = _restore_id(proposed, sec.id)
                parsed = parse_section(proposed, sec.path)
                if parsed.id != sec.id:
                    raise RuntimeError(
                        f"the model changed the section id to {parsed.id!r} and it "
                        f"could not be restored. Rejected.")
                log("the reply renamed the section, id restored")
            log("proposal parses as a valid section, nothing written yet")
            return {"task": task, "kind": "proposal", "section": section_id,
                    "before": sec.to_markdown(), "after": proposed}

        return self.jobs.start("assist", run, detail=f"{assist.TASKS.get(task, task)}")

    def job_verify(self, env):
        def run(log):
            from ..signin import verify
            r = verify(env, self.root, log=log)
            if not r.get("ok"):
                raise RuntimeError(r.get("reason", "could not sign in"))
            log(f"writes blocked during the check: {r.get('blocked_writes', 0)}")
            return r
        return self.jobs.start("verify connection", run, detail=env.label or env.id)

    def job_signin(self, env):
        def run(log):
            from ..signin import interactive_signin
            r = interactive_signin(env, self.root, log=log)
            if not r.get("saved"):
                raise RuntimeError("no session was saved")
            log("now use Verify to confirm the session works")
            return r
        return self.jobs.start("interactive sign-in", run, detail=env.label or env.id)

    def job_drift(self):
        def run(log):
            p = self.reload()
            run_dir = self.capture_dir
            if not run_dir:
                raise RuntimeError("no capture yet, run a capture first")
            log(f"comparing against capture {run_dir.name}")
            rep = analyse(p, run_dir)
            out = self.root / "review" / "DRIFT.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(to_markdown(rep, p), encoding="utf-8")
            for k, v in rep.summary().items():
                log(f"  {k}: {v}")
            log("wrote review/DRIFT.md")
            return rep.summary()
        return self.jobs.start("drift", run)


# ---------------------------------------------------------------- http layer


class Handler(BaseHTTPRequestHandler):
    state: ConsoleState = None       # set by serve()
    server_version = "verba"

    def log_message(self, fmt, *args):
        pass

    # -- helpers ---------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def json(self, data, code: int = 200):
        self._send(code, json.dumps(data, default=str).encode(), "application/json")

    def fail(self, message: str, code: int = 400):
        self.json({"ok": False, "error": message}, code)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    # -- routing ---------------------------------------------------------
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, q = url.path, urllib.parse.parse_qs(url.query)
        st = self.state
        try:
            if path in ("/", "/index.html"):
                return self._static("app.html")
            if path == "/fonts.css":
                # generated, not a file: the choice lives in typography.yaml and
                # a stylesheet on disk would only ever be a stale copy of it
                face = Typography.load(st.root).face("console")
                css = (f"{face.css_import()}:root{{\n"
                       f"  --font-body: {face.css_body()};\n"
                       f"  --font-mono: {face.css_mono()};\n"
                       f"  --font-track: {face.tracking()};\n}}\n")
                return self._send(200, css.encode(), "text/css; charset=utf-8")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/state":
                return self.json(st.state())
            if path.startswith("/api/section/"):
                sid = urllib.parse.unquote(path[len("/api/section/"):])
                return self._get_section(sid)
            if path.startswith("/api/job/"):
                job = st.jobs.get(path[len("/api/job/"):])
                if not job:
                    return self.fail("no such job", 404)
                return self.json(job.to_dict(since=int(q.get("since", [0])[0])))
            if path == "/api/live":
                runs = sorted((st.root / "capture").glob("*"),
                              key=lambda x: x.stat().st_mtime, reverse=True)
                for r in runs[:2]:
                    meta, shot = r / "live.json", r / "live.png"
                    if meta.exists() and shot.exists():
                        try:
                            info = json.loads(meta.read_text())
                        except Exception:
                            continue
                        # `age` was the modification time, which is not an age.
                        # The last frame of a finished crawl stays on disk, so
                        # without a real age the viewer cannot tell a live crawl
                        # from one that ended an hour ago.
                        import time as _time
                        age = max(0.0, _time.time() - shot.stat().st_mtime)
                        return self.json({"ok": True, **info,
                                          "url_png": f"/files/capture/{r.name}/live.png",
                                          "age": round(age, 1),
                                          "fresh": age < 12})
                return self.json({"ok": True, "screen": None, "fresh": False})

            if path == "/api/forms":
                from ..capture import merged_inventory
                merged, _ = merged_inventory(st.root / "capture")
                screens = merged.get("screens", {})
                sid = q.get("section", [""])[0]
                p = st.reload()
                out, issues, a11y = [], [], []
                for node in p.nodes:
                    if node.section is None or (sid and node.id != sid):
                        continue
                    for scr in node.section.screens:
                        rec = screens.get(scr) or {}
                        if not rec.get("forms"):
                            continue
                        out.append({"screen": scr, "section": node.id,
                                    "number": node.number, "title": node.section.title,
                                    "counts": rec.get("form_counts", {}),
                                    "scoped_to": rec["forms"].get("scoped_to", ""),
                                    "forms": rec["forms"].get("forms", [])})
                        issues += formlib.compare(node.section, rec["forms"])
                        a11y += rec.get("a11y") or []
                return self.json({"screens": out, "issues": issues,
                                  "a11y": a11y, "captured": bool(screens)})

            if path == "/api/notes":
                from ..notes import Notes
                n = Notes.load(st.root)
                return self.json({"summary": n.summary(),
                                  "notes": [x.to_dict() for x in n.items]})

            if path == "/api/tidy":
                from ..tidy import Tidy
                return self.json(Tidy.load(st.root))

            if path == "/api/survey":
                from ..survey import Survey
                sv = Survey.run(st.reload(), st.root)
                sv.save()
                return self.json(sv.to_dict())

            if path == "/api/findings":
                # Every finding, with what would clear it and the section it
                # belongs to, so the interface can offer the fix rather than
                # printing the problem and stopping there.
                from ..lint import lint as _lint
                from ..lint import remedy
                p = st.reload()
                out = []
                for f in _lint(p):
                    sid = (f.section or "").split(" ", 1)
                    out.append({
                        "rule": f.rule, "level": f.level,
                        "number": sid[0] if len(sid) > 1 else "",
                        "section": sid[1] if len(sid) > 1 else (f.section or ""),
                        "message": f.message, "detail": f.detail,
                        "remedy": remedy(f.rule),
                    })
                order = {"error": 0, "warning": 1, "info": 2}
                out.sort(key=lambda x: (order.get(x["level"], 3), x["rule"]))
                return self.json({"findings": out,
                                  "errors": sum(1 for x in out if x["level"] == "error")})

            if path == "/api/design":
                from ..design import Design
                d = Design.load(st.root)
                return self.json({
                    "summary": d.summary(),
                    "tokens": d.tokens,
                    "areas": {a: [{"id": x.id, "decided": x.decided.strip(),
                                   "because": x.because.strip(),
                                   "held_by": x.held_by} for x in items]
                              for a, items in d.by_area().items()},
                    "traps": d.traps,
                    "findings": d.check(st.reload()),
                })

            if path == "/api/jobs/running":
                return self.json({"job": st.jobs.running()})

            if path == "/api/masking":
                mk = st.masker()
                return self.json({
                    "active": mk.active(),
                    "enabled": bool(getattr(mk, "enabled", True)),
                    "path": str(st.root / "content" / "masking.yaml"),
                    "columns": [dict(c) for c in (mk.columns or [])],
                    "patterns": [dict(x) for x in (mk.patterns or [])],
                    "literals": [dict(x) for x in (mk.literals or [])],
                    "mapping": mk.table(),
                    # Pictures nobody has looked at, with a link to each, so the
                    # only person who can settle them can actually see them.
                    "unchecked": _unchecked_pictures(st),
                })

            if path == "/api/screens":
                # imported here rather than relied on from module scope: this
                # handler imports it further down, which makes the name local
                # for the whole function and unbound until that line runs
                from .server import merged_inventory as _merged
                site, screens = st.screens()
                routes = st.routes()
                proj = st.reload()
                bound = {}
                for sec in proj.sections.values():
                    for sid in sec.screens:
                        bound.setdefault(sid, []).append(sec.id)
                merged, _ = _merged(st.root / "capture")
                seen = merged.get("screens", {})
                # Pictures the document ships that no screen produces. They are
                # a hole in the registry, not a fault in the document, so they
                # are reported here rather than beside the writing.
                unreachable = [f.message.split(":", 1)[-1].strip()
                               for f in lint(proj) if f.rule == "ASSET-11"]
                return self.json({
                    "unreachable": unreachable,
                    "base_url": site.get("base_url", ""),
                    "path": str(st.root / "content" / "screens.yaml"),
                    "screens": [{
                        "id": s.id,
                        "title": getattr(s, "title", "") or s.id,
                        "shot": getattr(s, "shot", "") or "",
                        "sections": sorted(set(list(getattr(s, "sections", []) or [])
                                               + bound.get(s.id, []))),
                        "steps": len(getattr(s, "steps", []) or []),
                        "extract": sorted((getattr(s, "extract", {}) or {}).keys()),
                        "elements": len(getattr(s, "elements", []) or []),
                        "url": (routes.get(s.id) or {}).get("url", ""),
                        "captured": s.id in seen,
                        "labels": {k: len(v) for k, v in
                                   (seen.get(s.id, {}).get("elements") or {}).items()},
                    } for s in screens],
                })

            if path == "/api/theme":
                from ..theme import Theme, table
                cur = Theme.load(st.root)
                return self.json({
                    "current": cur.name, "label": cur.label,
                    "themes": table(),
                })

            if path == "/api/assistant":
                from .. import console as _c  # noqa: F401
                return self.json({
                    "model": assist.DEFAULT_MODEL,
                    "gateway": assist.LITELLM_BASE,
                    "key_helper": assist.LITELLM_KEY_HELPER,
                    # never the key itself, only whether there is one
                    "has_key": bool(assist.stored_api_key()),
                    "models": assist.KNOWN_MODELS,
                    # what the configured gateway actually carries, asked at
                    # the moment the page is opened rather than guessed
                    "gateway_models": assist.gateway_models(),
                    "backends": assist.backends(),
                    "house_rules": (assist.house_rules_path(st.root).read_text(encoding="utf-8")
                                    if assist.house_rules_are_custom(st.root)
                                    else assist.HOUSE_RULES),
                    "house_is_custom": assist.house_rules_are_custom(st.root),
                    "house_path": str(assist.house_rules_path(st.root)),
                })

            if path == "/api/documents":
                from ..workspaces import default_home, listing
                return self.json({"documents": listing(st.root),
                                  "home": str(default_home())})

            if path == "/api/layout":
                from .. import layout
                return self.json(layout.read(st.root))

            if path == "/api/edition":
                from .. import editions
                pr = st.reload()
                rows = editions.read(pr)
                return self.json({
                    "profile": pr.profile.name,
                    "mode": "include" if pr.profile.include is not None else "exclude",
                    "carried": sum(1 for r in rows if r["carried"]),
                    "total": len(rows),
                    "sections": rows,
                })

            if path == "/api/fonts":
                t = Typography.load(st.root)
                return self.json({"faces": t.table(),
                                  "document": t.document, "console": t.console})

            if path == "/api/proposals":
                return self.json(Sweep.load(st.root))

            if path == "/api/images":
                return self.json(_all_images(st.root))

            if path == "/api/document":
                pr = st.reload()
                pr.config["_release_label"] = "review copy"
                out = st.root / "dist" / "_review" / pr.profile.name
                renderer = PdfRenderer(pr, ReleaseStore(st.root).history(pr.profile.name))
                page = renderer.build_html(out)
                return self.json({
                    "ok": True,
                    "url": f"/files/{page.relative_to(st.root)}",
                    "profile": pr.profile.name,
                    "sections": len(pr.nodes),
                    "figures": sum(1 for n in pr.nodes if n.section
                                   for b in n.section.blocks if b.kind == "screenshot"),
                })

            if path == "/api/incidents":
                return self.json({
                    "summary": st.incidents.summary(),
                    "items": [i.to_dict() for i in st.incidents.open_items()],
                })
            if path == "/api/incidents/brief":
                body = st.incidents.brief(q.get("signature", [None])[0]).encode()
                return self._send(200, body, "text/plain; charset=utf-8")

            if path.startswith("/api/history"):
                rest = path[len("/api/history"):].strip("/")
                if not rest:
                    return self.json({"entries": st.history.entries(limit=200),
                                      "stats": st.history.stats()})
                sid = urllib.parse.unquote(rest)
                entries = st.history.entries(sid)
                rev = q.get("revision", [None])[0]
                body = {"section": sid, "entries": entries,
                        "stats": st.history.stats()}
                if rev:
                    body["content"] = st.history.content(sid, rev)
                    body["previous"] = st.history.previous(sid, rev)
                return self.json(body)

            if path == "/api/drift":
                rep, run = st.drift()
                return self.json({
                    "run": run.name if run else None,
                    "changes": [st._change(c) for c in rep.changes] if rep else [],
                    "unmapped": rep.unmapped_screens if rep else [],
                    "summary": rep.summary() if rep else {}})
            if path.startswith("/files/"):
                return self._file(path[len("/files/"):])
            return self.fail("not found", 404)
        except Exception as e:
            return self.fail(f"{type(e).__name__}: {e}", 500)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        st = self.state
        data = self.body()
        try:
            if path == "/api/profile":
                st.reload(profile=data.get("profile"))
                return self.json({"ok": True, "profile": st.profile})

            if path.startswith("/api/env"):
                verb = path[len("/api/env"):].strip("/")
                envs = st.envs()

                if verb in ("", "save"):
                    d = data.get("environment") or {}
                    if not d.get("id"):
                        return self.fail("an id is required")
                    env = Environment.from_dict(d)
                    existing = envs.items.get(env.id)
                    if existing and not env.user:
                        env.user = existing.user
                    envs.add(env)
                    pw_value = data.get("password")
                    if env.auth == "form" and pw_value:
                        try:
                            env.set_password(d.get("user", "") or env.user, pw_value)
                            envs.save()
                        except Exception as e:
                            return self.fail(str(e))
                    return self.json({"ok": True, "message": f"saved {env.label or env.id}",
                                      "environments": envs.summary()})

                if verb == "activate":
                    try:
                        envs.activate(data.get("id", ""))
                    except KeyError:
                        return self.fail("no such profile", 404)
                    return self.json({"ok": True, "environments": envs.summary(),
                                      "message": f"now using {data.get('id')}"})

                if verb == "remove":
                    envs.remove(data.get("id", ""))
                    return self.json({"ok": True, "environments": envs.summary(),
                                      "message": "profile removed"})

                if verb == "verify":
                    env = envs.items.get(data.get("id", ""))
                    if env is None:
                        return self.fail("no such profile", 404)
                    return self.json({"ok": True, "job": st.job_verify(env).id})

                if verb == "signin":
                    env = envs.items.get(data.get("id", ""))
                    if env is None:
                        return self.fail("no such profile", 404)
                    if env.auth != "sso":
                        return self.fail("interactive sign-in is for single sign-on "
                                         "profiles. A form profile just needs its "
                                         "password saved.")
                    return self.json({"ok": True, "job": st.job_signin(env).id})

                return self.fail(f"unknown action {verb!r}")

            if path == "/api/heal/apply":
                path_r = st.root / "review" / "repairs.json"
                if not path_r.exists():
                    return self.fail("no repairs recorded yet")
                good = [r for r in json.loads(path_r.read_text()) if r.get("verified")]
                applied = apply_repairs(st.root / "content" / "screens.yaml", good)
                return self.json({"ok": True, "applied": applied,
                                  "message": f"{len(applied)} selector repair(s) written"})

            if path == "/api/images/remove":
                # Only a picture nothing refers to. Removing one a section
                # shows would trade a duplicate for a missing figure.
                name = (data.get("name") or "").strip()
                p = st.reload()
                used = {n for node in p.nodes if node.section
                        for n in node.section.screenshots()}
                used |= {m for node in p.nodes if node.section
                         for b in node.section.blocks
                         for it in (b.items or [])
                         for m in re.findall(r"\[icon:([^\]\s]+)", str(it))}
                if name in used:
                    return self.fail(f"{name} is shown in the document. "
                                     f"Take it out of the section first.")
                target = p.asset_path(name)
                if not target.exists():
                    return self.fail(f"no such picture: {name}")

                keep = st.root / ".verba" / "removed"
                keep.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(keep / name))
                p.assets.registry.pop(name, None)
                p.assets.save()
                st.history.record_asset(
                    name, f"removed/{name}",
                    note="removed as an unused duplicate, kept in .verba/removed")
                st.reload()
                return self.json({"ok": True,
                                  "message": f"{name} removed, and kept in "
                                             f".verba/removed if you want it back"})

            if path == "/api/images/adopt":
                name, run_name = data.get("name"), data.get("run")
                src = st.root / "capture" / str(run_name) / "screenshots" / str(name)
                if not src.exists():
                    return self.fail(f"{name} is not in capture {run_name}")
                st.reload()
                dest = st.project.asset_path(str(name))
                shutil.copyfile(src, dest)
                entry = st.project.assets.registry.setdefault(str(name), {})
                entry.update({"source": str(src),
                              "replaced_on": date.today().isoformat()})
                st.project.assets.save()
                st.history.record_asset(str(name), f"{run_name}/{name}",
                                        actor="capture",
                                        note=f"adopted from {run_name}")
                r = refresh_derived(st.project.assets, str(name),
                                    capture_dir=st.root / "capture" / str(run_name))
                tail = (f", refreshed {len(r['captured'])} inline element(s)"
                        if r["captured"] else "")
                return self.json({"ok": True,
                                  "message": f"{name} adopted from {run_name}{tail}"})

            if path == "/api/credentials":
                try:
                    info = st.save_credentials(data.get("user", "").strip(),
                                               data.get("password", ""))
                except Exception as e:
                    return self.fail(str(e))
                return self.json({"ok": True, "credentials": info,
                                  "message": f"signed in as {info['user']}, "
                                             f"stored in the login keychain"})

            if path == "/api/capture":
                job = st.job_capture(data.get("screens") or None, data.get("section"),
                                     mask=data.get("mask", True),
                                     replay_steps=bool(data.get("replay_steps")),
                                     heal=data.get("heal", True),
                                     sweep=data.get("sweep", True))
                return self.json({"ok": True, "job": job.id})

            if path == "/api/drift/run":
                return self.json({"ok": True, "job": st.job_drift().id})

            if path == "/api/drift/preview":
                st.reload()
                _, run = st.drift()
                change = data.get("change") or {}
                sec = st.project.sections.get(change.get("section", ""))
                if sec is None:
                    return self.fail("unknown section")
                before = sec.path.read_text(encoding="utf-8")
                # apply, capture the result, then put the file straight back:
                # the preview must show the real outcome, not a guess at it
                try:
                    msg = actions.apply_change(st.project, change, run)
                    after = sec.path.read_text(encoding="utf-8")
                finally:
                    sec.path.write_text(before, encoding="utf-8")
                    st.reload()
                return self.json({"ok": True, "message": msg,
                                  "before": before, "after": after,
                                  "changed": before != after})

            if path == "/api/heal/preview":
                path_r = st.root / "review" / "repairs.json"
                if not path_r.exists():
                    return self.fail("no repairs recorded yet")
                good = [r for r in json.loads(path_r.read_text()) if r.get("verified")]
                target = st.root / "content" / "screens.yaml"
                before = target.read_text(encoding="utf-8")
                try:
                    applied = apply_repairs(target, good)
                    after = target.read_text(encoding="utf-8")
                finally:
                    target.write_text(before, encoding="utf-8")
                return self.json({"ok": True, "repairs": good, "applied": applied,
                                  "before": before, "after": after,
                                  "changed": before != after})

            if path == "/api/decision":
                change = data.get("change") or {}
                verdict = data.get("verdict", "")
                reason = data.get("reason", "")
                if verdict not in ("approved", "declined"):
                    return self.fail("verdict must be approved or declined")
                try:
                    d = st.decisions.record(change, verdict, reason)
                except ValueError as e:
                    return self.fail(str(e))
                # approving is also the instruction to make the change
                if verdict == "approved" and change.get("applicable"):
                    st.reload()
                    _, run = st.drift()
                    sec = st.project.sections.get(change.get("section", ""))
                    before = sec.path.read_text(encoding="utf-8") if sec else None
                    msg = actions.apply_change(st.project, change, run)
                    if sec and before is not None:
                        st.history.record(sec.id, sec.path, before,
                                          sec.path.read_text(encoding="utf-8"),
                                          actor="drift",
                                          action=change.get("change", "apply"),
                                          note=change.get("line", ""))
                    st.reload()
                    return self.json({"ok": True, "message": msg, "decision": d.to_dict()})
                return self.json({"ok": True, "decision": d.to_dict(),
                                  "message": "declined, and the reason is on record"})

            if path == "/api/fonts/choose":
                t = Typography.load(st.root)
                try:
                    for which in ("document", "console"):
                        if data.get(which):
                            t.choose(which, data[which])
                except ValueError as e:
                    return self.fail(str(e))
                return self.json({"ok": True,
                                  "message": f"set in {t.face('document').label}"})

            if path == "/api/images/checked":
                # A picture no crawl can reach is not a defect, it is a picture
                # nobody has looked at. A person can look at it: that is the
                # whole finding. Recorded as a person's verdict rather than as
                # proof of masking, because those are different claims and only
                # one of them is true here.
                d = data or {}
                name = str(d.get("name") or "").strip()
                proj = st.reload()
                if not name or not proj.assets.exists(name):
                    return self.fail(f"no picture called {name!r}")
                if d.get("undo"):
                    proj.assets.registry.get(name, {}).pop("checked_by", None)
                    proj.assets.save()
                    st.reload()
                    return self.json({"ok": True,
                                      "message": f"{name} is unchecked again"})
                entry = proj.assets.registry.setdefault(name, {})
                entry["checked_by"] = {
                    "who": "a person at this console",
                    "when": datetime.now().strftime("%Y-%m-%d"),
                    "note": str(d.get("note") or "").strip(),
                }
                proj.assets.save()
                st.reload()
                return self.json({"ok": True,
                                  "message": f"{name} marked as checked"})

            if path == "/api/masking/literal":
                # The one rule a person adds by hand: "this exact name must
                # never appear, put that instead". Columns and patterns need a
                # selector or a regular expression and belong in the file, with
                # the comments that explain them.
                import yaml as _yaml

                from ..atomic import write_text as _wt
                d = data or {}
                match = str(d.get("match") or "").strip()
                with_ = str(d.get("with") or "").strip()
                drop = bool(d.get("drop"))
                if not match:
                    return self.fail("which name should never appear?")
                if not drop and not with_:
                    return self.fail("what should appear instead?")
                cfg = st.root / "content" / "masking.yaml"
                raw = _yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
                lits = [x for x in (raw.get("literals") or [])
                        if str(x.get("match", "")) != match]
                if not drop:
                    lits.append({"match": match, "with": with_})
                raw["literals"] = lits
                _wt(cfg, _yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
                return self.json({"ok": True, "message":
                                  f"removed the rule for {match!r}" if drop
                                  else f"{match!r} will be shown as {with_!r} "
                                       f"from the next capture"})

            if path == "/api/theme/use":
                import re as _re

                from ..atomic import write_text as _wt
                from ..theme import Theme, available
                key = str((data or {}).get("use") or "").strip()
                if key not in available():
                    return self.fail(f"no such theme: {key!r}. "
                                     f"try one of: {', '.join(available())}")
                cfg = st.root / "content" / "theme.yaml"
                text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
                if _re.search(r"^use:.*$", text, _re.M):
                    text = _re.sub(r"^use:.*$", f"use: {key}", text, count=1, flags=_re.M)
                else:
                    text = f"use: {key}\ntokens: {{}}\n" + text
                _wt(cfg, text)
                st.reload()
                return self.json({"ok": True,
                                  "message": f"the document is now set in "
                                             f"{Theme.named(key).label}. Rebuild to see it."})

            if path == "/api/assistant/set":
                # Written into content/doc.yaml, not into an environment
                # variable, because a setting that lives in a shell is lost the
                # moment somebody opens a new terminal and is invisible to the
                # next person to pick this up.
                from ..typography import rewrite_block
                d = data or {}
                cfg = st.root / "content" / "doc.yaml"
                text = cfg.read_text(encoding="utf-8")
                values = {}
                for k in ("gateway", "model", "key_helper"):
                    if k in d:
                        values[k] = str(d[k]).strip()
                if values:
                    text = rewrite_block(text, "assist", values)
                    from ..atomic import write_text as _wt
                    _wt(cfg, text)
                if "api_key" in d:
                    if not assist.set_api_key(str(d["api_key"] or "")):
                        return self.fail("the key could not be saved to the keychain")
                if "house_rules" in d:
                    body = str(d["house_rules"] or "").strip()
                    hp = assist.house_rules_path(st.root)
                    from ..atomic import write_text as _wt2
                    if body and body != assist.HOUSE_RULES.strip():
                        _wt2(hp, body + "\n")
                    elif hp.exists():
                        hp.unlink()          # back to the built-in set
                return self.json({"ok": True,
                                  "message": "saved. it takes effect on the next "
                                             "writing action",
                                  "restart_hint": bool(values)})

            if path == "/api/documents/open":
                # Re-point the whole console at another document. Everything
                # derived from a project lives on ConsoleState, so replacing it
                # is the switch: nothing else holds a stale root.
                from ..workspaces import is_document, remember
                target = Path((data or {}).get("path") or "").expanduser()
                if not is_document(target):
                    return self.fail(f"no document at {target}")
                Handler.state = ConsoleState(target, None)
                remember(target)
                return self.json({"ok": True, "path": str(target),
                                  "message": f"opened {target.name}"})

            if path == "/api/documents/forget":
                from ..workspaces import forget
                forget((data or {}).get("path") or "")
                return self.json({"ok": True,
                                  "message": "removed from the list. "
                                             "the folder itself is untouched"})

            if path == "/api/documents/new":
                from ..scaffold import Answers, Scaffold
                from ..workspaces import is_document, remember
                d = data or {}
                where = Path(d.get("path") or "").expanduser()
                if not where.name:
                    return self.fail("where should the new document go?")
                if is_document(where):
                    return self.fail(f"there is already a document at {where}")
                try:
                    answers = Answers(**{k: v for k, v in d.items()
                                         if k in Answers.__dataclass_fields__ and v})
                except (ValueError, TypeError) as e:
                    return self.fail(str(e))
                where.mkdir(parents=True, exist_ok=True)
                Scaffold(root=where, a=answers).build()
                Handler.state = ConsoleState(where, None)
                remember(where)
                return self.json({"ok": True, "path": str(where),
                                  "message": f"{answers.product} is ready"})

            if path == "/api/layout/set":
                from .. import layout
                try:
                    touched = layout.apply(st.root, **{
                        k: v for k, v in (data or {}).items() if v not in (None, "")})
                except ValueError as e:
                    return self.fail(str(e))
                st.reload()
                return self.json({
                    "ok": True, "layout": layout.read(st.root),
                    "message": (f"changed {', '.join(touched)}. rebuild to see it"
                                if touched else "nothing to change")})

            if path == "/api/edition/carry":
                from .. import editions
                pr = st.reload()
                sid = (data or {}).get("id") or ""
                if sid not in pr.sections and sid not in pr.listed:
                    return self.fail(f"no such section: {sid}")
                try:
                    msg = editions.carry(st.root, pr.profile.name, sid,
                                         bool((data or {}).get("carried")))
                except ValueError as e:
                    return self.fail(str(e))
                st.reload()
                return self.json({"ok": True, "message": msg})

            if path == "/api/edition/reset":
                from .. import editions
                pr = st.reload()
                msg = editions.reset(st.root, pr.profile.name)
                st.reload()
                return self.json({"ok": True, "message": msg})

            if path == "/api/fonts/verify":
                job = st.jobs.start("check the typefaces", lambda log: {
                    "results": Typography.load(st.root).verify(log=log)})
                return self.json({"ok": True, "job": job.id})

            if path == "/api/note":
                from ..notes import Notes
                n = Notes.load(st.root)
                try:
                    note = n.add(data.get("text", ""),
                                 section=data.get("section", ""),
                                 figure=data.get("figure", ""))
                except ValueError as e:
                    return self.fail(str(e))
                return self.json({"ok": True, "note": note.to_dict(),
                                  "message": "noted, and it will be dealt with "
                                             "on the next run"})

            if path == "/api/note/drop":
                from ..notes import Notes
                n = Notes.load(st.root)
                return self.json({"ok": n.drop(data.get("id", "")),
                                  "message": "removed"})

            if path == "/api/note/reopen":
                from ..notes import Notes
                n = Notes.load(st.root)
                return self.json({"ok": n.reopen(data.get("id", "")),
                                  "message": "back on the list"})

            if path == "/api/fix":
                # One press, everything the system can settle on its own.
                #
                # The pieces existed and each asked for a separate decision:
                # run the loop, then tidy the writing, then accept the tidy,
                # then look at the rules again. That is four deliberate acts to
                # clear findings the system already knew how to clear, and the
                # honest description of it is homework. What is genuinely a
                # person's call is handed back at the end, and only that.
                from .. import fixer

                def _fix(log):
                    return fixer.run(
                        st.root, st.reload, st.history, st.knowledge, log=log,
                        allow_crawl=bool((data or {}).get("crawl", True)),
                        capture=lambda sid, lg: st.capture_now(
                            st.screens_for_section(sid) or None, sid,
                            mask=True, sweep=False, log=lg))

                job = st.jobs.start("fix what can be fixed", _fix,
                                    detail="apply, tidy, re-check")
                return self.json({"ok": True, "job": job.id})

            if path == "/api/auto":
                # "Run everything" has to mean everything: photograph the whole
                # document, hold what it says against what came back, and fix
                # what can be fixed. It used to crawl only the screens a survey
                # thought would close a gap, so the run you reach for to find
                # out whether the product moved was the one run that would not
                # go and look.
                from .. import fixer
                d = data or {}

                def _everything(log):
                    return fixer.run(
                        st.root, st.reload, st.history, st.knowledge, log=log,
                        rounds=int(d.get("rounds") or 3),
                        allow_crawl=bool(d.get("crawl", True)),
                        full=bool(d.get("crawl", True)),
                        capture=lambda sid, lg: st.capture_now(
                            st.screens_for_section(sid) or None, sid,
                            mask=True, sweep=False, log=lg),
                        capture_all=lambda lg: st.capture_now(
                            None, None, mask=True, sweep=True, log=lg))

                job = st.jobs.start("run everything", _everything,
                                    detail="photograph every screen, then fix")
                return self.json({"ok": True, "job": job.id})

            if path == "/api/tidy/prepare":
                from ..tidy import Tidy
                job = st.jobs.start("fix the writing", lambda log: {
                    "count": len(Tidy(st.reload(), st.root).run(
                        data.get("sections") or None, log=log))},
                    detail="the whole document")
                return self.json({"ok": True, "job": job.id})

            if path == "/api/tidy/apply":
                from ..tidy import Tidy
                out = Tidy.apply(st.root, st.reload(), st.history,
                                 st.knowledge)
                st.reload()
                if out["failed"] and not out["written"]:
                    return self.fail("; ".join(out["failed"][:3]))
                msg = f"{len(out['written'])} section(s) written"
                if out["failed"]:
                    msg += f", {len(out['failed'])} could not be"
                return self.json({"ok": True, "message": msg, **out})

            if path == "/api/tidy/discard":
                from ..tidy import Tidy
                Tidy.clear(st.root)
                return self.json({"ok": True, "message": "the proposal was discarded"})

            if path == "/api/sweep":
                job = st.jobs.start("review the crawl", lambda log: {
                    "count": len(Sweep(st.reload(), st.root, st.decisions,
                                       st.knowledge).run(
                        data.get("sections") or None, log=log,
                        write_text=not data.get("images_only")))},
                    detail=data.get("sections") and ", ".join(data["sections"]) or "everything")
                return self.json({"ok": True, "job": job.id})

            if path == "/api/proposal/accept":
                pid = data.get("id", "")
                store = Sweep.load(st.root)
                pr = next((x for x in store["proposals"] if x.get("id") == pid), None)
                if pr is None:
                    return self.fail("no such proposal")
                st.reload()
                sec = st.project.sections.get(pr["section"])
                if pr["kind"] == "image":
                    src = st.root / "capture" / pr["run"] / "screenshots" / pr["asset"]
                    if not src.exists():
                        return self.fail(f"{pr['asset']} is no longer in that capture")
                    shutil.copyfile(src, st.project.asset_path(pr["asset"]))
                    st.project.assets.registry.setdefault(pr["asset"], {}).update(
                        {"source": str(src), "replaced_on": date.today().isoformat()})
                    st.project.assets.save()
                    st.history.record_asset(pr["asset"], f"{pr['run']}/{pr['asset']}",
                                            note="adopted from the crawl review")
                    refresh_derived(st.project.assets, pr["asset"],
                                    capture_dir=st.root / "capture" / pr["run"])
                    msg = f"{pr['asset']} updated"
                else:
                    if sec is None:
                        return self.fail("that section no longer exists")
                    try:
                        parsed = parse_section(pr["after"], sec.path)
                    except Exception as e:
                        return self.fail(f"will not write, it does not parse: {e}")
                    if parsed.id != sec.id:
                        return self.fail("will not write, the section id changed")
                    before = sec.path.read_text(encoding="utf-8")
                    sec.path.write_text(pr["after"], encoding="utf-8")
                    st.history.record(sec.id, sec.path, before, pr["after"],
                                      actor="assist", action="fill gaps",
                                      note="accepted from the crawl review")
                    st.knowledge.record_accepted(sec.id, "fill_todos", pr["after"])
                    msg = f"{sec.title} updated"
                Sweep.drop(st.root, pid)
                st.reload()
                return self.json({"ok": True, "message": msg})

            if path == "/api/proposal/reject":
                Sweep.drop(st.root, data.get("id", ""))
                return self.json({"ok": True, "message": "proposal discarded"})

            if path == "/api/decision/reopen":
                change = data.get("change") or {}
                old = st.decisions.reopen(change, data.get("note", ""))
                if old is None:
                    return self.fail("there is no decision on that change")
                return self.json({
                    "ok": True,
                    "message": f"reopened, it was {old.verdict} on "
                               f"{old.at.replace('T', ' ')}",
                    "was": old.to_dict()})

            if path == "/api/drift/apply":
                st.reload()
                _, run = st.drift()
                change = data.get("change") or {}
                sec = st.project.sections.get(change.get("section", ""))
                before = sec.path.read_text(encoding="utf-8") if sec else None
                msg = actions.apply_change(st.project, change, run)
                if sec and before is not None:
                    st.history.record(sec.id, sec.path, before,
                                      sec.path.read_text(encoding="utf-8"),
                                      actor="drift", action=change.get("change", "apply"),
                                      note=change.get("line", ""))
                st.reload()
                return self.json({"ok": True, "message": msg})

            if path == "/api/assist":
                task = data.get("task")
                if task not in assist.TASKS:
                    return self.fail(f"unknown task {task!r}")
                job = st.job_assist(data.get("section"), task)
                return self.json({"ok": True, "job": job.id})

            if path == "/api/assist/accept":
                st.reload()
                sec = st.project.sections.get(data.get("section", ""))
                if sec is None:
                    return self.fail("unknown section")
                text = data.get("markdown") or ""
                try:
                    parsed = parse_section(text, sec.path)
                except Exception as e:
                    return self.fail(f"will not write, it does not parse: {e}")
                if parsed.id != sec.id:
                    return self.fail("will not write, the section id changed")
                before = sec.path.read_text(encoding="utf-8")
                final = text if text.endswith(chr(10)) else text + chr(10)
                sec.path.write_text(final, encoding="utf-8")
                st.history.record(sec.id, sec.path, before, final, actor="assist",
                                  action=data.get("task", "assist"),
                                  note="accepted from the writing assistant")
                # what a person approved is the only real evidence of house style
                st.knowledge.record_accepted(sec.id, data.get("task", "assist"), final)
                st.knowledge.learn_vocabulary(st.reload())
                findings = [f for f in lint(st.project) if sec.id in (f.section or "")]
                return self.json({"ok": True, "message": f"{sec.title} updated",
                                  "lint": [{"rule": f.rule, "level": f.level,
                                            "message": f.message,
                                            "detail": f.detail,
                                            "remedy": _lint_remedy(f.rule)}
                                           for f in findings]})

            if path == "/api/publish":
                job = st.job_publish(
                    data.get("formats") or ["docx"],
                    (data.get("version") or "").strip() or None,
                    data.get("summary", ""), bool(data.get("force")))
                return self.json({"ok": True, "job": job.id})

            if path.startswith("/api/section/"):
                rest = path[len("/api/section/"):]
                sid, _, verb = rest.partition("/")
                return self._post_section(urllib.parse.unquote(sid), verb, data)

            return self.fail("not found", 404)
        except Exception as e:
            return self.fail(f"{type(e).__name__}: {e}", 500)

    def do_PUT(self):
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/api/section/"):
            sid = urllib.parse.unquote(url.path[len("/api/section/"):])
            return self._put_section(sid, self.body())
        return self.fail("not found", 404)

    # -- section endpoints ------------------------------------------------
    def _get_section(self, sid: str):
        st = self.state
        st.reload()
        sec = st.project.sections.get(sid)
        if not sec:
            return self.fail(f"no section {sid!r}", 404)
        rep, run = st.drift()
        changes = [st._change(c) for c in (rep.changes if rep else []) if c.section == sid]
        node = next((n for n in st.project.nodes if n.id == sid), None)
        site, screens = st.screens()
        inv = {}
        if run and (run / "inventory.json").exists():
            data = json.loads((run / "inventory.json").read_text())
            for s in sec.screens:
                if s in data.get("screens", {}):
                    inv[s] = data["screens"][s]
        return self.json({
            "id": sid, "number": node.number if node else "",
            "title": sec.title, "meta": sec.meta,
            "markdown": sec.to_markdown(),
            "path": str(sec.path.relative_to(st.root)) if sec.path else "",
            "screens": sec.screens,
            "screenshots": [{"name": n, "url": f"/files/content/assets/"
                             f"{'icons' if n.startswith('icon-') else 'screenshots'}/{n}"}
                            for n in sec.screenshots()],
            "drift": changes,
            "inventory": inv,
            "routes": [{"screen": s, **(st.routes().get(s) or {})} for s in sec.screens],
            "capture_run": run.name if run else None,
            # only this section's own captures: the full run belongs in the
            # image library, not repeated at the foot of every section
            "capture_shots": _section_captures(st.root, sec),
            "available_screens": [{"id": s.id, "title": s.title} for s in screens],
        })

    def _put_section(self, sid: str, data: dict):
        st = self.state
        st.reload()
        sec = st.project.sections.get(sid)
        if not sec:
            return self.fail(f"no section {sid!r}", 404)
        md = data.get("markdown")
        if md is None:
            return self.fail("nothing to save")
        try:
            parsed = parse_section(md, sec.path)
        except Exception as e:
            return self.fail(f"could not parse: {e}")
        if parsed.id != sid:
            return self.fail(
                f"the id in the front matter is {parsed.id!r} but this section is "
                f"{sid!r}. Rename it in content/doc.yaml instead.")
        before = sec.path.read_text(encoding="utf-8")
        text = md if md.endswith(chr(10)) else md + chr(10)
        sec.path.write_text(text, encoding="utf-8")
        st.history.record(sid, sec.path, before, text, actor="human",
                          action="edit", note="edited in the console")
        st.reload()
        findings = [f for f in lint(st.project) if sid in (f.section or "")]
        return self.json({"ok": True, "lint": [
            {"rule": f.rule, "level": f.level, "message": f.message, "detail": f.detail}
            for f in findings]})

    def _post_section(self, sid: str, verb: str, data: dict):
        st = self.state
        st.reload()
        sec = st.project.sections.get(sid)
        if not sec:
            return self.fail(f"no section {sid!r}", 404)

        if verb == "recapture":
            screens = data.get("screens") or sec.screens
            if not screens:
                return self.fail(
                    "this section is not bound to a screen. Add one under `screens:` "
                    "in its front matter and define it in content/screens.yaml.")
            job = st.job_capture(list(screens), section_id=sid,
                                 mask=data.get("mask", True),
                                 replay_steps=bool(data.get("replay_steps")))
            return self.json({"ok": True, "job": job.id})

        if verb == "verify":
            before = sec.path.read_text(encoding="utf-8")
            msg = actions.verify(sec, data.get("date"))
            st.history.record(sid, sec.path, before,
                              sec.path.read_text(encoding="utf-8"),
                              actor="human", action="verify", note=msg)
            return self.json({"ok": True, "message": msg})

        if verb == "meta":
            before = sec.path.read_text(encoding="utf-8")
            msg = actions.set_meta(sec, data.get("meta") or {})
            st.history.record(sid, sec.path, before,
                              sec.path.read_text(encoding="utf-8"),
                              actor="human", action="metadata", note=msg)
            return self.json({"ok": True, "message": msg})

        if verb == "restore":
            rev = data.get("revision")
            try:
                st.history.restore(sid, rev, sec.path, actor="human")
            except FileNotFoundError as e:
                return self.fail(str(e), 404)
            st.reload()
            return self.json({"ok": True, "message": f"restored revision {rev}"})

        if verb == "adopt-shot":
            run = st.capture_dir
            if not run:
                return self.fail("no capture available")
            src_name, dest_name = data.get("from"), data.get("to")
            src = run / "screenshots" / str(src_name)
            if not src.exists():
                return self.fail(f"{src_name} is not in capture {run.name}")
            dest = st.project.asset_path(str(dest_name))
            shutil.copyfile(src, dest)
            entry = st.project.assets.registry.setdefault(str(dest_name), {})
            entry.update({"source": str(src), "replaced_on": date.today().isoformat(),
                          "section": sid})
            st.project.assets.save()
            st.history.record_asset(str(dest_name), f"{run.name}/{src_name}",
                                    actor="capture",
                                    note=f"adopted into {sid} from {run.name}")
            r = refresh_derived(st.project.assets, str(dest_name), capture_dir=run)
            bits = []
            if r["captured"]:
                bits.append(f"refreshed {len(r['captured'])} inline element(s)")
            if r["recut"]:
                bits.append(f"re-cut {len(r['recut'])} from stored rectangles, "
                            f"please check those")
            tail = (", " + ", ".join(bits)) if bits else ""
            return self.json({"ok": True,
                              "message": f"{dest_name} replaced from {run.name}{tail}"})
        return self.fail(f"unknown action {verb!r}")

    # -- static and files -------------------------------------------------
    def _static(self, name: str):
        path = (STATIC / name).resolve()
        if not str(path).startswith(str(STATIC.resolve())) or not path.exists():
            return self.fail("not found", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            ctype = "text/javascript"      # modules are refused under text/plain
        self._send(200, path.read_bytes(), ctype)

    def _file(self, rel: str):
        root = self.state.root.resolve()
        path = (root / urllib.parse.unquote(rel)).resolve()
        if not str(path).startswith(str(root)) or not path.is_file():
            return self.fail("not found", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        extra = {}
        if path.suffix in (".docx", ".pdf"):
            extra["Content-Disposition"] = f'attachment; filename="{path.name}"'
        self._send(200, path.read_bytes(), ctype, extra)


def _same_bytes(a: Path, b: Path) -> bool:
    """Is this capture already the picture the document ships?

    Without this the answer is always no: a capture folder keeps its files
    after they are adopted, so a screen that has been settled goes on being
    reported as waiting, the button goes on offering to adopt it, and pressing
    it changes nothing anyone can see. The work happens, the panel does not
    move, and the reasonable conclusion is that the button is broken.
    """
    try:
        if not a.exists() or not b.exists():
            return False
        if a.stat().st_size != b.stat().st_size:
            return False
        return hashlib.sha256(a.read_bytes()).digest() == \
               hashlib.sha256(b.read_bytes()).digest()
    except OSError:
        return False


def _restore_id(text: str, want: str) -> str:
    """Put the section id back into front matter the writer rewrote."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return text
    head = re.sub(r"^id:.*$", f"id: {want}", m.group(1), count=1, flags=re.M)
    if "id:" not in head:
        head = f"id: {want}\n" + head
    return f"---\n{head}\n---\n" + text[m.end():]


def _section_captures(root: Path, sec) -> list[dict]:
    """Captures that differ from what this section currently ships."""
    from ..capture import merged_inventory
    wanted = set(sec.screenshots())
    for name in list(wanted):
        wanted.add("icon-" + name) if not name.startswith("icon-") else None
    merged, _ = merged_inventory(root / "capture")
    origins = merged.get("_runs", {})
    out, seen = [], set()
    for screen_id in sec.screens:
        run_name = origins.get(screen_id)
        if not run_name:
            continue
        folder = root / "capture" / run_name / "screenshots"
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.png")):
            if f.name in seen:
                continue
            # a capture folder holds only the screens of that run, but a run may
            # cover several screens, so match on what this section references
            if f.name in wanted or f.name.replace("icon-", "") in wanted:
                seen.add(f.name)
                sub = "icons" if f.name.startswith("icon-") else "screenshots"
                if _same_bytes(f, root / "content" / "assets" / sub / f.name):
                    continue                 # already adopted, nothing pending
                out.append({"name": f.name, "run": run_name,
                            "url": f"/files/capture/{run_name}/screenshots/{f.name}"})
    return out


def _all_images(root: Path) -> dict:
    """The whole picture library: what ships, and what is waiting in captures."""
    from ..capture import merged_inventory
    from ..project import Project

    proj = Project.load(root)
    used: dict[str, list[str]] = {}
    for node in proj.nodes:
        if node.section is None:
            continue
        for name in node.section.screenshots():
            used.setdefault(name, []).append(f"{node.number} {node.section.title}")
        for b in node.section.blocks:
            for it in b.items:
                for m in re.finditer(r"\[icon:([^\]\s]+)", str(it)):
                    used.setdefault(m.group(1), []).append(
                        f"{node.number} {node.section.title}")

    registry = proj.assets.registry
    shipping = []
    for name in proj.assets.all_names():
        meta = registry.get(name, {})
        path = proj.asset_path(name)
        sub = "icons" if name.startswith("icon-") else "screenshots"
        shipping.append({
            "name": name,
            "url": f"/files/content/assets/{sub}/{name}",
            "sections": sorted(set(used.get(name, []))),
            "orphan": name not in used,
            "from_capture": bool(meta.get("replaced_on")),
            "replaced_on": meta.get("replaced_on"),
            "kb": path.stat().st_size // 1024 if path.exists() else 0,
        })

    merged, _ = merged_inventory(root / "capture")
    origins = merged.get("_runs", {})
    pending, seen = [], set()
    for screen_id, run_name in origins.items():
        folder = root / "capture" / run_name / "screenshots"
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.png")):
            if f.name in seen:
                continue
            seen.add(f.name)
            sub = "icons" if f.name.startswith("icon-") else "screenshots"
            current = root / "content" / "assets" / sub / f.name
            adopted = _same_bytes(f, current)
            pending.append({
                "name": f.name, "run": run_name, "screen": screen_id,
                "url": f"/files/capture/{run_name}/screenshots/{f.name}",
                "in_document": f.name in {a["name"] for a in shipping},
                "adopted": adopted,
                "kb": f.stat().st_size // 1024,
            })
    return {"shipping": shipping, "pending": pending,
            "orphans": len([a for a in shipping if a["orphan"]])}


def _unchecked_pictures(st) -> list[dict]:
    proj = st.reload()
    reg = getattr(proj.assets, "registry", {}) or {}
    out = []
    for f in lint(proj):
        if f.rule not in ("ASSET-10", "ASSET-11"):
            continue
        name = f.message.split(":", 1)[-1].strip()
        out.append({
            "name": name,
            "section": f.section or "",
            "reachable": f.rule == "ASSET-10",
            "where": (reg.get(name) or {}).get("legacy_name", ""),
            "url": f"/files/content/assets/screenshots/{name}",
        })
    return out


def serve(root: Path, port: int = 8800, profile: str | None = None,
          open_browser: bool = True):
    from ..workspaces import remember
    Handler.state = ConsoleState(root, profile)
    remember(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"verba console  {url}")
    print(f"  project  {root}")
    print(f"  profile  {Handler.state.profile}")
    print("  ctrl-c to stop")
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0
