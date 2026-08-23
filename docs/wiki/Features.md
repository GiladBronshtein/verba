# Features

Everything Verba does, in one list. Each row links to the page that explains it
properly.

## Capture: getting the evidence

| | |
|---|---|
| **Crawl a live product** | Signs in, walks every screen in the registry, photographs each at a fixed 1440x768 viewport |
| **Read labels off the page** | Columns, fields, actions, tabs and terms, by CSS selector, per screen |
| **Screen registry** | One file saying how each screen is reached and what to read off it. See [Screens registry](Screens-registry) |
| **Step vocabulary** | `goto`, `click`, `click_text`, `wait_for`, `wait_ms`, `press`, `scroll`, `hover`, `expand_all`, `mask` |
| **Remembered routes** | Where each screen actually ended up last time, so a redirect is visible instead of silently photographing somewhere else |
| **Targeted recapture** | `--section` or `--screens`, so writing does not mean waiting for a full crawl |
| **Signed-out capture** | The sign-in page photographed in a clean context, because a signed-in browser redirects away from it |
| **Element crops** | Named crops by selector, for modals and panels |
| **Form inspection** | Every form, field, type and validation rule the crawl saw. See `verba forms` |
| **Screenshot fingerprinting** | A changed screen is flagged even when no label moved |
| **Live frame** | A rolling picture of what the crawler is looking at right now |
| **Timestamped runs** | One folder per crawl, kept, so any past run can be compared against |
| **Incidents** | Failures recorded and grouped by signature, with `--export` writing a brief an agent can act on |

## Sign in: including the ones a machine cannot finish

| | |
|---|---|
| **Form login** | Username and password, the password in the OS keychain |
| **Single sign on** | Sign in once in a real browser, session saved, no password anywhere |
| **Hand over for two-factor** | A browser opens, Verba fills what it knows, **you** finish: one-time code, phone prompt, hardware key. The crawl carries on by itself the moment the product is on screen. See [Connections and sign in](Connections-and-sign-in) |
| **Session reuse** | A hand over saves its session, so you are asked once and not again until it lapses |
| **Expired session recovery** | An expired session used to end the run. On a connection that can ask a person, it asks instead |
| **`--wait-for-signin`** | Force a hand over on any connection, for the morning a product starts asking for a code |
| **Loud sign-in failure** | Failing once beats twenty selector timeouts that each look like a broken screen |
| **Several connections** | Staging, production, whatever else, one active at a time |

## Safety: what it will not do

| | |
|---|---|
| **Never writes to your product** | Every non-GET request aborted in the browser after sign in. No flag disables it. See [The read only guarantee](The-read-only-guarantee) |
| **Writing steps refused** | `fill`, `select`, `check`, `upload` are permitted during sign in only |
| **Enter refused** | A key press can submit a focused form even when nothing was clicked |
| **Registry linted for commits** | Steps whose labels read like save, delete or publish are reported before a crawl runs |
| **The hand-over window closes at the product** | A person driving the browser is inside the sign-in phase, where writes are permitted. That ends the instant the product appears, before the crawl resumes |
| **Auditable exception** | Every request permitted during sign in is recorded in the run manifest |
| **Proved by test** | A real server, a real browser, a button wired to a `PUT`, and an assertion that the server got nothing |

## Privacy: keeping your customers out of the manual

| | |
|---|---|
| **Column masking** | Values under a table header replaced row by row, without knowing the names in advance |
| **Pattern masking** | Regular expressions for identifiers, with format specs so the placeholder is the same shape |
| **Literal masking** | Exact strings, for what no column or pattern reaches |
| **Stable placeholders** | One real value always becomes the same placeholder, across screens and across months |
| **Cross-screen grouping** | `as:` ties rules that name the same kind of thing, so two figures never contradict each other |
| **Masked before the shot** | Rewritten in the DOM, never submitted |
| **Production refusal** | `mask_required: true` refuses an unmasked crawl outright |
| **Unchecked-picture detection** | Pictures no crawl produced are found and reported |
| **Vision name check** | Every unchecked picture read against the exact list of names that must never appear |

## Drift: what changed

| | |
|---|---|
| **Label comparison** | What the crawl read against what your sections claim |
| **Renames as renames** | Matched rather than diffed as text, so a rename is not a deletion plus an addition |
| **Confidence** | High confidence differences apply on their own; judgement is handed back |
| **A queue, not a discovery** | `review/DRIFT.md` and the console's Review page |
| **Per-screen merge** | A targeted recrawl refreshes exactly what it captured and leaves the rest standing |
| **Knowledge** | What the crawl has learned about the product, accumulated across runs |
| **Survey** | What the document is missing, **before** you crawl, with `--crawl` to close exactly those gaps |

## Autonomy: the loop

