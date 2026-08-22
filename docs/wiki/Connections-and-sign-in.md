# Connections and sign in

`content/environments.yaml` says which system a crawl talks to, and how it gets
in. It never holds a password.

```yaml
active: staging
environments:
  - id: staging
    label: Staging
    base_url: https://app-staging.example.com
    auth: form
    user: docs@example.com
    signed_in_when: "nav a"
    mask_required: false

  - id: production
    label: Production
    base_url: https://app.example.com
    auth: sso
    signed_in_when: "[data-testid=user-menu]"
    mask_required: true
```

| Key | Meaning |
|---|---|
| `id` | What you pass to `verba env use` |
| `base_url` | Where the crawl goes. Screens use paths relative to this |
| `auth` | `form`, `sso`, `handoff` or `none` |
| `user` | The account the crawl signs in as. Never the password |
| `signed_in_when` | A selector that proves a session is live |
| `mask_required` | `true` refuses an unmasked crawl outright |
| `keychain_prefix` | Which keychain entries this project's passwords live under |
| `signin_timeout_s` | How long a hand over waits for you. Default 300 |

## The four ways in

### form

A username and password typed into the product's own sign in page. The password
lives in the OS keychain, never in the project:

```bash
verba env password staging
```

The login steps reference `${VERBA_USER}` and `${VERBA_PASSWORD}`, which are
filled from the keychain at crawl time. For scheduled runs on a machine with no
keychain, set `VERBA_PASSWORD` in the environment instead. It is checked second,
so a stray environment variable never quietly overrides what you stored.

### sso

Single sign on, where you sign in once in a real browser and Verba keeps the
session:

```bash
verba env signin production
```

A window opens, you complete whatever your identity provider asks for, including
any second factor, and the session is saved under `.verba/sessions`. There is no
password anywhere in the process, and nothing to store. Sessions expire; sign in
again when they do.

`.verba/sessions` is a credential. The scaffold's `.gitignore` excludes it.
Keep it that way.

### handoff

**For a product that asks for something a machine cannot produce**: a one-time
code, a prompt on your phone, a hardware key, a picture of a bus.

```yaml
  - id: production
    label: Production
    base_url: https://app.example.com
    auth: handoff
    user: docs@example.com        # optional
    signed_in_when: "[data-testid=user-menu]"
    signin_timeout_s: 300
```

A browser opens. Verba fills in whatever it knows, which is the boring half, and
then **stops and waits for you** to finish. The moment the product is on screen
the crawl carries on by itself, in the same run, and the session is saved so
nobody is asked again until it lapses.

```
signing in ...
    sign-in request allowed: POST https://app.example.com/login

  over to you: finish signing in in the browser window,
  including any code, prompt or key. The crawl carries on
  by itself the moment the product is on screen.
    waiting for you to sign in, 4m 58s left
    signed in
  session saved, the next crawl will not ask (production.json)
read-only guard armed: writes are blocked from here on
  captured accounts.list in 1.1s via steps  [columns=6]
```

Username and password are both optional. With neither, the browser simply opens
at the sign-in page and waits. With both, you only deal with the second factor.

Three details that matter:

- **A step that fails does not stop the run.** A product that has just started
  asking for a code will fail on a step that worked last week, and that is not a
  reason to stop: it is exactly the case a person is here for.
- **An expired session asks rather than fails.** Every other mode ends the run.
  On a connection that already knows how to ask a person, ending the run is the
  one thing there is no reason to do.
- **The permitted-write window closes at the product, not at the end.** While you
  are signing in, the browser is in its sign-in phase, where writes are allowed,
  and you have a mouse. Verba stops permitting them the instant the product
  appears, before it resumes. See
  [The read only guarantee](The-read-only-guarantee).

Force it on any connection for one run:

```bash
verba capture --wait-for-signin
```

That is the flag for the morning your product starts asking for a code and you
have not changed the connection yet.

### none

No sign in needed. Public documentation, a demo, or a product with no login.

## Checking a connection

```bash
verba env list          # every connection, whether it has a password or a session
verba env use staging   # make one active
verba env verify        # can it be reached, and can we get in
```

`verify` is the command to run when a crawl fails. It separates "the network is
wrong", "the credentials are wrong" and "the selectors are wrong", which
otherwise all present as twenty selector timeouts.

Sign in failure is deliberately loud:

```
sign-in did not reach the product, still on https://app.example.com/login
```

Failing there once beats twenty timeouts that each look like a broken screen
when the real fault is one sign in.

## Production and masking

`mask_required: true` refuses to capture unmasked. Set it on anything holding
real customer data, and it is one line rather than a habit.

The safest arrangement is to document staging, where the data is already
fictional, and keep production behind `mask_required`. When staging is not
representative, capture production with masking on and check the pictures: the
loop reads every unchecked image against the exact list of names that must never
appear. See [Masking and names](Masking-and-names).

## What a crawl is allowed to do to your system

Sign in, and nothing else. That is enforced in the browser, not by discipline.
See [The read only guarantee](The-read-only-guarantee).
