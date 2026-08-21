"""Settle everything the system can settle, and hand back only what it cannot.

Each piece of this already worked and each asked for a separate decision: run
the loop, then tidy the writing, then accept the tidy, then look at the rules
again, then notice that the one remaining finding wants a photograph and go and
take it. Five deliberate acts to clear findings the system already knew how to
clear, and the honest description of that is homework.

The last step is the one that matters. A rule finding carries the action that
clears it, and some of those actions are `capture`: this picture is used twice,
this section has a screen and no picture of it. Refusing to crawl meant those
findings could never clear on their own, however obvious the fix, so the loop
always ended by handing a person a job it could have done itself.

It still will not decide anything a person owns, and it still measures after
every step and puts back whatever made the document worse.
"""
from __future__ import annotations

from pathlib import Path

from .lint import lint, remedy, summarise


def _needs_capture(project) -> list[str]:
    """Sections whose open findings would be cleared by photographing them.

    A finding does not always belong to one section. "This image is used by two
    sections" is about the pair, so it names neither in `section` and both in
    its detail: reading only `section` skipped exactly the finding most likely
    to want a fresh photograph, and the loop handed back a job it could do.
    """
    known = set(project.sections)
    out: list[str] = []
    for f in lint(project):
        if f.level != "error" or remedy(f.rule).get("action") != "capture":
            continue
        if f.section and f.section in known:
            out.append(f.section)
            continue
        # Otherwise take whatever section ids the finding mentions. Longest
        # first, so `a.b.c` is not matched as `a.b`.
        blob = f"{f.section} {getattr(f, 'detail', '') or ''}"
        for sid in sorted(known, key=len, reverse=True):
            if sid in blob:
                out.append(sid)
                # Take the match out of the text. `dashboard-overview` is a
                # prefix of `dashboard-overview.main-dashboard`, so leaving it
                # in would report the chapter as needing a photograph it does
                # not have.
                blob = blob.replace(sid, " ")
    return sorted(set(out))


def run(root: Path | str, load, history, knowledge, log=None,
        rounds: int = 2, allow_crawl: bool = True, capture=None) -> dict:
    """Fix what can be fixed. `load` returns a freshly read project.

    `capture(section_id, log)` is how a photograph gets taken. It is passed in
    rather than imported, because the console and the command line each already
    know how to crawl and neither should learn the other's way of doing it.
    """
    emit = log or (lambda *_: None)
    root = Path(root)
    from .auto import Auto
    from .tidy import Tidy

    before = summarise(lint(load()))

    def settle(crawl: bool):
        Auto(root).run(rounds=rounds, crawl=crawl, log=emit)

    settle(crawl=False)

    emit("")
    emit("fixing the writing the crawl cannot settle")
    if Tidy(load(), root).run(None, log=emit):
        out = Tidy.apply(root, load(), history, knowledge, log=emit)
        emit(f"  {len(out.get('written', []))} section(s) rewritten")
    else:
        emit("  nothing to do")

    crawled: list[str] = []
    wanted = _needs_capture(load())
    if wanted and allow_crawl and capture is not None:
        from .environments import Environments
        env = Environments.load(root).current()
        ready, why = env.ready(root) if env is not None else (False, "no connection")
        emit("")
        if ready:
            emit(f"{len(wanted)} finding(s) want a fresh photograph. taking it.")
            for sid in wanted:
                emit(f"  recapturing {sid}")
                try:
                    capture(sid, emit)
                    crawled.append(sid)
                except Exception as e:                       # a crawl can fail
                    emit(f"    could not: {e}")
            if crawled:
                emit("")
                emit("applying what the new capture settles")
                settle(crawl=False)
        else:
            emit(f"{len(wanted)} finding(s) want a fresh photograph, "
                 f"but the connection is not ready: {why}")

    after = summarise(lint(load()))
    left = [f for f in lint(load()) if f.level == "error"]
    emit("")
    emit(f"findings: {before['error']} error to {after['error']} error, "
         f"{before['warning']} warning to {after['warning']} warning")
    if left:
        emit("")
        emit("what is left needs a person:")
        for f in left:
            emit(f"  {f.rule}  {f.section}: {f.message}")
            r = remedy(f.rule)
            # The label is a button caption. What a person standing here needs
            # is the reason and the choice, so print that too.
            if r.get("why"):
                import textwrap as _tw
                for line in _tw.wrap(r["why"], 72):
                    emit(f"      {line}")
            if r.get("label"):
                emit(f"      -> {r['label']}")
    return {"before": before, "after": after, "recaptured": crawled,
            "left": [{"rule": f.rule, "section": f.section, "message": f.message}
                     for f in left]}
