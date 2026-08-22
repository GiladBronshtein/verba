# Console guide

```bash
verba console            # opens http://127.0.0.1:8800
verba console --port 9000 --no-open
```

The console is the management interface, and the easiest way in. Everything it
does, the command line can do; nothing it does is exclusive to it.

<img src="https://raw.githubusercontent.com/GiladBronshtein/verba/main/docs/img/console-changes.png" alt="The review queue">

## The header is the process

Six numbered steps across the top, in the order the work actually happens.

| | Step | Done when |
|---|---|---|
| 1 | **Connect** | A system is chosen and reachable |
| 2 | **Capture** | Something has been photographed, and it is not stale |
| 3 | **Review** | Nothing outstanding between the crawl and the document |
| 4 | **Write** | Every section is verified |
| 5 | **Check** | The document breaks no rules |
| 6 | **Publish** | A version is ready to cut |

A completed step shows a tick instead of its number. The step with work in it is
marked, and the console opens there on arrival, so what you should be looking at
and what is marked can never disagree.

**Every step stays clickable.** Somebody who wants Publish on a Tuesday is
working, not lost. A stepper that locks the future is a wizard, and this is not a
wizard: it is a process with a memory of where you got to.

## The rail

Two groups below the steps.

**Look at** is things you go and look at, at any point, which have no place in a
sequence:

| | |
|---|---|
| **Document** | The document as it prints, live |
| **Screens** | The registry: what gets photographed and what is read off each one |
| **Images** | Every picture, where it is used, and whether anything has checked it |
| **Fields** | Every form, field and rule the crawl read |
| **Names** | What must never appear, every replacement made, and any unchecked picture |
| **History** | Every change ever made, with a diff and a restore |

**Set up** is set once and then left alone, which is why it stays folded shut:

| | |
|---|---|
| **Documents** | Every system you document, in one console |
| **Editions** | What each edition carries |
| **Design** | Palette, typeface, sheet, margins |
| **The writer** | Model, key, house rules |

At the foot of the rail is the fold control, which collapses it to icons. It sits
at the bottom because that is where a control you press once and forget belongs,
and because putting it at the top made it compete with the document switcher.

## The document switcher

Under the logo, above **Look at**. One console, every system you document.

```bash
verba console --root ~/docs/other-product   # or just switch in the header
```

Switching changes everything below it: sections, screens, captures, history.
Projects are remembered in `~/.verba/workspaces.json`.

## Screens

<img src="https://raw.githubusercontent.com/GiladBronshtein/verba/main/docs/img/console-screens.png" alt="Screens">

Each screen, how it is reached, what is read off it, and which sections it
evidences. It reports **screens that read nothing**, because a screen with a
photograph and no selectors looks like it is working right up until the day the
product changes and nothing notices.

## Names

<img src="https://raw.githubusercontent.com/GiladBronshtein/verba/main/docs/img/console-names.png" alt="Names">

Which real names must never appear, every replacement made so far, and any
picture nobody has checked. See [Masking and names](Masking-and-names).

## The writer

<img src="https://raw.githubusercontent.com/GiladBronshtein/verba/main/docs/img/console-writer.png" alt="The writer">

Built for someone who does not have an opinion about gateways. Paste a key, pick
a model from cards that say what each is for. The gateway settings fold away for
the people who have one. See [The writer](The-writer).

## A section, open

<img src="https://raw.githubusercontent.com/GiladBronshtein/verba/main/docs/img/console-section.png" alt="A section open">

The outline down the side, what is outstanding at the top, the source and its
preview together. You can recapture just this section's screens without leaving
the page, which is the fastest loop there is when you are writing.

## Fix what can be fixed

The button that runs [the loop](The-loop). It streams its log while it works and
the page updates when it finishes: the findings it settled are gone, the document
under **Look at** has the change, and **Publish** offers the new version.

If the loop is working, you should not have much of a "to fix" list to read.
Findings the system can settle are settled and not reported. What reaches you is
what a person owns.

## Light and dark

Both are real, and both are measured: every text colour is checked against the
background it is actually painted on. The toggle is in the header.

<img src="https://raw.githubusercontent.com/GiladBronshtein/verba/main/docs/img/console-changes-light.png" alt="Light mode">

## Two people at once

Two consoles cannot lose each other's work. Every write takes an advisory lock
and lands atomically, write then rename. This is tested by four concurrent
writers making eight hundred changes: before the locking, six hundred were lost
and three of the writers crashed reading a half written file.
