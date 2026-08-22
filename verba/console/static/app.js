/* verba console */
import { icon, iconSprite } from './icons.js';

const $ = (s, r = document) => r.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c;
  if (h !== undefined) e.innerHTML = h; return e; };
// A dialog body is sometimes markup and sometimes a built element. `el`'s third
// argument is innerHTML, so passing a node there stringifies it to
// "[object HTMLDivElement]" and the dialog comes up empty.
const fill = (host, content) => {
  if (content == null) return host;
  if (content instanceof Node) host.append(content);
  else host.innerHTML = content;
  return host;
};
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

let S = null;            // server state
let view = 'overview';
let currentId = null;
let dirty = false;

async function api(path, opts) {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json' }, ...opts,
    body: opts && opts.json ? JSON.stringify(opts.json) : undefined
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.error || `${r.status}`);
  return d;
}

/* A short line stays on screen; the rest lives behind the marker. */
let hintSeq = 0;
const HINTS = new Map();

function hint(text) {
  const id = 'h' + (++hintSeq);
  HINTS.set(id, text);
  // the visible "i" is drawn by the ::before, so the button itself can be a
  // 28px target without the mark growing with it
  return `<button class="hint" data-hint="${id}" data-mark="i" aria-expanded="false"
    aria-label="More about this"></button>`;
}

function closeHints() {
  document.querySelectorAll('.pop').forEach(p => p.remove());
  document.querySelectorAll('button.hint[aria-expanded="true"]')
    .forEach(b => b.setAttribute('aria-expanded', 'false'));
}

document.addEventListener('click', e => {
  const btn = e.target.closest && e.target.closest('button.hint');
  if (!btn) { closeHints(); return; }
  const open = btn.getAttribute('aria-expanded') === 'true';
  closeHints();
  if (open) return;
  const body = HINTS.get(btn.dataset.hint);
  if (!body) return;
  btn.setAttribute('aria-expanded', 'true');
  const pop = el('div', 'pop', body);
  document.body.append(pop);
  const r = btn.getBoundingClientRect();
  const w = Math.min(340, window.innerWidth - 24);
  pop.style.width = w + 'px';
  pop.style.left = Math.max(12, Math.min(r.left - 8, window.innerWidth - w - 12)) + 'px';
  const below = window.innerHeight - r.bottom;
  if (below > pop.offsetHeight + 16) pop.style.top = (r.bottom + 8) + 'px';
  else pop.style.top = Math.max(12, r.top - pop.offsetHeight - 8) + 'px';
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHints(); });

/* An in-app dialog. The browser's confirm() cannot be styled, cannot hold a
   reason field, and looks like a page from 2004. */
function modal({ title, body, confirmLabel, confirmClass, needsReason, onConfirm }) {
  return new Promise(resolve => {
    const scrim = el('div', 'scrim');
    const box = el('div', 'modal');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.append(el('h3', null, (needsReason ? icon('x') : icon('alert')) + esc(title)));
    box.append(fill(el('div', 'body'), body));

    let ta = null;
    if (needsReason) {
      const f = el('div', 'field');
      f.innerHTML = `<label for="mReason">Why are you declining this?</label>
        <textarea id="mReason" placeholder="This is kept, and every later crawl and
proposal is told about it."></textarea>`;
      box.append(f);
    }

    const foot = el('div', 'foot');
    const cancel = el('button', 'act ghost', 'Cancel');
    const ok = el('button', 'act ' + (confirmClass || 'primary'), confirmLabel || 'Confirm');
    const close = (v) => { scrim.remove(); document.removeEventListener('keydown', key); resolve(v); };
    const key = (e) => { if (e.key === 'Escape') close(null); };
    cancel.onclick = () => close(null);
    ok.onclick = async () => {
      const reason = ta ? ta.value.trim() : '';
      if (needsReason && !reason) {
        ta.focus();
        toast('A reason is needed. The next crawl reads it.', true);
        return;
      }
      ok.disabled = true;
      close(await (onConfirm ? onConfirm(reason) : reason || true));
    };
    foot.append(cancel, ok);
    box.append(foot);
    scrim.append(box);
    scrim.onclick = (e) => { if (e.target === scrim) close(null); };
    document.body.append(scrim);
    document.addEventListener('keydown', key);
    ta = $('#mReason');
    (ta || ok).focus();
  });
}

/* The dock: a running task shows here rather than taking over the view, so you
   keep your place and can watch a crawl while reading the section it is about. */
let dockEl = null;

/* modal() is callback shaped, which reads badly at a call site that just wants
   a yes or no before carrying on. This is the same dialog, awaited. */
async function ask(opts) {
  // modal() resolves null when dismissed, and true when confirmed with no
  // handler of its own. That is exactly a yes or no.
  return (await modal(opts)) !== null;
}

const leaveDirty = () => ask({
  title: 'Leave without saving?',
  body: 'This section has edits that have not been saved.',
  confirmLabel: 'Leave', confirmClass: 'danger',
});

function dock({ name, onCancelView }) {
  if (dockEl) dockEl.remove();
  const d = el('div', 'dock');
  d.innerHTML = `
    <div class="bar">
      <span class="spin"></span>
      <span class="name">${esc(name)}</span>
      <button class="fold" title="Minimise">&minus;</button>
      <button class="close" title="Close">&times;</button>
    </div>
    <div class="where"></div>
    <div class="lines"></div>
    <div class="foot"></div>`;
  document.body.append(d);
  dockEl = d;
  d.querySelector('.fold').onclick = () => d.classList.toggle('min');
  d.querySelector('.close').onclick = () => { d.remove(); dockEl = null; };
  return {
    root: d,
    setState(state, label) {
      const bar = d.querySelector('.bar');
      const spin = bar.querySelector('.spin');
      if (spin && state !== 'running') {
        const dot = el('span', 'dot-state ' + state);
        spin.replaceWith(dot);
      }
      if (label) bar.querySelector('.name').textContent = label;
    },
    where(text) {
      const w = d.querySelector('.where');
      w.textContent = text || '';
      w.style.display = text ? '' : 'none';
    },
    frame(src) {
      let img = d.querySelector('img.frame');
      if (!img) {
        img = el('img', 'frame');
        d.querySelector('.where').after(img);
      }
      img.src = src;
    },
    log(lines) {
      const box = d.querySelector('.lines');
      lines.forEach(line => {
        const cls = /error|failed|!\s|refused/i.test(line) ? 'e'
          : /^\s*(done|captured|released|rendering|signed in|proposal)/i.test(line) ? 'k' : '';
        box.append(el('div', cls, esc(line)));
      });
      box.scrollTop = box.scrollHeight;
    },
    action(label, cls, fn) {
      const b = el('button', 'act ' + (cls || ''), label);
      b.onclick = fn;
      d.querySelector('.foot').append(b);
      return b;
    },
  };
}

function toast(msg, bad) {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const t = el('div', 'toast' + (bad ? ' bad' : ''), esc(msg));
  document.body.appendChild(t);
  setTimeout(() => t.remove(), bad ? 8000 : 3800);
}

async function refresh() {
  S = await api('/api/state');
  $('#profile').innerHTML = S.profiles
    .map(p => `<option ${p === S.profile ? 'selected' : ''}>${esc(p)}</option>`).join('');
  // The application is Verba and it is always Verba. What changes is which
  // document you have open, so that is what the second line says, and clicking
  // it is how you change it.
  const dt = $('#docTitle');
  // A line of text that silently does something when clicked is not a control.
  // It reads as a caption, so nobody clicks it, and the feature may as well not
  // exist. This one says what it is and looks like it can be pressed.
  dt.innerHTML = `<span class="dnow">${esc(S.product.name)}</span>` +
                 `<svg class="dchev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
                    aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>`;
  dt.setAttribute('role', 'button');
  dt.setAttribute('tabindex', '0');
  dt.title = 'Switch document, or start a new one';
  dt.onclick = documentPicker;
  dt.onkeydown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); documentPicker(); }
  };
  drawNav(); drawTree();
  render();
}

/* ---------------------------------------------------------------- tree */
/* Twelve places, listed flat, made every one of them look equally important.
   The rule is that primary navigation and the things you set up once have to
   be separated, so they are: the top group is the working day, the rest is
   grouped and quieter, and the last group is shut until you want it.

   Grouped by what you came to do, not by what the thing is. "Images" and
   "Fields" are both evidence from the crawl; "Connections" and "Design" are
   both setup; History is neither, and lives with the evidence because that is
   what you go there to read. */
/* The rail is the process, not a shelf of nouns.

   This was a flat list: Overview, To fix, Changes, Sections, Document, Images,
   Fields, History, and a Setup drawer. Every entry true, none of them saying
   what to do first, and the same 38 sections listed twice, once as "Sections"
   and again as the outline underneath it. A person who already knew the
   pipeline could work it. Nobody else could tell where they were in it.

   Documenting a system is a sequence and it has a current position:

     connect -> capture -> review -> write -> check -> publish

   So the rail is that sequence, each step carrying its own state, and the step
   with work in it is marked. It is not a wizard: every step stays clickable at
   all times, because a person who wants to jump to Publish on a Tuesday is not
   confused, they are working. What changes is that the order is now visible to
   someone seeing this for the first time.

   `state(S)` returns the one line under a step, and the tone that colours its
   mark. Tone never carries meaning alone: the line says the same thing. */
const STAGES = [
  {
    id: 'connections', n: 1, label: 'Connect', icon: 'connections',
    state: (s) => {
      const act = ((s.environments || {}).items || []).find(x => x.active);
      if (!act) return { line: 'no system chosen yet', tone: 'todo' };
      return act.ready
        ? { line: `${act.label || act.id}, ready`, tone: 'done' }
        : { line: act.status || 'not ready', tone: 'blocked' };
    },
  },
  {
    id: 'capture', n: 2, label: 'Capture', icon: 'camera',
    state: (s) => {
      const cap = s.capture || {};
      if (!cap.run) return { line: 'nothing photographed yet', tone: 'todo' };
      const imgs = (s.summary || {}).assets || 0;
      return { line: `${ago(cap.run)} · ${imgs} image${imgs === 1 ? '' : 's'}`,
               tone: (s.summary || {}).stale ? 'attention' : 'done' };
    },
  },
  {
    id: 'queue', n: 3, label: 'Review', icon: 'queue',
    state: (s) => {
      const d = (s.summary || {}).drift_items || 0;
      return d
        ? { line: `${d} change${d === 1 ? '' : 's'} from the live system`, tone: 'attention' }
        : { line: 'matches the live system', tone: 'done' };
    },
  },
  {
    id: 'sections', n: 4, label: 'Write', icon: 'sections',
    state: (s) => {
      const sum = s.summary || {};
      const n = sum.sections || 0;
      const unverified = n - (sum.verified || 0);
      return unverified
        ? { line: `${n} sections · ${unverified} not verified`, tone: 'attention' }
        : { line: `${n} sections, all verified`, tone: 'done' };
    },
  },
  {
    id: 'findings', n: 5, label: 'Check', icon: 'alert',
    state: (s) => {
      const sum = s.summary || {};
      if (sum.error) return { line: `${sum.error} thing${sum.error === 1 ? '' : 's'} block a build`,
                              tone: 'blocked' };
      if (sum.warning) return { line: `${sum.warning} worth a look`, tone: 'attention' };
      return { line: 'breaks no rules', tone: 'done' };
    },
  },
  {
    id: 'publish', n: 6, label: 'Publish', icon: 'publish',
    state: (s) => {
      const sum = s.summary || {};
      if (sum.error) return { line: 'blocked until Check is clear', tone: 'todo' };
      return { line: `${s.next_version || 'a version'} ready to cut`, tone: 'ready' };
    },
  },
];

/* Not steps. Things you go and look at, at any point, and which have no place
   in a sequence: the document as it prints, the evidence a crawl gathered, and
   the record of every change. */
const LOOK = [
  ['document', 'Document', 'document'],
  ['screens',  'Screens',  'overview'],
  ['images',   'Images',   'camera'],
  ['fields',   'Fields',   'form'],
  ['masking',  'Names',    'shield'],
  ['history',  'History',  'history'],
];

/* Set once and then left alone, which is why it stays shut. */
const SETUP = [
  ['documents', 'Documents', 'layers'],
  ['editions',  'Editions',  'sections'],
  ['design',    'Design',    'palette'],
  ['assistant', 'The writer', 'sparkle'],
];

const NAV = [
  { items: STAGES.map(s => [s.id, s.label, s.icon]) },
  { label: 'Look at', items: LOOK },
  { label: 'Set up', fold: true, items: SETUP },
];

/* Where the work is right now: the first step that is not done.

   Used to decide what to open on arrival and which step to mark, so the two can
   never disagree about what the person should be looking at. */
function currentStage() {
  const found = STAGES.find(st => {
    const tone = st.state(S).tone;
    return tone === 'blocked' || tone === 'attention' || tone === 'todo';
  });
  return found || STAGES[STAGES.length - 1];
}

function ago(stamp) {
  // capture runs are stamped 2026-08-21T211503
  const m = String(stamp || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return 'captured';
  const then = new Date(+m[1], +m[2] - 1, +m[3]);
  const days = Math.round((Date.now() - then) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  return `${Math.round(days / 30)} months ago`;
}

const NAV_IDS = NAV.flatMap(g => g.items.map(i => i[0]));

/* Light, dark, or whatever the machine says.

   Three states rather than two. A two-way switch has to decide what "off"
   means and gets it wrong for everyone whose machine is set the other way, so
   Follow is a real option and it is the default. */
const SCHEMES = [['system', 'Follow the system'], ['light', 'Light'], ['dark', 'Dark']];

function scheme() {
  return localStorage.getItem('verba.scheme') || 'system';
}

function setScheme(v) {
  if (v === 'system') {
    localStorage.removeItem('verba.scheme');
    document.documentElement.removeAttribute('data-theme');
  } else {
    localStorage.setItem('verba.scheme', v);
    document.documentElement.setAttribute('data-theme', v);
  }
  drawNav();
}

function schemeControl() {
  const wrap = el('div', 'scheme');
  wrap.setAttribute('role', 'group');
  wrap.setAttribute('aria-label', 'Appearance');
  const now = scheme();
  SCHEMES.forEach(([v, label]) => {
    const b = el('button', v === now ? 'on' : '', icon(
      v === 'light' ? 'sun' : v === 'dark' ? 'moon' : 'contrast'));
    b.title = label;
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-pressed', v === now ? 'true' : 'false');
    b.onclick = () => setScheme(v);
    wrap.append(b);
  });
  return wrap;
}

function drawNav() {
  const n = $('#nav'); n.innerHTML = '';
  const here = currentStage().id;

  // A step: its number, its name, and one line saying where it stands. The
  // line matters more than the mark beside it, because the mark is a colour
  // and a person who cannot separate two colours still has to be able to work.
  const step = (st) => {
    const s = st.state(S);
    const b = el('button', 'step' + (view === st.id ? ' on' : '') +
                           (st.id === here ? ' here' : ''));
    b.dataset.v = st.id;
    b.setAttribute('aria-current', view === st.id ? 'page' : 'false');
    b.innerHTML =
      `<span class="stepn ${s.tone}">${s.tone === 'done' ? '&#10003;' : st.n}</span>` +
      `<span class="stepbody"><span class="stept">${esc(st.label)}</span>` +
      `<span class="steps">${esc(s.line)}</span></span>`;
    if (st.id === here) b.append(el('span', 'younow', 'now'));
    b.onclick = () => setView(st.id);
    return b;
  };

  const plain = ([id, label, ic]) => {
    const b = el('button', view === id ? 'on' : '', icon(ic) + `<span>${esc(label)}</span>`);
    b.dataset.v = id;
    b.setAttribute('aria-current', view === id ? 'page' : 'false');
    b.onclick = () => setView(id);
    return b;
  };

  n.append(el('div', 'navlabel', 'The document'));
  STAGES.forEach(st => n.append(step(st)));

  n.append(el('div', 'navlabel', 'Look at'));
  LOOK.forEach(i => n.append(plain(i)));

  const d = el('details', 'navgroup');
  d.open = SETUP.some(i => i[0] === view) || localStorage.getItem('verba.nav.setup') === '1';
  d.ontoggle = () => localStorage.setItem('verba.nav.setup', d.open ? '1' : '0');
  d.append(el('summary', null, 'Set up'));
  SETUP.forEach(i => d.append(plain(i)));
  n.append(d);

  // Reload is something you do, not somewhere you go.
  const r = el('button', 'quiet', icon('refresh') + '<span>Reload</span>');
  r.title = 'Read the content tree again from disk';
  r.onclick = () => refresh().then(() => toast('Reloaded from disk'));
  n.append(el('div', 'spacer'), r, schemeControl());
}

function drawTree() {
  const t = $('#tree'); t.innerHTML = '';
  // The outline belongs to writing, not to the whole application. It used to
  // sit under the rail at all times, which meant every section appeared twice:
  // once as the "Sections" destination and again as thirty-eight rows beneath
  // it. Two lists of the same thing, one of them always the wrong one to click.
  // Only inside a section. On the Sections list the table *is* the outline,
  // and showing both is the duplication this was pulled out of the rail to end.
  // With one section open it stops being a second list and becomes what it was
  // always for: moving to the next section without going back first.
  const writing = view === 'section';
  t.hidden = !writing;
  if (!writing) return;
  t.append(el('div', 'head', 'Outline'));
  S.sections.forEach(s => {
    const r = el('div', `row l${s.level}${s.id === currentId && view === 'section' ? ' on' : ''}`);
    r.setAttribute('role', 'button');
    r.setAttribute('tabindex', '0');
    r.append(el('span', `dot ${s.status}`));
    r.append(el('span', 'n', esc(s.number)));
    r.append(el('span', 't', esc(s.title)));
    const bad = s.drift.length + s.lint.filter(l => l.level === 'error').length;
    if (bad) r.append(el('span', 'flag', bad));
    r.onclick = () => openSection(s.id);
    r.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSection(s.id); } };
    t.append(r);
  });
}

/* ---------------------------------------------------------------- views */
async function setView(v) {
  if (dirty && !(await leaveDirty())) return;
  dirty = false; view = v;
  drawNav();
  render();
  $('#main').scrollTop = 0;
}

function fixtureBanner() {
  // The shipped sample capture must never be mistaken for real evidence.
  if (!S.capture.run || !S.capture.run.includes('fixture')) return null;
  const b = el('div', 'panel');
  b.style.borderColor = 'var(--amber)';
  b.innerHTML = `<b style="color:var(--amber)">Sample capture</b>
    <div class="muted">The queue is showing made-up data.` + hint(
    `<code>${esc(S.capture.run)}</code> is a sample capture included so you can see ` +
    `how review works. Run a real capture, then delete that folder.`) + `</div>`;
  return b;
}

function holder() {
  // a hint popover is anchored to a marker in the view being replaced, so it
  // must go with it rather than float over whatever comes next
  closeHints();
  const host = $('#main');
  host.innerHTML = '';
  const bar = nextStepBar();
  if (bar) host.append(bar);
  const h = el('div', 'hold');
  host.append(h);
  return h;
}

/* One line, in every view, naming the next thing worth doing.

   The console showed six panels of true statements and left the reader to work
   out which of them was their move. That is fine for someone who built it and
   useless for everybody else: a document is a piece of work with an order to
   it, and the interface should know that order rather than making each person
   rediscover it.

   The order is not a wizard and does not lock anything: every view is still one
   click away in the rail. This only answers "what now", which is the question
   an eleven-view tool is worst at answering on its own. */
function nextStep() {
  const s = (S && S.summary) || {};
  if (!S) return null;
  // The primary action does the work. It used to open a list, which is the
  // interface saying "here is your homework": every one of these findings the
  // system already knows how to clear, and asking a person to walk a list and
  // press the same button on each is friction with nothing on the other side
  // of it. What genuinely needs a decision is handed back afterwards.
  if (s.error)
    return { tone: 'bad', what: `${s.error} thing${s.error > 1 ? 's' : ''} to fix`,
             why: 'These stop the document being built. Most of them clear themselves.',
             cta: 'Fix what can be fixed', go: fixEverything, at: 'findings',
             also: ['See them', () => setView('findings')] };
  if (s.drift_items)
    return { tone: 'warn',
             what: `${s.drift_items} change${s.drift_items > 1 ? 's' : ''} in the live system`,
             why: 'The product moved. The mechanical ones apply on their own.',
             cta: 'Apply what can be applied', go: fixEverything, at: 'queue',
             also: ['See them', () => setView('queue')] };
  if (!S.capture || !S.capture.run)
    return { tone: 'go', what: 'Nothing has been photographed yet',
             why: 'A crawl signs in, pictures every screen and reads its labels.',
             cta: 'Capture the live system', at: 'capture',
             go: () => runJob('/api/capture', {}, 'capture') };
  if (s.stale)
    return { tone: 'warn', what: `${s.stale} section${s.stale > 1 ? 's' : ''} not checked lately`,
             why: 'Re-crawl to confirm they still match the product.',
             cta: 'Capture the live system', at: 'capture',
             go: () => runJob('/api/capture', {}, 'capture') };
  return { tone: 'ok', what: 'The document matches the system and breaks no rules',
           why: 'Nothing is outstanding. This is the moment to cut a version.',
           cta: 'Publish', go: () => setView('publish'), at: 'publish' };
}

