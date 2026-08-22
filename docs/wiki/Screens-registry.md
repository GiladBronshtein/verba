# Screens registry

`content/screens.yaml` answers two questions for every documented screen: how to
reach it, and what to read off it. Everything else in Verba follows from those
two answers.

```yaml
site:
  base_url: https://app.example.com
  login:
    - goto: /login
    - wait_for: "input"
    - fill: 'input[type="email"]'
      value: "${VERBA_USER}"
    - fill: 'input[type="password"]'
      value: "${VERBA_PASSWORD}"
    - click: 'button[type="submit"]'
    - wait_ms: 600
  readonly:
    allow_post_matching: []

defaults: &table
  columns: "table thead th"
  actions: "main button"

screens:
  - id: accounts.list
    title: Accounts
    sections: [accounts.list]
    shot: accounts-list-1.png
    steps:
      - goto: /accounts
      - wait_for: "table"
    extract:
      <<: *table
      filters: ".seg button"
```

## A screen

| Key | Meaning |
|---|---|
| `id` | Stable name. Used by `verba capture --section`, by the registry, and in every report |
| `title` | What to call it in the console |
| `sections` | Which sections this screen evidences. This is what binds drift to your writing |
| `shot` | The filename its photograph lands under |
| `steps` | How to get there, from signed in |
| `extract` | What to read off the page, as CSS selectors |
| `signed_out` | Captured before sign in, for screens that redirect away once you are in |
| `crop` | A selector to crop to, for modals and panels |

## Steps

Only verbs that can read are allowed outside sign in.

| Verb | Does |
|---|---|
| `goto: /path` | Navigate, relative to `base_url` or absolute |
| `click: "sel"` | Click a selector |
| `click_text: "Label"` | Click by visible text |
| `wait_for: "sel"` | Wait for a selector |
| `wait_ms: 600` | Wait |
| `press: "Escape"` | A key. `Enter` is refused outside sign in |
| `scroll: 400` | Wheel |
| `hover: "sel"` | Hover, for menus that open on it |
| `expand_all: "sel"` | Click every match, for accordions |
| `mask: "sel"` | Blank a region before the photograph |

`fill`, `select`, `check` and `upload` exist but are **permitted during sign in
only**. Outside it they are refused, not warned about:

```
step 'fill' types into the page and is only permitted during sign-in.
Remove it from the screen definition.
```

A `click` whose selector or text reads like a commit (save, submit, delete,
archive, publish, confirm, and a dozen more) is reported before the crawl runs:

```
accounts.detail: step clicks 'button.save', which reads like a commit (save).
The network guard will block any write it attempts, but the step should be removed.
```

Add `opens_form: true` to a step that opens a form rather than committing one,
and the advisory goes away. The network guard does not: see
[The read only guarantee](The-read-only-guarantee).

## Extract

Each key becomes a list of strings read off the page, and each has a block kind
it is compared against.

| Extract key | Compared against | Typical selector |
|---|---|---|
| `columns` | ` ```columns ` blocks | `table thead th` |
| `fields` | ` ```fields ` blocks | `form label, .field .label` |
| `actions` | ` ```actions ` blocks | `main button` |
| `tabs` | ` ```tabs ` blocks | `[role=tab]` |
| `terms` | ` ```terms ` blocks | a glossary list |

Anything else you extract is kept as evidence and shown in the console, but is
not compared, because there is no block kind that declares it.

**A screen that extracts nothing can never detect a change.** The console
reports those explicitly, because a screen with a photograph and no selectors
looks like it is working right up until the day the product changes.

The YAML merge key (`<<: *table`) is ordinary YAML and worth using: most screens
in one product share their table and button selectors, and a single anchor means
one edit when the markup changes.

## Routes

`verba routes` prints the remembered address of every screen. Verba records
where each screen actually ended up, so a redirect is visible rather than
silently producing a photograph of somewhere else. Two screens whose
photographs are byte identical is a rule (`ASSET-04`), and a redirect is usually
the reason.

## Recapturing one screen

```bash
verba capture --section accounts.list
```

Photographs only the screens that section uses. The console does the same from
inside a section, which is the fastest loop when you are writing.
