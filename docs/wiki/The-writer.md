# The writer

A model is configured once, and then used for everything it is actually good at,
not just prose. Nothing it produces is written without being measured, and
nothing it produces is written without being reversible.

## Setting it up

The console's **Writer** page is the intended route, and it is built for people
who do not have an opinion about gateways. Paste a key, pick a model from cards
that say what each is for, done. Everything an organisation needs and an
individual does not is folded away.

From a file, for a team that wants it pinned:

```yaml
# content/doc.yaml
assist:
  gateway: https://gateway.example.com
  model: claude-sonnet-5
  key_helper: ~/.config/gateway-key.sh
```

This is the durable place for it. An organisation that meters model usage
centrally needs every run to go through its gateway, and an environment variable
is set per shell and lost the moment somebody opens a new terminal.

## The three routes, tried in order

| Route | Needs | Can send images |
|---|---|---|
| **1. Your organisation's AI service** | A gateway URL, and a key or a key helper | yes |
| **2. Your own key** | Pasted into the console, kept in the OS keychain | yes |
| **3. The Claude Code CLI** | Nothing. It is already signed in | no |

The console names whichever one it is using, so "which model is this actually
running on" is never a guess.

Route 3 is the zero configuration path and it is genuinely useful, but it cannot
be given an image. The picture checks need route 1 or route 2.

## Choosing a model

Verba asks a configured gateway **what it actually carries** and offers you
those, rather than guessing at a list:

```
12 models offered by this gateway
```

On a real deployment that included GPT variants alongside the Claude models, and
they answer, because the gateway translates. Verba speaks the Anthropic Messages
API; a gateway that translates for other providers means the model list is your
organisation's business rather than this tool's.

With no gateway you get three cards:

| Model | For |
|---|---|
| Claude Sonnet 5 | The default. Fast, and good at following house rules |
| Claude Opus 5 | Slower and stronger. Worth it for a first draft of a hard section |
| Claude Haiku 4.5 | Quickest and cheapest. Fine for filling in short descriptions |

Free text still works, because a list baked into a released tool is out of date
the week after it ships.

## Where the key lives

In the OS keychain, under the service `verba-api-key`. Never in the project,
never in a log, never in this repository. Same mechanism the crawl passwords
use.

`ANTHROPIC_BASE_URL` is deliberately **not** consulted, even though it is the
obvious variable. It is set per shell and per Claude Code session, and can point
somewhere the operator did not choose for this pipeline. Use `VERBA_GATEWAY` to
be explicit.

| Variable | Sets |
|---|---|
| `VERBA_GATEWAY` | The gateway base URL |
| `VERBA_KEY_HELPER` | A script that prints the gateway key |
| `VERBA_MODEL` | The model id |
| `ANTHROPIC_API_KEY` | A direct key, checked before the keychain |
| `VERBA_CLAUDE` | Path to the `claude` executable, if it is not on PATH |

## What it is asked to do

| Task | What it gets |
|---|---|
| Rewrite to house style | The section, the rules, and the findings that named a rewrite |
| Apply the crawl differences | The section and the drift |
| Write the missing descriptions | The evidence, and permission to leave a marker |
| Draft this section from the crawl | The evidence, and nothing else |
| Review and report | The section and the evidence. Explicitly told not to rewrite |
| Look at this picture | The image, and the exact names that must never appear |
| Does this picture match | The image and the section it illustrates |
| Decide | A closed menu of three moves |

## House rules

The craft rules are the same everywhere and ship built in. What your product is,
what its words mean, and which of two readings is right are things only your
project can say, and they come from `content/system.md`, which is put **in
front** of the rules because it is the part the model has no other way of
knowing.

A project may replace the writing rules entirely with `content/house.md`. The
built in set is one house's, and a tool that documents anybody's product cannot
also insist on one company's punctuation. A team that documents route paths on
purpose had no way to say so and watched the writer undo them every pass. Now
they can.

## The guardrails

Every model action is measured like any other change, judged one at a time, and
recorded in History with its reasoning.

- **No rewrite may drop a figure.** A model asked about labels is not being asked
  whether the section should have pictures.
- **A step that raises the rule count is reverted.**
- **The writer leaves a marker rather than inventing a meaning** the evidence does
  not support, and that marker fails the build so it can never ship.
- **The decider has three moves and no fourth.**

## What is sent

Only what the task needs: the section text, the crawl evidence for it, and for
the picture checks the image. Your whole project is never uploaded. With route 3
nothing leaves the machine's existing Claude Code session at all.
