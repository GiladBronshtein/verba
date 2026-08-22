#!/usr/bin/env python3
"""Meridian: a small fictional admin console, so Verba has something to document.

Nothing here is a real product. It exists so the whole loop can be demonstrated
and reproduced by anyone, without pointing the crawler at a system they do not
own and without shipping screenshots of somebody's live account.

    python3 examples/meridian/serve.py        # http://127.0.0.1:8910

Sign in with any address and any password: it checks nothing. The point is that
there *is* a sign-in, so the read-only guard and the masking rules have
something real to act on.
"""
from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PORT = 8910
HERE = Path(__file__).parent

ACCOUNTS = [
    ("Northwind Trading", "NW", "acc_7f3b21c9e4d80a5612bb", "eu-west-1", "Scale", "live"),
    ("Fabrikam Media", "FM", "acc_2c91ea70bb4413de08a7", "us-east-1", "Growth", "live"),
    ("Contoso Retail", "CR", "acc_9a44df02c17e6b3390fd", "us-west-2", "Scale", "hold"),
    ("Tailspin Toys", "TT", "acc_51e6ab8830cc27419dfe", "ap-south-1", "Starter", "live"),
    ("Litware Health", "LH", "acc_08bd7c4419af5e2266ca", "eu-central-1", "Growth", "off"),
    ("Proseware Group", "PG", "acc_63fa1d95e2b70c8845ae", "us-east-1", "Starter", "live"),
]
PILL = {"live": ("live", "Live"), "hold": ("hold", "On hold"), "off": ("off", "Disabled")}


def shell(title: str, active: str, crumb: str, body: str) -> str:
    nav = [("Dashboard", "/", "dashboard"), ("Accounts", "/accounts", "accounts"),
           ("Reports", "/reports", "reports")]
    items = "".join(
        f'<a href="{href}" class="{"on" if key == active else ""}">{label}</a>'
        for label, href, key in nav)
    settings = f'<a href="/settings" class="{"on" if active == "settings" else ""}">Workspace settings</a>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Meridian</title><link rel="stylesheet" href="/style.css"></head>
<body><div class="shell">
<aside class="side">
  <div class="brand"><span class="glyph">M</span> Meridian</div>
  <nav class="nav">{items}<div class="grp">Configure</div>{settings}
    <a href="/settings/members">Members</a><a href="/settings/api">API keys</a></nav>
  <div class="foot">Meridian 4.2.0</div>
</aside>
<div class="main">
  <header class="top"><div class="crumb">{crumb}</div><div class="spacer"></div>
    <div class="avatar">AD</div></header>
  <div class="body">{body}</div>
</div></div></body></html>"""


def page_login() -> str:
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · Meridian</title><link rel="stylesheet" href="/style.css"></head>
<body><div class="signin"><form class="box" method="get" action="/">
  <div class="glyph">M</div>
  <h2>Sign in to Meridian</h2><p class="s">Use your workspace account.</p>
  <div class="field"><label for="email">Work email</label>
    <input id="email" name="email" type="email" autocomplete="username"
      placeholder="you@company.com"></div>
  <div class="field"><label for="password">Password</label>
    <input id="password" name="password" type="password"
      autocomplete="current-password" placeholder="••••••••••"></div>
  <button class="btn primary" type="submit">Sign in</button>
  <div class="alt">Trouble signing in? Contact your workspace owner.</div>
</form></div></body></html>"""


def page_dashboard() -> str:
    tiles = [("Active accounts", "218", "+12 this month", ""),
             ("Events today", "1,904,772", "+4.1% vs yesterday", ""),
             ("Delivery rate", "99.2%", "-0.3% vs last week", "down"),
             ("Open incidents", "2", "1 resolved today", "")]
    tl = "".join(f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div>'
                 f'<div class="d {c}">{d}</div></div>' for k, v, d, c in tiles)
    rows = "".join(
        f'<tr><td><div class="who"><div class="sq">{ini}</div><div>'
        f'<div class="n">{name}</div><div class="e">{region}</div></div></div></td>'
        f'<td class="mono">{aid}</td><td>{plan}</td>'
        f'<td><span class="pill {PILL[st][0]}">{PILL[st][1]}</span></td></tr>'
        for name, ini, aid, region, plan, st in ACCOUNTS[:4])
    return shell("Dashboard", "dashboard", "<b>Dashboard</b>", f"""
<h1>Dashboard</h1><div class="sub">Everything across your workspace, updated a minute ago.</div>
<div class="tiles">{tl}</div>
<div class="card"><div class="bar"><b style="font-size:14px">Recently active accounts</b>
  <div class="spacer" style="flex:1"></div>
  <a class="btn ghost" href="/accounts">View all</a></div>
<table><thead><tr><th>Account</th><th>Account ID</th><th>Plan</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table></div>""")


