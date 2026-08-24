# Sections

One Markdown file per section, with YAML front matter. The body uses a small,
fixed set of conventions that map one to one onto renderable blocks, so the same
source produces DOCX, PDF, HTML and a drift checkable inventory.

````markdown
---
id: accounts.list
title: Accounts list
status: verified
screens: [accounts.list]
last_verified: 2026-08-22
---

Every account in the workspace, with the controls that filter it.

```columns
- column: NAME
  description: The account name, as the customer set it.
- column: PLAN
  description: The plan this account is billed on.
```

![The accounts list](accounts-list-1.png)
````

## Front matter

| Key | Meaning |
|---|---|
| `id` | Must match the id in the outline |
| `title` | The heading, without a number |
| `status` | `draft`, `review`, `verified` or `stale` |
| `screens` | Which registry screens evidence this section. Drives drift |
| `last_verified` | The date a person last checked this against the product |
| `verified_by` | Who accepted it. Written by `verba section verify`, never by hand |
| `verified_against` | The capture they accepted it against |
| `profiles` | Which editions carry it. See [Editions](Editions) |
| `icon` | A drawn mark, if the theme has one |

**No section file carries a number.** Numbering is derived from the outline in
`content/doc.yaml`, so inserting a section renumbers the body and the contents
page together, and cross references never rot.

## Block syntax

| You write | You get |
|---|---|
| `#### Heading` | A heading, at a level relative to the section |
| a plain paragraph | A paragraph |
| `- item` | Bullets |
| `1. item` | Numbered steps |
| `> [!Note] text` | A callout box |
| `![caption](file.png)` | A numbered figure |
| `![caption](file.png =14cm)` | The same, at that width |
| ` ```fields ` | A field table |
| ` ```actions ` | An actions table |
| ` ```columns ` | A columns table |
| ` ```tabs ` | A tabs table |
| ` ```terms ` | A glossary table |

The five fenced kinds take a YAML list.

````yaml
```fields
- field: Region
  type: choice
  required: true
  description: Where events for this account are delivered.
```
````

````yaml
```actions
- action: Suspend
  description: Stops delivery without deleting the account.
```
````

## Why the structured blocks matter

They are what drift compares. A screen declares `columns: "table thead th"`, the
crawl reads the headers off the page, and those are held against the `column:`
values in your section. A rename is detected as a rename, not as a deletion plus
an addition, because the two lists are matched rather than diffed as text.

Prose is not compared, so anything you write as a paragraph is invisible to
drift. That is a reason to use the block kinds for anything the interface
actually shows.

## Figures

An image is a figure when it has a caption, and a detail when it does not.
Figures are numbered and listed; details sit inline. That distinction is a rule
(`ASSET-08`), because a screenshot with no caption in a list of figures reads as
a mistake to every reader.

Two rules protect figures from each other: the same picture may not appear in two
sections (`ASSET-03`), and may not appear twice in a row (`ASSET-02`). Both are
errors, because a reused screenshot means one of the two sections is illustrated
by a screen it does not describe.

## TODO markers

The writer is told to leave `TODO: describe this.` rather than invent a purpose
the evidence does not support. That marker is refused at build time
(`CONTENT-02`), so it can never ship. Confident, fluent and wrong is the worst
failure a documentation tool has, and this is the mechanism that prevents it.

## What verified means

`status: verified` on its own is a string somebody typed. The rules treat it as
a claim, and `FRESH-04` asks the claim for its evidence: a name, and the crawl
that person read the section against.

```bash
verba accept                                        # walk everything unsigned
verba section verify accounts.list --who "your name"   # or one at a time
```

`verba accept` puts each section in front of you with what the crawl saw behind
it and where the two disagree, so signing is reading rather than typing.

That writes `verified_by` and `verified_against`. **Any change with a machine
behind it drops the section back to `review`**, at the one point in the engine
every machine write passes through, because a person verified the section they
read and not the one a model rewrote after them.

## Who signed it

A signature names its signer. The loop signs what it has checked, and a person
signs what they have read:

```yaml
status: verified
verified_by: the loop (claude-sonnet-5)
verified_against: content/system.md
verified_kind: loop
```

The loop can check a section two ways. One bound to a screen is read against
the crawl of that screen. One bound to no screen, an introduction or a page of
key terms, has no crawl to be read against, so it is read against
`content/system.md`, the description of the product you wrote: does this
contradict it, does it invent a feature it does not support, does it use the
vocabulary it forbids. On the first real document that found a chapter calling
the product by a name that does not exist.

`FRESH-04` reports a claim with no signer at all. `FRESH-05` reports, as
information rather than a fault, the sections only the loop has read, so you
can still find them. A person's signature outranks the loop's and is never
written over; `verba accept` upgrades one.

The rule this replaced said only a person may sign. That fixed the wrong half
of the problem. The fault was a document claiming thirty-eight human checks
that nobody had made, which is a lie about the signer, not a fact about
automation, and requiring a person put a human bottleneck into a system built
not to need one.

When a section loses its signature the console says **why**: how many changes
were made since you last signed it, by which step, and what each one did, with
a button that opens the diff of the first one. "review" on its own tells nobody
anything, and the only control on the page marks it verified, which is the one
thing a reader cannot responsibly press without knowing what changed.

This is deliberately expensive. On the first real document built with this
engine, all thirty-eight sections said verified, thirty-five carried the same
bulk date, and History recorded that 2.8% of the changes to that document had a
human behind them. The rule that should have caught it stayed quiet because a
date was present and nothing asked where the date came from.

## Editing

By hand, in any editor. Or in the console, which shows the outline, what is
outstanding, the source and a live preview side by side, and lets you recapture
just this section's screens without leaving the page.

```bash
verba section show accounts.list
verba section set accounts.list status verified
verba section new accounts.exports
```
