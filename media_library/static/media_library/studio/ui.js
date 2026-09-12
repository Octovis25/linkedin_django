// ui.js — shell behaviour: builds the panels from the declaration in
// toolbar.js and handles mode switching, media tabs, the retouch tool/scope
// matrix and the animation bar.
//
// Nothing in here knows what a tool DOES. Every control keeps the data-act /
// data-tool / data-shape attribute the existing handlers in studio.js listen
// for, so this file could be deleted and the app would still work — it would
// just look like the old wall of buttons again.

import { buildRail, buildPanels, buildMediaTabs, buildMedia, MODE_TITLES } from './toolbar.js';

/* --- Retouch: which legacy tool a (tool, scope) pair maps to ---------------
   The old UI had one button per cell of this table — 6 buttons for what is
   really two decisions. `data-tool` still carries the legacy name so
   setTool() in studio.js is untouched. */
const TOOL_MATRIX = {
  erase:    { brush: 'erase', area: 'fill',        all: 'pick' },
  recolour: { brush: 'paint', area: 'recolorpick', all: 'recolorpickall' },
};

// Default is the click-an-area scope, not the brush: "pick the tool, click the
// spot, the spot is gone" is how this was used before the rebuild. Starting on
// the brush turned that one click into a 20px dot and made the tool look broken.
let _scope = 'area';

/* --------------------------------------------------------------------------
   1. Build the shell. Must run before studio.js binds anything by id.
   -------------------------------------------------------------------------- */
export function mountShell() {
  const put = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  put('mode-rail', buildRail());
  put('panel-mount', buildPanels());
  put('media-tabs', buildMediaTabs());
  put('media-mount', buildMedia());
}

/* --------------------------------------------------------------------------
   2. Wire the shell. Run after mountShell().
   -------------------------------------------------------------------------- */
export function initUi() {
  wireModes();
  wireMediaTabs();
  wireRetouchScope();
  wireAnimBar();
}

/* ---- Modes --------------------------------------------------------------- */
function wireModes() {
  const rail = document.getElementById('mode-rail');
  const title = document.getElementById('panel-title');
  if (!rail) return;

  rail.addEventListener('click', e => {
    // Help does not switch mode, it opens the documentation overlay.
    if (e.target.closest('[data-help]')) {
      const box = document.getElementById('studio-help');
      if (box) box.style.display = 'flex';
      return;
    }
    const btn = e.target.closest('[data-mode]');
    if (!btn) return;
    setMode(btn.dataset.mode);
  });

  // Remember the last mode per browser. Wrapped because localStorage throws
  // outright in some privacy settings.
  let saved = null;
  try { saved = localStorage.getItem('studio.mode'); } catch { /* ignore */ }
  if (saved && document.querySelector(`[data-panel="${saved}"]`)) setMode(saved);
  else if (title) title.textContent = MODE_TITLES.build || 'Build';
}

export function setMode(mode) {
  document.querySelectorAll('#mode-rail [data-mode]').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === mode));
  document.querySelectorAll('[data-panel]').forEach(p =>
    p.hidden = p.dataset.panel !== mode);
  const title = document.getElementById('panel-title');
  if (title) title.textContent = MODE_TITLES[mode] || mode;
  try { localStorage.setItem('studio.mode', mode); } catch { /* ignore */ }
}

/* ---- Media tabs ---------------------------------------------------------- */
function wireMediaTabs() {
  const tabs = document.getElementById('media-tabs');
  if (!tabs) return;
  tabs.addEventListener('click', e => {
    const btn = e.target.closest('[data-media]');
    if (!btn) return;
    tabs.querySelectorAll('[data-media]').forEach(b => b.classList.toggle('on', b === btn));
    document.querySelectorAll('[data-media-panel]').forEach(p =>
      p.hidden = p.dataset.mediaPanel !== btn.dataset.media);
  });
}

/* ---- Retouch: tool × scope ----------------------------------------------- */
function wireRetouchScope() {
  const seg = document.getElementById('scope-seg');
  const scopeRow = document.getElementById('scope-row');
  const selectRow = document.getElementById('select-row');
  const body = document.getElementById('retouch-body');
  if (!body) return;

  // Scope change: rewrite the data-tool of the two matrix tools, then re-fire
  // whichever of them is currently active so the change takes effect at once.
  if (seg) seg.addEventListener('click', e => {
    const btn = e.target.closest('[data-scope]');
    if (!btn) return;
    _scope = btn.dataset.scope;
    seg.querySelectorAll('[data-scope]').forEach(b => b.classList.toggle('on', b === btn));
    const active = applyMatrix();
    if (active) active.click();
  });

  // Select is not a matrix tool: it swaps the scope row for the shape row.
  body.addEventListener('click', e => {
    const btn = e.target.closest('[data-toolkey]');
    if (!btn) return;
    const isSelect = btn.dataset.toolkey === 'select'
      || btn.dataset.toolkey === 'sel-rect' || btn.dataset.toolkey === 'sel-free';
    if (scopeRow)  scopeRow.hidden  = isSelect;
    if (selectRow) selectRow.hidden = !isSelect;
  }, true);

  applyMatrix();
}

// Writes the current scope into the tool buttons and returns the active one.
function applyMatrix() {
  let active = null;
  document.querySelectorAll('#retouch-body [data-toolkey]').forEach(btn => {
    const row = TOOL_MATRIX[btn.dataset.toolkey];
    if (row) btn.dataset.tool = row[_scope];
    if (btn.classList.contains('primary') && row) active = btn;
  });
  return active;
}

/* ---- Animation bar ------------------------------------------------------- */
// Stays under the canvas — that is where you compare the timing of all
// elements against each other. Collapsible for the times you only build a
// still image.
function wireAnimBar() {
  const wrap = document.getElementById('anim-wrap');
  if (!wrap) return;

  let closed = false;
  try { closed = localStorage.getItem('studio.anim') === 'closed'; } catch { /* ignore */ }
  wrap.classList.toggle('closed', closed);

  // renderAnimBar() in studio.js rebuilds the bar's contents on every change,
  // so the head element is a moving target — delegate instead of binding it.
  wrap.addEventListener('click', e => {
    if (!e.target.closest('.anim-bar-head')) return;
    if (e.target.closest('input, button, select')) return;   // controls inside the head
    const now = !wrap.classList.contains('closed');
    wrap.classList.toggle('closed', now);
    try { localStorage.setItem('studio.anim', now ? 'closed' : 'open'); } catch { /* ignore */ }
  });
}
