"""Read every form, field and screen, and change none of them.

The crawler already collects the labels a screen shows. That is enough to notice
a rename and not much else: it cannot tell you that Publisher Name is required,
that Status offers exactly two values, or that a field the document calls a text
box is really a dropdown. Those are the things a reader relies on and the things
that quietly change.

Everything here is a **read**. The inspector never types, never focuses, never
clicks, never dispatches an event, and never calls `checkValidity()` or
`reportValidity()`, both of which fire an `invalid` event that application code
is free to act on. It reads attributes, the live `validity` object, option
lists, and the accessibility relationships the page declares. A constraint that
can only be discovered by entering a bad value is deliberately not discovered:
that would be a write, and this system does not write.

`verba/readonly.py` is the second line. This module is the first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Everything below runs in the page. Every expression is a getter.
INSPECT_JS = r"""
() => {
  // Zero-width characters are everywhere in this product's markup, used as
  // layout spacers. Left in, every field comes back named "".
  const ZW = /[\u200B-\u200D\uFEFF\u2060]/g;
  const clean = (s) => (s || '').replace(ZW, '').trim().replace(/\s+/g, ' ');
  const txt = (el) => clean(el && (el.innerText || el.textContent) || '');
  const attr = (el, ...names) => {
    for (const n of names) {
      const v = el.getAttribute && el.getAttribute(n);
      if (v !== null && v !== undefined && String(v).trim() !== '') return String(v).trim();
    }
    return '';
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
  };

  const CONTROLS = 'input:not([type=hidden]),select,textarea,[role=combobox],[role=switch],[contenteditable=true]';

  // How a control gets its name, in the order a screen reader would try, and
  // recorded so a weak source can be reported rather than silently accepted.
  const nameOf = (el) => {
    const byAria = clean(attr(el, 'aria-label'));
    if (byAria) return { text: byAria, from: 'aria-label' };

    const ref = attr(el, 'aria-labelledby');
    if (ref) {
      const parts = ref.split(/\s+/).map(id => document.getElementById(id))
        .filter(Boolean).map(txt).filter(Boolean);
      if (parts.length) return { text: parts.join(' '), from: 'aria-labelledby' };
    }
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab && txt(lab)) return { text: txt(lab), from: 'label' };
    }
    const wrap = el.closest('label');
    if (wrap && txt(wrap)) return { text: txt(wrap), from: 'wrapping label' };

    // Material UI without MuiFormLabel, which is what this product is: no
    // <label> element exists anywhere, so the name is whatever text the eye
    // reads immediately above the control.
    //
    // "Nearest text" alone is not enough. Walking up containers finds the
    // group's heading, and walking back through siblings finds the field
    // above, so the last input on a form ends up wearing its neighbour's
    // label. The rule that actually holds: a control is named by the text
    // between it and the control before it. Nothing earlier can belong to it,
    // because that text is the previous field's.
    const OWN = new Set([clean(attr(el, 'placeholder')), clean(el.value || '')]);
    const usable = (t) => t && t.length < 60 && !OWN.has(t) && !/^[^a-z0-9]+$/i.test(t);

    const container = el.closest('form, fieldset, [role=dialog], main, body') || document.body;
    const walker = document.createTreeWalker(
      container, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    const before = [];          // usable text since the previous control
    let found = false;
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (n === el) { found = true; break; }
      if (n.nodeType === 1) {
        if (n.matches(CONTROLS)) { before.length = 0; continue; }   // new field starts here
        continue;
      }
      const t = clean(n.nodeValue);
      if (usable(t)) before.push(t);
    }
    if (found && before.length) {
      // the closest line wins: "Partner Name *" beats the panel heading above it
      return { text: before[before.length - 1], from: 'nearby text' };
    }

    const ph = clean(attr(el, 'placeholder'));
    if (ph) return { text: ph, from: 'placeholder' };
    return { text: '', from: 'none' };
  };

  const kindOf = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'select') return el.multiple ? 'multi-select' : 'dropdown';
    if (tag === 'textarea') return 'text area';
    const t = (el.type || 'text').toLowerCase();
    return ({ checkbox: 'checkbox', radio: 'radio option', number: 'number',
              email: 'email', password: 'password', date: 'date', file: 'file',
              search: 'search', tel: 'telephone', url: 'address',
              range: 'slider', color: 'colour' })[t] || 'text';
  };

  // Declared constraints only. A rule that reveals itself solely by entering a
  // bad value stays unknown: finding it out would mean typing into a live
  // system.
  const rulesOf = (el) => {
    const r = {};
    if (el.required || el.getAttribute('aria-required') === 'true') r.required = true;
    const num = (n) => { const v = attr(el, n); return v === '' ? undefined : v; };
    for (const [key, a] of [['max_length', 'maxlength'], ['min_length', 'minlength'],
                            ['min', 'min'], ['max', 'max'], ['step', 'step'],
                            ['pattern', 'pattern']]) {
      const v = num(a);
      if (v !== undefined) r[key] = v;
    }
    if (el.readOnly) r.read_only = true;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') r.disabled = true;
    const v = el.validity;
    if (v) {
      // A read of the live ValidityState. It is computed on access and fires
      // nothing, unlike checkValidity(), which dispatches an invalid event.
      const flags = ['patternMismatch', 'rangeOverflow', 'rangeUnderflow',
                     'stepMismatch', 'tooLong', 'tooShort', 'typeMismatch',
                     'valueMissing'].filter(f => v[f]);
      if (flags.length) r.currently_invalid = flags;
    }
    return r;
  };

  const optionsOf = (el) => {
    if (el.tagName.toLowerCase() === 'select') {
      return Array.from(el.options).map(o => txt(o) || o.value).filter(Boolean).slice(0, 40);
    }
    if (el.type === 'radio' && el.name) {
      const group = document.querySelectorAll(
        `input[type="radio"][name="${CSS.escape(el.name)}"]`);
      return Array.from(group).map(g => nameOf(g).text).filter(Boolean).slice(0, 40);
    }
    const list = el.getAttribute && el.getAttribute('list');
    if (list) {
      const dl = document.getElementById(list);
      if (dl) return Array.from(dl.options).map(o => o.value).filter(Boolean).slice(0, 40);
    }
    return [];
  };

  const helpOf = (el) => {
    const ref = attr(el, 'aria-describedby', 'aria-errormessage');
    if (!ref) return '';
    return ref.split(/\s+/).map(id => document.getElementById(id))
      .filter(Boolean).map(txt).filter(Boolean).join(' ');
  };

  // This product marks a required field with a trailing asterisk on its
  // visible name and nothing in the markup. Left alone, "Partner Name *" ends
  // up as a field name in the document, and the requirement goes unrecorded.
  const STAR = /\s*[*\uFF0A\u2217]\s*$/;

  const describe = (el, formIndex) => {
    const name = nameOf(el);
    const rules = rulesOf(el);
    if (STAR.test(name.text)) {
      name.text = name.text.replace(STAR, '');
      if (!rules.required) { rules.required = true; rules.required_from = 'asterisk'; }
    }
    const opts = optionsOf(el);
    const notes = [];
    if (name.from === 'none') notes.push('no accessible name at all');
    else if (name.from === 'placeholder')
      notes.push('named only by its placeholder, which disappears once typing starts');
    else if (name.from === 'nearby text' || name.from === 'preceding text')
      notes.push('no label element: the name is read from adjacent text');
    if (el.type === 'radio' && !el.name) notes.push('radio with no group name');
    if (rules.required && name.from === 'none') notes.push('required but unnamed');

    return {
      name: name.text, name_from: name.from,
      kind: kindOf(el),
      placeholder: attr(el, 'placeholder'),
      help: helpOf(el),
      rules: rules,
      options: opts,
      has_value: !!(el.value && String(el.value).trim()),
      form: formIndex,
      findings: notes,
    };
  };

  // When a dialog is open it is the screen. Reading the list behind it would
  // report the page's filter toggles as fields of the form being documented.
  const openDialog = Array.from(document.querySelectorAll(
      '[role=dialog],[role=alertdialog],dialog[open],.MuiDialog-root,.MuiModal-root'))
    .filter(visible).pop();
  const scope = openDialog || document;
  const inScope = (el) => scope === document || scope.contains(el);

  const forms = [];
  const seen = new Set();

  Array.from(scope.querySelectorAll('form')).forEach((f, i) => {
    if (!visible(f)) return;
    const controls = Array.from(f.querySelectorAll(CONTROLS)).filter(visible);
    controls.forEach(c => seen.add(c));
    const submits = Array.from(f.querySelectorAll(
      'button,[type=submit],[role=button]')).filter(visible).map(txt).filter(Boolean);
    forms.push({
      index: i,
      name: (clean(attr(f, 'aria-label', 'name', 'id')) ||
             txt(f.querySelector('legend,h1,h2,h3,[class*="title" i]')) || '')
            .replace(STAR, ''),
      fields: controls.map(c => describe(c, i)),
      actions: submits.slice(0, 12),
      // Recorded, never used. Knowing where a form would post is useful in a
      // review; the crawler is forbidden from ever posting it.
      would_submit_to: attr(f, 'action') || '(same address)',
      method: (attr(f, 'method') || 'get').toUpperCase(),
    });
  });

  // Controls outside any <form>, which is most of a modern application.
  const loose = Array.from(scope.querySelectorAll(CONTROLS))
    .filter(visible).filter(c => !seen.has(c)).filter(inScope);
  if (loose.length) {
    forms.push({
      index: -1, name: '(controls not inside a form)',
      fields: loose.map(c => describe(c, -1)),
      actions: Array.from(scope.querySelectorAll('button,[role=button]'))
        .filter(visible).map(txt).filter(Boolean).slice(0, 20),
      would_submit_to: '', method: '',
    });
  }

  return {
    forms: forms,
    scoped_to: openDialog ? 'the open dialog' : 'the whole page',
    counts: {
      forms: forms.filter(f => f.index >= 0).length,
      fields: forms.reduce((n, f) => n + f.fields.length, 0),
      required: forms.reduce((n, f) =>
        n + f.fields.filter(x => x.rules.required).length, 0),
      unlabelled: forms.reduce((n, f) =>
        n + f.fields.filter(x => x.name_from === 'none' ||
                                 x.name_from === 'placeholder').length, 0),
    },
  };
}
"""


@dataclass
class FieldReport:
    screen: str
    name: str
    kind: str
    required: bool = False
    options: list = field(default_factory=list)
    rules: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)


def inspect(page, log=None) -> dict:
    """Read the forms on the current page. Performs no interaction."""
    try:
        data = page.evaluate(INSPECT_JS)
    except Exception as e:
        if log:
            log(f"    form inspection skipped: {e}")
        return {"forms": [], "counts": {}}
    if log:
        c = data.get("counts", {})
        if c.get("fields"):
            line = (f"    read {c.get('fields', 0)} field(s) in "
                    f"{c.get('forms', 0)} form(s), {c.get('required', 0)} required")
            if c.get("unlabelled"):
                line += f", {c['unlabelled']} with no proper label"
            log(line)
    return data


def scrub(data: dict, masker) -> dict:
    """Run the same name masking over what was read.

    Field values and option lists carry publisher and partner names, and this
    inventory ends up quoted in the review queue and in the document.
    """
    if not data or masker is None:
        return data

    def clean(x):
        if isinstance(x, str):
            return masker.scrub_text(x)
        if isinstance(x, list):
            return [clean(i) for i in x]
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        return x

    return clean(data)


# ---------------------------------------------------------------------------
def declared_fields(section) -> dict:
    """What the document says a screen's fields are, keyed by lower-cased name."""
    out = {}
    for b in section.blocks:
        if b.kind not in ("fields", "field_list", "fields_list"):
            continue
        for it in b.items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("field") or it.get("name") or "").strip()
            if name:
                out[name.lower()] = it
    return out