| | |
|---|---|
| **One command** | `verba fix`, or `verba fix --full` to photograph everything first. See [The loop](The-loop) |
| **Twelve steps** | Notes, strays, gaps, writing, drift, pictures, unchecked pictures, evidence review, picture match, the decider, polish |
| **Measure and revert** | Every step applied, the rules counted again, anything that made it worse put straight back |
| **Invariants no rule measures** | A step may never lose a figure, lose a table block, cut a section below half its words, or delete a section, whatever the count says |
| **Tug-of-war detection** | Two steps writing the same file in two rounds running is reported, which a flat error count never could |
| **No rewrite may drop a figure** | Counting errors is not enough: a rewrite that quietly loses pictures looks like an improvement to a counter |
| **The decider** | A closed menu: repoint a figure, retire one, stop the crawl making a picture nothing shows, accept, or say plainly that this is yours |
| **Rules report only actionable work** | A finding no step can clear is not put in front of a person. Unused legacy pictures are inventory, listed under Images |
| **Retirement is honoured** | Marked on the asset, so the sweep cannot re-offer what the decider removed |
| **Reports only what you own** | If the loop works, its own debris is not your problem |
| **Safe unattended** | `verba capture && verba fix && verba build --pdf` on a schedule |
| **One implementation** | The console button and the command line call the same code, so they cannot disagree |

## The writer

| | |
|---|---|
| **Three routes to a model** | Your organisation's gateway, your own key, or the Claude Code CLI. See [The writer](The-writer) |
| **Gateway model discovery** | Asks the gateway what it carries rather than guessing at a list |
| **Other providers** | Through a translating gateway, GPT and others answer |
| **Key in the keychain** | Never in the project, never in a log |
| **Writes missing descriptions** | From evidence, leaving a marker rather than inventing a meaning |
| **Rewrites to house style** | Triggered by the findings that name a rewrite as their fix |
| **Drafts a section from a crawl** | For a section that has nothing yet |
| **Reads a section against the evidence** | Does what it says survive contact with the screen, and does it omit what the screen is for |
| **Looks at every picture** | Vision check against exact forbidden strings |
| **Checks the picture matches the section** | A Dashboard chapter illustrated by the accounts list passes every other rule |
| **Repairs broken selectors** | And verifies the answer in the live page before believing it. See [Healing selectors](Healing-selectors) |
| **Your product, in your words** | `content/system.md`, given to the model ahead of the writing rules |
| **Your own writing rules** | `content/house.md` replaces the built-in set entirely |
| **Everything is a proposal** | Measured, judged one at a time, recorded in History with its reasoning |

## The document

| | |
|---|---|
| **DOCX, PDF and HTML** | One content tree, three outputs |
| **Derived numbering** | No section file carries a number, so inserting one renumbers the body and the contents page together |
| **Typed blocks** | Headings, paragraphs, bullets, steps, callouts, figures, and five structured table kinds. See [Sections](Sections) |
| **Figures and details** | A caption makes it a numbered figure; no caption makes it an inline detail |
| **Cover and contents page** | Generated, with configurable depth |
| **Versioned releases** | `release --version v2` refuses to overwrite an output |
| **Derived changelog** | Built from what actually changed |

## Editions and design

| | |
|---|---|
| **Editions** | One tree, several documents. See [Editions](Editions) |
| **Variables** | `{{ operator.name }}` rather than naming a company, with unresolved variables failing the build |
| **Self-extending neutral edition** | The names it must not print are read off your other editions |
| **Five themes** | Each contrast measured rather than eyeballed. See [Themes and layout](Themes-and-layout) |
| **Four typefaces** | Each with its own body size, line height, tracking, and a DOCX fallback |
| **Page setup** | Paper, margins, header and footer bands, alignment, hyphenation, figure width, contents depth |
| **Judged before written** | A layout change is checked against the page you are choosing, all or nothing |
| **Recorded decisions** | `verba design` says what was decided and why |

## Rules

| | |
|---|---|
| **34 rules** | Structure, content, style, freshness, assets, profiles, design. See [Rule reference](Rule-reference) |
| **Rules held to a corpus** | Narrowing a rule prints exactly what stops being reported, on every known document, and fails CI until accepted in the same commit |
| **Three severities** | Errors fail the build; warnings and info do not |
| **Every rule carries its remedy** | And whether the system or a person clears it. A finding with nothing to press is a complaint |
| **Reviewable suppressions** | Only in `doc.yaml`, naming the rule and a reason |
| **Markers cannot ship** | `TODO:` fails the build, which is what makes it safe to tell the writer to leave one |

## Working

| | |
|---|---|
| **The console** | Six-step process header, contextual rail, live preview. See [Console guide](Console-guide) |
| **Light and dark** | Both measured against the surface each colour is actually painted on |
| **Several documents** | Every system you document, switchable in one console |
| **History** | Every change ever made, by whom, with a diff and a restore |
| **Verification that costs something** | Accepting a section records who accepted it and which crawl they read it against, and any machine change drops the badge |
| **An acceptance walk** | `verba accept` shows each unsigned section against its crawl evidence and what the two disagree about, one at a time. An empty answer is a skip, never a yes |
| **A ceiling on model calls** | Every run has a call limit and keeps a tally by task, written to a ledger, so a loop stuck in a circle stops rather than continuing until an invoice arrives |
| **Verdicts expire with their picture** | A picture judgement is fingerprinted against the image it judged, so a screen photographed again is looked at again rather than silenced by a stale ruling |
| **Notes** | `verba note "..."` and the loop does what you asked on its next run |
| **Locked atomic writes** | Two consoles cannot lose each other's work |
| **Start without a blank page** | `verba new` asks six questions and writes a project that builds |
| **A demo that ships** | A fictional product and a document built from it, in the repository |
