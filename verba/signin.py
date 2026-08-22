"""Interactive sign-in and connection checking.

For single sign-on there is no password to store and none is asked for. A real
browser window opens, the person signs in themselves through Okta including any
second factor, and once the product is reached the browser session is saved.
Later crawls load that session and never see the sign-in page at all.

The read-only guard is armed for verification and for every crawl that follows,
so a session captured here can still never be used to change anything.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .readonly import Guard

VIEWPORT = {"width": 1440, "height": 768}

# A page that shows any of these is the product, not an identity provider.
DEFAULT_SIGNED_IN = ("nav a, aside a, [role=navigation] a, [role=tab], "
                     "table, [role=table]")

IDP_HOSTS = ("okta.com", "oktapreview.com", "accounts.google.com",
             "login.microsoftonline.com", "auth0.com")


def _expand_env(value: str) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), str(value))


def _on_idp(url: str) -> bool:
    return any(h in (url or "") for h in IDP_HOSTS)


def await_signed_in(page, marker: str, timeout_ms: int = 30000, log=None) -> bool:
    """Wait for the sign-in to actually land.

    Polls rather than relying on wait_for_url. This product is a single page
    application behind Clerk: the address can change without a navigation event,
    and the redirect timing varies by seconds between runs. Treating either
    signal as sufficient, and checking both on a loop, is far steadier than
    waiting for one event that may never fire.
    """
    emit = log or (lambda *_: None)
    deadline = time.monotonic() + timeout_ms / 1000.0
    last = ""
    while time.monotonic() < deadline:
        try:
            url = page.url
        except Exception:
            break
        if url != last:
            last = url
        off_login = "/auth/" not in url and "/login" not in url
        if off_login:
            emit(f"    redirected to {url[:80]}")
            try:
                page.wait_for_selector(marker, timeout=8000)
                return True
            except Exception:
                return False
        # the address may lag behind the application: if the product's own
        # furniture is already on screen, the sign-in has in fact succeeded
        try:
            if page.query_selector(marker) and not page.query_selector(
                    'input[autocomplete="current-password"]'):
                emit(f"    signed in, the address still reads {url[:60]}")
                return True
        except Exception:
            pass
        page.wait_for_timeout(500)

    emit(f"    still on the sign-in page after {timeout_ms // 1000}s ({last[:70]})")
    return False


# Fields that mean the sign-in is not finished, whatever the address says. A
# one-time-code page often lives on the same path as the password page and has
# already redirected off /login, so the address alone reports success while the
# product is still two steps away.
PENDING_FIELDS = ('input[autocomplete="current-password"], '
                  'input[autocomplete="one-time-code"], '
                  'input[type="password"], '
                  'input[name*="otp" i], input[name*="code" i], '
                  'input[id*="otp" i], input[id*="code" i]')


def hand_over(page, marker: str, timeout_s: int = 300, log=None,
              tick=None, poll_ms: int = 400) -> bool:
    """Stop, and let the person finish signing in.

    This is the answer to every sign-in a machine cannot complete: a one-time
    code, a push notification, a hardware key, a picture of a bus. Verba fills
    in what it knows, and then gets out of the way until the product is on
    screen.

    Returns True once the product is reached. `tick(page, seconds_left)` is
    called on every poll, which is how the console streams progress and how the
    tests stand in for the person.

    The poll is deliberately short. Between the moment somebody finishes signing
    in and the moment this notices, the browser is still in its sign-in phase
    and a write would be permitted, so that window should be small and every
    request inside it is recorded in the manifest.
    """
    emit = log or (lambda *_: None)
    deadline = time.monotonic() + timeout_s
    last_note = ""
    announced = 0

    while time.monotonic() < deadline:
        left = int(deadline - time.monotonic())
        try:
            url = page.url
        except Exception:
            break

        here = "identity provider" if _on_idp(url) else "product"
        if here != last_note:
            emit(f"    now on the {here}: {url[:90]}")
            last_note = here

        if not _on_idp(url):
            try:
                pending = page.query_selector(PENDING_FIELDS)
            except Exception:
                pending = None
            if not pending:
                try:
                    if page.query_selector(marker):
                        emit("    signed in")
                        return True
                except Exception:
                    pass

        # A minute at a time, so a long wait does not look like a hang.
        if left // 60 != announced // 60 or announced == 0:
            announced = left
            emit(f"    waiting for you to sign in, {left // 60}m {left % 60:02d}s left")

        if tick:
            try:
                tick(page, left)
            except Exception as e:      # a caller's progress hook must never
                emit(f"    (waiting: {e})")   # be able to fail a sign-in
        page.wait_for_timeout(poll_ms)

    emit(f"    gave up waiting after {timeout_s // 60} minutes")
    return False


def interactive_signin(env, root: Path, log=None, timeout_s: int = 300) -> dict:
    """Open a browser, wait for the person to sign in, save the session."""
    from playwright.sync_api import sync_playwright

    emit = log or (lambda *_: None)
    target = env.base_url
    if not target:
        raise RuntimeError("this profile has no address")

    session = env.session_path(root)
    session.parent.mkdir(parents=True, exist_ok=True)
    marker = env.signed_in_when or DEFAULT_SIGNED_IN

    emit(f"opening a browser window at {target}")
    emit("sign in there yourself, including any second factor.")
    emit(f"this waits up to {timeout_s // 60} minutes and saves the session when "
         f"the product loads.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--window-size=1440,900"])
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()
        page.goto(target, wait_until="domcontentloaded", timeout=60000)

        saved = hand_over(page, marker, timeout_s=timeout_s, log=emit)
        if saved:
            ctx.storage_state(path=str(session))
            emit(f"  signed in, session saved to {session.name}")

        if not saved:
            try:
                ctx.storage_state(path=str(session))
                emit("  the product page was not recognised, saving the session anyway. "
                     "Use Verify to check whether it works.")
            except Exception:
                pass
        ctx.close()
        browser.close()

    info = env.session_info(root)
    return {"saved": session.exists(), "recognised": saved, **info}


def verify(env, root: Path, log=None) -> dict:
    """Check a profile can actually reach the product while signed in."""
    from playwright.sync_api import sync_playwright

    emit = log or (lambda *_: None)
    if not env.base_url:
        return {"ok": False, "reason": "this profile has no address"}
    marker = env.signed_in_when or DEFAULT_SIGNED_IN
    guard = Guard()

    emit(f"checking {env.label or env.id} at {env.base_url}")
    emit(f"sign-in method: {env.auth}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        kwargs = {"viewport": VIEWPORT}
        if env.auth in ("sso", "handoff"):
            sp = env.session_path(root)
            if not sp.exists():
                browser.close()
                if env.auth == "handoff":
                    return {"ok": True, "pending": True,
                            "reason": "nobody has signed in yet. The next crawl "
                                      "will open a browser and wait for you."}
                return {"ok": False, "reason": "no saved session, sign in first"}
            kwargs["storage_state"] = str(sp)
            emit("using the saved browser session")
        ctx = browser.new_context(**kwargs)
        page = ctx.new_page()
        page.set_default_timeout(25000)
        guard.attach(page, log=emit)

        result: dict = {"ok": False}
        try:
            if env.auth == "form":
                pw_value = env.password()
                if not pw_value:
                    raise RuntimeError("no password saved for this profile")
                os.environ["VERBA_USER"] = env.user
                os.environ["VERBA_PASSWORD"] = pw_value
                from .environments import DEFAULT_FORM_LOGIN
                for step in (env.login_steps or DEFAULT_FORM_LOGIN):
                    base = env.base_url
                    if "goto" in step:
                        t = step["goto"]
                        page.goto(t if t.startswith("http") else base + t,
                                  wait_until="domcontentloaded")
                    elif "fill" in step:
                        page.fill(step["fill"], _expand_env(step.get("value", "")))
                    elif "click" in step:
                        page.click(step["click"])
                    elif "wait_for" in step:
                        page.wait_for_selector(step["wait_for"])
                    elif "wait_ms" in step:
                        page.wait_for_timeout(int(step["wait_ms"]))
                emit("submitted the sign-in form")
                await_signed_in(page, marker, log=emit)
            else:
                page.goto(env.base_url, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)

            guard.lock()
            url = page.url
            emit(f"landed on {url[:100]}")

            if _on_idp(url):
                result = {"ok": False, "url": url,
                          "reason": "the identity provider is still asking to sign in. "
                                    "The saved session has expired, sign in again."
                          if env.auth != "handoff" else
                          "the saved session has expired. The next crawl will open "
                          "a browser and wait for you to sign in again."}
            else:
                try:
                    page.wait_for_selector(marker, timeout=8000)
                    title = page.title()
                    result = {"ok": True, "url": url, "title": title,
                              "reason": f"reached the product: {title or url}"}
                    emit(f"  product recognised: {title}")
                except Exception:
                    result = {"ok": False, "url": url,
                              "reason": "the page loaded but did not look like the "
                                        "product. Adjust 'signed in when' for this "
                                        "profile."}
        except RuntimeError as e:
            result = {"ok": False, "reason": str(e)}
        except Exception as e:
            result = {"ok": False, "reason": f"{type(e).__name__}: {str(e)[:200]}"}
        finally:
            result["blocked_writes"] = guard.report()["blocked_writes"]
            ctx.close()
            browser.close()

    emit(("verified: " if result["ok"] else "not verified: ") + result.get("reason", ""))
    return result