def page_accounts() -> str:
    rows = "".join(
        f'<tr><td><div class="who"><div class="sq">{ini}</div><div>'
        f'<div class="n"><a href="/accounts/{i}">{name}</a></div>'
        f'<div class="e">{plan} plan</div></div></div></td>'
        f'<td class="mono">{aid}</td><td>{region}</td><td>{plan}</td>'
        f'<td>Alex Morgan</td>'
        f'<td><span class="pill {PILL[st][0]}">{PILL[st][1]}</span></td></tr>'
        for i, (name, ini, aid, region, plan, st) in enumerate(ACCOUNTS, 1))
    return shell("Accounts", "accounts", "<b>Accounts</b>", f"""
<h1>Accounts</h1><div class="sub">Every account in this workspace, and how it is configured.</div>
<div class="card"><div class="bar">
  <div class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
    <input type="search" placeholder="Search accounts"></div>
  <div class="seg"><button class="on">All</button><button>Live</button>
    <button>On hold</button><button>Disabled</button></div>
  <div class="spacer" style="flex:1"></div>
  <button class="btn">Export</button>
  <button class="btn primary">New account</button></div>
<table><thead><tr><th>Name</th><th>Account ID</th><th>Data Region</th><th>Tier</th>
  <th>Owner</th><th>Health</th></tr></thead><tbody>{rows}</tbody></table></div>""")


def page_account(idx: int) -> str:
    name, ini, aid, region, plan, st = ACCOUNTS[idx - 1]
    return shell(name, "accounts",
                 f'<a href="/accounts">Accounts</a> <span>/</span> <b>{name}</b>', f"""
<div class="head"><div class="acct"><div class="sq">{ini}</div>
  <div><h1>{name}</h1><div class="sub" style="margin:0">
    <span class="pill {PILL[st][0]}">{PILL[st][1]}</span>
    &nbsp;<span class="mono" style="font-size:12.5px">{aid}</span></div></div></div>
  <div><button class="btn">Duplicate</button>
    <button class="btn primary">Edit account</button></div></div>
<div class="card"><div class="tabs"><a class="on">Configuration</a><a>Usage</a>
  <a>Billing</a><a>Integrations</a></div>
<div class="fields">
  <div class="lbl">Display name<small>Shown across the console</small></div><div>{name}</div>
  <div class="lbl">Account ID<small>Immutable</small></div><div class="mono">{aid}</div>
  <div class="lbl">Region<small>Where events are processed</small></div><div>{region}</div>
  <div class="lbl">Plan</div><div>{plan}</div>
  <div class="lbl">Event retention<small>Days before events are purged</small></div><div>90 days</div>
  <div class="lbl">Delivery endpoint</div><div class="mono">https://hooks.{name.split()[0].lower()}.example/ingest</div>
  <div class="lbl">Owner</div><div>Dana Reyes</div>
  <div class="lbl">Created</div><div>14 March 2026</div>
</div></div>""")


def page_settings() -> str:
    return shell("Workspace settings", "settings",
                 '<a href="/settings">Settings</a> <span>/</span> <b>Workspace</b>', """
<h1>Workspace settings</h1>
<div class="sub">Applies to every account in this workspace unless an account overrides it.</div>
<div class="card"><div class="tabs"><a class="on">General</a><a>Members</a>
  <a>API keys</a><a>Notifications</a></div>
<div class="pad" style="max-width:560px">
  <div class="field"><label for="wname">Workspace name</label>
    <input id="wname" value="Meridian Operations">
    <div class="help">Appears in the sidebar and on exported reports.</div></div>
  <div class="field"><label for="region">Default region <small>inherited by new accounts</small></label>
    <select id="region"><option>eu-west-1</option><option>us-east-1</option>
      <option>ap-south-1</option></select></div>
  <div class="field"><label for="ret">Default event retention</label>
    <select id="ret"><option>30 days</option><option selected>90 days</option>
      <option>365 days</option></select>
    <div class="help">An account with its own retention setting keeps it.</div></div>
  <div style="margin-top:22px">
    <div class="toggle"><div class="sw"></div><div><div class="t">Require two-factor sign-in</div>
      <div class="s">Every member must enrol before their next sign-in.</div></div></div>
    <div class="toggle"><div class="sw"></div><div><div class="t">Alert on delivery failure</div>
      <div class="s">Notifies the account owner after three consecutive failures.</div></div></div>
    <div class="toggle"><div class="sw off"></div><div><div class="t">Allow data export by members</div>
      <div class="s">Off, so only workspace owners can export.</div></div></div>
  </div>
  <div style="margin-top:22px"><button class="btn primary">Save changes</button>
    <button class="btn ghost">Cancel</button></div>
</div></div>""")


ROUTES = {
    "/login": page_login,
    "/": page_dashboard,
    "/accounts": page_accounts,
    "/settings": page_settings,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/style.css":
            return self._send((HERE / "style.css").read_bytes(), "text/css")
        if path.startswith("/accounts/") and path[10:].isdigit():
            n = int(path[10:])
            if 1 <= n <= len(ACCOUNTS):
                return self._send(page_account(n).encode(), "text/html")
        fn = ROUTES.get(path.rstrip("/") or "/")
        if fn:
            return self._send(fn().encode(), "text/html")
        self.send_error(404)

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"Meridian running at http://127.0.0.1:{port}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