REQUIRED_WORDS = re.compile(r"\b(required|mandatory|must be (?:set|entered|provided))\b", re.I)


def compare(section, observed: dict) -> list[dict]:
    """Differences between what the document claims and what the screen shows.

    Only about constraints. Names and their comings and goings are drift's job;
    this is the layer underneath, where a field that quietly became required, or
    a dropdown that gained an option, would otherwise go unnoticed for a year.
    """
    declared = declared_fields(section)
    findings = []
    for form in observed.get("forms", []):
        for f in form.get("fields", []):
            key = (f.get("name") or "").strip().lower()
            if not key or key not in declared:
                continue
            doc = declared[key]
            blurb = " ".join(str(v) for v in doc.values())
            says_required = bool(doc.get("required")) or bool(REQUIRED_WORDS.search(blurb))
            is_required = bool(f.get("rules", {}).get("required"))

            if is_required and not says_required:
                findings.append({
                    "kind": "constraint", "change": "became_required",
                    "section": section.id, "label": f["name"],
                    "line": f"{f['name']} is required on the screen, "
                            f"and the document does not say so",
                    "confidence": 0.95})
            elif says_required and not is_required:
                findings.append({
                    "kind": "constraint", "change": "no_longer_required",
                    "section": section.id, "label": f["name"],
                    "line": f"the document calls {f['name']} required, "
                            f"and the screen does not mark it so",
                    "confidence": 0.8})

            opts = f.get("options") or []
            if opts:
                missing = [o for o in opts if o.lower() not in blurb.lower()]
                if missing and len(missing) < len(opts):
                    findings.append({
                        "kind": "constraint", "change": "options_changed",
                        "section": section.id, "label": f["name"],
                        "became": ", ".join(opts),
                        "line": f"{f['name']} offers {len(opts)} choice(s); "
                                f"the document does not mention {', '.join(missing[:4])}",
                        "confidence": 0.75})

            max_len = f.get("rules", {}).get("max_length")
            if max_len and str(max_len) not in blurb:
                findings.append({
                    "kind": "constraint", "change": "limit_undocumented",
                    "section": section.id, "label": f["name"],
                    "became": str(max_len),
                    "line": f"{f['name']} accepts at most {max_len} characters, "
                            f"which the document does not mention",
                    "confidence": 0.6})
    return findings


def accessibility(observed: dict, screen_id: str) -> list[dict]:
    """What the screen does not tell assistive technology.

    Not documentation faults. They are reported because the crawler is already
    looking, they are cheap to collect, and a field with no accessible name is
    also a field the crawler struggles to name in the document.
    """
    out = []
    for form in observed.get("forms", []):
        for f in form.get("fields", []):
            for note in f.get("findings", []):
                out.append({"screen": screen_id,
                            "field": f.get("name") or "(unnamed)",
                            "kind": f.get("kind"), "issue": note})
    return out


def summary(data: dict) -> dict:
    c = dict(data.get("counts") or {})
    c.setdefault("forms", 0)
    c.setdefault("fields", 0)
    return c
