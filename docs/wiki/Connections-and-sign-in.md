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
| `auth` | `form`, `sso` or `none` |
| `user` | The account the crawl signs in as. Never the password |
| `signed_in_when` | A selector that proves a session is live |
| `mask_required` | `true` refuses an unmasked crawl outright |
| `keychain_prefix` | Which keychain entries this project's passwords live under |

## The three ways in

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
