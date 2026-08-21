"""AI writing assistance for the console.

Every action here produces a *proposal*. Nothing is written to a section until a
person accepts it, and the console always shows the before and after first. That
boundary is deliberate: the model is good at turning captured evidence into
house-style prose, and bad at knowing when the evidence does not support a claim.

The model is reached through the local `claude` CLI in print mode, so it uses the
sign-in already on this machine and needs no API key. If the CLI is missing or
fails, the console says so and the rest of the pipeline carries on unaffected.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 240

HOUSE_RULES = """You are the technical writer for this product's documentation.


Absolute content rules. A build fails on any of these:
- Never use an em dash. Use a colon, a comma, or rewrite the sentence.
- Never put a URL or a route path in body text. Describe navigation by tab name,
  button label and breadcrumb.
- Document only what a user can see in the interface. No HTTP status codes, no
  token internals, no API paths, no developer-facing values.
- Prefer bullets over prose whenever the content is a list of fields, options or
  steps. Prose is for explanation.
- Never name a customer. Write {{ operator.name }} or {{ operator.role }} instead.
- Never invent a fact. If the evidence does not show what something does, write
  the placeholder and say so in your summary. It contains a colon, so it must be
  quoted: `description: "TODO: describe this."`
- Inside a yaml block, any value containing a colon followed by a space must be
  quoted, or the block will not parse.

Section file format. A section is Markdown with YAML front matter:
- Front matter carries id, title, icon, status, last_verified, screens, sources.
- The title never contains a number: numbering is derived elsewhere.
- Body blocks: paragraphs, `- ` bullets, `1. ` steps, `#### ` sub-headings,
  `> [!Label] text` callouts, `![caption](file.png)` figures,
  `[icon:name.png]` inline UI elements, and fenced yaml blocks named
  fields, actions, columns, terms.

Example of a fields block:
```fields
- field: Publisher Name
  type: Text
  required: true
  description: Name shown in the publishers list, must be unique
```

Callout labels with styling: Note, Tip, Key Concept, Important, Warning,
Access Scope, Example.

Output rules:
- Return the complete section file and nothing else: no commentary, no code
  fence around the whole document, no preamble.
