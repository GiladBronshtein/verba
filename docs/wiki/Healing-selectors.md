# Healing selectors

A crawl is a set of CSS selectors pointed at somebody else's markup. It will
break. The question is only whether it breaks loudly and repairably, or quietly.

```bash
verba capture --heal      # propose repairs while crawling
verba heal                # review them
verba heal --apply        # apply the ones you accept
```

## What happens

When a selector matches nothing, the crawler snapshots what the page **actually**
offers: the elements around where the match should have been, their classes,
their roles, their text. A model is asked for a replacement, given that snapshot
and the name of what was being looked for.

Then the important part: **the answer is verified in the live page before it is
believed.** A selector that matches nothing is never proposed. A model that
confidently invents `.account-table__header` gets its answer thrown away rather
than written into your registry.

## Why they are proposals

A selector that resolves is not necessarily the right one. `div > span` resolves
on every page ever written. The repair is offered with what it now matches, so
you can see that it found the table headers rather than the breadcrumb.

```
accounts.list / columns
  was:  table thead th            (0 matches)
  now:  [role=columnheader]       (6 matches: NAME, PLAN, REGION, STATUS, ...)
```

Six matches with recognisable text is a repair. One match reading "Home" is not.

## Incidents

A crawl that fails outright is recorded rather than printed and lost:

```bash
verba incidents
verba incidents --export
```

`--export` writes a brief a coding agent can act on: what was being done, what
happened, the page state at the time, and what has already been ruled out.
Failures are grouped by signature, so the same broken selector across twelve
screens is one incident rather than twelve.

## When healing will not help

Healing repairs **where to look**. It does not repair **how to get there**. If a
navigation step fails because a menu now needs a hover before the click, that is
a `steps:` change and a person makes it.

The tell is in `verba env verify`. If sign in works and the screens time out, the
steps are wrong. If sign in fails, nothing downstream means anything, which is
why sign in failure is deliberately loud rather than degrading into twenty
selector timeouts that each look like a broken screen.
