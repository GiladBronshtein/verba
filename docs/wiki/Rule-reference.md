# Rule reference

`verba lint` runs the content rules. Every rule carries what would clear it, and
whether the system can do that or a person must.

```bash
verba lint                    # everything
verba lint --level error      # only what blocks a build
verba lint --strict           # exit non-zero on errors, for CI
```

## Severities

| | |
|---|---|
| **ERROR** | Fails the build. The document does not ship |
| **WARN** | Worth a look. Does not block |
| **INFO** | Reported, never blocking |

An ERROR is a claim that this document would be wrong or unsafe to publish, so
the list of them is deliberately short and deliberately absolute.

## Suppressing a rule

Only through `content/doc.yaml`, and only with a recorded reason:

```yaml
lint:
  allow:
    - rule: STYLE-02
      section: api.endpoints
      why: This chapter documents route paths on purpose.
    - rule: ASSET-03
      match: shared-empty-state.png
      why: The empty state is genuinely the same screen in both chapters.
```

An entry names the rule and then either a `section` (matched as a substring of
the section id) or a `match` (matched against the finding's detail). The list is
itself reviewable, which is the point. A suppression that nobody can
find is a rule that was never really enforced.

If you disagree with the writing rules as a whole rather than in one place, do
not suppress them one at a time: replace them. `content/house.md` overrides the
built in set entirely. See [The writer](The-writer).

## Every rule

| Rule | Severity | What it means | What clears it | Who |
|---|---|---|---|---|
| `ASSET-01` | ERROR | The image the section refers to is not in the library. | Recapture this screen | the system |
| `ASSET-02` | ERROR | The same image is used for two figures in a row. | Capture this screen | the system |
| `ASSET-03` | ERROR | Two sections show the same picture, so one of them is illustrated by a screen it does not describe. Either give the second section a screen of its own in content/screens.yaml, or take its figure out and let the text stand alone. Which of the two is a judgement about the document, so nothing decides it for you. | Capture this screen | the system |
| `ASSET-04` | ERROR | The same picture is stored under two names. Usually one of them belongs to a screen that redirected, so its capture is a picture of somewhere else. Remove the one nothing uses. | Show it in Images | the system |
| `ASSET-05` | INFO | Nothing in the document uses this picture. Put it in a section or delete it. | Show it in Images | the system |
| `ASSET-06` | INFO | The section maps to a screen and shows no picture of it. | Capture this screen | the system |
| `ASSET-07` | WARN | The screen captured under a name this section does not use. | Adopt the captured version | the system |
| `ASSET-08` | ERROR | Give it a caption only if it really is a picture of a screen; otherwise leave it captionless and it renders as a detail. | Edit the section | you |
| `ASSET-09` | ERROR | The capture came back blank. | Recapture this screen | the system |
| `ASSET-10` | WARN | This picture never went through masking, so nothing has checked whether it shows a real customer's account. Photographing the screen again puts it through the masking rules and settles it. | Photograph this screen properly | the system |
| `ASSET-11` | WARN | Nothing has checked this picture for real names, and no screen in the registry produces it, so photographing the system will never replace it. Someone added it by hand, or it came out of an older document. Either register a screen that captures this view, or take the picture out. Nothing can decide that for you. | Open the section that shows it | you |
| `ASSET-12` | WARN | The picture is of a different part of the product from the one this section describes. Either point the section at a screen that shows what it is about, or take the figure out and let the text stand. | Open the section that shows it | you |
| `CONTENT-01` | WARN | The section is empty. | Draft from the crawl | the system |
| `CONTENT-02` | ERROR | It writes what the crawl can answer and offers to remove anything that was never a control. | Ask the writer to fill these in | the system |
| `CONTENT-03` | ERROR | A placeholder or a tooltip is being documented as though it were the name of a control. The writer offers to remove them. | Ask the writer to tidy these | the system |
| `DESIGN-01` | WARN | The mark has no drawn equivalent, so it prints as an emoji. | Add a drawn mark | you |
| `DESIGN-02` | WARN | Console text below the type floor. | Edit app.css | you |
| `DESIGN-03` | WARN | A browser dialog is used. | Replace with modal() | you |
| `DESIGN-04` | WARN | content/theme.yaml names a palette that is not in this project or in the engine, so the document is rendering in the default. Nothing is broken and nothing was lost: put the file back under themes/, or choose another with verba themes --use. | Pick a theme that exists | you |
| `FRESH-01` | WARN | Nobody has checked this against the live product. | Mark verified | you |
| `FRESH-02` | WARN | The check is old. | Recapture this screen | the system |
| `FRESH-03` | WARN | The check is old. | Recapture this screen | the system |
| `FRESH-04` | WARN | These sections were marked verified before signatures were recorded, so the badge does not say who checked them or what they checked them against. Nothing automatic can close this, and that is the point of it: run verba accept and the count comes down as you read. Each signature is dropped again the next time anything but a person changes that section. | Read and sign them | you |
| `GENERIC-01` | ERROR | A customer is named in the tenant-neutral edition. | Edit the section | you |
| `META-01` | WARN | The status is not one we use. | Edit the section | you |
| `PROFILE-01` | ERROR | A profile variable did not resolve. | Edit the section | you |
| `PROFILE-02` | ERROR | A profile variable was left unresolved in the text. | Edit the section | you |
| `STRUCT-01` | ERROR | The outline names a file that does not exist. | Create the section | you |
| `STRUCT-02` | WARN | The file exists but ships nowhere. | Add it to the outline | you |
| `STYLE-01` | ERROR | An em dash is not permitted. | Rewrite to house style | the system |
| `STYLE-02` | ERROR | A route or address in prose. | Rewrite to house style | the system |
| `STYLE-03` | WARN | Protocol detail that is not visible in the interface. | Rewrite to house style | the system |
| `STYLE-04` | WARN | An icon is named in prose but not shown. | Rewrite to house style | the system |
| `STYLE-05` | INFO | Prose that should be bullets. | Rewrite to house style | the system |
| `STYLE-06` | ERROR | The text names one account's value where it should name the feature. The reader is looking at a different account. | Rewrite to house style | the system |

## The ones worth understanding

**`FRESH-04`, verified with nothing behind it.** The rule that exists because
the other freshness rules could not tell an acceptance from a stamp. It reports
**once for the whole document**, with a count, not once per section: every
section marked verified before signatures were recorded is in the same state
for the same reason, and thirty-eight identical rows is a list nobody shortens
by reading it. `verba accept` shortens it. See [Sections](Sections).

**Changing a rule is itself checked.** `tools/rule_baseline.py` holds every
rule against a corpus of known documents and prints exactly what a change stops
and starts reporting. CI fails until the new state is accepted in the same
commit, so narrowing a rule to empty a list is a thing a reviewer sees.

**A rule fires only when something can act on it.** `ASSET-05` reports an
unreferenced picture only when a screen produces it, because a legacy import no
crawl can reach is inventory rather than work. `ASSET-06` stays quiet when the
section's screen produces only pictures another section already shows, because
adopting one would make a duplicate. `ASSET-07` stays quiet when the picture
check has ruled that capture is of a different screen. Each of those used to
report work whose only available fix was a worse finding.

**`ASSET-03`, two sections showing the same picture.** An error rather than a
warning, because it means one of the two sections is illustrated by a screen it
does not describe, and a reader trusts a picture more than a paragraph. Which of
the two should keep it is a judgement about the document, so nothing decides it
for you.

**`ASSET-10` and `ASSET-11`, pictures nobody has checked.** `ASSET-10` is a
picture that never went through masking, so nothing has confirmed it does not
show a real customer. `ASSET-11` is worse: nothing produced it and no registered
screen ever will, so photographing the system cannot fix it. Someone added it by
hand, or it came out of an older document.

**`ASSET-12`, the picture is of the wrong thing.** A chapter called Dashboard
Overview illustrated by the accounts list passes every other rule in this table.
Fed from a vision check, held in `review/picture-match.json`.

**`CONTENT-02`, a TODO marker.** The writer is told to leave one rather than
invent a meaning the evidence does not support. This rule is what makes that
instruction safe to give: the marker cannot ship.

**`GENERIC-01`, a customer named in the neutral edition.** The names it checks
for are read off your other editions rather than configured, so it extends
itself when you add a customer edition.

**`STYLE-06`, one account's value where the feature belongs.** "Set the region to
eu-west-1" is true of the account that happened to be open when the screenshot
was taken. The reader is looking at a different account.

**`DESIGN-02` and `DESIGN-03`** are about the console, not your document. They
hold this project to its own type floor and to using its own dialogs rather than
the browser's.
