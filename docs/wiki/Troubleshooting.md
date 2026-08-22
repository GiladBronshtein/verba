# Troubleshooting

## Sign in

**`sign-in did not reach the product, still on .../login`**

The crawl got to the login page and never left it. In order of likelihood:

```bash
verba env verify        # start here, always
```

| Cause | Check |
|---|---|
| Wrong password | `verba env password <id>` to store it again |
| Wrong `signed_in_when` | It must be a selector that only exists once signed in |
| A second factor | Use `auth: sso` instead of `form`. `verba env signin <id>` |
| The login selectors moved | `verba capture --headed` and watch it |

`verify` is the command that separates the network, the credentials and the
selectors. Guessing between those three is what makes this slow.

**Single sign on worked yesterday and not today.** Sessions expire. `verba env
signin <id>` again. There is nothing stored to clear.

## Capture

**Every screen times out but sign in succeeded.** The steps are wrong, not the
credentials. `verba capture --headed --screens one.screen` and watch.

**`step 'fill' types into the page and is only permitted during sign-in.`**
Working as intended. Nothing outside sign in may put data into the page. If the
screen genuinely cannot be reached without filling a field, that state does not
get documented. See [The read only guarantee](The-read-only-guarantee).

**`step clicks '...', which reads like a commit`** is advisory. Remove the step,
or add `opens_form: true` if the control opens a form rather than committing one.

**A screen photographs the wrong page.** It redirected. `verba routes` shows
where each screen actually ended up. Two identical photographs is `ASSET-04`,
and this is usually why.

**The capture came back blank** (`ASSET-09`). The page had not finished
rendering. Add a `wait_for` on something that only exists once the content is
there, rather than a `wait_ms` that is right on your machine and wrong on CI.

## Build

**`refused: a 15cm figure does not fit the 11.2cm column on A5 at 18mm margins`**
Working as intended. The layout is judged against the page you are choosing.
Narrow the figure or widen the page.

**`TODO: describe this.` fails the build** (`CONTENT-02`). Also working as
intended. The writer leaves a marker rather than inventing a purpose the
evidence does not support, and the marker cannot ship. Write the description, or
let the loop try again with better evidence.

**`{{ operator.name }}` in the output** (`PROFILE-02`). The variable was not
substituted. Check the edition defines it under `vars:`.

**Fonts look wrong in Word.** `verba fonts` reports what the outputs are
actually set in on this machine. Each face names a DOCX fallback for exactly
this.

## The writer

**"no model configured".** Three routes, and the console's Writer page names
which one is in use. If you are inside Claude Code, route 3 needs nothing at
all. Otherwise paste a key.

**The picture checks are unavailable.** Route 3, the Claude Code CLI, cannot be
given an image. Use a gateway or a pasted key.

**Everything goes to the wrong gateway.** `ANTHROPIC_BASE_URL` is deliberately
ignored: it is set per shell and per session. Set `VERBA_GATEWAY`, or pin it in
`content/doc.yaml` under `assist:`.

## The loop

**It says it fixed things and the findings are still there.** Reload. If they
persist, they are findings a person owns: the loop reports what it could not
justify, with the reason. Anything with "Who: you" in the
[Rule reference](Rule-reference) will not clear itself.

**It changed something it should not have.** Everything is reversible:

```bash
verba history <section>
verba history --restore <id>
```

Read the stored content rather than trusting the timestamps. The newest revision
of a damaged section is the damage.

**A figure disappeared.** That was a real bug, and there is now a guard: no
rewrite may drop a figure. If you see it again on a current version, it is worth
an issue, with the `review/auto.json` from that run.

## The console

**Port already in use.** `verba console --port 9000`.

**It shows the wrong product's name.** The switcher under the logo. Or
`verba console --root path/to/other`.

**Two people editing.** Supported. Writes are locked and atomic. If you see a
conflict message, someone else saved that section first; reload and reapply.
