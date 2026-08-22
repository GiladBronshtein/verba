# Editions

One content tree, several documents. An edition declares what it carries, so
"what is in the customer edition" is one list you can read rather than a
property scattered across forty section files.

```yaml
# content/profiles/acmecorp.yaml
name: acmecorp
audience: operator
title_suffix: " (AcmeCorp Edition)"
sections:
  exclude: [admin-tools]
vars:
  operator:
    name: AcmeCorp
    role: publisher
    possessive: AcmeCorp's
```

```bash
verba build --profile acmecorp --pdf
verba edition                      # what this edition carries
verba edition drop admin-tools     # leave a section out
verba edition add admin-tools      # put it back
verba edition reset
```

## How a section says who it is for

Two mechanisms, and they mean different things.

| Where | Means |
|---|---|
| `sections.exclude` in the profile | The edition saying what it leaves out |
| `profiles:` in a section's front matter | The section saying which editions it belongs to |

The profile list is the one to reach for. It keeps the answer in one file, so
you can read an edition's shape without opening every section. Section level
`profiles:` is for the rare case where a section is genuinely only meaningful in
one edition, and belongs with the section rather than in a list somewhere else.

Dropping a branch drops its children, and **the numbering closes up behind it**.
Section 5 becomes section 4 in the body and on the contents page together,
because no section file carries a number.

## Variables

Sections write `{{ operator.name }}` rather than naming a company:

```markdown
Each account is billed to {{ operator.name }} at the end of the month.
```

Two rules protect this. `PROFILE-01` fails the build when a variable does not
resolve, and `PROFILE-02` fails it when a variable was left unsubstituted in the
output. A document that ships `{{ operator.name }}` to a customer is worse than
one that fails to build.

## The neutral edition

A tenant neutral edition must not name a customer. `GENERIC-01` enforces it, and
the interesting part is where the list comes from: **the names it must not print
are read off your other editions**, not configured separately.

Add a customer edition and the neutral one is automatically held to not naming
that customer. Nobody has to remember to update a blocklist, which is exactly
the kind of thing nobody remembers to update.

## A worked shape

```
content/profiles/
  default.yaml      neutral, "your organization", everything
  acmecorp.yaml     branded, drops admin-tools
  internal.yaml     everything, including the admin chapters
```

```bash
verba build --profile default --pdf
verba build --profile acmecorp --pdf
verba release --version v3
```

`release` cuts every edition and refuses to overwrite an output that already
exists.