/* Everything the system can settle, in one press.

   It applies the mechanical differences, adopts the fresh screenshots, fills
   the descriptions the evidence can answer and tidies the writing, measuring
   the rules after each step and putting back anything that made the document
   worse. Then it says what is left and why it is a person's call. */
function fixEverything() {
  runJob('/api/fix', {}, 'fix what can be fixed');
}

function nextStepBar() {
  const n = nextStep();
  if (!n) return null;
  // Not on the step it is pointing at. The rail already says where the work is
  // and the step's own page already offers the action, so repeating both in a
  // banner above them is the interface saying the same thing three times.
  if (n.at && n.at === view) return null;
  const bar = el('div', 'nextbar ' + n.tone);
  const dot = el('span', 'nsdot');
  const body = el('div', 'nsbody');
  body.append(el('div', 'nswhat', esc(n.what)));
  body.append(el('div', 'nswhy', esc(n.why)));
  const act = el('button', 'act primary', esc(n.cta));
  act.onclick = n.go;

  const right = el('div', 'nsacts');
  right.append(act);
  if (n.also) {
    const b = el('button', 'act ghost', esc(n.also[0]));
    b.onclick = n.also[1];
    right.append(b);
  }
  // Publishing is where all of this is going, so it stays reachable from every
  // view instead of being one more destination competing in the rail.
  if (n.cta !== 'Publish') {
    const pub = el('button', 'act ghost', icon('publish') + 'Publish');
    pub.title = 'Build and cut a version';
    pub.onclick = () => setView('publish');
    right.append(pub);
  }
  bar.append(dot, body, right);
  return bar;
}

function render() {
  const m = holder();
  if (view === 'capture') return drawCapture(m);
  // Overview is gone. It was seven unrelated panels stacked in one place, and
  // every one of them now lives with the step it belongs to. Anything still
  // asking for it gets the step that has the work.
  if (view === 'overview') { view = currentStage().id; return render(); }
  if (view === 'sections') return drawSections(m);
  if (view === 'queue') return drawQueue(m);
  if (view === 'publish') return drawPublish(m);
  if (view === 'images') return drawImages(m);
  if (view === 'document') return drawDocument(m);
  if (view === 'history') return drawHistory(m);
  if (view === 'connections') return drawConnections(m);
  if (view === 'design') return drawDesign(m);
  if (view === 'editions') return drawEditions(m);
  if (view === 'documents') return drawDocuments(m);
  if (view === 'assistant') return drawAssistant(m);
  if (view === 'screens') return drawScreens(m);
  if (view === 'masking') return drawMasking(m);
  if (view === 'fields') return drawFields(m);
  if (view === 'findings') return drawFindings(m);
  if (view === 'section') return drawSection(m);
}

/* ---------------------------------------------------------------- overview */
/* The first five minutes.

   Three steps, in the order they actually have to happen, each saying what it
   is for rather than only what it is called. A step that is already done says
   so and stops offering itself, which is the same rule the rest of this
   interface follows: a control disappears once its work is done. */
function firstRun(s) {
  const wrap = el('div', 'panel start');
  wrap.append(el('h3', null, 'You have a document. Three things make it true.'));
  wrap.append(el('div', 'muted',
    'It already builds, so nothing here is required to get output. These are ' +
    'what turn it from a template into documentation of your system.'));

  const described = (S.system || {}).exists;
  const screens = (S.screens || []).length;

  const steps = [
    { done: described,
      title: 'Say what your product is',
      body: described
        ? 'content/system.md is written. The writer reads it before every task.'
        : 'A crawl can prove a control exists. It cannot say what the control is ' +
          'for, or what you call it. Write that down once, in content/system.md, ' +
          'and every later piece of writing is held to it.',
      cta: null },
    { done: screens > 1,
      title: 'List the screens worth documenting',
      body: screens > 1
        ? `${screens} screens are registered in content/screens.yaml.`
        : 'content/screens.yaml starts with one screen: the home page. Add the ' +
          'others, with what to read off each, and the document is held against ' +
          'them from then on.',
      cta: null },
    { done: !!S.capture.run,
      title: 'Photograph them',
      body: S.capture.run
        ? `Last crawled ${esc(S.capture.run)}.`
        : 'The crawl signs in, takes one picture per screen, and reads the real ' +
          'labels off the page. Nothing is ever written to your system.',
      cta: ['Capture the live system', '/api/capture', {}] },
  ];

  const list = el('div', 'steps');
  steps.forEach((st, i) => {
    const row = el('div', 'step' + (st.done ? ' done' : ''));
    row.append(el('div', 'dot', st.done ? icon('check') : String(i + 1)));
    const body = el('div', 'stepbody');
    body.append(el('div', 'steptitle', esc(st.title)));
    body.append(el('div', 'muted', st.body));
    if (st.cta && !st.done) {
      const b = el('button', 'act', icon('camera') + esc(st.cta[0]));
      b.onclick = () => runJob(st.cta[1], st.cta[2], 'capture');
      const bar = el('div', 'row'); bar.style.marginTop = '9px';
      bar.append(b); body.append(bar);
    }
    row.append(body);
    list.append(row);
  });
  wrap.append(list);
  return wrap;
}

/* Step 2. Photographing the system.

   This had no home. The button lived on the old Overview beside five others,
   the safety guarantees sat in a panel under it, and what the last crawl found
   was in a third place, so "have I got a current picture of the product?" was
   a question you answered by reading three panels and doing the sums. */
function drawCapture(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Capture the live system'));
  m.append(el('div', 'muted',
    'Sign in, photograph every screen, and read the labels off each one. ' +
    'Nothing is ever written to the product.' + hint(
      'A crawl is the evidence everything else rests on. The differences in ' +
      'Review, the labels in Fields and the pictures in the document all come ' +
      'from here, so a document is only ever as current as its last capture.')));

  const cap = S.capture || {};
  const sum = S.summary || {};
  const active = ((S.environments || {}).items || []).find(x => x.active);

  const state = el('div', 'panel');
  if (!cap.run) {
    state.append(el('div', 'empty',
      'Nothing has been photographed yet. This is the first thing to do.'));
  } else {
    state.append(el('h3', null, 'The last capture'));
    const g = el('div', 'kv');
    g.innerHTML =
      `<div><span>When</span><b>${esc(ago(cap.run))}</b></div>` +
      `<div><span>Run</span><b class="mono">${esc(cap.run)}</b></div>` +
      `<div><span>Images in the document</span><b>${sum.assets || 0}</b></div>` +
      `<div><span>Sections not checked lately</span><b>${sum.stale || 0}</b></div>`;
    state.append(g);
  }

  const row = el('div', 'row'); row.style.marginTop = '14px';
  const go = el('button', 'act primary', icon('camera') + 'Photograph every screen');
  go.onclick = () => runCapture(null);
  const one = el('button', 'act', icon('sections') + 'Just one section');
  one.onclick = () => setView('sections');
  one.title = 'Open a section and recapture only the screens it uses';
  row.append(go, one);
  if (!active || !active.ready) {
    go.disabled = true;
    go.title = active ? active.status : 'Choose a system to document first';
    const fix = el('button', 'act', icon('connections') + 'Set up the connection');
    fix.onclick = () => setView('connections');
    row.append(fix);
  }
  state.append(row);
  m.append(state);

  m.append(safetyPanel());

  if ((cap.unmapped_screens || []).length) {
    const u = el('div', 'panel');
    u.append(el('h3', null, 'Photographed, but in no section'));
    u.append(el('div', 'muted',
      'These screens are in the registry and were captured, but no section ' +
      'shows them. Either write a section for one, or take it out of ' +
      'content/screens.yaml.'));
    cap.unmapped_screens.forEach(x => u.append(el('div', null, `<code>${esc(x)}</code>`)));
    m.append(u);
  }

  m.append(jobsPanel());
}

function signInPanel() {
  const p = el('div', 'panel');
  p.style.borderColor = 'var(--amber)';
  p.append(el('h3', null, icon('key') + 'Sign in to capture'));
  p.append(el('div', 'muted',
    'Capturing screens needs the Rise Hub staging sign-in. Everything else works ' +
    'without it. Stored in your login keychain, never in a file.'));
  const g = el('div', 'grid2'); g.style.marginTop = '11px';
  g.innerHTML = `
    <div class="field"><label for="ciUser">Email</label><input id="ciUser" type="email"
      autocomplete="username" placeholder="you@example.com"></div>
    <div class="field"><label for="ciPass">Password</label><input id="ciPass" type="password"
      autocomplete="current-password"></div>`;
  p.append(g);
  const row = el('div', 'row'); row.style.marginTop = '11px';
  const go = el('button', 'act primary', 'Save to keychain');
  go.onclick = async () => {
    const user = $('#ciUser').value.trim(), password = $('#ciPass').value;
    if (!user || !password) return toast('Both fields are needed', true);
    go.disabled = true;
    try {
      const r = await api('/api/credentials',
        { method: 'POST', json: { user, password } });
      toast(r.message); await refresh(); setView(currentStage().id);
    } catch (e) { toast(e.message, true); go.disabled = false; }
  };
  row.append(go); p.append(row);
  return p;
}

function safetyPanel() {
  const p = el('div', 'panel');
  p.append(el('h3', null, icon('shield') + 'Crawl safety'));
  const ro = S.readonly || {};
  const mk = S.masking || {};
  const g = el('div', 'grid2');

  const box = (title, ok, body) => {
    const d = el('div');
    d.innerHTML = `<div><span class="chip ${ok ? 'verified' : 'err'}">${ok ? 'on' : 'off'}</span>
      <b> ${esc(title)}</b></div><div class="muted" style="margin-top:4px">${body}</div>`;
    return d;
  };
  g.append(box('Read only', true,
    (ro.blocked_writes ? `<b>${ro.blocked_writes}</b> write attempt(s) blocked last crawl.`
                       : 'No write can reach the platform.') + hint(
    'Every request that is not GET, HEAD or OPTIONS is aborted in the browser once ' +
    'sign-in finishes, so a stray click cannot change platform data. Sign-in is the ' +
    'single permitted exception and every such request is logged.' +
    (ro.sign_in_requests ? ` Last crawl: ${ro.sign_in_requests} sign-in request(s).` : ''))));
  const cr = S.credentials || {};
  const act = ((S.environments || {}).items || []).find(x => x.active);
  g.append(box(act ? `Sign-in: ${act.label || act.id}` : 'Sign-in', !!cr.ready,
    cr.ready
      ? `${esc(cr.user || cr.detail || 'ready')}`
      : `${esc(cr.detail || 'not signed in')}` + hint(
        'Capture stays unavailable until this is sorted. Fix it under Connections.')));
  g.append(box('Name masking', !!mk.active,
    mk.active
      ? `<b>${mk.known_values || 0}</b> value(s) mapped.` + hint(
        'Publisher and partner names, account ids, deal ids and email addresses are ' +
        'replaced in the page immediately before each screenshot, and in the labels ' +
        'read off it afterwards. The mapping is stable across crawls, so a given ' +
        'real value always becomes the same placeholder.')
      : 'Off. Screenshots would show real names.'));
  p.append(g);

  const row = el('div', 'row'); row.style.marginTop = '11px';
  const b1 = el('button', 'act ghost', 'Show the name mapping');
  b1.onclick = () => showMasking();
  const b2 = el('button', 'act ghost', 'Show remembered addresses');
  b2.onclick = () => showRoutes();
  row.append(b1, b2); p.append(row);
  return p;
}

function showMasking() {
  const m = holder();
  m.append(el('h2', 'page', 'Name masking'));
  m.append(el('div', 'muted', 'Real value on the left, what ships on the right.' + hint(
    'Substitution happens in the browser just before each screenshot. Nothing is ' +
    'sent back, so the platform is never changed. Rules live in ' +
    '<code>content/masking.yaml</code>.')));
  const back = el('button', 'act', 'Back'); back.style.margin = '13px 0';
  back.onclick = () => setView(currentStage().id); m.append(back);
  const p = el('div', 'panel');
  const rows = (S.masking && S.masking.map) || [];
  if (!rows.length) {
    p.append(el('div', 'muted',
      'Nothing mapped yet. The mapping fills in the first time you capture.'));
  } else {
    const t = el('table', null,
      '<thead><tr><th>Rule</th><th>Real value</th><th>Shown in the document</th></tr></thead>');
    const b = el('tbody');
    rows.forEach(r => b.append(el('tr', null,
      `<td class="muted">${esc(r.rule)}</td><td>${esc(r.from)}</td><td><b>${esc(r.to)}</b></td>`)));
    t.append(b); p.append(t);
  }
  m.append(p);
}

function showRoutes() {
  const m = holder();
  m.append(el('h2', 'page', 'Remembered addresses'));
  m.append(el('div', 'muted', 'Where each screen was last found.' + hint(
    'A per-section recrawl navigates straight to the remembered address instead of ' +
    'clicking through from the top, and falls back to replaying the steps if the ' +
    'address stops resolving.')));
  const back = el('button', 'act', 'Back'); back.style.margin = '13px 0';
  back.onclick = () => setView(currentStage().id); m.append(back);
  const p = el('div', 'panel');
  const t = el('table', null, `<thead><tr><th>Screen</th><th>Sections</th>
    <th>Address</th><th>Last seen</th><th></th></tr></thead>`);
  const b = el('tbody');
  S.screens.forEach(sc => {
    const tr = el('tr', null, `<td>${esc(sc.id)}</td>
      <td class="muted">${esc((sc.sections || []).join(', ') || '-')}</td>
      <td class="muted" style="word-break:break-all">${esc(sc.url || 'not captured yet')}</td>
      <td class="muted">${esc(sc.last_seen || '-')}</td>`);
    const td = el('td');
    const btn = el('button', 'mini', 'Recrawl');
    btn.onclick = () => runCapture([sc.id]);
    td.append(btn); tr.append(td); b.append(tr);
  });
  t.append(b); const w = el('div','wrap-x'); w.append(t); p.append(w); m.append(p);
}

function outputsPanel() {
  const p = el('div', 'panel');
  p.append(el('h3', null, icon('download') + 'Published files'));
  if (!S.outputs.length) { p.append(el('div', 'muted', 'Nothing built yet.')); return p; }
  const t = el('table', null,
    '<thead><tr><th>File</th><th>Size</th><th>Built</th><th></th></tr></thead>');
  const b = el('tbody');
  S.outputs.forEach(o => b.append(el('tr', null,
    `<td>${esc(o.name)}</td><td>${o.size_kb} KB</td><td class="muted">${esc(o.modified)}</td>
     <td><a href="${o.url}">download</a></td>`)));
  t.append(b); const w = el('div','wrap-x'); w.append(t); p.append(w); return p;
}

function jobsPanel() {
  const p = el('div', 'panel');
  p.append(el('h3', null, icon('clock') + 'Recent runs'));
  if (!S.jobs.length) { p.append(el('div', 'muted', 'No runs yet.')); return p; }
  const t = el('table', null,
    '<thead><tr><th>Task</th><th>Detail</th><th>State</th><th>Started</th></tr></thead>');
  const b = el('tbody');
  S.jobs.forEach(j => {
    const tr = el('tr', 'click', `<td>${esc(j.name)}</td><td class="muted">${esc(j.detail)}</td>
      <td><span class="chip ${j.state === 'failed' ? 'err' : j.state === 'done' ? 'verified' : 'warn'}">
      ${esc(j.state)}</span></td><td class="muted">${esc(j.started)}</td>`);
    tr.onclick = () => watchJob(j.id, j.name);
    b.append(tr);
  });
  t.append(b); const w = el('div','wrap-x'); w.append(t); p.append(w); return p;
}

/* ---------------------------------------------------------------- to fix */
/* Reporting a problem and stopping there leaves the person holding it. Every
   finding here carries what would clear it and the button that does it. */