- Preserve the existing front matter unless the task asks you to change it.
- Preserve every existing `![...](...)` figure line exactly as it is.
"""


# Where the model is reached. The order is: an explicit gateway if one is
# configured, then the Anthropic API if a key is present, then the Claude Code
# CLI, which needs no key at all.
#
# A gateway is set per project or per machine, never defaulted to. An earlier
# version of this file defaulted to one company's LiteLLM proxy, which is
# correct inside that company and wrong everywhere else.
#
# ANTHROPIC_BASE_URL is deliberately NOT consulted. It is set per shell and per
# Claude Code session and can point somewhere the operator did not choose for
# this pipeline. Set VERBA_GATEWAY to be explicit about it.
# A project may pin all of this in content/doc.yaml, which is the durable place
# for it: an organisation that meters model usage centrally needs every run to
# go through its gateway, and an environment variable is set per shell and lost
# the moment somebody opens a new terminal.
#
#   assist:
#     gateway: https://gateway.example.com
#     model: claude-sonnet-5
#     key_helper: ~/.config/gateway-key.sh
def _project_assist(root: Path | str = ".") -> dict:
    try:
        import yaml
        cfg = yaml.safe_load(
            (Path(root) / "content" / "doc.yaml").read_text(encoding="utf-8")) or {}
        return cfg.get("assist") or {}
    except Exception:
        return {}


_CFG = _project_assist(os.environ.get("VERBA_ROOT", "."))

LITELLM_BASE = (os.environ.get("VERBA_GATEWAY")
                or os.environ.get("VERBA_LITELLM_BASE")
                or _CFG.get("gateway") or "").rstrip("/")
LITELLM_KEY_HELPER = (os.environ.get("VERBA_KEY_HELPER")
                      or _CFG.get("key_helper") or "")
DEFAULT_MODEL = (os.environ.get("VERBA_MODEL")
                 or _CFG.get("model") or "claude-sonnet-5")


@dataclass
class AssistResult:
    ok: bool
    output: str = ""
    error: str = ""
    task: str = ""
    backend: str = ""


def gateway_key() -> str | None:
    """The gateway key, printed on demand by a helper script.

    Never written to the repository and never logged. The helper is usually a
    one-line script that reads the key out of the OS keychain.
    """
    direct = os.environ.get("VERBA_LITELLM_KEY") or os.environ.get("LITELLM_API_KEY")
    if direct:
        return direct
    # `~` is how a path to a helper is written in a config file by hand, and
    # Path does not expand it on its own, so a perfectly correct setting
    # resolves to a file that does not exist.
    helper = Path(LITELLM_KEY_HELPER).expanduser() if LITELLM_KEY_HELPER else Path("")
    if not helper.exists():
        return None
    try:
        proc = subprocess.run(["bash", str(helper)], capture_output=True,
                              text=True, timeout=15)
    except Exception:
        return None
    key = (proc.stdout or "").strip()
    return key or None


def backends() -> list[dict]:
    """What the console can reach, in preference order.

    The gateway comes first: it is the sanctioned route for Claude access here,
    and unlike the CLI it also works when the console is launched from inside
    another Claude Code session, where a nested CLI invocation blocks.
    """
    out = []

    try:
        import anthropic  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False

    key = gateway_key()
    host = LITELLM_BASE.replace("https://", "").replace("http://", "")
    if not sdk:
        note = "the anthropic package is not installed"
        ready = False
    elif not key:
        note = (f"no key. The helper {LITELLM_KEY_HELPER} returned nothing: check the "
                f"keychain entry 'rise-ai-hub-gateway', or set VERBA_LITELLM_KEY.")
        ready = False
    else:
        note = f"{host}, key from the keychain, model {DEFAULT_MODEL}"
        ready = True
    out.append({"id": "litellm", "label": f"Rise AI Hub ({DEFAULT_MODEL})",
                "ready": ready, "note": note})

    if os.environ.get("ANTHROPIC_API_KEY") and sdk:
        out.append({"id": "api", "label": "Anthropic API direct", "ready": True,
                    "note": "ANTHROPIC_API_KEY is set. The gateway is preferred so "
                            "usage stays metered centrally."})

    exe = os.environ.get("VERBA_CLAUDE", "claude")
    path = shutil.which(exe)
    out.append({
        "id": "cli", "label": "Claude Code CLI", "ready": bool(path),
        "note": (f"{path}. Works from an ordinary terminal: a nested call blocks when "
                 f"the console is started from inside another Claude Code session."
                 if path else
                 f"{exe!r} not found. Install Claude Code or set VERBA_CLAUDE."),
    })
    return out


def available() -> tuple[bool, str]:
    ready = [b for b in backends() if b["ready"]]
    if not ready:
        return False, ("no way to reach a model. Set ANTHROPIC_API_KEY, or install "
                       "the Claude Code CLI.")
    return True, ready[0]["id"]


# Extended thinking is counted inside max_tokens. At 8000 this model could
# spend the entire budget reasoning and return a reply whose only content block
# was `thinking`, with no text at all: a successful call, an empty answer, and
# every downstream check then failing for an invented reason.
MAX_TOKENS = 16000
MAX_TOKENS_RETRY = 32000


def _text_of(msg) -> str:
    return "".join(b.text for b in msg.content
                   if getattr(b, "type", "") == "text")


def _call_messages(client, system: str, prompt: str, backend: str) -> AssistResult:
    budget = MAX_TOKENS
    for attempt in (1, 2):
        msg = client.messages.create(
            model=DEFAULT_MODEL, max_tokens=budget, system=system,
            messages=[{"role": "user", "content": prompt}])
        text = _text_of(msg).strip()
        stop = getattr(msg, "stop_reason", "")

        if text and stop != "max_tokens":
            return AssistResult(True, output=text, backend=backend)

        if attempt == 1:
            # Ran out of room. Thinking is charged against the same budget, so
            # a section with a lot of evidence can exhaust it before writing a
            # word. Once more with room to finish.
            budget = MAX_TOKENS_RETRY
            continue

        thought = sum(1 for b in msg.content if getattr(b, "type", "") == "thinking")
        if not text:
            return AssistResult(False, backend=backend, error=(
                f"the model returned no text. It stopped because {stop!r} after "
                f"{msg.usage.output_tokens} token(s)"
                + (f", all of it thinking" if thought else "")
                + f", even with {budget} to work in. The section may be too "
                  f"large to rewrite in one piece."))
        return AssistResult(False, backend=backend, error=(
            f"the model ran out of room after {msg.usage.output_tokens} token(s) "
            f"and its answer is cut off, so it was not used."))
    return AssistResult(False, backend=backend, error="no answer")


def _run_litellm(prompt: str, system: str, timeout: int) -> AssistResult:
    import anthropic
    key = gateway_key()
    if not key:
        return AssistResult(False, backend="litellm",
                            error="the Rise AI Hub key could not be read")
    client = anthropic.Anthropic(base_url=LITELLM_BASE, api_key=key, timeout=timeout)
    return _call_messages(client, system, prompt, "litellm")


def _run_api(prompt: str, system: str, timeout: int) -> AssistResult:
    import anthropic
    client = anthropic.Anthropic(timeout=timeout)
    return _call_messages(client, system, prompt, "api")


def _run_cli(prompt: str, system: str, timeout: int) -> AssistResult:
    path = shutil.which(os.environ.get("VERBA_CLAUDE", "claude"))
    proc = subprocess.run(
        [path, "-p", "--output-format", "text", "--append-system-prompt", system],
        input=prompt, capture_output=True, text=True, timeout=timeout,
        # a neutral working directory: the assistant reasons from the prompt, not
        # from whatever happens to be in the project folder
        cwd=str(Path.home()))
    if proc.returncode != 0:
        return AssistResult(False, backend="cli",
                            error=(proc.stderr or proc.stdout or "no output")[:600])
    return AssistResult(True, output=proc.stdout.strip(), backend="cli")


def house_rules(root: Path | str = ".") -> str:
    """The writing rules, with this product's description in front of them.

    The rules are about craft and are the same everywhere. What the product is,
    what its words mean and which of two readings is right are things only the
    project can say, and they come from content/system.md. Putting the
    description first matters: it is the part the model should weigh most
    heavily, and the part it has no other way of knowing.
    """
    from ..system import System
    return f"{System.load(root).prompt_block()}\n\n---\n\n{HOUSE_RULES}"


def run_model(prompt: str, system: str | None = None,
              timeout: int = DEFAULT_TIMEOUT, log=None,
              backend: str | None = None,
              root: Path | str = ".") -> AssistResult:
    # None, not HOUSE_RULES, because the default has to be read from the
    # project at call time: a module-level default would bake in whichever
    # product happened to be loaded when this module was imported.
    system = house_rules(root) if system is None else system
    ready = [b for b in backends() if b["ready"]]
    if not ready:
        return AssistResult(False, error=available()[1])
    chosen = backend or ready[0]["id"]
    if log:
        label = next((b["label"] for b in ready if b["id"] == chosen), chosen)
        log(f"asking {label}, up to {timeout}s ...")
    try:
        if chosen == "litellm":
            return _run_litellm(prompt, system, timeout)
        if chosen == "api":
            return _run_api(prompt, system, timeout)
        return _run_cli(prompt, system, timeout)
    except subprocess.TimeoutExpired:
        return AssistResult(False, backend=chosen, error=(
            f"no answer within {timeout}s. If the console was started from inside "
            f"another Claude Code session, the nested CLI call blocks: run the console "
            f"from a normal terminal, or set ANTHROPIC_API_KEY to use the API instead."))
    except Exception as e:
        return AssistResult(False, backend=chosen, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- context


def _evidence(project, section, inventory: dict, drift: list) -> str:
    """Everything the model is allowed to reason from, and nothing else."""
    parts = []
    node = next((n for n in project.nodes if n.id == section.id), None)
    parts.append(f"Section id: {section.id}")
    parts.append(f"Number in the document: {node.number if node else 'unknown'}")
    parts.append(f"Title: {section.title}")
    if section.screens:
        parts.append(f"Screens it documents: {', '.join(section.screens)}")

    if inventory:
        parts.append("\nWhat the last crawl actually read off those screens:")
        for screen_id, rec in inventory.items():
            parts.append(f"  screen {screen_id} at {rec.get('url','unknown address')}")
            for kind, values in (rec.get("elements") or {}).items():
                if values:
                    parts.append(f"    {kind}: {' | '.join(values)}")
        parts.append(
            "\nEntity names above are already masked placeholders such as "
            "'Test Publisher 1'. Treat them as the real labels.")
    else:
        parts.append("\nNo crawl evidence is available for this section.")

    if drift:
        parts.append("\nDifferences the crawl found against the current text:")
        for c in drift:
            parts.append(f"  - {c.get('line', '')}")
    return "\n".join(parts)


def _lint_notes(findings) -> str:
    if not findings:
        return "No rule findings are open on this section."
    return "Open rule findings on this section:\n" + "\n".join(
        f"  - {f.get('rule')} ({f.get('level')}): {f.get('message')} {f.get('detail','')}"
        for f in findings)


# ---------------------------------------------------------------- tasks

TASKS = {
    "polish": "Rewrite to house style",
    "reconcile": "Apply the crawl differences",
    "fill_todos": "Write the missing descriptions",
    "draft": "Draft this section from the crawl",
    "review": "Review and report, do not rewrite",
}


def build_prompt(task: str, project, section, inventory, drift, findings,
                 notes: str = "") -> str:
    evidence = _evidence(project, section, inventory, drift)
    current = section.to_markdown()
    lint = _lint_notes(findings)
    if notes:
        evidence += f"\n\n{notes}"

    if task == "polish":
        instruction = (
            "Rewrite the section below so it follows the house rules. Fix any rule "
            "finding listed. Convert list-like prose into bullets or into a fields, "
            "actions or columns block where that fits. Do not add any fact that is "
            "not already in the text or in the evidence. Do not remove figures.")
    elif task == "reconcile":
        instruction = (
            "Update the section so it matches the crawl evidence. Apply the listed "
            "differences: rename what was renamed, add what is new, remove what is "
            "gone. For anything newly added, write a description only if the "
            "evidence supports one, otherwise write 'TODO: describe this.'")
    elif task == "fill_todos":
        instruction = (
            "Replace every description that currently reads 'TODO: describe this.' "
            "with a real description, using the crawl evidence and the surrounding "
            "context. If the evidence does not tell you what an item does, leave the "
            "TODO exactly as it is rather than guessing.")
    elif task == "draft":
        instruction = (
            "Write this section from the crawl evidence. Cover what the screen shows: "
            "its controls, its table columns or form fields, and what a user does "
            "there. Keep the existing front matter and any existing figure lines. "
            "Where the evidence does not support an explanation, write "
            "'TODO: describe this.'")
    elif task == "review":
        return (
            "Review this documentation section against the house rules and the crawl "
            "evidence. Report only: anything factually contradicted by the evidence, "
            "anything the screen shows that the section omits, rule violations, and "
            "unclear wording. Be specific and brief, as a short bulleted list. Do NOT "
            "rewrite the section and do NOT output a section file.\n\n"
            f"=== EVIDENCE ===\n{evidence}\n\n=== {lint} ===\n\n"
            f"=== CURRENT SECTION ===\n{current}\n")
    else:
        raise ValueError(f"unknown assist task {task!r}")

    return (f"{instruction}\n\n=== EVIDENCE ===\n{evidence}\n\n{lint}\n\n"
            f"=== CURRENT SECTION FILE ===\n{current}\n\n"
            f"Return the complete updated section file and nothing else.")


def clean_output(text: str) -> str:
    """Strip a wrapping code fence if the model added one."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip() + "\n"
