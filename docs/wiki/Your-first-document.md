# Your first document

## Two minutes

```bash
verba new my-docs
cd my-docs
verba build --pdf
verba console
```

`verba new` asks six questions, every one with a default, and then writes a
project that builds. Not a skeleton that needs three more steps: an actual PDF,
with a cover, a contents page and a first section. The first thing you meet
should be a document, not an error about a rule you have not read yet.

## What the six questions are

| Question | What it sets | If you press Return |
|---|---|---|
| What is the product called? | `product.name`, and the cover | My Product |
| Who makes it? | `product.vendor` | the same as the product |
| What does it do, in one sentence? | the opening of `content/system.md` | left blank |
| Where does it live? | `site.base_url`, and the first connection | example.com, fill it in later |
| How do you sign in? | `form`, `sso` or `none` | form, and it then asks which account |
| Which look? | one of five themes | slate |

None of it is permanent. Every answer is a line in a YAML file you can edit,
and the console has a page for each.

## What you get

```
my-docs/
  content/
    doc.yaml            the outline, and therefore the numbering
    system.md           what your product is, in your words
    screens.yaml        how to reach each screen, what to read off it
    masking.yaml        what must never appear in a screenshot
    environments.yaml   which system to talk to, and how to get in
    theme.yaml          which palette
    typography.yaml     the sheet, margins, and how text is set
    sections/           one Markdown file per section
    assets/             pictures, with a registry
    profiles/           editions
  capture/              one folder per crawl, timestamped
  review/               the queue, decisions, and what the crawl learned
  dist/                 what you publish
  .verba/               history, sessions, locks
```

## Pointing it at your product

Two files matter. `content/environments.yaml` says which system and how to sign
in. `content/screens.yaml` says which screens to visit.

```bash
verba env verify        # can it reach the system, and get in
verba env password prod # store a password in the OS keychain
verba capture           # crawl
verba status            # what that changed
```

See [Connections and sign in](Connections-and-sign-in) and
[Screens registry](Screens-registry) for the detail.

## Writing something

You can write sections by hand. Most people start by letting the crawl draft
them and then editing:

```bash
verba capture
verba fix
```

`fix` drafts what is empty, fills what is missing, applies the differences it
can justify, adopts fresh pictures, and rewrites what the rules object to. It
then reports only what a person has to decide.

## Telling it what your product is

The one thing no crawl can learn is what anything is for. That goes in
`content/system.md`, once, in your words, and is given to the writer ahead of
every task:

```markdown
## Vocabulary
- **Account** : a customer workspace. Never "tenant" in user facing text.

## Rules that are true of this system
- Event delivery falls back to the workspace setting when an account has none.
```

Without it the writer describes buttons. With it the writer describes the
product. It is the highest value twenty minutes in the whole setup.

## Publishing

```bash
verba build --pdf
verba release --version v1
```

`release` refuses to overwrite an output that already exists. Versions are
cheap; a silently replaced deliverable is not.
