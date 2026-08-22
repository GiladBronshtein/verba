# Masking and names

Screenshots are the part of a manual that leaks. A paragraph is written by
someone who was thinking about what to say; a screenshot shows whatever happened
to be on the screen, including three real customers and an account identifier.

Verba rewrites real values in the page's DOM immediately before each screenshot,
and in the labels read off the page afterwards. Nothing is ever submitted: the
substitution exists only in the captured pixels.

```yaml
enabled: true

columns:
  - header: NAME
    with: "Example Account {n}"
    as: account
  - header: ACCOUNT
    with: "Example Account {n}"
    as: account

patterns:
  - name: account-id
    pattern: "acc_[0-9a-f]{20}"
    with: "acc_{n:020d}"

literals:
  - match: "Meridian Operations"
    with: "Example Workspace"
```

## The three kinds of rule

### columns

The main one. Values under a table header, replaced row by row. This catches
every name in a list view **without knowing the names in advance**, which is
what matters, because the data changes between crawls and a literal list goes
stale the first time someone signs up.

`as:` groups rules that name the same kind of thing. Two screens listing the
same entities under different headers share `as: account`, so a name masked on
one screen gets the same placeholder on the other, and two figures never
contradict each other.

A name learned from a column is masked everywhere else on that page too, not
only inside the table. The customer whose name is in the header of a detail
view is the same customer.

### patterns

A regular expression, for identifiers. `{n}` is the counter, and Python format
specs work, so `acc_{n:020d}` produces an identifier of the same shape and
length as the real one. A placeholder that is visibly shorter than the thing it
replaced makes the screenshot look wrong.

### literals

Exact strings. For the handful of things no column or pattern reaches: a
workspace name in a page header, a person's name in an audit trail.

## Stability

The mapping is stored in `content/masking-map.json`, so a given real value
always becomes the same placeholder, in this crawl and in crawls months from
now.

```bash
verba masking
```

This is not a nicety. Without it, figure 4.1 shows "Example Account 3" and
figure 4.2 shows "Example Account 7" for the same customer, and a reader trying
to follow one account through a workflow concludes the document is wrong.

The map is readable and should be committed. It contains placeholders and the
real values they stand for, so treat it with the same care as any file that
names your customers.

## Pictures no crawl produced

Masking protects what a crawl takes. It says nothing about a picture that
arrived some other way: pasted in by hand, or inherited from an older document.

Those are found and reported (`ASSET-10`, `ASSET-11`), and the loop deals with
them in two steps:

1. **Replace what can be replaced.** If a registered screen produces that view,
   photograph it. The new picture goes through masking, and the question is
   settled.
2. **Look at what cannot.** Every remaining unchecked picture is read by a model
   with vision, against the exact list of names that must never appear.

That list is exact strings, not a description. An early version asked "does this
image contain real customer names" and got different answers for the same
picture depending on the wording of the question, which is worse than not
checking: sixteen verdicts were thrown away. Now the names are passed in, and
the check is a lookup rather than a judgement.

## Names in the text

The other half of the problem. A tenant neutral edition must not name a
customer, and `GENERIC-01` enforces it. The names it must not print are read off
your **other** editions rather than configured separately, so adding a customer
edition automatically extends what the neutral one is held to. See
[Editions](Editions).
