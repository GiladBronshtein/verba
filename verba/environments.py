"""Connection profiles: which system to crawl, and how to get in.

Two ways in, because the systems differ:

* **form**: a username and password typed into the product's own sign-in page.
  The password lives in the login keychain, never in this repository. Suitable
  for a shared test account on staging.

* **sso**: single sign-on, Okta in this case. Nothing is typed by automation and
  no password is stored anywhere. A real browser window opens, the person signs
  in themselves including any second factor, and the resulting browser session
  is saved. Later crawls reuse that session until it expires.

The second mode is the only honest way to handle SSO. Driving an Okta password
form from a script means storing a corporate password and breaks the moment a
second factor is required, which it should be.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

CONFIG = "content/environments.yaml"
SESSIONS = ".verba/sessions"
KEYCHAIN_PREFIX = "verba-env"

AUTH_MODES = ("form", "sso", "none")


@dataclass
class Environment:
    id: str
    label: str = ""
    base_url: str = ""
    auth: str = "form"                  # form | sso | none
    user: str = ""
    login_steps: list = field(default_factory=list)
    signed_in_when: str = ""            # selector proving a session is live
    mask_required: bool = False         # production data must never ship unmasked
    notes: str = ""
    # Which keychain entries this project's passwords live under. A project that
    # existed before the engine was renamed keeps its old prefix, so migrating
    # does not silently orphan a password somebody has already stored.
    keychain_prefix: str = KEYCHAIN_PREFIX

    @classmethod
    def from_dict(cls, d: dict) -> "Environment":
        return cls(
            id=d["id"], label=d.get("label", d["id"]),
            base_url=(d.get("base_url", "") or "").rstrip("/"),
            auth=d.get("auth", "form"), user=d.get("user", "") or "",
            login_steps=d.get("login_steps", []) or [],
            signed_in_when=d.get("signed_in_when", "") or "",
            mask_required=bool(d.get("mask_required", False)),
            notes=d.get("notes", "") or "",
        )

    def to_dict(self) -> dict:
        d = {"id": self.id, "label": self.label, "base_url": self.base_url,
             "auth": self.auth}
        if self.user:
            d["user"] = self.user
        if self.login_steps:
            d["login_steps"] = self.login_steps
        if self.signed_in_when:
            d["signed_in_when"] = self.signed_in_when
        if self.mask_required:
            d["mask_required"] = True
        if self.notes:
            d["notes"] = self.notes
        return d

    # -- secrets ---------------------------------------------------------
    @property
    def keychain_service(self) -> str:
        return f"{self.keychain_prefix or KEYCHAIN_PREFIX}-{self.id}"

    def password(self) -> str | None:
        """The password for this profile's current user.

        The account must be part of the lookup. Searching by service alone
        returns whichever entry the keychain happens to match first, so changing
        the username on a profile silently kept handing back the previous user's
        password while reporting the new username as signed in.
        """
        if self.auth != "form":
            return None
        cmd = ["security", "find-generic-password", "-s", self.keychain_service]
        if self.user:
            cmd += ["-a", self.user]
        r = subprocess.run(cmd + ["-w"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()

        # The keychain is the right place for a password a person types once on
        # their own machine, and the wrong place for one supplied to a scheduled
        # run: there is no keychain in a container, and no one there to unlock
        # it. VERBA_PASSWORD covers that, and is checked second so a stray
        # variable in somebody's shell can never override what they saved.
        return os.environ.get("VERBA_PASSWORD") or None

    def set_password(self, user: str, password: str):
        # Drop any entry for a previous username on this profile, so one profile
        # never leaves several passwords behind for the lookup to choose between.
        if self.user and self.user != user:
            subprocess.run(["security", "delete-generic-password",
                            "-s", self.keychain_service, "-a", self.user],
                           capture_output=True)
        r = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", self.keychain_service,
             "-a", user, "-w", password], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "the keychain refused the entry")
        self.user = user

    def stray_accounts(self) -> list[str]:
        """Other usernames still holding a password under this profile."""
        found, guard = [], 0
        while guard < 8:
            guard += 1
            cmd = ["security", "find-generic-password", "-s", self.keychain_service]
            for a in found + ([self.user] if self.user else []):
                cmd += ["-a", a]
            r = subprocess.run(
                ["security", "find-generic-password", "-s", self.keychain_service],
                capture_output=True, text=True)
            if r.returncode != 0:
                break
            acct = ""
            for line in r.stdout.splitlines():
                if '"acct"' in line and '="' in line:
                    acct = line.split('="')[-1].rstrip('"')
            if not acct or acct in found or acct == self.user:
                break
            found.append(acct)
            break
        return found

    def export_credentials(self) -> bool:
        """Put this profile's sign-in into the environment for the step interpreter.

        The login steps reference ${VERBA_USER} and ${VERBA_PASSWORD}.
        Without this the substitution yields empty strings, the form submits
        blank, and every screen afterwards fails with a timeout that looks like
        a selector problem rather than a sign-in one.
        """
        import os
        if self.auth != "form":
            return True
        pw = self.password()
        if not pw or not self.user:
            return False
        os.environ["VERBA_USER"] = self.user
        os.environ["VERBA_PASSWORD"] = pw
        return True

    def forget_password(self):
        # loop: one profile may have accumulated entries for several usernames
        for _ in range(8):
            r = subprocess.run(["security", "delete-generic-password", "-s",
                                self.keychain_service], capture_output=True)
            if r.returncode != 0:
                break

    # -- sso session -----------------------------------------------------
    def session_path(self, root: Path) -> Path:
        return Path(root) / SESSIONS / f"{self.id}.json"

    def session_info(self, root: Path) -> dict:
        p = self.session_path(root)
        if not p.exists():
            return {"present": False}
        try:
            data = json.loads(p.read_text())
        except Exception:
            return {"present": False, "error": "unreadable"}
        expiries = [c.get("expires", -1) for c in data.get("cookies", [])
                    if c.get("expires", -1) > 0]
        soonest = min(expiries) if expiries else None
        return {
            "present": True,
            "saved_at": datetime.fromtimestamp(p.stat().st_mtime)
            .isoformat(timespec="minutes"),
            "cookies": len(data.get("cookies", [])),
            "expires": datetime.fromtimestamp(soonest).isoformat(timespec="minutes")
            if soonest else None,
            "expired": bool(soonest and soonest < datetime.now().timestamp()),
        }

    def ready(self, root: Path) -> tuple[bool, str]:
        if not self.base_url:
            return False, "no address set"
        if self.auth == "none":
            return True, "no sign-in needed"
        if self.auth == "form":
            return (True, f"signed in as {self.user}") if self.password() \
                else (False, "no password saved")
        info = self.session_info(root)
        if not info.get("present"):
            return False, "not signed in yet"
        if info.get("expired"):
            return False, f"session expired, saved {info.get('saved_at')}"
        return True, f"session saved {info.get('saved_at')}"


@dataclass
class Environments:
    root: Path
    active: str = ""
    items: dict = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Environments":
        root = Path(root)
        path = root / CONFIG
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        data = data or {}
        prefix = str(data.get("keychain_prefix", "") or KEYCHAIN_PREFIX)
        envs = {}
        for e in data.get("environments", []):
            env = Environment.from_dict(e)
            env.keychain_prefix = str(e.get("keychain_prefix", "") or prefix)
            envs[env.id] = env
        return cls(root=root, active=data.get("active", "") or
                   (next(iter(envs), "") if envs else ""), items=envs)

    def save(self):
        path = self.root / CONFIG
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Connection profiles. Which system a crawl talks to, and how it gets\n"
            "# in. Passwords are never stored here: form logins keep theirs in the\n"
            "# login keychain, and single sign-on keeps a browser session under\n"
            "# .verba/sessions instead of a password at all.\n"
        )
        body = {"active": self.active,
                "environments": [e.to_dict() for e in self.items.values()]}
        path.write_text(header + yaml.safe_dump(body, sort_keys=False,
                                                allow_unicode=True), encoding="utf-8")

    # ------------------------------------------------------------------
    def current(self) -> Environment | None:
        return self.items.get(self.active)

    def add(self, env: Environment) -> Environment:
        self.items[env.id] = env
        if not self.active:
            self.active = env.id
        self.save()
        return env

    def remove(self, env_id: str):
        env = self.items.pop(env_id, None)
        if env:
            env.forget_password()
            p = env.session_path(self.root)
            if p.exists():
                p.unlink()
        if self.active == env_id:
            self.active = next(iter(self.items), "")
        self.save()

    def activate(self, env_id: str):
        if env_id not in self.items:
            raise KeyError(env_id)
        self.active = env_id
        self.save()

    def as_site(self, env: Environment | None = None,
                fallback_login: list | None = None) -> dict:
        """Shape an environment the way the capture engine expects a site.

        Sign-in steps come from the connection first, then from whatever the
        project wrote in screens.yaml, and only then from the generic default.
        The middle step used to be missing, so a project that had described its
        own sign-in in screens.yaml watched the crawler ignore it and try a
        path that belonged to a different product entirely.
        """
        env = env or self.current()
        if env is None:
            return {}
        site = {"base_url": env.base_url, "signed_in_when": env.signed_in_when}
        if env.auth == "form":
            site["login"] = (env.login_steps or fallback_login
                             or DEFAULT_FORM_LOGIN)
        else:
            site["login"] = []
            site["storage_state"] = str(env.session_path(self.root))
        return site

    def summary(self) -> list[dict]:
        out = []
        for e in self.items.values():
            ok, why = e.ready(self.root)
            out.append({
                **e.to_dict(), "active": e.id == self.active,
                "ready": ok, "status": why,
                "session": e.session_info(self.root) if e.auth == "sso" else None,
                "has_password": bool(e.password()) if e.auth == "form" else None,
            })
        return out


# A last-resort guess, used only when neither the connection nor screens.yaml
# says how to sign in. `/login` is the commonest path; anything else belongs in
# the project's own screens.yaml, which is now consulted first.
DEFAULT_FORM_LOGIN = [
    {"goto": "/login"},
    {"wait_for": "input"},
    {"wait_ms": 1200},
    {"fill": 'input[autocomplete="username"], input[name="email"], input[type="email"]',
     "value": "${VERBA_USER}"},
    {"fill": 'input[autocomplete="current-password"], input[name="password"], '
             'input[type="password"]',
     "value": "${VERBA_PASSWORD}"},
    {"click": 'button[type="submit"]'},
    # no blind sleep here: the caller waits for the redirect to actually happen
]
