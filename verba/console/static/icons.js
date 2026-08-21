/* Icon set: 24x24 outline glyphs, stroke-based, currentColor.
 *
 * Emoji were doing this job before. They render differently on every machine,
 * carry no semantics for a screen reader, and cannot inherit colour or weight,
 * so they read as decoration rather than interface. These are drawn once into a
 * hidden sprite and referenced with <use>. */

const ICON_PATHS = {
  overview: '<path d="M3 12l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/>',
  sections: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h10M7 17h6"/>',
  queue: '<path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="16" r="3"/><path d="M18 14.5V16l1 .8"/>',
  connections: '<path d="M9 15l6-6"/><path d="M13.5 6.5l1.4-1.4a4 4 0 015.7 5.7L19.2 12"/><path d="M10.5 17.5l-1.4 1.4a4 4 0 01-5.7-5.7L4.8 12"/>',
  document: '<path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
  history: '<path d="M3 12a9 9 0 109-9 9 9 0 00-6.4 2.6L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
  publish: '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"/>',
  form: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 8h10M7 12h6"/><rect x="7" y="15" width="6" height="3" rx="1"/>',
  palette: '<path d="M12 3a9 9 0 000 18 2 2 0 001.6-3.2 2 2 0 011.6-3.2h1.7A4.1 4.1 0 0021 10.4C21 6.3 16.9 3 12 3z"/><circle cx="7.5" cy="10.5" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16.5" cy="10.5" r="1"/>',
  refresh: '<path d="M3 12a9 9 0 019-9 9 9 0 016.4 2.6L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 01-9 9 9 9 0 01-6.4-2.6L3 16"/><path d="M3 21v-5h5"/>',

  camera: '<path d="M3 8a2 2 0 012-2h2.2l1.2-2h6.2l1.2 2H20a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><circle cx="12" cy="12.5" r="3.5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  check: '<path d="M4 12.5l5 5L20 6.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/>',
  lock: '<rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/>',
  eye: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/>',
  edit: '<path d="M4 20h4l10-10-4-4L4 16z"/><path d="M14 6l4 4"/>',
  save: '<path d="M5 4h11l3 3v13H5z"/><path d="M9 4v5h6V4"/><path d="M8 20v-6h8v6"/>',
  trash: '<path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  sparkle: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  download: '<path d="M12 4v11"/><path d="M7 11l5 5 5-5"/><path d="M4 19h16"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.3l3.3 2"/>',
  link: '<path d="M4 7h10a5 5 0 010 10H9"/><path d="M12 13l-3 4 3 4" transform="translate(0,-7)"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.4 8.3-8 9.5C7.4 20.3 4 17 4 12V6z"/><path d="M9 12l2 2 4-4"/>',
  key: '<circle cx="8" cy="14" r="4"/><path d="M11 11l9-9"/><path d="M17 5l2 2M15 7l3 3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 010 18 14 14 0 010-18z"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
};

const SIZE_DEFAULT = 18;

export function iconSprite() {
  const symbols = Object.entries(ICON_PATHS)
    .map(([name, d]) => `<symbol id="i-${name}" viewBox="0 0 24 24">${d}</symbol>`)
    .join('');
  return `<svg aria-hidden="true" style="position:absolute;width:0;height:0;overflow:hidden">
    <defs>${symbols}</defs></svg>`;
}

/** Inline icon markup. Decorative by default; pass a label to expose it. */
export function icon(name, { size = SIZE_DEFAULT, cls = '', label = '' } = {}) {
  if (!ICON_PATHS[name]) return '';
  const a11y = label
    ? `role="img" aria-label="${label}"`
    : 'aria-hidden="true" focusable="false"';
  return `<svg class="ic ${cls}" width="${size}" height="${size}" ${a11y}><use href="#i-${name}"/></svg>`;
}

export const ICON_NAMES = Object.keys(ICON_PATHS);