async function drawFindings(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'To fix'));

  let d;
  try { d = await api('/api/findings'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  m.append(el('div', 'muted',
    d.errors
      ? `${d.errors} thing(s) block a build, ${d.findings.length - d.errors} worth a look.`
      : `Nothing blocks a build. ${d.findings.length} thing(s) worth a look.`));

  // Offered above the list, not after it: the point is that most of this does
  // not need reading one item at a time.
  if (d.findings.length) {
    const bar = el('div', 'row'); bar.style.margin = '14px 0';
    const go = el('button', 'act primary', icon('sparkle') + 'Fix what can be fixed');
    go.title = 'Applies the mechanical changes, adopts fresh pictures, tidies the ' +
               'writing, and puts back anything that made the document worse.';
    go.onclick = fixEverything;
    bar.append(go);
    m.append(bar);
  }

  await drawSurvey(m);

  if (!d.findings.length) {
    m.append(el('div', 'panel accent',
      '<div class="empty">The document is clean.</div>'));
    return;
  }

  await drawNotes(m);
  await drawTidy(m);

  const bulk = el('div', 'row'); bulk.style.margin = '14px 0';
  const sweepAll = el('button', 'act',
    icon('edit') + 'Ask the writer about everything unwritten');
  sweepAll.onclick = () => runJob('/api/sweep', {}, 'review');
  const relint = el('button', 'act', icon('refresh') + 'Check again');
  relint.onclick = () => drawFindings(holder());
  bulk.append(sweepAll, relint); m.append(bulk);

  const LEVEL = { error: 'err', warning: 'warn', info: '' };
  ['error', 'warning', 'info'].forEach(level => {
    const items = d.findings.filter(f => f.level === level);
    if (!items.length) return;
    const p = el('div', 'panel' + (level === 'error' ? ' warn-edge' : ''));
    // A tick beside "3 warnings" says the opposite of what it means.
    const LEVEL_ICON = { error: 'alert', warning: 'alert', info: 'overview' };
    p.append(el('h3', null,
      icon(LEVEL_ICON[level]) +
      `${items.length} ${level}${items.length > 1 ? 's' : ''}` +
      (level === 'error' ? ' blocking a build' : '')));

    items.forEach(f => {
      // The chip already says which level this is. A bare "!" beside it reads
      // as a stray character, not a mark.
      const row = el('div', 'item ' + (level === 'error' ? 'open' : 'done'));
      row.append(el('span', 'what',
        `<span class="chip ${LEVEL[level]}">${esc(f.rule)}</span> ` +
        `${f.number ? `<b>${esc(f.number)}</b> ` : ''}${esc(f.message)}` +
        `<div class="why">${esc(f.remedy.why)}` +
        (f.detail ? ` <span class="muted">${esc(f.detail)}</span>` : '') +
        `</div>`));

      const act = f.remedy.action;
      if (act !== 'none') {
        const b = el('button', 'mini go', f.remedy.label);
        b.onclick = () => runRemedy(act, f);
        row.append(b);
      } else if (f.section) {
        const b = el('button', 'mini', 'Open');
        b.onclick = () => openSection(f.section);
        row.append(b);
      }
      p.append(row);
    });
    m.append(p);
  });
}

/* Read the document before opening a browser. A crawl is the expensive step,
   so working out what it should look at first means it looks at that and
   nothing else. */
async function drawSurvey(m) {
  let s;
  try { s = (await api('/api/survey')).summary; } catch (e) { return; }

  const p = el('div', 'panel accent');
  p.append(el('h3', null, icon('overview') + 'Before the next crawl' + hint(
    'This reads the document as it stands, with no browser involved: what is ' +
    'unwritten, which pictures are missing or no longer of anything, and which ' +
    'parts of the platform nothing describes. Anything the last crawl already ' +
    'saw is answered without another one.')));

  const strip = el('div', 'stats');
  const cell = (k, v, cls) => strip.append(el('div', 'cell ' + (cls || ''),
    `<div class="v">${v}</div><div class="k">${esc(k)}</div>`));
  cell('unwritten', s.unwritten, s.unwritten ? 'bad' : 'good');
  cell('picture gaps', s.images, s.images ? 'warn' : 'good');
  cell('undocumented', s.undocumented, s.undocumented ? 'warn' : 'good');
  cell('stale', s.stale, s.stale ? 'warn' : 'good');
  p.append(strip);

  const row = el('div', 'row');
  if (s.answerable_now) {
    const b = el('button', 'act primary', icon('edit') +
      `Finish ${s.answerable_now} section(s) from what is already captured`);
    b.onclick = () => runJob('/api/sweep', {}, 'review');
    row.append(b);
  }
  const n = (s.screens_worth_crawling || []).length;
  if (n) {
    const c = el('button', 'act', icon('camera') +
      `Crawl the ${n} screen(s) that would tell us something new`);
    c.title = s.screens_worth_crawling.join(', ');
    c.onclick = () => runCapture(s.screens_worth_crawling, null);
    row.append(c);
  }
  p.append(row);
  p.append(el('div', 'muted', n
    ? `A full crawl would visit every screen. These ${n} are the ones with a `
      + `gap behind them: ${esc(s.screens_worth_crawling.join(', '))}.`
    : 'No crawl would tell us anything the last one did not.'));
  m.append(p);
}

/* One pass over the writing, and one decision about it.

   The mechanical pass could tell that "Enter publisher name" is not the name of
   a control, and the only thing it knew to do was delete, which loses the
   description and arrives as ten separate chores. This asks what each entry
   really is, and comes back as one proposal covering the document. */
/* Somewhere to put what you noticed, said in a sentence, next to the button
   that acts on it. The rest of this system finds its own work; this is the only
   place where the work is something a person asked for. */
async function drawNotes(m) {
  let d;
  try { d = await api('/api/notes'); } catch (e) { return; }

  const p = el('div', 'panel');
  p.append(el('h3', null, icon('edit') + 'Things you noticed' + hint(
    'Write down what you saw and where, in your own words. The next run works ' +
    'out which section it is about, decides what kind of fix it needs, and does ' +
    'it. Anything it cannot work out stays on the list and says why.')));

  const box = el('div', 'field');
  box.innerHTML = `<label for="noteText">What did you notice?</label>
    <textarea id="noteText" rows="2"
      placeholder="figure 4.3 shows a real customer name, it should show a test name"></textarea>`;
  p.append(box);

  const row = el('div', 'row'); row.style.marginTop = 'var(--s2)';
  const add = el('button', 'act primary', icon('check') + 'Note it');
  add.onclick = async () => {
    const t = ($('#noteText') || {}).value || '';
    if (!t.trim()) return toast('Write what you noticed first', true);
    try {
      const r = await api('/api/note', { method: 'POST', json: { text: t.trim() } });
      toast(r.message); drawFindings(holder());
    } catch (e) { toast(e.message, true); }
  };
  const run = el('button', 'act', icon('play') + 'Run now');
  run.title = 'Deal with these, and everything else outstanding';
  run.onclick = () => runJob('/api/auto', { rounds: 3, crawl: true }, 'run everything');
  row.append(add, run);
  p.append(row);

  const notes = d.notes || [];
  if (notes.length) {
    const open = notes.filter(n => n.status === 'open');
    const done = notes.filter(n => n.status !== 'open');
    const line = (n) => {
      const item = el('div', 'item ' + (n.status === 'open' ? 'open' : 'done'));
      const chip = n.status === 'fixed'
        ? '<span class="chip verified">done</span>'
        : n.status === 'stuck' ? '<span class="chip warn">needs you</span>'
        : '<span class="chip">waiting</span>';
      item.append(el('span', 'what',
        `${chip} ${esc(n.text)}` +
        (n.outcome ? `<div class="why">${esc(n.outcome)}</div>` : '') +
        (n.section ? `<div class="why">${esc(n.section)}</div>` : '')));
      const b = el('button', 'mini', n.status === 'open' ? 'Remove' : 'Ask again');
      b.onclick = async () => {
        const path = n.status === 'open' ? '/api/note/drop' : '/api/note/reopen';
        try {
          const r = await api(path, { method: 'POST', json: { id: n.id } });
          toast(r.message); drawFindings(holder());
        } catch (e) { toast(e.message, true); }
      };
      item.append(b);
      return item;
    };
    open.forEach(n => p.append(line(n)));
    if (done.length) {
      const fold = el('details', 'settled');
      fold.append(el('summary', null, `${done.length} already dealt with`));
      done.forEach(n => fold.append(line(n)));
      p.append(fold);
    }
  }
  m.append(p);
}

async function drawTidy(m) {
  let d;
  try { d = await api('/api/tidy'); } catch (e) { return; }

  const p = el('div', 'panel accent');
  const edits = d.edits || [];

  if (!edits.length) {
    p.append(el('h3', null, icon('edit') + 'Fix the writing' + hint(
      'Reads every entry that is named by a placeholder, a tooltip or a heading, ' +
      'and decides what each one really is: the real name of a control that ' +
      'nobody captured, or a repeat of something already documented. One pass ' +
      'over the document, one decision.')));
    p.append(el('div', 'muted',
      'Placeholders and tooltip sentences documented as though they were the ' +
      'names of controls. The writer works out the real name where there is ' +
      'one, and drops the rest.'));
    const go = el('button', 'act primary', icon('edit') + 'Fix the writing');
    go.style.marginTop = 'var(--s3)';
    go.onclick = () => runJob('/api/tidy/prepare', {}, 'fix the writing');
    p.append(go);
    m.append(p);
    return;
  }

  const changes = edits.reduce((n, e) => n + (e.notes || []).length, 0);
  p.append(el('h3', null, icon('edit') +
    `${changes} writing fix(es) across ${edits.length} section(s), ready` + hint(
      'Nothing is written yet. Review any section to see its diff, or accept ' +
      'the whole pass. Each section is recorded separately in History, so one ' +
      'of them can be put back without the others.')));

  edits.forEach(e => {
    const row = el('div', 'item open');
    row.append(el('span', 'what',
      `<b>${esc(e.number)} ${esc(e.title)}</b>` +
      `<div class="why">${(e.notes || []).map(esc).join(' &middot; ')}</div>`));
    const b = el('button', 'mini', 'See the diff');
    b.onclick = () => reviewChange({
      title: `${e.number} ${e.title}`,
      note: (e.notes || []).join('. '),
      before: e.before, after: e.after,
      approveLabel: 'Accept the whole pass',
      onApprove: () => applyTidy(),
      onDecline: () => modal({
        title: 'Discard the whole pass?',
        body: `All ${changes} fix(es) across ${edits.length} section(s) go, and `
            + 'nothing is written.',
        confirmLabel: 'Discard', confirmClass: 'danger',
        onConfirm: async () => {
          try {
            const r = await api('/api/tidy/discard', { method: 'POST', json: {} });
            toast(r.message); drawFindings(holder());
          } catch (err) { toast(err.message, true); }
        },
      }),
      onCancel: () => drawFindings(holder()),
    });
    row.append(b);
    p.append(row);
  });

  const row = el('div', 'row'); row.style.marginTop = 'var(--s3)';
  const ok = el('button', 'act primary',
    icon('check') + `Accept all ${changes} fix(es)`);
  ok.onclick = () => applyTidy();
  const no = el('button', 'act ghost', 'Discard');
  no.onclick = () => modal({
    title: 'Discard the whole pass?',
    body: 'Nothing is written and the proposal goes.',
    confirmLabel: 'Discard', confirmClass: 'danger',
    onConfirm: async () => {
      try {
        const r = await api('/api/tidy/discard', { method: 'POST', json: {} });
        toast(r.message); drawFindings(holder());
      } catch (err) { toast(err.message, true); }
    },
  });
  row.append(ok, no);
  p.append(row);
  m.append(p);
}

async function applyTidy() {
  try {
    const r = await api('/api/tidy/apply', { method: 'POST', json: {} });
    toast(r.message);
    if ((r.failed || []).length) r.failed.forEach(f => toast(f, true));
    await refresh();
    drawFindings(holder());
  } catch (e) { toast(e.message, true); }
}

async function runRemedy(action, f) {
  try {
    if (action === 'sweep')
      return runJob('/api/sweep', { sections: [f.section] }, `review ${f.number}`);
    if (action === 'capture') {
      const s = S.sections.find(x => x.id === f.section);
      return runCapture(s && s.capturable && s.capturable.length ? s.capturable : null,
                        f.section);
    }
    if (action.startsWith('assist')) {
      // "assist" alone only opened the section and left the person to find the
      // right task. The remedy names the task, so run it.
      const task = action.split(':')[1] || 'polish';
      const label = f.remedy.label + ` ${f.number || ''}`.trimEnd();
      return runAssist(f.section, task, label);
    }
    if (action === 'images') return setView('images');
    if (action === 'adopt' || action === 'open') {
      return f.section ? openSection(f.section) : setView('images');
    }
    if (action === 'verify') {
      const r = await api(`/api/section/${encodeURIComponent(f.section)}/verify`,
                          { method: 'POST', json: {} });
      toast(r.message); await refresh(); return drawFindings(holder());
    }
  } catch (e) { toast(e.message, true); }
}

/* ---------------------------------------------------------------- fields */
async function drawFields(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Forms and fields'));
  m.append(el('div', 'muted',
    'Every control the crawl read, and the rules each one declares.' + hint(
      'This is a read and nothing else. The inspector never types, never ' +
      'focuses, never clicks and never asks the browser to validate, because ' +
      'asking fires an event the application is free to act on. A rule that ' +
      'only reveals itself when you enter a bad value is deliberately left ' +
      'undiscovered.')));

  let d;
  try { d = await api('/api/forms'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  if (!d.screens.length) {
    m.append(el('div', 'panel', `<div class="empty">${d.captured
      ? 'The last crawl found no forms. Every screen it visited was a list or a view.'
      : 'No capture yet. Run one from Overview.'}</div>`));
    return;
  }

  if (d.issues.length) {
    const p = el('div', 'panel warn-edge');
    p.append(el('h3', null, icon('alert') +
      `${d.issues.length} rule(s) the document and the screen disagree on`));
    d.issues.forEach(i => {
      const row = el('div', 'item open');
      row.append(el('span', 'mark', '!'));
      row.append(el('span', 'what',
        `${esc(i.line)}<div class="why">${esc(i.section)}</div>`));
      const b = el('button', 'mini go', 'Open the section');
      b.onclick = () => openSection(i.section);
      row.append(b);
      p.append(row);
    });
    m.append(p);
  }

  d.screens.forEach(sc => {
    const p = el('div', 'panel');
    const c = sc.counts || {};
    p.append(el('h3', null, icon('form') + esc(sc.screen) +
      `<span class="muted"> ${esc(sc.number)} ${esc(sc.title)}</span>`));
    p.append(el('div', 'muted',
      `${c.fields || 0} field(s), ${c.required || 0} required` +
      (sc.scoped_to ? ` \u00b7 read from ${esc(sc.scoped_to)}` : '')));

    sc.forms.forEach(f => {
      if (!f.fields.length) return;
      const t = el('table', null, `<thead><tr><th>Field</th><th>Kind</th>
        <th>Rules</th><th>Choices</th><th>Named by</th></tr></thead>`);
      const b = el('tbody');
      f.fields.forEach(fl => {
        const r = fl.rules || {};
        const chips = [];
        if (r.required) chips.push('<span class="chip err">required</span>');
        if (r.read_only) chips.push('<span class="chip">read only</span>');
        if (r.disabled) chips.push('<span class="chip">disabled</span>');
        if (r.max_length) chips.push(`<span class="chip">max ${esc(r.max_length)}</span>`);
        if (r.pattern) chips.push('<span class="chip">pattern</span>');
        // How a field got its name matters: a control named only by its
        // placeholder loses its name the moment someone types.
        const weak = fl.name_from === 'none' || fl.name_from === 'placeholder';
        b.append(el('tr', null, `
          <td><b>${esc(fl.name || '(unnamed)')}</b></td>
          <td class="muted">${esc(fl.kind)}</td>
          <td>${chips.join(' ') || '<span class="muted">-</span>'}</td>
          <td class="muted">${esc((fl.options || []).slice(0, 4).join(', ')) || '-'}</td>
          <td class="${weak ? 'bad' : 'muted'}">${esc(fl.name_from)}</td>`));
      });
      t.append(b);
      if (f.name) p.append(el('div', 'sub', esc(f.name)));
      const w = el('div', 'wrap-x'); w.append(t); p.append(w);
      if (f.actions && f.actions.length) {
        p.append(el('div', 'muted',
          'Buttons on this form: ' + esc(f.actions.slice(0, 8).join(', ')) +
          '. None of them is ever pressed.'));
      }
    });
    m.append(p);
  });

  if (d.a11y.length) {
    const p = el('div', 'panel');
    p.append(el('h3', null, icon('alert') +
      `${d.a11y.length} thing(s) the platform does not tell assistive technology` +
      hint('Not documentation faults. They are collected because the crawler is ' +
           'already looking, and a field with no accessible name is also a field ' +
           'the crawler struggles to name in the document.')));
    d.a11y.slice(0, 40).forEach(a => p.append(el('div', 'muted',
      `<b>${esc(a.field)}</b> on ${esc(a.screen)}: ${esc(a.issue)}`)));
    m.append(p);
  }
}

/* --------------------------------------------------------------- masking */
/* Which real names must never appear in a picture.

   The rules ran in the browser milliseconds before every screenshot and lived
   in a YAML file nobody could see. That is a strange place for a control whose
   whole job is stopping one customer's account appearing in another customer's
   document: a person who needs to check it is usually not the person who wrote
   it, and often has a reason to be nervous.

   Adding a literal is offered here because it is the rule anybody can state:
   this exact name, that instead. Columns and patterns need a selector or a
   regular expression and stay in the file, where the comments explaining them
   are. */
async function drawMasking(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Names in pictures'));

  let d;
  try { d = await api('/api/masking'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  const head = el('div', 'panel ' + (d.active ? 'ok-edge' : 'warn-edge'));
  head.append(el('div', 'bigstate', d.active
    ? 'On. Real names are replaced before every screenshot is taken.'
    : 'Off. Screenshots will show whatever the screen shows.'));
  head.append(el('div', 'muted',
    'The swap happens in the browser, in the moment before the shutter. ' +
    'Nothing is sent to the product and nothing about it is changed.' + hint(
      'A name learned once keeps its placeholder for good, in this capture and ' +
      'in capture months from now, so the same account is the same Example ' +
      'Account in every figure and two pictures never contradict each other.')));
  m.append(head);

  const add = el('div', 'panel');
  add.append(el('h3', null, 'Never show this name'));
  add.append(el('div', 'muted',
    'For a name you know should not appear. It takes effect at the next capture.'));
  const uid = 'mk' + Math.random().toString(36).slice(2, 6);
  const g = el('div', 'grid2'); g.style.marginTop = '12px';
  g.innerHTML = `
    <div class="field"><label for="${uid}a">This name</label>
      <input id="${uid}a" placeholder="Northwind Trading"></div>
    <div class="field"><label for="${uid}b">Show this instead</label>
      <input id="${uid}b" placeholder="Example Account"></div>`;
  add.append(g);
  const row = el('div', 'row');
  const go = el('button', 'act primary', icon('check') + 'Add the rule');
  go.onclick = async () => {
    const a = document.getElementById(uid + 'a').value;
    const b = document.getElementById(uid + 'b').value;
    try {
      const r = await api('/api/masking/literal', { method: 'POST',
                                                    json: { match: a, with: b } });
      toast(r.message);
      drawMasking(holder());
    } catch (e) { toast(e.message, true); }
  };
  row.append(go); add.append(row);
  m.append(add);

  if (d.literals.length) {
    const p = el('div', 'panel'); p.style.padding = '0';
    const tb = el('table', null,
      '<thead><tr><th>This name</th><th>Is shown as</th><th></th></tr></thead>');
    const body = el('tbody');
    d.literals.forEach(x => {
      const tr = el('tr', null,
        `<td><code>${esc(x.match)}</code></td><td><code>${esc(x.with)}</code></td>`);
      const td = el('td');
      const rm = el('button', 'mini', 'Remove');
      rm.onclick = async () => {
        await api('/api/masking/literal', { method: 'POST',
                                            json: { match: x.match, drop: true } });
        toast('rule removed'); drawMasking(holder());
      };
      td.append(rm); tr.append(td); body.append(tr);
    });
    tb.append(body); p.append(tb);
    m.append(el('h3', 'sub', 'Names you named')); m.append(p);
  }

  // the rules that catch names nobody listed
  const auto = el('div', 'panel');
  auto.append(el('h3', null, 'Rules that catch names automatically'));
  auto.append(el('div', 'muted',
    `These need a selector or a pattern, so they live in ${esc(d.path)} where ` +
    `the notes explaining them are.`));
  d.columns.forEach(c => auto.append(el('div', null,
    `Everything under the column <code>${esc(c.header)}</code> becomes ` +
    `<code>${esc(c.with)}</code>`)));
  d.patterns.forEach(x => auto.append(el('div', null,
    `Anything matching <code>${esc(x.name || x.pattern)}</code> becomes ` +
    `<code>${esc(x.with)}</code>`)));
  if (!d.columns.length && !d.patterns.length) {
    auto.append(el('div', 'muted', 'None yet.'));
  }
  m.append(auto);

  if (d.mapping.length) {
    const p = el('div', 'panel'); p.style.padding = '0';
    const tb = el('table', null,
      '<thead><tr><th>Real value</th><th>Appears as</th></tr></thead>');
    const body = el('tbody');
    d.mapping.forEach(r => body.append(el('tr', null,
      `<td><code>${esc(r.real ?? r.from ?? '')}</code></td>` +
      `<td><code>${esc(r.placeholder ?? r.to ?? '')}</code></td>`)));
    tb.append(body); p.append(tb);
    m.append(el('h3', 'sub', `Everything replaced so far (${d.mapping.length})`));
    m.append(el('div', 'muted',
      'Kept, so the same account is the same placeholder in every figure.'));
    m.append(p);
  }
}

/* --------------------------------------------------------------- screens */
/* What gets photographed, and what is read off each one.

   This is the heart of the system and it was a YAML file you edited by hand.
   Every difference in Review, every label in Fields and every picture in the
   document comes from here, and there was no way to see it: to answer "is that
   screen even being crawled?" you opened a file. Nothing here writes the
   registry, because a selector is a real decision and the healing flow already
   proposes those with evidence. This is the reading half, which was missing
   entirely. */
async function drawScreens(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Screens'));

  let d;
  try { d = await api('/api/screens'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  m.append(el('div', 'muted',
    `Every screen a crawl visits, at ${esc(d.base_url || 'the connected system')}. ` +
    `Edited in ${esc(d.path)}.` + hint(
      'A screen says how to reach itself and what to read off it. The labels it ' +
      'reads are what Review compares the document against, so a screen that ' +
      'reads nothing can never tell you the product changed.')));

  const orphan = d.screens.filter(s => !s.sections.length);
  const mute = d.screens.filter(s => s.sections.length && !s.extract.length);
  if (orphan.length || mute.length) {
    const w = el('div', 'panel warn-edge');
    w.append(el('h3', null, 'Worth knowing'));
    if (orphan.length) {
      w.append(el('div', null,
        `<b>${orphan.length}</b> screen(s) are crawled but no section shows them: ` +
        orphan.map(s => `<code>${esc(s.id)}</code>`).join(' ')));
    }
    if (mute.length) {
      w.append(el('div', null,
        `<b>${mute.length}</b> screen(s) are photographed but read nothing, so they ` +
        `cannot report a change: ` +
        mute.map(s => `<code>${esc(s.id)}</code>`).join(' ')));
    }
    m.append(w);
  }

  // The gap that matters most: pictures shipping in the document that no screen
  // here produces. No capture will ever replace them, so no button can fix it,
  // and saying so plainly is worth more than another finding in a list.
  if ((d.unreachable || []).length) {
    const u = el('div', 'panel warn-edge');
    u.append(el('h3', null, `${d.unreachable.length} picture(s) no crawl can reach`));
    u.append(el('div', 'muted',
      'These ship in the document and no screen here produces them, so ' +
      'photographing the system will never replace them. They were added by ' +
      'hand or came out of an older document, which also means nothing has ' +
      'checked them for real customer names.'));
    u.append(el('div', 'muted',
      'Either register a screen that captures the view, or take the picture ' +
      'out of the section. Both are decisions about the document.'));
    const list = el('div', 'unreach');
    d.unreachable.forEach(n => list.append(el('code', null, esc(n))));
    u.append(list);
    m.append(u);
  }

  const panel = el('div', 'panel'); panel.style.padding = '0';
  const tb = el('table', null,
    '<thead><tr><th>Screen</th><th>Shown in</th><th>Reads</th>' +
    '<th>How it is reached</th><th>Last capture</th></tr></thead>');
  const body = el('tbody');
  d.screens.forEach(s => {
    const reads = s.extract.length
      ? s.extract.map(k => {
          const n = (s.labels || {})[k];
          return `<span class="tag">${esc(k)}${n ? ' ' + n : ''}</span>`;
        }).join(' ')
      : '<span class="muted">nothing</span>';
    const shown = s.sections.length
      ? s.sections.map(x => `<code>${esc(x)}</code>`).join('<br>')
      : '<span class="muted">no section</span>';
    const how = s.url
      ? `<span class="muted">straight to a remembered address</span>`
      : `<span class="muted">${s.steps} step(s)</span>`;
    const row = el('tr', null,
      `<td><b>${esc(s.title)}</b><div class="mono muted">${esc(s.id)}</div></td>
       <td>${shown}</td><td>${reads}</td><td>${how}</td>
       <td>${s.captured ? 'yes' : '<span class="muted">never</span>'}</td>`);
    body.append(row);
  });
  tb.append(body); panel.append(tb); m.append(panel);

  const bar = el('div', 'row'); bar.style.margin = '16px 0 26px';
  const go = el('button', 'act primary', icon('camera') + 'Photograph every screen');
  go.onclick = () => runCapture(null);
  const heal = el('button', 'act', icon('alert') + 'Review selector repairs');
  heal.title = 'What the healer proposed when a selector stopped resolving';
  heal.onclick = () => setView('capture');
  bar.append(go, heal);
  m.append(bar);
}

/* ------------------------------------------------------------- assistant */
/* Which model does the writing, how it is reached, and the rules it writes by.

   All three were real settings with no interface. The model and the gateway
   lived in content/doc.yaml or in an environment variable, so the honest answer
   to "which model is this using?" was to read a YAML file, and to "can I point
   it at mine?" was to edit one. The writing rules were worse: a string compiled
   into the engine, so a team that documents route paths on purpose, or writes
   in a different register, had no way to say so and watched every pass undo
   them. */
async function drawAssistant(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'The writer'));
  m.append(el('div', 'muted',
    'Verba can draft and tidy sections for you. It needs a key to do that, ' +
    'and it never writes anything without showing you first.'));

  let d;
  try { d = await api('/api/assistant'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  const uid = 'as' + Math.random().toString(36).slice(2, 6);
  const ready = d.backends.filter(b => b.ready);

  // Where it stands, in one sentence, before any settings at all.
  const state = el('div', 'panel ' + (ready.length ? 'ok-edge' : 'warn-edge'));
  state.append(el('div', 'bigstate', ready.length
    ? `Ready, using ${esc(ready[0].label)}.`
    : 'Not set up yet. Add a key below and the writer starts working.'));
  if (ready.length) {
    state.append(el('div', 'muted',
      'Everything else on this page is optional.'));
  }
  m.append(state);

  // The one thing most people need.
  const keyp = el('div', 'panel');
  keyp.append(el('h3', null, 'Your Claude key'));
  keyp.append(el('div', 'muted',
    d.has_key
      ? 'A key is saved on this machine, in the login keychain. It is never ' +
        'written into this project or shown again.'
      : 'Paste a key from console.anthropic.com. It is saved on this machine, ' +
        'in the login keychain, never into this project and never into a log.'));
  const kf = el('div', 'field'); kf.style.maxWidth = '520px'; kf.style.marginTop = '12px';
  kf.innerHTML = `<label for="${uid}key">Key</label>
    <input id="${uid}key" type="password" autocomplete="off"
      placeholder="${d.has_key ? '\u2022'.repeat(24) + '  (saved)' : 'sk-ant-...'}">
    <div class="help">Leave blank to keep the one you have.</div>`;
  keyp.append(kf);
  const krow = el('div', 'row');
  const ksave = el('button', 'act primary', icon('check') + 'Save the key');
  ksave.onclick = async () => {
    const v = document.getElementById(uid + 'key').value;
    if (!v.trim()) return toast('Nothing to save', true);
    ksave.disabled = true;
    try {
      await api('/api/assistant/set', { method: 'POST', json: { api_key: v } });
      toast('Key saved on this machine');
      drawAssistant(holder());
    } catch (e) { toast(e.message, true); ksave.disabled = false; }
  };
  krow.append(ksave);
  if (d.has_key) {
    const drop = el('button', 'act ghost', 'Forget it');
    drop.onclick = async () => {
      if (!await modal({ title: 'Forget the saved key?',
        body: '<p>It is removed from this machine\u2019s keychain. The writer ' +
              'stops working until another is added.</p>',
        confirmLabel: 'Forget it', confirmClass: 'danger' })) return;
      await api('/api/assistant/set', { method: 'POST', json: { api_key: '' } });
      toast('Key forgotten');
      drawAssistant(holder());
    };
    krow.append(drop);
  }
  keyp.append(krow);
  m.append(keyp);

  // Which model, chosen by what it is good at rather than by its id.
  const mp = el('div', 'panel');
  mp.append(el('h3', null, 'Which model does the writing'));
  const grid = el('div', 'models');
  const known = d.models.some(x => x.id === d.model);
  d.models.forEach(mo => {
    const card = el('button', 'model' + (mo.id === d.model ? ' on' : ''));
    card.innerHTML = `<div class="mname">${esc(mo.label)}${mo.id === d.model ? ' \u2713' : ''}</div>
      <div class="mwhy">${esc(mo.why)}</div>`;
    card.disabled = mo.id === d.model;
    card.onclick = async () => {
      await api('/api/assistant/set', { method: 'POST', json: { model: mo.id } });
      toast(`Now writing with ${mo.label}`);
      drawAssistant(holder());
    };
    grid.append(card);
  });
  mp.append(grid);
  if (!known && d.model) {
    mp.append(el('div', 'muted',
      `Currently set to <code>${esc(d.model)}</code>, which is not one of these. ` +
      `That is fine: it is passed through exactly as written.`));
  }
  m.append(mp);

  // Everything an ordinary person never has to see.
  const adv = el('details', 'advanced');
  adv.append(el('summary', null, 'If your company runs its own AI service'));
  const inner = el('div', 'pad');
  inner.append(el('div', 'muted',
    'Some organisations route all AI usage through one internal address so it ' +
    'can be paid for and audited centrally. If yours does, whoever set it up ' +
    'will give you these two. Otherwise ignore this.'));
  const g = el('div', 'grid2'); g.style.marginTop = '12px';
  g.innerHTML = `
    <div class="field"><label for="${uid}g">Address of the service</label>
      <input id="${uid}g" value="${esc(d.gateway || '')}"
        placeholder="https://ai.yourcompany.com"></div>
    <div class="field"><label for="${uid}k">Script that supplies the key</label>
      <input id="${uid}k" value="${esc(d.key_helper || '')}"
        placeholder="~/.config/ai-key.sh">
      <div class="help">Only if they gave you one instead of a key.</div></div>
    <div class="field" style="grid-column:1/-1">
      <label for="${uid}m">Model name, exactly as your service knows it</label>
      <input id="${uid}m" value="${esc(d.model || '')}" placeholder="claude-sonnet-5"></div>`;
  inner.append(g);
  const arow = el('div', 'row');
  const asave = el('button', 'act', icon('check') + 'Save these');
  asave.onclick = async () => {
    const v = (k) => (document.getElementById(uid + k).value || '').trim();
    try {
      const r = await api('/api/assistant/set', { method: 'POST', json: {
        gateway: v('g'), key_helper: v('k'), model: v('m') } });
      toast(r.message);
      if (r.restart_hint) toast('Reload the console for this to take effect', true);
      drawAssistant(holder());
    } catch (e) { toast(e.message, true); }
  };
  arow.append(asave); inner.append(arow);
  adv.append(inner);
  m.append(adv);

  // How it is reached, as a fact rather than a setting.
  const reach = el('details', 'advanced');
  reach.append(el('summary', null, 'How the writer is reaching a model'));
  const rin = el('div', 'pad');
  rin.append(el('div', 'muted', 'Tried in this order. The first that answers is used.'));
  d.backends.forEach(b => {
    const row = el('div', 'backend' + (b.ready ? ' on' : ''));
    row.innerHTML = `<span class="bmark">${b.ready ? '&#10003;' : '&#8212;'}</span>` +
      `<span class="bbody"><b>${esc(b.label)}</b>` +
      `<span class="bnote">${esc(b.note || '')}</span></span>`;
    rin.append(row);
  });
  reach.append(rin);
  m.append(reach);

  // The rules, last, because most people never change them.
  const rules = el('details', 'advanced');
  rules.append(el('summary', null, 'The rules it writes by'));
  const rr = el('div', 'pad');
  rr.append(el('div', 'muted',
    d.house_is_custom
      ? 'Your own. Empty the box and save to go back to the built-in set.'
      : 'The built-in set: no em dashes, no web addresses in the text, bullets ' +
        'for lists, never invent a fact. Edit it and it becomes yours.'));
  const ta = el('textarea', 'houserules');
  ta.value = d.house_rules || '';
  ta.spellcheck = false;
  ta.setAttribute('aria-label', 'House writing rules');
  rr.append(ta);
  const rrow = el('div', 'row');
  const rsave = el('button', 'act', icon('check') + 'Save the rules');
  rsave.onclick = async () => {
    try {
      await api('/api/assistant/set', { method: 'POST', json: { house_rules: ta.value } });
      toast('Rules saved');
      drawAssistant(holder());
    } catch (e) { toast(e.message, true); }
  };
  rrow.append(rsave); rr.append(rrow);
  rules.append(rr);
  m.append(rules);
}

/* ------------------------------------------------------------- documents */
/* Which system you are documenting.

   The console served exactly one folder, fixed when the process started, which
   is the right shape for a tool living inside the single project it serves and
   the wrong one for a tool you point at whatever you like. Documenting a second
   system meant a second terminal and a second port, and remembering which tab
   was which. A document is still only a folder with a content/doc.yaml in it;
   this is the list of where they are. */
async function documentPicker() {
  let d;
  try { d = await api('/api/documents'); }
  catch (e) { return toast(e.message, true); }

  const body = el('div');
  body.append(el('div', 'muted',
    'Every document this machine knows about. Opening one switches the whole ' +
    'console over to it; nothing about the one you leave is changed.'));

  const list = el('div', 'docs');
  d.documents.forEach(doc => {
    const row = el('button', 'docrow' + (doc.current ? ' on' : '') +
                             (doc.exists ? '' : ' gone'));
    row.innerHTML =
      `<div class="dmark">${icon(doc.current ? 'check' : 'document')}</div>
       <div class="dbody"><div class="dname">${esc(doc.product)}</div>
         <div class="dpath">${esc(doc.path)}</div></div>` +
      (doc.exists ? '' : '<div class="dgone">missing</div>');
    row.disabled = doc.current || !doc.exists;
    row.onclick = async () => {
      try {
        const r = await api('/api/documents/open', { method: 'POST',
                                                     json: { path: doc.path } });
        toast(r.message);
        scrim.remove();
        view = 'overview';
        await refresh();
      } catch (e) { toast(e.message, true); }
    };
    list.append(row);
  });
  if (!d.documents.length) {
    list.append(el('div', 'empty', 'No documents yet.'));
  }
  body.append(list);

  const scrim = el('div', 'scrim');
  const box = el('div', 'modal wide');
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.append(el('h3', null, icon('layers') + 'Documents'));
  box.append(fill(el('div', 'body'), body));

  const foot = el('div', 'foot');
  const close = () => { scrim.remove(); document.removeEventListener('keydown', key); };
  const key = (e) => { if (e.key === 'Escape') close(); };
  const cancel = el('button', 'act ghost', 'Close');
  cancel.onclick = close;
  const fresh = el('button', 'act primary', icon('plus') + 'New document');
  fresh.onclick = () => { close(); newDocument(d.home); };
  foot.append(cancel, fresh);
  box.append(foot);
  scrim.append(box);
  document.body.append(scrim);
  document.addEventListener('keydown', key);
  scrim.onclick = (e) => { if (e.target === scrim) close(); };
}

/* The same list as a full view, for anyone who never thinks to click a
   masthead. Two ways in is not duplication here: one is where you are already
   looking when you want to switch, the other is where you look when you are
   hunting for a feature you were told exists. */
async function drawDocuments(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Documents'));
  m.append(el('div', 'muted',
    'Every system you document with Verba. A document is a folder with a ' +
    'content/doc.yaml in it; this is the list of where they are.'));

  let d;
  try { d = await api('/api/documents'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  const bar = el('div', 'row'); bar.style.margin = '14px 0';
  const add = el('button', 'act primary', icon('plus') + 'New document');
  add.onclick = () => newDocument(d.home);
  bar.append(add); m.append(bar);

  const panel = el('div', 'panel'); panel.style.padding = '10px';
  const list = el('div', 'docs'); list.style.marginTop = '0';
  d.documents.forEach(doc => {
    const row = el('div', 'docrow' + (doc.current ? ' on' : '') +
                            (doc.exists ? '' : ' gone'));
    row.innerHTML =
      `<div class="dmark">${icon(doc.current ? 'check' : 'document')}</div>
       <div class="dbody"><div class="dname">${esc(doc.product)}</div>
         <div class="dpath">${esc(doc.path)}</div></div>`;
    const acts = el('div', 'row');
    if (doc.exists && !doc.current) {
      const open = el('button', 'mini go', 'Open');
      open.onclick = async () => {
        try {
          const r = await api('/api/documents/open', { method: 'POST',
                                                       json: { path: doc.path } });
          toast(r.message); view = 'overview'; await refresh();
        } catch (e) { toast(e.message, true); }
      };
      acts.append(open);
    }
    if (doc.current) acts.append(el('span', 'muted', 'open now'));
    if (!doc.exists) acts.append(el('span', 'dgone', 'missing'));
    if (!doc.current) {
      const drop = el('button', 'mini', 'Remove');
      drop.title = 'Takes it off this list. The folder itself is untouched.';
      drop.onclick = async () => {
        await api('/api/documents/forget', { method: 'POST', json: { path: doc.path } });
        drawDocuments(holder());
      };
      acts.append(drop);
    }
    row.append(acts);
    list.append(row);
  });
  panel.append(list);
  m.append(panel);
}

/* Starting one. The same six questions the command line asks, because a person
   who has never seen this should not have to learn a file format to begin. Every
   field has a default, so the whole thing can be submitted as it stands. */
async function newDocument(home) {
  const uid = 'nd' + Math.random().toString(36).slice(2, 7);
  const body = el('div');
  body.append(el('div', 'muted',
    'Six questions, then you have a document that builds. Everything here can ' +
    'be changed afterwards.'));

  const g = el('div', 'grid2'); g.style.marginTop = '14px';
  g.innerHTML = `
    <div class="field"><label for="${uid}p">What is the product called?</label>
      <input id="${uid}p" placeholder="Acme Console"></div>
    <div class="field"><label for="${uid}v">Who makes it?</label>
      <input id="${uid}v" placeholder="same as the product"></div>
    <div class="field" style="grid-column:1/-1">
      <label for="${uid}a">What does it do, in one sentence?</label>
      <input id="${uid}a" placeholder="Where operators configure campaigns."></div>
    <div class="field"><label for="${uid}u">Where does it live?</label>
      <input id="${uid}u" placeholder="https://app.example.com"></div>
    <div class="field"><label for="${uid}h">How do you sign in?</label>
      <select id="${uid}h">
        <option value="form">A username and password</option>
        <option value="sso">Single sign-on</option>
        <option value="none">No sign-in needed</option>
      </select></div>`;
  body.append(g);

  const looks = el('div', 'field'); looks.style.marginTop = '4px';
  looks.innerHTML = `<label for="${uid}t">Which look?</label>
    <select id="${uid}t">
      <option value="slate">Slate — the neutral default</option>
      <option value="ink">Ink — editorial monochrome, one warm accent</option>
      <option value="atlas">Atlas — deep teal, engineering register</option>
      <option value="ember">Ember — warm charcoal and amber</option>
      <option value="forest">Forest — deep green, unbranded</option>
    </select>`;
  body.append(looks);

  const where = el('div', 'field'); where.style.marginTop = '11px';
  where.innerHTML = `<label for="${uid}w">Where should it go?</label>
    <input id="${uid}w" value="${esc(home || '')}">
    <div class="help">A folder is created here. The product name is added to it.</div>`;
  body.append(where);

  const scrim = el('div', 'scrim');
  const box = el('div', 'modal wide');
  box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
  box.append(el('h3', null, icon('plus') + 'New document'));
  box.append(fill(el('div', 'body'), body));

  const foot = el('div', 'foot');
  const close = () => { scrim.remove(); document.removeEventListener('keydown', key); };
  const key = (e) => { if (e.key === 'Escape') close(); };
  const cancel = el('button', 'act ghost', 'Cancel');
  cancel.onclick = close;
  const make = el('button', 'act primary', icon('check') + 'Create it');
  make.onclick = async () => {
    const v = (k) => (box.querySelector('#' + uid + k).value || '').trim();
    const product = v('p') || 'My Product';
    const base = v('w') || home || '';
    const slug = product.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    make.disabled = true;
    try {
      const r = await api('/api/documents/new', { method: 'POST', json: {
        path: base.replace(/\/$/, '') + '/' + (slug || 'document'),
        product, vendor: v('v'), about: v('a'), base_url: v('u'),
        auth: v('h'), theme: v('t') } });
      toast(r.message);
      close();
      view = 'overview';
      await refresh();
    } catch (e) { toast(e.message, true); make.disabled = false; }
  };
  foot.append(cancel, make);
  box.append(foot);
  scrim.append(box);
  document.body.append(scrim);
  document.addEventListener('keydown', key);
  box.querySelector('#' + uid + 'p').focus();
}

/* -------------------------------------------------------------- editions */
/* What this edition of the document carries.

   Before this, an edition could add a section and could not drop one: the only
   mechanism was `profiles:` in a section's own front matter, which answers the
   question from the wrong end. Seeing what the customer edition contained meant
   opening thirty-eight files; dropping a chapter from it meant editing every
   file underneath. The list belongs to the edition, so it is edited here.

   A section under a dropped chapter shows why it is out and offers no control:
   its chapter is the decision, and offering a switch that cannot be the answer
   is worse than offering none. */
async function drawEditions(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Editions'));

  let d;
  try { d = await api('/api/edition'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  m.append(el('div', 'muted',
    `The <b>${esc(d.profile)}</b> edition carries ${d.carried} of ${d.total} sections.` + hint(
      d.mode === 'include'
        ? 'This edition is written as a list of exactly what it carries. Naming a ' +
          'sub-section keeps the chapter above it, so the numbering still reads.'
        : 'This edition carries everything except what is switched off. Dropping a ' +
          'chapter drops what is under it, because that is what dropping a chapter ' +
          'means. Numbering closes up: leave out chapter 3 and what follows becomes 3.')));

  const bar = el('div', 'row'); bar.style.margin = '14px 0';
  const build = el('button', 'act primary', icon('publish') + 'Rebuild this edition');
  build.onclick = () => runJob('/api/build', { pdf: true }, 'build');
  bar.append(build);
  if (d.carried !== d.total) {
    const all = el('button', 'act', icon('refresh') + 'Carry everything again');
    all.onclick = async () => {
      try { const r = await api('/api/edition/reset', { method: 'POST', json: {} });
            toast(r.message); drawEditions(holder()); }
      catch (e) { toast(e.message, true); }
    };
    bar.append(all);
  }
  m.append(bar);

  const panel = el('div', 'panel');
  d.sections.forEach(s => {
    const row = el('div', 'erow' + (s.carried ? '' : ' off'));
    row.style.paddingLeft = (10 + s.depth * 18) + 'px';

    const box = el('label', 'egrip');
    if (s.settable) {
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = s.carried;
      cb.onchange = async () => {
        cb.disabled = true;
        try {
          const r = await api('/api/edition/carry', { method: 'POST',
            json: { id: s.id, carried: cb.checked } });
          toast(r.message);
          drawEditions(holder());
        } catch (e) { toast(e.message, true); cb.checked = !cb.checked; cb.disabled = false; }
      };
      box.append(cb);
    } else {
      box.append(el('span', 'muted', s.carried ? '' : icon('lock')));
    }
    row.append(box);

    const body = el('div', 'ebody');
    body.append(el('div', 'etitle',
      (s.number ? `<span class="num">${esc(s.number)}</span> ` : '') + esc(s.title)));
    body.append(el('div', 'eid', esc(s.id) + (s.why ? ` &middot; ${esc(s.why)}` : '')));
    row.append(body);
    panel.append(row);
  });
  m.append(panel);

  m.append(el('div', 'muted',
    'Which sections an edition carries lives in content/profiles/' +
    esc(d.profile) + '.yaml. A section written for one customer and no one else ' +
    'still says so in its own front matter, and that still wins.'));
}

/* ---------------------------------------------------------------- design */
async function drawDesign(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Design'));
  await drawThemes(m);
  m.append(el('div', 'muted',
    'The typeface the document is set in, and the one this interface uses.' + hint(
      'A face is only usable if this machine can render it. Some are installed ' +
      'here; some are served from Google Fonts and fetched when needed. Check ' +
      'asks Chromium directly, because Chromium is what prints the PDF.')));

  let d;
  try { d = await api('/api/fonts'); }
  catch (e) { m.append(el('div', 'panel', `<div class="empty">${esc(e.message)}</div>`)); return; }

  const bar = el('div', 'row'); bar.style.margin = '14px 0';
  const chk = el('button', 'act', icon('check') + 'Check every typeface');
  chk.onclick = () => runJob('/api/fonts/verify', {}, 'typeface check');
  const bld = el('button', 'act primary', icon('publish') + 'Rebuild the document');
  bld.onclick = () => runJob('/api/build', { pdf: true }, 'build');
  bar.append(chk, bld); m.append(bar);

  const pick = async (which, key) => {
    try {
      const r = await api('/api/fonts/choose', { method: 'POST', json: { [which]: key } });
      toast(r.message);
      if (which === 'console') {
        // the generated stylesheet is what carries the change, so pull it again
        const link = [...document.querySelectorAll('link')].find(l => l.href.includes('/fonts.css'));
        if (link) link.href = '/fonts.css?t=' + Date.now();
      }
      drawDesign(holder());
    } catch (e) { toast(e.message, true); }
  };

  // A specimen set in the wrong font is worse than no specimen: it shows a
  // choice that is not the choice. Pull each served face in before drawing.
  d.faces.filter(f => f.url).forEach(f => {
    if (document.querySelector(`link[data-face="${f.key}"]`)) return;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = f.url; l.dataset.face = f.key;
    document.head.append(l);
  });
  try { await document.fonts.ready; } catch (e) { /* specimens fall back */ }

  const grid = el('div', 'faces');
  d.faces.forEach(f => {
    const card = el('div', 'face' + (f.is_document ? ' on' : ''));
    if (!f.available) card.classList.add('gone');
    card.append(el('div', 'name', esc(f.label)));

    // The specimen is set in the face itself, so the choice is made by looking
    // rather than by reading a font name and imagining it.
    const spec = el('div', 'spec');
    spec.style.fontFamily = f.stack || `"${f.primary}", sans-serif`;
    spec.innerHTML = `<div class="big">Rise Platform 2.0</div>
      <div class="run">Supply partners, demand connections and deals.</div>
      <div class="fig">0123456789 &middot; ID 4821 &middot; 12.5%</div>`;
    card.append(spec);

    const where = f.available
      ? (f.webfont ? 'served from Google Fonts' : 'installed on this machine')
      : 'not on this machine';
    card.append(el('div', 'where', esc(where)));
    if (f.note) card.append(el('div', 'why', esc(f.note)));

    const row = el('div', 'row');
    const doc = el('button', 'mini' + (f.is_document ? ' on' : ' go'),
      f.is_document ? 'Document \u2713' : 'Use for the document');
    doc.disabled = f.is_document || !f.available;
    doc.onclick = () => pick('document', f.key);
    const con = el('button', 'mini' + (f.is_console ? ' on' : ''),
      f.is_console ? 'Interface \u2713' : 'Use here');
    con.disabled = f.is_console || !f.available;
    con.onclick = () => pick('console', f.key);
    row.append(doc, con);
    card.append(row);
    grid.append(card);
  });
  m.append(grid);

  m.append(el('div', 'muted',
    'Faces live in content/typography.yaml. Add one by giving it a family stack, ' +
    'the size and leading it wants, and what Word should fall back to.'));

  await drawLayout(m);
  await drawDecisions(m);
}

/* Where the ink goes. Every control here used to be either a constant in a
   renderer or a key in a file that nothing read: doc.yaml carried `page: A4`
   for months while A4 was written into the PDF renderer three times over, so
   changing it moved nothing at all. The readout under the controls is the
   point of the panel: a margin is a number until you see what it leaves you to
   print on. */
async function drawLayout(m) {
  let d;
  try { d = await api('/api/layout'); }
  catch (e) { return; }

  const p = el('div', 'panel'); p.style.marginTop = '18px';
  p.append(el('h3', null, 'Page and layout'));
  p.append(el('div', 'muted',
    'The sheet, the margins, and how body text is set.' + hint(
      'The PDF and the Word file are laid out from these same numbers, so they ' +
      'cannot disagree about what the document is. Margins are in millimetres ' +
      'and the figure width is in centimetres, which is how each is written in ' +
      'the files behind this panel.')));

  const uid = 'ly' + Math.random().toString(36).slice(2, 7);
  const num = (k, label, val, step) =>
    `<div class="field"><label for="${uid}${k}">${esc(label)}</label>
      <input id="${uid}${k}" type="number" step="${step || 1}" min="0" value="${val}"></div>`;
  const sel = (k, label, opts, val) =>
    `<div class="field"><label for="${uid}${k}">${esc(label)}</label><select id="${uid}${k}">` +
    opts.map(o => `<option value="${esc(o[0])}" ${o[0] === val ? 'selected' : ''}>${esc(o[1])}</option>`).join('') +
    `</select></div>`;

  const sheet = el('div', 'grid2'); sheet.style.marginTop = '12px';
  sheet.innerHTML =
    sel('paper', 'Paper', d.papers.map(x => [x.name, `${x.name}  (${x.mm})`]), d.paper) +
    num('side', 'Side margins (mm)', d.side) +
    num('edge', 'Edge (mm)', d.edge) +
    num('gap', 'Gap under the header (mm)', d.gap) +
    num('header_band', 'Header band (mm)', d.header_band) +
    num('footer_band', 'Footer band (mm)', d.footer_band);
  p.append(sheet);

  const setting = el('div', 'grid2'); setting.style.marginTop = '12px';
  setting.innerHTML =
    sel('align', 'Body text', [['left', 'Ragged right'], ['justify', 'Justified']], d.align) +
    sel('hyphens', 'Hyphenation', [['on', 'On'], ['off', 'Off']], d.hyphens) +
    num('screenshot_width_cm', 'Figure width (cm)', d.screenshot_width_cm, 0.5) +
    num('toc_depth', 'Contents depth', d.toc_depth);
  p.append(setting);

  // What the numbers above actually leave you, recomputed as they are typed.
  const read = el('div', 'muted'); read.style.marginTop = '12px';
  const keys = ['paper', 'side', 'edge', 'gap', 'header_band', 'footer_band',
                'align', 'hyphens', 'screenshot_width_cm', 'toc_depth'];
  // Scoped to the panel, not to the document: these run before the panel is
  // appended, so a document-wide lookup finds nothing and the readout never wires up.
  const node = k => p.querySelector(`#${uid}${k}`);
  const val = k => {
    const n = node(k);
    return n.type === 'number' ? Number(n.value) : n.value;
  };
  const PAPERS = {}; d.papers.forEach(x => {
    const [w, h] = x.mm.replace(' mm', '').split(' x ').map(Number);
    PAPERS[x.name] = [w, h];
  });
  const refresh = () => {
    const [w] = PAPERS[val('paper')] || [210];
    const col = w - 2 * val('side');
    const top = val('edge') + val('header_band') + val('gap');
    const over = val('screenshot_width_cm') * 10 > col + 0.5;
    read.innerHTML =
      `A ${esc(val('paper'))} sheet leaves a <b>${(col / 10).toFixed(1)} cm</b> column, ` +
      `with ${top.toFixed(0)} mm above the first line.` +
      (over ? ` <span class="bad">A ${val('screenshot_width_cm')} cm figure runs off it.</span>` : '');
  };
  keys.forEach(k => { const n = node(k); n.oninput = refresh; n.onchange = refresh; });
  refresh();
  p.append(read);

  const bar = el('div', 'row'); bar.style.marginTop = '14px';
  const save = el('button', 'act primary', icon('check') + 'Save and rebuild');
  save.onclick = async () => {
    const body = {}; keys.forEach(k => { body[k] = val(k); });
    save.disabled = true;
    try {
      const r = await api('/api/layout/set', { method: 'POST', json: body });
      toast(r.message);
      if ((r.message || '').startsWith('changed')) runJob('/api/build', { pdf: true }, 'build');
    } catch (e) { toast(e.message, true); }
    save.disabled = false;
  };
  const back = el('button', 'act', 'Reset to A4');
  back.onclick = async () => {
    try {
      await api('/api/layout/set', { method: 'POST',
        json: { paper: 'A4', side: 18, edge: 12, header_band: 8, footer_band: 7, gap: 9 } });
      drawDesign(holder());
    } catch (e) { toast(e.message, true); }
  };
  bar.append(save, back);
  p.append(bar);
  m.append(p);
}

/* The palette the document prints in.

   Five of these shipped from the first day and there was no way to choose one:
   the setting lived in content/theme.yaml and the Design view offered
   typefaces. A theme you cannot pick is a theme nobody has. */
async function drawThemes(m) {
  let d;
  try { d = await api('/api/theme'); }
  catch (e) { return; }

  m.append(el('div', 'muted',
    'The palette the document prints in. Every one of these is measured rather ' +
    'than eyeballed: body text at 7:1 and the accent at 4.5:1, against the ' +
    'ground each colour actually sits on.' + hint(
      'An accent usually fails on its own tinted callout background rather ' +
      'than on the page, which is why each is checked there too. ' +
      '`verba themes --check` measures whatever you have set.')));

  const grid = el('div', 'themes');
  d.themes.forEach(th => {
    const card = el('button', 'theme' + (th.name === d.current ? ' on' : ''));
    const sw = th.swatch.map(s => `<i style="background:#${esc(s)}"></i>`).join('');
    card.innerHTML = `<div class="tsw">${sw}</div>
      <div class="tname">${esc(th.label)}${th.name === d.current ? ' \u2713' : ''}</div>
      <div class="tabout">${esc((th.about || '').trim())}</div>`;
    card.disabled = th.name === d.current;
    card.onclick = async () => {
      try {
        const r = await api('/api/theme/use', { method: 'POST', json: { use: th.name } });
        toast(r.message);
        drawDesign(holder());
      } catch (e) { toast(e.message, true); }
    };
    grid.append(card);
  });
  m.append(grid);
}

/* What was decided about how this looks, why, and what holds us to it.
   The content side of this system has remembered for a while: house terms,
   accepted phrasing, every decision with its reason. This is the same idea for
   the other half of the work, and the reason it is here rather than in a
   document is that a note nothing reads gets made twice. */
async function drawDecisions(m) {
  let d;
  try { d = await api('/api/design'); } catch (e) { return; }

  const head = el('h3', 'page');
  head.style.marginTop = 'var(--s6)';
  head.innerHTML = `Decisions${hint(
    'Each one names what holds us to it: a lint rule that fails a build, or ' +
    'the module that applies it. A decision nothing enforces is a note, and ' +
    'is listed as such.')}`;
  m.append(head);
  m.append(el('div', 'muted',
    `${d.summary.decisions} decision(s), ${d.summary.traps} recorded trap(s)` +
    (d.summary.unenforced.length
      ? ` \u00b7 ${d.summary.unenforced.length} not held by anything`
      : ' \u00b7 all of them enforced')));

  if (d.findings.length) {
    const p = el('div', 'panel warn-edge');
    p.append(el('h3', null, icon('alert') +
      `${d.findings.length} place(s) the project has drifted from a decision`));
    d.findings.forEach(f => p.append(el('div', 'muted',
      `<b>${esc(f.rule)}</b> ${esc(f.message)}` +
      (f.detail ? `<div class="why">${esc(f.detail)}</div>` : ''))));
    m.append(p);
  }

  Object.entries(d.areas).sort().forEach(([area, items]) => {
    const p = el('div', 'panel');
    p.append(el('h3', null, esc(area)));
    items.forEach(x => {
      const row = el('div', 'item done');
      row.append(el('span', 'mark', '\u2713'));
      const held = x.held_by === 'nothing yet'
        ? '<span class="chip err">nothing enforces this</span>'
        : `<span class="chip">${esc(x.held_by)}</span>`;
      row.append(el('span', 'what',
        `${esc(x.decided)} ${held}` +
        (x.because ? `<div class="why">${esc(x.because)}</div>` : '')));
      p.append(row);
    });
    m.append(p);
  });

  if (d.traps.length) {
    const p = el('div', 'panel');
    p.append(el('h3', null, icon('alert') +
      `${d.traps.length} trap(s) that cost real time once` + hint(
        'Kept so they cost it once. Each names the file it lives in.')));
    d.traps.forEach(t => p.append(el('div', 'muted',
      `<b>${esc(t.where)}</b>: ${esc(t.trap)}`)));
    m.append(p);
  }
}

/* ---------------------------------------------------------------- sections */
function drawSections(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Sections'));
  m.append(el('div', 'muted',
    'Click a row to open it. Recapture pulls that screen from the live system again.'));
  const p = el('div', 'panel');
  const t = el('table', null, `<thead><tr><th>#</th><th>Section</th><th>Status</th>
    <th>Verified</th><th>Screen</th><th>Words</th><th>Flags</th></tr></thead>`);
  const b = el('tbody');
  S.sections.forEach(s => {
    const errs = s.lint.filter(l => l.level === 'error').length;
    const flags = [];
    if (s.drift.length) flags.push(`<span class="chip err">${s.drift.length} drift</span>`);
    if (errs) flags.push(`<span class="chip err">${errs} lint</span>`);
    const tr = el('tr', 'click', `
      <td class="muted">${esc(s.number)}</td>
      <td>${s.mark || (s.icon ? esc(s.icon) + ' ' : '')}${esc(s.title)}</td>
      <td><span class="chip ${s.status}">${esc(s.status)}</span></td>
      <td class="muted">${esc(s.last_verified || '-')}</td>
      <td class="muted">${esc(s.screens.join(', ') || '-')}</td>
      <td class="muted">${s.words}</td>
      <td>${flags.join(' ') || '<span class="muted">-</span>'}</td>`);
    tr.onclick = () => openSection(s.id);
    b.append(tr);
  });
  t.append(b); const w = el('div','wrap-x'); w.append(t); p.append(w); m.append(p);
}

/* ---------------------------------------------------------------- queue */
function drawQueue(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Review queue'));
  const fb = fixtureBanner(); if (fb) m.append(fb);
  const withDrift = S.sections.filter(s => s.drift.some(c => !c.decided));
  const allSettled = S.sections.filter(
    s => s.drift.length && !s.drift.some(c => !c.decided));
  const gaps = S.proposals?.proposals || [];
  m.append(el('div', 'muted', S.capture.run
    ? `Differences between capture ${esc(S.capture.run)} and the document.`
    : 'No capture yet. Run one from Overview to populate this queue.'));

  const bar = el('div', 'row'); bar.style.margin = '14px 0';
  const rc = el('button', 'act primary', 'Capture everything'); rc.onclick = () => runCapture(null);
  const sw = el('button', 'act', 'Review the crawl');
  sw.title = 'Look for pictures that moved on and descriptions the crawl can now answer';
  sw.onclick = () => runJob('/api/sweep', {}, 'review');
  const rd = el('button', 'act', 'Recheck drift');
  rd.onclick = () => runJob('/api/drift/run', {}, 'drift');
  bar.append(rc, sw, rd); m.append(bar);

  if (gaps.length) {
    const g = el('div', 'panel accent');
    g.append(el('h3', null, icon('edit') +
      `${gaps.length} gap(s) the crawl filled in for you` + hint(
        'After a crawl the system reviews its own work: pictures that no longer ' +
        'match, and TODO markers the fresh evidence can answer. Each is a proposal ' +
        'waiting on you.')));
    gaps.forEach(pr => {
      const row = el('div', 'item open');
      row.append(el('span', 'mark', pr.kind === 'image' ? '\u25a3' : '\u270e'));
      row.append(el('span', 'what',
        `${esc(pr.title)}<div class="why">${esc(pr.detail)}</div>`));
      const b = el('button', 'mini go', 'Review');
      b.onclick = () => settleProposal(pr, () => { view = 'queue'; render(); });
      row.append(b);
      g.append(row);
    });
    m.append(g);
  }

  if (!withDrift.length && !gaps.length) {
    m.append(el('div', 'panel accent',
      `<div class="empty">Nothing outstanding.` +
      (allSettled.length
        ? ` ${allSettled.length} section(s) have differences you have already
            decided on, below.</div>`
        : '</div>')));
  }
  // A queue that shows settled work alongside open work stops reading as a
  // queue. Decided items fold away, and say how many they are.
  const card = (s) => {
    const settled = s.drift.filter(c => c.decided).length;
    const openCount = s.drift.length - settled;
    const d = el('div', 'drift' + (openCount ? '' : ' settled-card'));
    const hd = el('div', 'hd');
    hd.append(el('div', null, `<b>${esc(s.number)} ${esc(s.title)}</b>
      <span class="muted"> ${esc(s.id)}</span>`));
    const acts = el('div', 'row');
    const open = el('button', 'mini', 'Open'); open.onclick = () => openSection(s.id);
    const recap = el('button', 'mini', 'Recapture');
    recap.disabled = !s.capturable.length;
    recap.onclick = () => runCapture(s.capturable, s.id);
    const ready = pending(s);
    const undecided = s.drift.filter(c => !c.decided).length;
    const all = el('button', 'mini go',
      ready.length ? `Apply all ${ready.length}` : 'Apply all');
    all.disabled = !ready.length;
    all.title = ready.length
      ? `Apply every open difference in this section`
      : (undecided
          ? `${undecided} picture(s) here, which are reviewed one at a time`
          : 'every difference here is already decided');
    all.onclick = () => applyAll(s);
    acts.append(open, recap, all); hd.append(acts); d.append(hd);

    const ul = el('ul');
    const settledList = settled ? el('ul') : null;
    s.drift.forEach(c => {
      const li = el('li');
      if (c.decided) li.className = 'decided';
      li.append(el('span', 'line',
        esc(c.line)));
      if (c.decided) {
        const row = el('span', 'row');
        const chip = el('span',
          'chip ' + (c.decided === 'declined' ? 'warn' : 'verified'),
          c.decided === 'declined' ? 'declined' : 'applied');
        if (c.decided_reason) chip.title = c.decided_reason;
        const back = el('button', 'mini', 'Reopen');
        back.title = 'Make this a live item again';
        back.onclick = () => reopen(c);
        row.append(chip, back);
        li.append(row);
      } else if (c.applicable) {
        const btn = el('button', 'mini go', 'Review');
        btn.onclick = () => previewDriftChange(c, s.title);
        li.append(btn);
      } else {
        // An observation, not a proposed edit: there is nothing to approve.
        // Closing it means writing the section, so offer that directly.
        const row = el('span', 'row');
        const write = el('button', 'mini go', 'Write it');
        write.title = 'Ask the writing assistant to cover this, then review the diff';
        write.onclick = () => writeFor(c, s);
        const open = el('button', 'mini', 'Open');
        open.onclick = () => openSection(c.section);
        const no = el('button', 'mini', 'Decline');
        no.onclick = () => decide(c, 'declined');
        row.append(write, open, no);
        li.append(row);
      }
      (c.decided && settledList ? settledList : ul).append(li);
    });
    if (ul.children.length) d.append(ul);
    if (settledList && settledList.children.length) {
      const fold = el('details', 'settled');
      fold.append(el('summary', null, `${settled} already decided`), settledList);
      d.append(fold);
    }
    return d;
  };

  withDrift.forEach(s => m.append(card(s)));

  // Sections whose every difference is settled are not work. They stay
  // reachable, because reopening one is a normal thing to want, but they do
  // not sit at the top wearing the colour of something outstanding.
  if (allSettled.length) {
    const fold = el('details', 'settled');
    fold.style.marginTop = 'var(--s5)';
    fold.append(el('summary', null,
      `${allSettled.length} section(s) where every difference is already decided`));
    allSettled.forEach(s => fold.append(card(s)));
    m.append(fold);
  }
}

async function previewDriftChange(change, sectionTitle) {
  // A replaced screenshot has no text diff to show. Comparing the two images is
  // the only review that means anything for it.
  if (change.change === 'image') return previewImageChange(change, sectionTitle);
  let r;
  try {
    r = await api('/api/drift/preview', { method: 'POST', json: { change } });
  } catch (e) { return toast(e.message, true); }
  reviewChange({
    title: `${sectionTitle || change.section}`,
    note: `Proposed from the crawl: ${change.line}. Nothing has been written yet.`,
    before: r.before, after: r.after,
    onApprove: () => decide(change, 'approved'),
    onDecline: () => decide(change, 'declined'),
    onCancel: () => setView('queue'),
  });
}

/* Approve applies the change. Decline asks why, and that reason is kept: the
   next crawl marks the item as already decided, and the writing assistant is
   told about it so a decision made once is not quietly undone. */
/* Some findings say the section is missing something rather than proposing a
   specific edit. Nothing can be approved, because nothing was proposed: the way
   to close one is to write the section, which is what the assistant is for. */
async function writeFor(change, section) {
  const go = await modal({
    title: 'Write this with the assistant',
    body: `<p><b>${esc(change.line)}</b></p>
      <p class="muted">This is an observation, not a proposed edit, so there is
      nothing to approve. The assistant will draft the section against the crawl
      evidence and you review the diff before anything is written.</p>
      <p class="muted">It writes <code>TODO: describe this.</code> wherever the
      evidence does not say what a control does.</p>`,
    confirmLabel: 'Draft it',
  });
  if (!go) return;
  try {
    const r = await api('/api/assist',
      { method: 'POST', json: { section: change.section, task: 'reconcile' } });
    watchJob(r.job, `Write: ${section.title}`, null,
      (result) => showProposal(change.section, `Write: ${section.title}`, result));
  } catch (e) { toast(e.message, true); }
}

/* A decision you cannot take back is a trap, not a decision. Reopening keeps
   the record that a judgement was made and reconsidered. */
async function reopen(change) {
  const note = await modal({
    title: 'Reopen this decision',
    body: `<p><b>${esc(change.line || '')}</b></p>
      <p class="muted">It becomes a live item again, and the writing assistant
      stops being told to respect it. The original decision and its reason stay
      on record.</p>`,
    confirmLabel: 'Reopen',
    needsReason: false,
  });
  if (note === null) return;
  try {
    const r = await api('/api/decision/reopen', { method: 'POST', json: { change } });
    toast(r.message);
    await refresh();
    if (view === 'section' && currentId) openSection(currentId);
    else setView('queue');
  } catch (e) { toast(e.message, true); }
}

async function decide(change, verdict) {
  let reason = '';
  if (verdict === 'declined') {
    reason = await modal({
      title: 'Decline this change',
      body: `<p><b>${esc(change.line)}</b></p>
        <p class="muted">In ${esc(change.section)}.</p>`,
      confirmLabel: 'Decline and remember',
      confirmClass: 'danger',
      needsReason: true,
    });
    if (!reason) return;
  }
  try {
    const r = await api('/api/decision',
      { method: 'POST', json: { change, verdict, reason } });
    toast(r.message);
    await refresh();
    setView('queue');
  } catch (e) { toast(e.message, true); }
}

/* Looking at a figure properly needs the whole window, not a card in a list. */
function lightbox(images, index = 0) {
  let i = Math.max(0, Math.min(index, images.length - 1));
  let zoom = false;
  const box = el('div', 'lightbox');
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.innerHTML = `
    <div class="lbbar">
      <span class="name"></span>
      <button class="act ghost" data-a="zoom"></button>
      <button class="act ghost" data-a="open">Open full size</button>
      <button class="act ghost" data-a="close">Close</button>
    </div>
    <div class="stage"><img alt=""></div>
    <div class="lbfoot">
      <button class="act" data-a="prev">Previous</button>
      <span class="meta"></span>
      <button class="act" data-a="next">Next</button>
    </div>`;
  document.body.append(box);

  const img = box.querySelector('img');
  const stage = box.querySelector('.stage');
  const draw = () => {
    const it = images[i];
    img.src = it.url + '?t=' + Date.now();
    box.querySelector('.name').textContent = it.name;
    box.querySelector('[data-a=zoom]').textContent = zoom ? 'Fit to window' : 'Actual size';
    stage.classList.toggle('zoom', zoom);
    img.onload = () => {
      box.querySelector('.meta').textContent =
        `${i + 1} of ${images.length}  ·  ${img.naturalWidth} × ${img.naturalHeight}`;
    };
  };
  const close = () => { box.remove(); document.removeEventListener('keydown', key); };
  const step = (d) => { i = (i + d + images.length) % images.length; zoom = false; draw(); };
  const key = (e) => {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'ArrowLeft') step(-1);
  };
  box.onclick = (e) => {
    const a = e.target.closest('[data-a]');
    if (!a) { if (e.target === box) close(); return; }
    const act = a.dataset.a;
    if (act === 'close') close();
    else if (act === 'next') step(1);
    else if (act === 'prev') step(-1);
    else if (act === 'zoom') { zoom = !zoom; draw(); }
    else if (act === 'open') window.open(images[i].url, '_blank');
  };
  document.addEventListener('keydown', key);
  draw();
}

async function previewImageChange(change, sectionTitle) {
  const m = holder();
  m.append(el('h2', 'page', esc(sectionTitle || change.section)));
  m.append(el('div', 'muted',
    `${esc(change.line)}. The captured version replaces the one in the document ` +
    `only if you approve it.`));

  let run = '';
  try { run = (await api('/api/drift')).run || ''; } catch (e) { /* shown below */ }
  const name = change.label;
  const cur = `/files/content/assets/${name.startsWith('icon-') ? 'icons' : 'screenshots'}/${name}`;
  const fresh = run ? `/files/capture/${run}/screenshots/${name}` : '';

  const p = el('div', 'panel');
  p.append(el('h3', null, icon('camera') + 'In the document, and from the crawl'));
  const g = el('div', 'shots');
  const card = (label, src) => {
    const c = el('div', 'shot');
    c.innerHTML = `<img src="${src}?t=${Date.now()}" alt="${esc(label)}">
      <div class="cap"><span>${esc(label)}</span></div>`;
    return c;
  };
  g.append(card('now in the document', cur));
  if (fresh) g.append(card('from the crawl', fresh));
  p.append(g); m.append(p);

  const row = el('div', 'row');
  const ok = el('button', 'act primary', icon('check') + 'Approve, use the new image');
  ok.onclick = () => decide(change, 'approved');
  const no = el('button', 'act danger', icon('x') + 'Decline, keep the current one');
  no.onclick = () => decide(change, 'declined');
  const back = el('button', 'act ghost', 'Back');
  back.onclick = () => setView('queue');
  row.append(ok, no, back); m.append(row);
}

/* Everything still open that can be applied without looking at a picture.
   Images are the one exception: a text diff says nothing about whether a
   screenshot is the right screenshot, so those keep their own review. */
function pending(s) {
  return s.drift.filter(c => c.applicable && c.change !== 'image' && !c.decided);
}

async function applyAll(s) {
  const items = pending(s);
  if (!items.length) {
    const open = s.drift.filter(c => !c.decided);
    if (!open.length) {
      return toast(`All ${s.drift.length} difference(s) here are already `
                 + `decided. Reopen one to change your mind.`);
    }
    return toast(`${open.length} difference(s) here are pictures. `
               + `Review those one at a time, so you can see them.`, true);
  }
  const go = await modal({
    title: `Apply ${items.length} change(s) to ${s.title}?`,
    body: `<p>Every open difference in this section: renames, additions and
      removals. Each is recorded in History and can be undone one at a time.</p>
      <p class="muted">Pictures are not included, because a text diff says
      nothing about whether a screenshot is the right screenshot.</p>`,
    confirmLabel: `Apply ${items.length}`,
  });
  if (!go) return;
  let done = 0, failed = 0;
  for (const c of items) {
    try {
      await api('/api/decision',
        { method: 'POST', json: { change: c, verdict: 'approved' } });
      done++;
    } catch (e) { failed++; console.warn(e.message); }
  }
  toast(failed ? `Applied ${done}, ${failed} failed. See History.`
               : `Applied ${done} change(s) to ${s.title}. Undo from History.`,
        failed > 0);
  await refresh();
  setView('queue');
}

/* ------------------------------------------------------------ connections */
function drawConnections(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Connections'));
  m.append(el('div', 'muted', 'Which system a crawl talks to.' + hint(
    'Passwords are kept in your login keychain, never in a file. Single sign-on ' +
    'keeps no password at all: you sign in once in a real browser window and the ' +
    'saved session is reused until it expires.')));

  const envs = (S.environments || {}).items || [];
  envs.forEach(e => m.append(envCard(e)));

  const add = el('button', 'act ghost', 'Add a connection');
  add.style.marginTop = '14px';
  add.onclick = () => m.append(envForm({ id: '', label: '', base_url: '',
    auth: 'form', user: '', signed_in_when: 'table, [role=table], [role=tab]' }, true));
  m.append(add);
}

function envCard(e) {
  const p = el('div', 'panel');
  if (e.active) p.style.borderColor = 'var(--blue)';

  const head = el('div', 'row spread');
  head.append(el('div', null, `
    <b>${esc(e.label || e.id)}</b>
    ${e.active ? '<span class="chip verified">in use</span>' : ''}
    <span class="chip">${esc(e.auth === 'sso' ? 'single sign-on' : e.auth)}</span>
    ${e.mask_required ? '<span class="chip warn">masking required</span>' : ''}
    <div class="muted" style="margin-top:3px">${esc(e.base_url || 'no address set')}</div>
    <div class="muted" style="display:flex;align-items:center;gap:5px">
      ${e.ready ? icon('check', { size: 14 }) : icon('alert', { size: 14 })}
      <span>${esc(e.status)}${e.user ? ' &middot; ' + esc(e.user) : ''}</span></div>`));
  p.append(head);

  if (e.session && e.session.present) {
    p.append(el('div', 'muted',
      `Session saved ${esc(e.session.saved_at)}, ${e.session.cookies} cookie(s)` +
      (e.session.expires ? `, expires ${esc(e.session.expires)}` : '') +
      (e.session.expired ? ', expired' : '')));
  }

  const row = el('div', 'row'); row.style.marginTop = '11px';
  const mk = (label, cls, fn) => { const b = el('button', 'act ' + (cls || ''), label);
    b.onclick = fn; row.append(b); return b; };

  if (e.auth === 'sso') {
    mk('Sign in with Okta', 'primary', async () => {
      try {
        const r = await api('/api/env/signin', { method: 'POST', json: { id: e.id } });
        watchJob(r.job, `sign in to ${e.label || e.id}`);
        toast('A browser window is opening. Sign in there, including any second factor.');
      } catch (err) { toast(err.message, true); }
    });
  }
  mk('Verify', e.auth === 'sso' ? '' : 'primary', async () => {
    try {
      const r = await api('/api/env/verify', { method: 'POST', json: { id: e.id } });
      watchJob(r.job, `verify ${e.label || e.id}`);
    } catch (err) { toast(err.message, true); }
  });
  if (!e.active) {
    mk('Use this one', '', async () => {
      try {
        const r = await api('/api/env/activate', { method: 'POST', json: { id: e.id } });
        toast(r.message); await refresh(); setView('connections');
      } catch (err) { toast(err.message, true); }
    });
  }
  mk('Edit', 'ghost', () => {
    const f = envForm(e, false);
    p.append(f); f.scrollIntoView({ block: 'nearest' });
  });
  mk('Remove', 'ghost', async () => {
    if (!(await ask({ title: `Remove ${e.label || e.id}?`,
      body: 'Its saved password or browser session is removed with it.',
      confirmLabel: 'Remove', confirmClass: 'danger' }))) return;
    try {
      const r = await api('/api/env/remove', { method: 'POST', json: { id: e.id } });
      toast(r.message); await refresh(); setView('connections');
    } catch (err) { toast(err.message, true); }
  });
  p.append(row);
  return p;
}

function envForm(e, isNew) {
  const f = el('div', 'panel');
  f.style.borderStyle = 'dashed';
  f.append(el('h3', null, isNew ? 'New connection' : `Edit ${esc(e.label || e.id)}`));
  const uid = 'ef' + Math.random().toString(36).slice(2, 7);
  const g = el('div', 'grid2');
  g.innerHTML = `
    <div class="field"><label for="${uid}id">Short id</label>
      <input id="${uid}id" value="${esc(e.id)}" ${isNew ? '' : 'disabled'}
        placeholder="production"></div>
    <div class="field"><label for="${uid}label">Name</label>
      <input id="${uid}label" value="${esc(e.label || '')}" placeholder="Production"></div>
    <div class="field"><label for="${uid}url">Address</label>
      <input id="${uid}url" value="${esc(e.base_url || '')}"
        placeholder="https://app.example.com"></div>
    <div class="field"><label for="${uid}auth">Sign-in method</label>
      <select id="${uid}auth">
        <option value="form" ${e.auth === 'form' ? 'selected' : ''}>Username and password</option>
        <option value="sso" ${e.auth === 'sso' ? 'selected' : ''}>Single sign-on (Okta)</option>
        <option value="none" ${e.auth === 'none' ? 'selected' : ''}>No sign-in needed</option>
      </select></div>`;
  f.append(g);

  const creds = el('div', 'grid2'); creds.style.marginTop = '11px';
  creds.innerHTML = `
    <div class="field"><label for="${uid}user">Username</label>
      <input id="${uid}user" value="${esc(e.user || '')}" autocomplete="username"
        placeholder="ops@example.com"></div>
    <div class="field"><label for="${uid}pass">Password ${e.has_password ? '(saved, leave blank to keep)' : ''}</label>
      <input id="${uid}pass" type="password" autocomplete="new-password"></div>`;
  f.append(creds);

  const extra = el('div', 'field'); extra.style.marginTop = '11px';
  extra.innerHTML = `<label for="${uid}marker">Signed in when this appears (CSS selector)</label>
    <input id="${uid}marker" value="${esc(e.signed_in_when || '')}"
      placeholder="table, [role=table], [role=tab]">`;
  f.append(extra);

  const maskRow = el('div', 'row'); maskRow.style.marginTop = '10px';
  maskRow.innerHTML = `<label><input type="checkbox" id="${uid}mask"
    ${e.mask_required ? 'checked' : ''}> this system holds real data, always mask names</label>`;
  f.append(maskRow);

  const note = el('div', 'muted'); note.style.marginTop = '8px';
  const syncNote = () => {
    const sso = $('#' + uid + 'auth').value === 'sso';
    creds.style.display = sso ? 'none' : '';
    note.innerHTML = sso
      ? 'Single sign-on stores no password. After saving, use <b>Sign in with Okta</b>: ' +
        'a browser window opens, you sign in yourself, and the session is saved.'
      : 'The password is written to your login keychain, never to a file.';
  };
  f.append(note);
  setTimeout(() => { $('#' + uid + 'auth').onchange = syncNote; syncNote(); }, 0);

  const row = el('div', 'row'); row.style.marginTop = '12px';
  const save = el('button', 'act primary', 'Save');
  save.onclick = async () => {
    const body = {
      environment: {
        id: $('#' + uid + 'id').value.trim() || e.id,
        label: $('#' + uid + 'label').value.trim(),
        base_url: $('#' + uid + 'url').value.trim(),
        auth: $('#' + uid + 'auth').value,
        user: $('#' + uid + 'user').value.trim(),
        signed_in_when: $('#' + uid + 'marker').value.trim(),
        mask_required: $('#' + uid + 'mask').checked
      },
      password: $('#' + uid + 'pass').value || null
    };
    if (!body.environment.id) return toast('A short id is needed', true);
    if (!body.environment.base_url) return toast('An address is needed', true);
    save.disabled = true;
    try {
      const r = await api('/api/env/save', { method: 'POST', json: body });
      toast(r.message); await refresh(); setView('connections');
    } catch (err) { toast(err.message, true); save.disabled = false; }
  };
  const cancel = el('button', 'act ghost', 'Cancel');
  cancel.onclick = () => f.remove();
  row.append(save, cancel); f.append(row);
  return f;
}

/* ----------------------------------------------------------------- images */
function drawImages(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Images'));
  m.append(el('div', 'muted', 'Every picture in the project.' + hint(
    'What ships in the document, and what is waiting in a capture. Click any ' +
    'image to look at it properly.')));

  const host = el('div');
  m.append(host);
  host.append(el('div', 'empty', 'Loading...'));

  api('/api/images').then(d => {
    host.innerHTML = '';

    const strip = el('div', 'stats');
    const cell = (k, v, cls) => strip.append(el('div', 'cell ' + (cls || ''),
      `<div class="v">${v}</div><div class="k">${esc(k)}</div>`));
    cell('in the document', d.shipping.length);
    cell('from a capture', d.shipping.filter(a => a.from_capture).length,
         d.shipping.filter(a => a.from_capture).length ? 'good' : '');
    cell('never adopted', d.shipping.filter(a => !a.from_capture).length,
         d.shipping.filter(a => !a.from_capture).length ? 'warn' : 'good');
    cell('unused', d.orphans, d.orphans ? 'warn' : 'good');
    cell('waiting in captures', d.pending.length);
    host.append(strip);

    const gallery = (title, items, note, adoptable) => {
      if (!items.length) return;
      const p = el('div', 'panel');
      p.append(el('h3', null, icon('camera') + `${title} (${items.length})`));
      if (note) p.append(el('div', 'muted', note));
      const g = el('div', 'shots');
      items.forEach((it, idx) => {
        const c = el('div', 'shot');
        c.innerHTML = `<img src="${it.url}?t=${Date.now()}" alt="${esc(it.name)}"
          style="cursor:zoom-in" loading="lazy">`;
        c.querySelector('img').onclick = () => lightbox(items, idx);
        const cap = el('div', 'cap');
        const where = it.sections && it.sections.length
          ? it.sections.join(', ')
          : (it.screen || (it.orphan ? 'not used anywhere' : ''));
        cap.innerHTML = `<span title="${esc(it.name)}">${esc(
          it.name.replace(/\.png$/, ''))}</span>`;
        const meta = el('div', 'muted');
        meta.style.cssText = 'padding:0 8px 6px;font-size:12px';
        meta.textContent = where;
        c.append(cap, meta);

        // A picture nothing refers to can go. It is moved aside rather than
        // deleted, because "it is not used anywhere" is a claim about today.
        if (it.orphan && !adoptable) {
          const rm = el('button', 'mini', 'Remove');
          rm.style.margin = '0 8px 8px';
          rm.title = 'Nothing in the document shows this picture';
          rm.onclick = async () => {
            if (!(await ask({
              title: `Remove ${it.name}?`,
              body: 'Nothing in the document shows it. It is moved to '
                  + '.verba/removed and recorded in History, not deleted.',
              confirmLabel: 'Remove', confirmClass: 'danger' }))) return;
            try {
              const r = await api('/api/images/remove',
                { method: 'POST', json: { name: it.name } });
              toast(r.message); await refresh(); drawImages(holder());
            } catch (e) { toast(e.message, true); }
          };
          c.append(rm);
        }

        // A capture whose bytes already match the shipping file has been
        // adopted. Offering Adopt again is the same button that appears to do
        // nothing, because there is nothing left for it to do.
        if (adoptable && it.in_document && !it.adopted) {
          const b = el('button', 'mini go', 'Adopt');
          b.style.margin = '0 8px 8px';
          b.onclick = async () => {
            if (!(await ask({ title: `Replace ${it.name}?`,
              body: 'The document takes the captured picture. The old one stays in history.',
              confirmLabel: 'Replace', confirmClass: 'primary' }))) return;
            try {
              const sec = (d.shipping.find(x => x.name === it.name) || {}).sections || [];
              const r = await api('/api/images/adopt',
                { method: 'POST', json: { name: it.name, run: it.run } });
              toast(r.message); await refresh(); setView('images');
            } catch (e) { toast(e.message, true); }
          };
          c.append(b);
        }
        g.append(c);
      });
      p.append(g); m.append(p);
    };

    gallery('In the document', d.shipping,
      'What the DOCX and PDF will contain right now.', false);
    gallery('Waiting in captures', d.pending,
      'Captured from the live platform and masked. Adopt one to put it in the ' +
      'document.', true);
  }).catch(e => { host.innerHTML = ''; host.append(el('div', 'empty', esc(e.message))); });
}

/* --------------------------------------------------------------- document */
function drawDocument(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'The document'));
  m.append(el('div', 'muted', 'The whole document as it will print.' + hint(
    'Laid out with the same stylesheet the PDF uses: cover, contents, every ' +
    'figure and every section, in order.')));

  const bar = el('div', 'row'); bar.style.margin = '14px 0';
  const reload = el('button', 'act', 'Rebuild the proof');
  const pdf = el('button', 'act', 'Build a PDF of this');
  pdf.onclick = () => publish(null, ['pdf'], '', S.summary.error > 0);
  const openTab = el('button', 'act ghost', 'Open in its own tab');
  bar.append(reload, pdf, openTab); m.append(bar);

  const stat = el('div', 'muted'); m.append(stat);
  const frame = el('iframe', 'proof');
  frame.setAttribute('title', 'Document proof');
  m.append(frame);

  const load = async () => {
    stat.textContent = 'Rendering ...';
    try {
      const r = await api('/api/document', { method: 'GET' });
      frame.src = r.url + '?t=' + Date.now();
      openTab.onclick = () => window.open(r.url, '_blank');
      stat.textContent = `${r.sections} sections, ${r.figures} figures, edition ${r.profile}`;
    } catch (e) { stat.textContent = e.message; }
  };
  reload.onclick = load;
  load();
}

/* ---------------------------------------------------------------- history */
function actorLabel(a) {
  return ({ human: 'by hand', assist: 'writing assistant', drift: 'drift queue',
            capture: 'capture', system: 'pipeline' })[a] || a;
}

function drawHistory(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Change history'));
  const h = S.history || {};
  m.append(el('div', 'muted',
    `${h.changes || 0} change(s) across ${h.sections_touched || 0} section(s)` +
    (h.last ? `, latest ${esc(h.last.replace('T',' '))}` : '') + hint(
    'Every edit stores the full text before and after, plus who made it: by hand, ' +
    'the writing assistant, the drift queue, a capture, or the pipeline. Any ' +
    'revision can be compared and restored.')));

  const cards = el('div', 'cards');
  Object.entries(h.by_actor || {}).forEach(([k, v]) => cards.append(
    el('div', 'card', `<div class="v">${v}</div><div class="k">${esc(actorLabel(k))}</div>`)));
  m.append(cards);

  const p = el('div', 'panel');
  p.append(el('h3', null, 'Everything that changed, newest first'));
  const t = el('table', null, `<thead><tr><th>When</th><th>Section</th><th>What</th>
    <th>Source</th><th>Note</th></tr></thead>`);
  const b = el('tbody');
  api('/api/history').then(r => {
    (r.entries || []).forEach(e => {
      const tr = el('tr', e.kind === 'section' ? 'click' : '', `
        <td class="muted">${esc(e.at.replace('T', ' '))}</td>
        <td>${esc(e.section)}</td>
        <td>${esc(e.action)}</td>
        <td><span class="chip">${esc(actorLabel(e.actor))}</span></td>
        <td class="muted">${esc((e.note || '').slice(0, 70))}</td>`);
      if (e.kind === 'section') tr.onclick = () => openSection(e.section);
      b.append(tr);
    });
    if (!(r.entries || []).length) b.append(el('tr', null,
      '<td colspan="5" class="muted">Nothing recorded yet.</td>'));
  }).catch(e => b.append(el('tr', null, `<td colspan="5">${esc(e.message)}</td>`)));
  t.append(b); const w = el('div','wrap-x'); w.append(t); p.append(w); m.append(p);
}

async function sectionHistoryPanel(sectionId) {
  const p = el('div', 'panel');
  p.append(el('h3', null, icon('history') + 'History'));
  let r;
  try { r = await api('/api/history/' + encodeURIComponent(sectionId)); }
  catch (e) { p.append(el('div', 'muted', e.message)); return p; }
  const entries = r.entries || [];
  if (entries.length <= 1) {
    p.append(el('div', 'muted',
      'No changes recorded yet. Every edit from here is tracked and revertable.'));
    return p;
  }
  const t = el('table', null,
    '<thead><tr><th>When</th><th>What</th><th>Source</th><th>Note</th><th></th></tr></thead>');
  const b = el('tbody');
  entries.forEach((e, i) => {
    const tr = el('tr', null, `
      <td class="muted">${esc(e.at.replace('T', ' '))}</td>
      <td>${esc(e.action)}</td>
      <td><span class="chip">${esc(actorLabel(e.actor))}</span></td>
      <td class="muted">${esc((e.note || '').slice(0, 46))}</td>`);
    const td = el('td'); const row = el('div', 'row');
    const view = el('button', 'mini', 'Compare');
    view.onclick = () => showRevision(sectionId, e);
    row.append(view);
    if (i > 0 && e.action !== 'baseline') {
      const rest = el('button', 'mini go', 'Restore');
      rest.onclick = async () => {
        if (!(await ask({ title: 'Restore this revision?',
          body: `The section goes back to how it read at ${e.at}. The restore is itself recorded.`,
          confirmLabel: 'Restore', confirmClass: 'primary' }))) return;
        try {
          const x = await api(`/api/section/${encodeURIComponent(sectionId)}/restore`,
            { method: 'POST', json: { revision: e.id } });
          toast(x.message); await refresh(); openSection(sectionId);
        } catch (err) { toast(err.message, true); }
      };
      row.append(rest);
    }
    td.append(row); tr.append(td); b.append(tr);
  });
  t.append(b); p.append(t);
  return p;
}

async function showRevision(sectionId, entry) {
  let r;
  try {
    r = await api(`/api/history/${encodeURIComponent(sectionId)}?revision=${entry.id}`);
  } catch (e) { return toast(e.message, true); }
  const m = holder();
  m.append(el('h2', 'page', `Revision from ${entry.at.replace('T', ' ')}`));
  m.append(el('div', 'muted',
    `${esc(entry.action)} &middot; ${esc(actorLabel(entry.actor))}` +
    (entry.note ? ` &middot; ${esc(entry.note)}` : '')));
  const rows = diffLines(r.previous || '', r.content || '');
  const p = el('div', 'panel');
  p.append(el('h3', null,
    `${rows.filter(x => x[0] !== 'same').length} changed line(s) in this revision`));
  const pre = el('div', 'diff');
  let run = 0;
  rows.forEach(([kind, line], idx) => {
    if (kind === 'same') {
      const near = rows.slice(Math.max(0, idx - 2), idx + 3).some(x => x[0] !== 'same');
      if (!near) { run++; return; }
    }
    if (run) { pre.append(el('div', 'skip', `... ${run} unchanged line(s)`)); run = 0; }
    pre.append(el('div', kind, esc(line) || '&nbsp;'));
  });
  if (run) pre.append(el('div', 'skip', `... ${run} unchanged line(s)`));
  p.append(pre); m.append(p);
  const back = el('button', 'act', 'Back to the section');
  back.onclick = () => openSection(sectionId);
  m.append(back);
}

/* ---------------------------------------------------------------- publish */
function drawPublish(m) {
  m.innerHTML = '';
  m.append(el('h2', 'page', 'Publish'));
  m.append(el('div', 'muted', 'Build a draft, or cut a version.' + hint(
    'A draft can be rebuilt any time. A version is recorded in the changelog, and ' +
    'its output file can never be overwritten: bump the version instead.')));

  const p = el('div', 'panel');
  p.append(el('h3', null, icon('publish') + 'Build'));
  const g = el('div', 'grid2');
  g.innerHTML = `
    <div class="field" role="group" aria-label="Formats to build"><span class="lab">Formats</span>
      <div class="row" style="padding-top:4px">
        <label><input type="checkbox" id="fDocx" checked> DOCX</label>
        <label><input type="checkbox" id="fPdf" checked> PDF</label>
        <label><input type="checkbox" id="fHtml"> HTML</label>
      </div></div>
    <div class="field"><label for="pVersion">Version (blank = draft)</label>
      <input id="pVersion" placeholder="${esc(S.next_version)}"></div>
    <div class="field"><label for="pEdition">Edition</label>
      <input id="pEdition" value="${esc(S.profile)}" disabled></div>`;
  p.append(g);
  const sm = el('div', 'field'); sm.style.marginTop = '11px';
  sm.innerHTML = `<label for="pSummary">Summary for the changelog</label>
    <textarea id="pSummary" rows="2" placeholder="Left blank, this is derived from what changed."></textarea>`;
  p.append(sm);

  const bad = S.summary.error;
  const foot = el('div', 'row'); foot.style.marginTop = '13px';
  const go = el('button', 'act primary', 'Build');
  go.onclick = () => {
    const fmts = [];
    if ($('#fDocx').checked) fmts.push('docx');
    if ($('#fPdf').checked) fmts.push('pdf');
    if ($('#fHtml').checked) fmts.push('html');
    if (!fmts.length) return toast('Pick at least one format', true);
    publish(($('#pVersion').value || '').trim() || null, fmts,
      $('#pSummary').value, $('#pForce') && $('#pForce').checked);
  };
  foot.append(go);
  if (bad) {
    foot.append(el('label', null,
      `<input type="checkbox" id="pForce"> ignore ${bad} lint error(s)`));
  }
  p.append(foot);
  if (bad) p.append(el('div', 'muted',
    'Publishing is blocked while error-level findings are open. See Overview.'));
  m.append(p);

  const r = el('div', 'panel');
  r.append(el('h3', null, icon('layers') + 'Release history'));
  if (!S.releases.length) r.append(el('div', 'muted', 'No releases yet.'));
  else {
    const t = el('table', null,
      '<thead><tr><th>Version</th><th>Edition</th><th>Date</th><th>Summary</th></tr></thead>');
    const b = el('tbody');
    S.releases.forEach(x => b.append(el('tr', null,
      `<td><b>${esc(x.version)}</b></td><td>${esc(x.profile)}</td>
       <td class="muted">${esc(x.date)}</td><td>${esc(x.summary || '')}</td>`)));
    t.append(b); const w2 = el('div','wrap-x'); w2.append(t); r.append(w2);
  }
  m.append(r);
  m.append(outputsPanel());
}

async function publish(version, formats, summary, force) {
  try {
    const r = await api('/api/publish', {
      method: 'POST', json: { version, formats, summary, force }
    });
    watchJob(r.job, version ? `publish ${version}` : 'build draft');
  } catch (e) { toast(e.message, true); }
}

/* ---------------------------------------------------------------- section */
async function openSection(id) {
  if (dirty && !(await leaveDirty())) return;
  dirty = false; currentId = id; view = 'section';
  drawNav(); drawTree();
  const d = await api('/api/section/' + encodeURIComponent(id));
  window._sec = d;
  drawSection(holder());
}

/* After a crawl the honest question is "what is left to do here", and the
   answer was previously scattered across four panels. This says it plainly and
   puts the action that clears each item next to it. */
function sectionTodo(d, meta) {
  const p = el('div', 'panel');
  const fresh = d.capture_shots || [];
  const drift = (d.drift || []).filter(c => !c.decided);
  const lintErrors = (meta.lint || []).filter(f => f.level === 'error');
  const stale = meta.status === 'stale';
  const outstanding = fresh.length + drift.length + lintErrors.length + (stale ? 1 : 0);

  p.classList.add(outstanding ? 'warn-edge' : 'accent');
  p.append(el('h3', null, (outstanding ? icon('alert') : icon('check')) +
    (outstanding ? `${outstanding} thing(s) to settle here` : 'Nothing outstanding')));

  const list = el('div', 'todo');
  const item = (open, what, why, actionLabel, fn) => {
    const row = el('div', 'item ' + (open ? 'open' : 'done'));
    row.append(el('span', 'mark', open ? '!' : '\u2713'));
    row.append(el('span', 'what',
      `${esc(what)}${why ? `<div class="why">${esc(why)}</div>` : ''}`));
    if (open && fn) {
      const b = el('button', 'mini go', actionLabel);
      b.onclick = fn;
      row.append(b);
    }
    list.append(row);
  };

  item(fresh.length > 0,
    fresh.length ? `${fresh.length} freshly captured image(s) not yet in the document`
                 : 'Images are up to date with the last crawl',
    fresh.length ? 'The crawl produced these. The document still shows the old ones.' : '',
    'Use them', () => modal({
      title: `Use ${fresh.length} captured image(s)?`,
      body: 'The old pictures stay in history, so this can be put back.',
      confirmLabel: 'Use them', confirmClass: 'primary',
      onConfirm: async () => {
        for (const sh of fresh) {
          try {
            await api(`/api/section/${encodeURIComponent(d.id)}/adopt-shot`,
              { method: 'POST', json: { from: sh.name, to: sh.name } });
          } catch (e) { toast(e.message, true); }
        }
        toast('Images updated'); await refresh(); openSection(d.id);
      },
    }));

  const gaps = proposalsFor(d.id);
  if (gaps.length) {
    gaps.forEach(pr => item(true,
      pr.kind === 'image' ? 'A picture here has changed'
                          : 'Descriptions written from the last crawl',
      pr.detail, 'Review', () => settleProposal(pr, () => openSection(d.id))));
  }

  item(drift.length > 0,
    drift.length ? `${drift.length} difference(s) against the live system`
                 : 'No open differences',
    drift.length ? 'Each one needs approving, writing, or declining.' : '',
    'Review them', () => setView('queue'));

  if (lintErrors.length) {
    item(true, `${lintErrors.length} rule finding(s) blocking a build`,
      lintErrors.map(f => f.message).join('; '), null, null);
  }

  item(stale,
    stale ? 'Marked stale' : `Verified ${meta.last_verified || 'at some point'}`,
    stale ? (meta.notes || 'Someone flagged this as needing a look.') : '',
    'Mark verified', async () => {
      try {
        const r = await api(`/api/section/${encodeURIComponent(d.id)}/verify`,
          { method: 'POST', json: {} });
        toast(r.message); await refresh(); openSection(d.id);
      } catch (e) { toast(e.message, true); }
    });

  p.append(list);
  if (!outstanding) {
    p.append(el('div', 'muted',
      'This section matches the last crawl and is verified.'));
  }
  return p;
}

function drawSection(m) {
  const d = window._sec;
  if (!d) return setView('sections');
  const meta = S.sections.find(x => x.id === d.id) || {};
  m.innerHTML = '';

  const head = el('div', 'row spread');
  head.append(el('div', null,
    `<h2 class="page">${esc(d.number)} ${esc(d.title)}</h2>
     <div class="muted">${esc(d.path)} · <span class="chip ${meta.status}">${esc(meta.status)}</span>
     ${meta.last_verified ? ' verified ' + esc(meta.last_verified) : ''}
     ${meta.changes ? ' &middot; ' + meta.changes + ' change(s) recorded' : ''}</div>`));
  const acts = el('div', 'row');
  const recap = el('button', 'act primary', 'Recapture from live system');
  recap.disabled = !(meta.capturable || []).length;
  recap.title = recap.disabled
    ? 'Bind this section to a screen in content/screens.yaml first' : '';
  recap.onclick = () => runCapture(meta.capturable, d.id);
  const save = el('button', 'act', 'Save');
  save.onclick = saveSection;
  const ver = el('button', 'act', 'Mark verified');
  ver.onclick = async () => {
    try { const r = await api(`/api/section/${encodeURIComponent(d.id)}/verify`,
      { method: 'POST', json: {} });
      toast(r.message); await refresh(); openSection(d.id);
    } catch (e) { toast(e.message, true); }
  };
  acts.append(recap, save, ver); head.append(acts); m.append(head);

  m.append(sectionTodo(d, meta));

  const ab = el('div', 'panel');
  ab.append(el('h3', null, icon('sparkle') + 'Writing assistance'));
  const ready = S.assist && S.assist.ready;
  if (!ready) {
    ab.append(el('div', 'muted',
      'No model is reachable. ' + ((S.assist && S.assist.backends) || [])
        .map(b => esc(b.label) + ': ' + esc(b.note)).join(' ')));
  } else {
    ab.append(el('div', 'muted', 'Each returns a proposal you review first.' + hint(
      'The model is given this section, the labels the last crawl read off its ' +
      'screens, the open differences and the open rule findings. It is told to ' +
      'write "TODO: describe this." rather than invent a meaning the evidence ' +
      'does not support.')));
    const row = el('div', 'row'); row.style.marginTop = '10px';
    const tasks = [
      ['polish', 'Rewrite to house style'],
      ['reconcile', 'Apply crawl differences'],
      ['fill_todos', 'Write missing descriptions'],
      ['draft', 'Draft from crawl'],
      ['review', 'Review only']
    ];
    tasks.forEach(([id, label]) => {
      const b = el('button', 'act' + (id === 'review' ? ' ghost' : ''), label);
      b.onclick = () => runAssist(d.id, id, label);
      row.append(b);
    });
    ab.append(row);
    const via = ((S.assist.backends || []).find(x => x.ready) || {}).label;
    if (via) ab.append(el('div', 'muted', 'Using ' + esc(via)));
  }
  m.append(ab);

  const smeta = S.sections.find(x => x.id === d.id) || {};
  if ((smeta.decided || []).length) {
    const np = el('div', 'panel');
    np.append(el('h3', null, icon('info') + 'Decisions already made here'));
    np.append(el('div', 'muted',
      'Declined with a reason. Every crawl and every proposal is told about these.'));
    smeta.decided.forEach(nt => {
      const c = el('div', 'note-card');
      c.innerHTML = `<b>${esc(nt.line)}</b><div>${esc(nt.reason)}</div>
        <div class="muted">${esc((nt.at || '').replace('T', ' '))}</div>`;
      const row = el('div', 'row');
      row.style.marginTop = '6px';
      const back = el('button', 'mini', 'Reopen this decision');
      back.onclick = () => reopen(nt.change || { section: d.id, line: nt.line });
      row.append(back);
      c.append(row);
      np.append(c);
    });
    m.append(np);
  }

  if ((d.routes || []).length) {
    const rp = el('div', 'panel');
    rp.append(el('h3', null, icon('globe') + 'Where this section is crawled from'));
    d.routes.forEach(r => {
      const line = el('div');
      line.innerHTML = `<code>${esc(r.screen)}</code>
        <div class="muted" style="word-break:break-all">
        ${r.url ? esc(r.url) : 'address not learned yet, the first crawl records it'}
        ${r.last_seen ? ' &middot; last seen ' + esc(r.last_seen) : ''}
        ${r.reached_by ? ' &middot; reached by ' + esc(r.reached_by) : ''}</div>`;
      rp.append(line);
    });
    const opts = el('div', 'row'); opts.style.marginTop = '10px';
    opts.innerHTML = `<label class="check"><input type="checkbox" id="rcMask" checked>
        mask names</label>
      <label class="check"><input type="checkbox" id="rcReplay"> replay the steps</label>` +
      hint('Replaying the steps clicks through from the top instead of navigating ' +
           'straight to the remembered address. Slower, but it re-learns the route.');
    const go = el('button', 'act', 'Recrawl just this section');
    go.disabled = !(meta.capturable || []).length;
    go.onclick = () => runCapture(meta.capturable, d.id,
      { mask: $('#rcMask').checked, replay_steps: $('#rcReplay').checked });
    opts.append(go);
    rp.append(opts);
    m.append(rp);
  }

  if (d.drift.length) {
    const dz = el('div', 'drift');
    dz.append(el('div', 'hd', '<b>Differences against the live system</b>'));
    const ul = el('ul');
    d.drift.forEach(c => {
      const li = el('li');
      li.append(el('span', null, esc(c.line)));
      if (c.decided) {
        const row = el('span', 'row');
        const chip = el('span',
          'chip ' + (c.decided === 'declined' ? 'warn' : 'verified'),
          c.decided === 'declined' ? 'declined' : 'applied');
        if (c.decided_reason) chip.title = c.decided_reason;
        const back = el('button', 'mini', 'Reopen');
        back.onclick = () => reopen(c);
        row.append(chip, back);
        li.append(row);
      } else if (c.applicable) {
        const b = el('button', 'mini go', 'Review');
        b.onclick = () => previewDriftChange(c, d.title);
        li.append(b);
      } else {
        const row = el('span', 'row');
        const w = el('button', 'mini go', 'Write it');
        w.onclick = () => writeFor(c, { title: d.title });
        const no = el('button', 'mini', 'Decline');
        no.onclick = () => decide(c, 'declined');
        row.append(w, no);
        li.append(row);
      }
      ul.append(li);
    });
    dz.append(ul); m.append(dz);
  }

  if ((meta.lint || []).length) {
    const lz = el('div', 'panel');
    lz.append(el('h3', null, 'Findings in this section'));
    // A finding with no way to act on it is a complaint. The same remedies the
    // To fix view offers belong here, where the person is already looking at
    // the section the finding is about.
    meta.lint.forEach(f => {
      const row = el('div', 'item ' + (f.level === 'error' ? 'open' : 'done'));
      row.append(el('span', 'what',
        `<span class="chip ${f.level === 'error' ? 'err' : 'warn'}">${esc(f.rule)}</span> ` +
        `${esc(f.message)}` +
        (f.detail ? `<div class="why">${esc(f.detail)}</div>` : '') +
        (f.remedy && f.remedy.why ? `<div class="why">${esc(f.remedy.why)}</div>` : '')));
      const rem = f.remedy || {};
      if (rem.action && rem.action !== 'none') {
        const b = el('button', 'mini go', rem.label);
        b.onclick = () => runRemedy(rem.action, { ...f, section: d.id, number: meta.number });
        row.append(b);
      }
      lz.append(row);
    });
    m.append(lz);
  }

  const ed = el('div', 'editor');
  const left = el('div');
  const ta = el('textarea', 'md'); ta.id = 'md'; ta.value = d.markdown;
  ta.oninput = () => { dirty = true; livePreview(); };
  ta.onkeydown = e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); saveSection(); }
  };
  left.append(ta);
  left.append(el('div', 'muted',
    'Cmd-S saves. Numbering comes from content/doc.yaml, so never write a number here.'));
  ed.append(left);
  const right = el('div', 'prev'); right.id = 'prev';
  ed.append(right);
  m.append(ed);
  livePreview();

  sectionHistoryPanel(d.id).then(panel => {
    // The fetch may resolve after the reader has moved on; only place the panel
    // if this section is still the one on screen.
    if (!m.isConnected || currentId !== d.id) return;
    const anchor = m.querySelector('.editor');
    if (anchor && anchor.parentNode === m && anchor.nextSibling)
      m.insertBefore(panel, anchor.nextSibling);
    else m.append(panel);
  });

  if (d.screenshots.length) {
    const sp = el('div', 'panel');
    sp.append(el('h3', null, icon('camera') +
      `Images used here (${d.screenshots.length})`));
    sp.append(el('div', 'muted', 'Click one to look at it properly.'));
    const strip = el('div', 'shotstrip');
    d.screenshots.forEach((s, idx) => {
      const t = el('div', 'thumb');
      t.setAttribute('role', 'button');
      t.setAttribute('tabindex', '0');
      t.innerHTML = `<img src="${s.url}?t=${Date.now()}" alt="${esc(s.name)}" loading="lazy">
        <div class="cap">${esc(s.name.replace(/^icon-/, '').replace(/\.png$/, ''))}</div>`;
      const open = () => lightbox(d.screenshots, idx);
      t.onclick = open;
      t.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } };
      strip.append(t);
    });
    sp.append(strip);
    m.append(sp);
  }

  if (d.capture_shots.length) {
    const cp = el('div', 'panel');
    cp.append(el('h3', null, icon('refresh') +
      `Freshly captured for this section (${d.capture_shots.length})`));
    cp.append(el('div', 'muted',
      'Adopt replaces the section image with the captured one.' +
      hint('Only this section&rsquo;s own captures are shown here. Every image in ' +
           'the project, and everything waiting in captures, lives under Images.')));
    const g = el('div', 'shots');
    d.capture_shots.forEach((s, idx) => {
      const c = el('div', 'shot');
      c.innerHTML = `<img src="${s.url}?t=${Date.now()}" alt="${esc(s.name)}"
                          style="cursor:zoom-in" loading="lazy">`;
      c.querySelector('img').onclick = () => lightbox(d.capture_shots, idx);
      const cap = el('div', 'cap');
      cap.append(el('span', null, esc(s.name)));
      const b = el('button', 'mini go', 'Adopt');
      b.onclick = async () => {
        const target = d.screenshots[0] ? d.screenshots[0].name : s.name;
        if (!(await ask({ title: `Replace ${target}?`,
          body: `The document takes the captured ${s.name}. The old picture stays in history.`,
          confirmLabel: 'Replace', confirmClass: 'primary' }))) return;
        try {
          const r = await api(`/api/section/${encodeURIComponent(d.id)}/adopt-shot`,
            { method: 'POST', json: { from: s.name, to: target } });
          toast(r.message); await refresh(); openSection(d.id);
        } catch (e) { toast(e.message, true); }
      };
      cap.append(b); c.append(cap); g.append(c);
    });
    cp.append(g); m.append(cp);
  }

  const inv = Object.keys(d.inventory || {});
  if (inv.length) {
    const ip = el('div', 'panel');
    ip.append(el('h3', null, 'What the live screen shows'));
    inv.forEach(k => {
      ip.append(el('div', null, `<b>${esc(k)}</b>`));
      const e = d.inventory[k].elements || {};
      Object.keys(e).forEach(kind => ip.append(el('div', 'muted',
        `${esc(kind)}: ${esc((e[kind] || []).join(' · ')) || 'none'}`)));
    });
    m.append(ip);
  }
}

async function saveSection() {
  const d = window._sec;
  try {
    const r = await api('/api/section/' + encodeURIComponent(d.id),
      { method: 'PUT', json: { markdown: $('#md').value } });
    dirty = false;
    const errs = r.lint.filter(x => x.level === 'error');
    toast(errs.length ? `Saved, but ${errs.length} error-level finding(s) remain`
      : 'Saved', errs.length > 0);
    await refresh(); openSection(d.id);
  } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------- live preview */
function livePreview() {
  const src = $('#md') ? $('#md').value : '';
  const body = src.replace(/^---\n[\s\S]*?\n---\n?/, '');
  const assetUrl = n => '/files/content/assets/' +
    (n.startsWith('icon-') ? 'icons/' : 'screenshots/') + n;
  const inline = t => esc(t).replace(/\[icon:([^\]\s]+)\]/g,
    (_, n) => `<img class="ic" src="${assetUrl(n)}">`);

  const out = [];
  const lines = body.split('\n');
  let i = 0, para = [], bullets = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
    if (bullets.length) {
      out.push('<ul>' + bullets.map(b => `<li>${inline(b)}</li>`).join('') + '</ul>');
      bullets = [];
    }
  };
  while (i < lines.length) {
    const L = lines[i], t = L.trim();
    if (!t) { flush(); i++; continue; }
    if (t.startsWith('```')) {
      const lang = t.slice(3).trim(); const buf = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) buf.push(lines[i++]);
      i++; flush();
      const key = { fields: 'field', actions: 'action', columns: 'column', terms: 'term' }[lang];
      if (key) {
        const rows = [];
        let cur = null;
        buf.forEach(ln => {
          const m = ln.match(/^\s*-\s+(\w+):\s*(.*)$/);
          const c = ln.match(/^\s+(\w+):\s*(.*)$/);
          if (m) { cur = { [m[1]]: m[2] }; rows.push(cur); }
          else if (c && cur) cur[c[1]] = c[2];
        });
        out.push('<div>' + rows.map(r => {
          const name = r[key] || r.term || '';
          const ty = r.type ? ` <span class="ty">${esc(r.type)}</span>` : '';
          const de = r.description || r.definition || '';
          return `<div class="df"><b>${esc(name)}</b>${ty}${de ? ': ' + esc(de) : ''}</div>`;
        }).join('') + '</div>');
      } else out.push(`<pre>${esc(buf.join('\n'))}</pre>`);
      continue;
    }
    let m;
    if ((m = t.match(/^(#{1,6})\s+(.*)$/))) { flush(); out.push(`<h4>${esc(m[2])}</h4>`); i++; continue; }
    if ((m = t.match(/^!\[([^\]]*)\]\(([^)\s]+)(?:\s*=[\d.]+cm)?\)$/))) {
      flush();
      out.push(`<figure><img src="${assetUrl(m[2])}" alt="">` +
        (m[1] ? `<figcaption>${esc(m[1])}</figcaption>` : '') + '</figure>');
      i++; continue;
    }
    if ((m = t.match(/^>\s*\[!([^\]]+)\]\s*(.*)$/))) {
      flush();
      const parts = [m[2]]; i++;
      while (i < lines.length && lines[i].trim().startsWith('>'))
        parts.push(lines[i++].trim().replace(/^>\s?/, ''));
      out.push(`<div class="note"><b>${esc(m[1])}:</b> ${inline(parts.join(' '))}</div>`);
      continue;
    }
    if ((m = t.match(/^[-*]\s+(.*)$/))) {
      if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
      bullets.push(m[1]); i++; continue;
    }
    para.push(t); i++;
  }
  flush();
  const p = $('#prev'); if (p) p.innerHTML = out.join('');
}

/* ---------------------------------------------------------------- jobs */
async function runAssist(sectionId, task, label) {
  try {
    const r = await api('/api/assist', { method: 'POST', json: { section: sectionId, task } });
    watchJob(r.job, label, null, (result) => showProposal(sectionId, label, result));
  } catch (e) { toast(e.message, true); }
}

function diffLines(before, after) {
  // Longest common subsequence over lines, so unchanged text stays quiet and the
  // reviewer only reads what actually moved.
  const a = before.split('\n'), b = after.split('\n');
  const n = a.length, mm = b.length;
  const L = Array.from({ length: n + 1 }, () => new Uint32Array(mm + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = mm - 1; j >= 0; j--)
      L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < mm) {
    if (a[i] === b[j]) { out.push(['same', a[i]]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) { out.push(['del', a[i]]); i++; }
    else { out.push(['add', b[j]]); j++; }
  }
  while (i < n) out.push(['del', a[i++]]);
  while (j < mm) out.push(['add', b[j++]]);
  return out;
}

/* Every change that touches a file goes through here first: see the diff, then
   approve or reject. Nothing writes without that step. */
function reviewChange({ title, note, before, after, onApprove, onDecline, onCancel,
                        approveLabel }) {
  const m = holder();
  m.append(el('h2', 'page', esc(title)));
  m.append(el('div', 'muted', (note || 'Nothing has been written yet.') + hint(
    'The preview applies the change, reads the result, then puts the file back. ' +
    'What you approve is exactly what you were shown.')));

  const rows = diffLines(before || '', after || '');
  const changed = rows.filter(r => r[0] !== 'same').length;
  const p = el('div', 'panel');
  p.append(el('h3', null, icon('edit') + `${changed} changed line(s)`));
  if (!changed) {
    p.append(el('div', 'empty', 'This would not change anything.'));
  } else {
    const pre = el('div', 'diff');
    let run = 0;
    rows.forEach(([kind, line], idx) => {
      if (kind === 'same') {
        const near = rows.slice(Math.max(0, idx - 2), idx + 3).some(r => r[0] !== 'same');
        if (!near) { run++; return; }
      }
      if (run) { pre.append(el('div', 'skip', `... ${run} unchanged line(s)`)); run = 0; }
      pre.append(el('div', kind, esc(line) || '&nbsp;'));
    });
    if (run) pre.append(el('div', 'skip', `... ${run} unchanged line(s)`));
    p.append(pre);
  }
  m.append(p);

  const row = el('div', 'row');
  const ok = el('button', 'act primary', icon('check') + (approveLabel || 'Approve and save'));
  ok.disabled = !changed;
  ok.onclick = async () => { ok.disabled = true; await onApprove(); };
  const no = el('button', 'act danger', icon('x') + 'Decline');
  no.onclick = () => onDecline ? onDecline() : onCancel();
  const back = el('button', 'act ghost', 'Back');
  back.onclick = () => onCancel();
  row.append(ok, no, back); m.append(row);
}

/* Gaps the crawl found in its own work: a picture that moved on, or a
   description the new evidence can now answer. Each one is a proposal and
   nothing is written until it is approved here. */
function proposalsFor(sectionId) {
  return (S.proposals?.proposals || []).filter(p => p.section === sectionId);
}

async function settleProposal(pr, done) {
  const finish = async (path, body, ok) => {
    try {
      const r = await api(path, { method: 'POST', json: { id: pr.id, ...body } });
      toast(r.message || ok); await refresh(); done();
    } catch (e) { toast(e.message, true); }
  };

  if (pr.kind === 'image') {
    const m = holder();
    m.append(el('h2', 'page', esc(pr.title)));
    m.append(el('div', 'muted', esc(pr.detail) + hint(
      'A text diff says nothing about a picture, so both are shown at full width. ' +
      'Approving copies the captured file over the one in the document and records it ' +
      'in history, where it can be put back.')));
    const g = el('div', 'panel shots');
    g.style.gridTemplateColumns = 'repeat(auto-fit, minmax(320px, 1fr))';
    const pane = (caption, src) => {
      const c = el('div', 'shot');
      c.append(el('div', 'cap', esc(caption)));
      const img = el('img'); img.src = src; img.alt = caption;
      img.onclick = () => lightbox([{ src, name: caption }], 0);
      c.append(img); return c;
    };
    const dir = pr.asset.startsWith('icon-') ? 'icons' : 'screenshots';
    g.append(pane('in the document now', `/files/content/assets/${dir}/${pr.asset}`));
    g.append(pane('what the crawl saw',
      `/files/capture/${pr.run}/screenshots/${pr.asset}`));
    m.append(g);
    const row = el('div', 'row');
    const ok = el('button', 'act primary', icon('check') + 'Use the new picture');
    ok.onclick = () => finish('/api/proposal/accept', {}, 'image updated');
    const no = el('button', 'act danger', icon('x') + 'Keep the old one');
    no.onclick = () => finish('/api/proposal/reject', {}, 'proposal discarded');
    const back = el('button', 'act ghost', 'Back');
    back.onclick = () => done();
    row.append(ok, no, back); m.append(row);
    return;
  }

  reviewChange({
    title: pr.title,
    note: pr.detail + '. Written from the crawl evidence, not invented: anything the ' +
          'evidence could not answer was left as a TODO.',
    before: pr.before, after: pr.after,
    approveLabel: 'Approve and save',
    onApprove: () => finish('/api/proposal/accept', {}, 'section updated'),
    onDecline: () => modal({
      title: 'Discard this writing?',
      body: 'The markers stay unwritten and the next crawl can offer again.',
      confirmLabel: 'Discard', confirmClass: 'danger',
      onConfirm: () => finish('/api/proposal/reject', {}, 'proposal discarded'),
    }),
    onCancel: () => done(),
  });
}

function showProposal(sectionId, label, result) {
  const m = holder();
  m.append(el('h2', 'page', esc(label)));

  if (result.kind === 'notes') {
    m.append(el('div', 'muted', 'A review only. Nothing was changed.'));
    const p = el('div', 'panel');
    p.append(el('pre', 'notes', esc(result.notes)));
    m.append(p);
    const back = el('button', 'act', 'Back to the section');
    back.onclick = () => openSection(sectionId);
    m.append(back);
    return;
  }

  m.append(el('div', 'muted',
    'Proposed. Nothing has been written. Review the change, then accept or discard.'));

  const rows = diffLines(result.before, result.after);
  const changed = rows.filter(r => r[0] !== 'same').length;
  const p = el('div', 'panel');
  p.append(el('h3', null, `${changed} changed line(s)`));
  const pre = el('div', 'diff');
  let run = 0;
  rows.forEach(([kind, line], idx) => {
    if (kind === 'same') {
      // collapse long unchanged runs
      const near = rows.slice(Math.max(0, idx - 2), idx + 3).some(r => r[0] !== 'same');
      if (!near) { run++; return; }
    }
    if (run) { pre.append(el('div', 'skip', `... ${run} unchanged line(s)`)); run = 0; }
    pre.append(el('div', kind, esc(line) || '&nbsp;'));
  });
  if (run) pre.append(el('div', 'skip', `... ${run} unchanged line(s)`));
  p.append(pre); m.append(p);

  const row = el('div', 'row');
  const ok = el('button', 'act primary', 'Accept and save');
  ok.onclick = async () => {
    ok.disabled = true;
    try {
      const r = await api('/api/assist/accept',
        { method: 'POST', json: { section: sectionId, markdown: result.after } });
      toast(r.message);
      await refresh(); openSection(sectionId);
    } catch (e) { toast(e.message, true); ok.disabled = false; }
  };
  const edit = el('button', 'act', 'Open in the editor instead');
  edit.onclick = () => {
    openSection(sectionId).then(() => {
      const ta = $('#md');
      if (ta) { ta.value = result.after; dirty = true; livePreview(); }
      toast('Loaded into the editor, unsaved');
    });
  };
  const no = el('button', 'act ghost', 'Discard');
  no.onclick = () => openSection(sectionId);
  row.append(ok, edit, no); m.append(row);
}

async function runCapture(screens, sectionId, opts) {
  const o = opts || {};
  if (o.mask === false && !(await ask({
    title: 'Capture with real names showing?',
    body: 'Screenshots would carry real publisher and partner names into the document.',
    confirmLabel: 'Capture unmasked', confirmClass: 'danger' }))) return;
  try {
    const r = await api('/api/capture', {
      method: 'POST', json: {
        screens: screens || null, section: sectionId || null,
        mask: o.mask !== false, replay_steps: !!o.replay_steps
      }
    });
    watchJob(r.job, screens ? `capture ${screens.join(', ')}` : 'capture all screens',
      sectionId);
  } catch (e) { toast(e.message, true); }
}

async function runJob(path, json, label) {
  try {
    const r = await api(path, { method: 'POST', json });
    watchJob(r.job, label);
  } catch (e) { toast(e.message, true); }
}

function watchJob(id, label, thenSection, onDone) {
  const d = dock({ name: label || 'Running' });
  let since = 0, liveTimer = null;

  // The rolling frame shows the page the crawler is actually on, which is how a
  // screen that loaded the wrong thing gives itself away immediately.
  //
  // This used to run only when the job's label contained the word "crawl",
  // which meant "run everything" showed nothing at all while it crawled. The
  // label is a caption, not a fact about the job. Ask the crawler instead: it
  // reports a frame only while it has one, and the frame carries its own age,
  // so a job that never crawls simply never shows one.
  const pollLive = async () => {
    try {
      const l = await api('/api/live');
      if (l.screen && l.fresh) {
        d.frame(l.url_png + '?t=' + Date.now());
        d.where(`${l.screen}  ${l.url || ''}`.slice(0, 96));
      }
    } catch (e) { /* the frame is a nicety, never a blocker */ }
    liveTimer = setTimeout(pollLive, 1200);
  };
  pollLive();

  const tick = async () => {
    let j;
    try { j = await api(`/api/job/${id}?since=${since}`); }
    catch (e) { d.log([e.message]); d.setState('failed'); return; }
    since = j.total_lines;
    d.log(j.lines);
    if (j.state === 'running') return setTimeout(tick, 700);

    if (liveTimer) clearTimeout(liveTimer);
    d.setState(j.state, `${label}: ${j.state}`);
    if (j.state === 'failed') {
      // The runner already writes the error into the job's own lines, so
      // appending it again prints every failure twice.
      const already = (j.lines || []).some(l => (l || '').trim() === (j.error || '').trim());
      if (!already) d.log(['', j.error]);
      toast(j.error, true);
    }
    else toast(`${label} finished`);
    await refresh();

    if (j.state === 'done' && onDone) { d.root.remove(); dockEl = null;
      return onDone(j.result || {}); }
    if (j.state === 'done') {
      if (thenSection)
        d.action('Open the section', 'primary', () => openSection(thenSection));
      // The file name is the version and the edition repeated on every button.
      // The kind is what tells them apart, and the full name is a hover away.
      (j.result && j.result.outputs || []).forEach(o => {
        const name = o.split('/').pop();
        const kind = (name.split('.').pop() || '').toUpperCase();
        const b = d.action(`Download ${kind || name}`, '', () =>
          window.open('/files/' + o, '_blank'));
        if (b) b.title = name;
      });
      const res = j.result || {};
      const gaps = res.proposals ?? res.count;
      const fixes = res.writing_fixes || 0;
      if (gaps || fixes) {
        const parts = [];
        if (gaps) parts.push(`${gaps} gap(s) filled in`);
        if (fixes) parts.push(`${fixes} section(s) of writing fixed`);
        d.log(['', parts.join(' and ') + ', waiting on your approval.']);
        d.action(`Review ${gaps + fixes} thing(s)`, 'primary',
                 () => setView(fixes ? 'findings' : 'queue'));
      } else if (res.lint_errors === 0 && res.run) {
        d.log(['', 'The crawl broke no rules.']);
      }
      if ((j.result || {}).run)
        d.action('Review the queue', '', () => setView('queue'));
    }
    d.action('Close', 'ghost', () => { d.root.remove(); dockEl = null; });
  };
  tick();
}

/* ---------------------------------------------------------------- boot */
const RAIL_MIN = 190, RAIL_MAX = 460;

function setupRail() {
  const app = document.querySelector('.app');
  const fold = $('#fold');
  const grip = $('#railGrip');
  fold.innerHTML = icon('chevron');

  const applyWidth = (px) => {
    document.documentElement.style.setProperty('--rail-w', px + 'px');
    localStorage.setItem('verba.rail', px);
  };
  const saved = parseInt(localStorage.getItem('verba.rail') || '', 10);
  if (saved >= RAIL_MIN && saved <= RAIL_MAX) applyWidth(saved);
  if (localStorage.getItem('verba.folded') === '1') app.classList.add('folded');

  const syncFold = () => {
    const folded = app.classList.contains('folded');
    fold.title = folded ? 'Expand the sidebar' : 'Collapse the sidebar';
    fold.setAttribute('aria-label', fold.title);
    localStorage.setItem('verba.folded', folded ? '1' : '0');
  };
  syncFold();
  fold.onclick = () => { app.classList.toggle('folded'); syncFold(); };

  // drag to resize, with the pointer captured so it keeps tracking outside the grip
  let dragging = false;
  grip.addEventListener('pointerdown', e => {
    if (app.classList.contains('folded')) return;
    dragging = true; grip.classList.add('dragging');
    grip.setPointerCapture(e.pointerId);
    document.body.style.userSelect = 'none';
  });
  grip.addEventListener('pointermove', e => {
    if (!dragging) return;
    applyWidth(Math.max(RAIL_MIN, Math.min(RAIL_MAX, Math.round(e.clientX))));
  });
  const stop = (e) => {
    if (!dragging) return;
    dragging = false; grip.classList.remove('dragging');
    try { grip.releasePointerCapture(e.pointerId); } catch (err) { /* already gone */ }
    document.body.style.userSelect = '';
  };
  grip.addEventListener('pointerup', stop);
  grip.addEventListener('pointercancel', stop);
  // keyboard: the grip is a real separator, so it should move with arrows
  grip.addEventListener('keydown', e => {
    const cur = parseInt(getComputedStyle(document.documentElement)
      .getPropertyValue('--rail-w'), 10) || 264;
    if (e.key === 'ArrowLeft') applyWidth(Math.max(RAIL_MIN, cur - 16));
    else if (e.key === 'ArrowRight') applyWidth(Math.min(RAIL_MAX, cur + 16));
    else return;
    e.preventDefault();
  });
}

function boot() {
  $('#sprite').innerHTML = iconSprite();
  setupRail();
  $('#profile').onchange = async e => {
    await api('/api/profile', { method: 'POST', json: { profile: e.target.value } });
    currentId = null; await refresh(); setView(currentStage().id);
  };
  window.onbeforeunload = () => dirty ? 'Unsaved edits' : undefined;
  adoptRunningJob();
  refresh().then(() => setView(currentStage().id)).catch(e => {
    holder().innerHTML = `<div class="panel warn-edge"><h3>Could not load the project</h3>
      <div class="muted">${esc(e.message)}</div></div>`;
  });
}

/* A crawl is a property of the machine, not of the tab that started it.

   The dock only ever existed for a job you launched yourself, in the view you
   launched it from. Reload the page, open a second window, or start a crawl
   from the command line, and the console showed nothing at all while the
   browser was busy driving a real product: the honest way to find out whether
   it was still going was to start another one.

   So the console asks. Every few seconds, and immediately on load. */
let adopted = null;
async function adoptRunningJob() {
  try {
    const r = await api('/api/jobs/running');
    const job = r.job;
    if (job && job.id !== adopted && !dockEl) {
      adopted = job.id;
      watchJob(job.id, job.name || 'Running');
    }
    if (!job) adopted = null;
  } catch (e) { /* the console still works without knowing */ }
  setTimeout(adoptRunningJob, 3000);
}

// A handle for the browser console. This is a local tool on a local port; being
// able to poke at it from devtools is worth more than hiding the surface.
window.verba = {
  setView, openSection, refresh, watchJob, api, dock,
  get state() { return S; },
};

if (document.readyState === 'loading')
  window.addEventListener('DOMContentLoaded', boot);
else boot();
