// elements.js - the elements the Studio builds itself: badges, text blocks,
// checklists (and splitting them into rows), SVG import, and the marks of the
// Effects tab - marker, stamp, question web and spotlight - with their
// in-place editing.
//
// Moved out of studio.js (review 27.09.2026). initElemente() hands over the
// editor and the current shape colour and wires the canvas events.
import * as media from './media.js';
import { fabric, hexPoints } from './editor.js';
import { toast, status, modal, wegDamit, hexNorm } from './util.js';
import { renderLayers, renderAnimBar } from './animbar.js';
import * as bg from './background.js';

let editor = null;
let formFarbe = () => '#F56E28';     // the palette colour for new shapes, read when needed

// ---- Kreis/Banner mit Text (Füllfarbe = Palette, Textfarbe = Textfarben-Feld) ----
// White or dark grey - whichever is readable on the fill colour
export function autoContrast(fill) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hexNorm(fill));
  if (!m) return '#ffffff';
  const n = parseInt(m[1], 16);
  const lum = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  return lum > 0.6 ? '#1a1a1a' : '#ffffff';
}

// Wabe: Sechseck mit Spitze oben

function buildBadge(kind, txt, fill, textColor) {
  const fs = (kind === 'circle' || kind === 'hex') ? 30 : 28;
  const label = new fabric.Text(txt, {
    fontSize: fs, fontWeight: 'bold', fontFamily: 'Roboto, Arial, sans-serif',
    fill: textColor, originX: 'center', originY: 'center', left: 0, top: 0,
  });
  let shape;
  if (kind === 'circle') {
    const r = Math.max(36, Math.hypot(label.width, label.height) / 2 + 12);
    shape = new fabric.Circle({ radius: r, fill, originX: 'center', originY: 'center', left: 0, top: 0 });
  } else if (kind === 'hex') {
    // The text has to fit the narrower width of the hexagon -> a more generous radius
    const r = Math.max(40, label.width / 1.55 + 16, label.height / 1.4 + 14);
    shape = new fabric.Polygon(hexPoints(r), { fill, originX: 'center', originY: 'center', left: 0, top: 0 });
  } else {
    const h = Math.max(64, label.height + 26);
    const w = Math.max(140, label.width + 56);
    shape = new fabric.Rect({ width: w, height: h, rx: h / 2, ry: h / 2, fill,
      originX: 'center', originY: 'center', left: 0, top: 0 });
  }
  return new fabric.Group([shape, label], {
    originX: 'center', originY: 'center', shapeKind: 'badge-' + kind,
  });
}

export function addBadge(kind) {
  const inp = fxWortfeld();
  const typed = inp?.value.trim();
  const fill = formFarbe();
  let textColor = document.getElementById('text-color')?.value || '#ffffff';
  // Gemeinsame Palette färbt beides gleich -> Text wäre unsichtbar. Dann automatisch.
  if (hexNorm(textColor) === hexNorm(fill)) textColor = autoContrast(fill);

  const dflt = (kind === 'circle' || kind === 'hex') ? '1' : 'Title';
  const g = buildBadge(kind, typed || dflt, fill, textColor);
  g.set({ left: editor.width / 2, top: editor.height / 2 });
  g.scale(markenGroesse());
  editor.canvas.add(g);
  editor.canvas.setActiveObject(g);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  if (inp) inp.value = '';
  if (!typed) startBadgeEdit(g);   // nichts vorgetippt -> gleich losschreiben
}

// ---- Textblock: Überschrift + Fließtext als EIN Objekt --------------------
export function buildTextblock(head, body, opts) {
  const w = opts.width, size = opts.size, col = opts.color;
  const check = !!opts.check;
  const align = opts.align || (check ? 'left' : 'center');
  const parts = [];
  // With a tick, indent the text to the right to leave room for it.
  const r = size * 0.42;                 // Haken-Radius ~ Buchstabenhöhe
  const textLeft = check ? Math.round(2 * r + size * 0.22) : 0;   // kleiner Abstand Haken→Text
  let y = 0;
  if (head) {
    const h = new fabric.Textbox(head, {
      width: w, fontSize: size, fontWeight: 'bold',
      fontFamily: 'Roboto, Arial, sans-serif', fill: col,
      textAlign: align, left: textLeft, top: 0, lineHeight: 1.25, splitByGrapheme: false,
    });
    parts.push(h);
    y = h.height + Math.round(size * 0.45);
  }
  if (body) {
    const b = new fabric.Textbox(body, {
      width: w, fontSize: Math.max(9, Math.round(size * 0.74)), fontWeight: 'normal',
      fontFamily: 'Roboto, Arial, sans-serif', fill: col,
      textAlign: align, left: textLeft, top: y, lineHeight: 1.35, splitByGrapheme: false,
    });
    parts.push(b);
  }
  if (!parts.length) return null;
  if (check) {
    // Octovis-Haken links, mittig zur ersten Zeile.
    const cx = r, cy = size * 0.62;
    const sc = r / 226;
    const circle = new fabric.Circle({ left: cx, top: cy, originX: 'center', originY: 'center', radius: r, fill: '#EB6E08' });
    const pd = `M ${cx + (-111) * sc} ${cy + 9 * sc} L ${cx + (-37) * sc} ${cy + 84 * sc} L ${cx + 123 * sc} ${cy - 87 * sc}`;
    const tick = new fabric.Path(pd, { fill: '', stroke: '#FFFFFF', strokeWidth: 58 * sc, strokeLineCap: 'round', strokeLineJoin: 'round' });
    parts.unshift(circle, tick);
  }
  const g = new fabric.Group(parts, {
    left: editor.width / 2, top: editor.height / 2,
    originX: 'center', originY: 'center',
    shapeKind: 'textblock', tbWidth: w, tbSize: size, tbAlign: align,
    tbHead: head, tbBody: body, tbCheck: check, tbColor: col,
  });
  return g;
}

export function addTextblock() {
  const head = document.getElementById('tb-head')?.value.trim() || '';
  const body = document.getElementById('tb-body')?.value.trim() || '';
  if (!head && !body) { status('Please enter a heading or text.', '#dc3545'); return; }
  const g = buildTextblock(head, body, {
    width: +(document.getElementById('tb-width')?.value || 260),
    size: +(document.getElementById('tb-size')?.value || 19),
    color: document.getElementById('text-color')?.value || '#111111',
    align: 'center',
  });
  if (!g) return;
  editor.canvas.add(g);
  editor.canvas.setActiveObject(g);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  status('Text block inserted – double-click to edit.', '#198754');
}

export function isTextblock(o) { return !!(o && o.shapeKind === 'textblock'); }

// What a rebuilt element takes over from the old one: its placement, its look
// beyond the build (flip, opacity, shadow, slant) and its timing. The rebuilds
// used to copy only placement and motion - editing a text lost its opacity,
// its flip, its shadow and its effect colour and tempo.
const MITNEHMEN = ['angle', 'scaleX', 'scaleY', 'flipX', 'flipY', 'skewX', 'skewY', 'opacity', 'shadow',
                   'fx', 'fxDelay', 'fxTempo', 'fxColor', 'startAt'];
function zustandVon(g) {
  const z = {};
  MITNEHMEN.forEach(k => { if (g[k] !== undefined) z[k] = g[k]; });
  z.anim = g.anim ? { ...g.anim } : g.anim;
  return z;
}

export function rebuildTextblock(g, head, body, over = {}) {
  const c = g.getCenterPoint();
  const firstText = (g._objects || []).find(x => x.type === 'textbox');
  const col = over.color || g.tbColor || (firstText && firstText.fill) || '#111111';
  const ng = buildTextblock(head, body, {
    width: over.width || g.tbWidth || 260,
    size:  over.size  || g.tbSize  || 19,
    color: col, align: g.tbAlign || 'center', check: !!g.tbCheck,
  });
  if (!ng) return null;
  ng.set({ ...zustandVon(g), left: c.x, top: c.y });
  const idx = editor.canvas.getObjects().indexOf(g);
  editor.canvas.remove(g);
  editor.canvas.add(ng);
  if (idx >= 0) ng.moveTo(idx);
  editor.canvas.setActiveObject(ng);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  return ng;
}

function startTextblockEdit(g) {
  if (!isTextblock(g)) return;
  wegDamit(document.getElementById('tb-edit'));
  const cEl = editor.canvas.upperCanvasEl;
  const r = cEl.getBoundingClientRect();
  const k = r.width / editor.canvas.getWidth();
  const p = g.getCenterPoint();
  const vt = editor.canvas.viewportTransform || [1, 0, 0, 1, 0, 0];
  const zoom = editor.canvas.getZoom();
  const x = r.left + (p.x * zoom + vt[4]) * k;
  const y = r.top + (p.y * zoom + vt[5]) * k;

  const box = document.createElement('div');
  box.id = 'tb-edit';
  box.style.cssText = `position:fixed;left:${x}px;top:${y}px;transform:translate(-50%,-50%);
    z-index:9999;background:#fff;border:2px solid #F56E28;border-radius:8px;padding:8px;
    box-shadow:0 6px 20px rgba(0,0,0,.3);display:flex;flex-direction:column;gap:5px;width:300px;`;
  box.innerHTML = `
    <input type="text" id="tb-e-head" placeholder="Heading" style="font-weight:700;font-size:14px;padding:5px;border:1px solid #ccc;border-radius:4px">
    <textarea id="tb-e-body" placeholder="Text" rows="3" style="font-size:13px;padding:5px;border:1px solid #ccc;border-radius:4px;resize:vertical;font-family:inherit"></textarea>
    <div style="display:flex;gap:8px;align-items:center;font-size:11px;color:#666">
      <label style="display:flex;gap:3px;align-items:center">Font size
        <input type="number" id="tb-e-size" min="8" step="1" style="width:56px;padding:3px;border:1px solid #ccc;border-radius:4px">
      </label>
      <label style="display:flex;gap:3px;align-items:center">Width
        <input type="number" id="tb-e-width" min="60" step="10" style="width:64px;padding:3px;border:1px solid #ccc;border-radius:4px">
      </label>
    </div>
    <div style="font-size:11px;color:#888">Ctrl+Enter = done, Esc = cancel</div>`;
  document.body.appendChild(box);
  const hi = box.querySelector('#tb-e-head'), bi = box.querySelector('#tb-e-body');
  const si = box.querySelector('#tb-e-size'), wi = box.querySelector('#tb-e-width');
  hi.value = g.tbHead || ''; bi.value = g.tbBody || '';
  si.value = g.tbSize || 19; wi.value = g.tbWidth || 260;
  hi.focus(); hi.select();
  status('Edit text block – size/width adjustable, Ctrl+Enter = done.');

  let done = false;
  const finish = save => {
    if (done) return; done = true;
    const h = hi.value.trim(), b = bi.value.trim();
    const sz = Math.max(8, +si.value || g.tbSize || 19);
    const wd = Math.max(60, +wi.value || g.tbWidth || 260);
    wegDamit(box);
    const geaendert = h !== (g.tbHead || '') || b !== (g.tbBody || '')
      || sz !== (g.tbSize || 19) || wd !== (g.tbWidth || 260);
    if (save && geaendert) rebuildTextblock(g, h, b, { size: sz, width: wd });
    status('Ready.');
  };
  box.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); finish(true); }
  });
  setTimeout(() => {
    document.addEventListener('mousedown', function out(ev) {
      if (!box.contains(ev.target)) { document.removeEventListener('mousedown', out); finish(true); }
    });
  }, 50);
}

// ---- Mehrzeilige Haken-Liste (Dreihaken): je Zeile ein Haken, EIN Objekt --
export function isChecklist(o) { return !!(o && o.shapeKind === 'checklist'); }

export function buildCheckList(items, opts) {
  const w = opts.width, size = opts.size, col = opts.color;
  const r = size * 0.42;
  const textLeft = Math.round(2 * r + size * 0.22);
  const parts = [];
  let y = 0;
  (items.length ? items : ['Line']).forEach(txt => {
    const tb = new fabric.Textbox(txt || ' ', {
      width: w, fontSize: size, fontWeight: 'bold',
      fontFamily: 'Roboto, Arial, sans-serif', fill: col,
      textAlign: 'left', left: textLeft, top: y, lineHeight: 1.25, splitByGrapheme: false,
    });
    const cx = r, cy = y + size * 0.62, sc = r / 226;
    const circle = new fabric.Circle({ left: cx, top: cy, originX: 'center', originY: 'center', radius: r, fill: '#EB6E08' });
    const pd = `M ${cx + (-111) * sc} ${cy + 9 * sc} L ${cx + (-37) * sc} ${cy + 84 * sc} L ${cx + 123 * sc} ${cy - 87 * sc}`;
    const tick = new fabric.Path(pd, { fill: '', stroke: '#FFFFFF', strokeWidth: 58 * sc, strokeLineCap: 'round', strokeLineJoin: 'round' });
    parts.push(circle, tick, tb);
    y += Math.max(tb.height, size * 1.25) + Math.round(size * 0.5);
  });
  const g = new fabric.Group(parts, {
    left: editor.width / 2, top: editor.height / 2,
    originX: 'center', originY: 'center',
    shapeKind: 'checklist', clItems: items.slice(), clWidth: w, clSize: size, clColor: col,
  });
  return g;
}


// ---- Splitting a checklist into one element per row ----------------------
// The list is ONE group: per row a circle, a tick and a textbox. A group
// carries a single Motion and a single Start, so the rows can only ever fly in
// together. Splitting hands each row its own timing.
//
// Each row becomes a checklist again - with a single item. That keeps
// double-click editing, the size and the colour; only editing all rows at once
// is gone. So: write the text first, split second, animate third.
//
// The geometry is the delicate part. A row must land exactly where it sat
// inside the group, or the list jumps on splitting and the user has to
// rearrange by hand. The centre is therefore taken in the group's own
// coordinates and put through the group matrix - that carries rotation and
// scaling along without doing the trigonometry here.
function circleCentre(circle, matrix) {
  // The circle carries originX/originY = 'center', so its left/top IS its
  // centre in the group's own coordinates. Through the group matrix that
  // becomes an absolute point - rotation and scaling included.
  return fabric.util.transformPoint(new fabric.Point(circle.left, circle.top), matrix);
}

export function splitChecklist(g) {
  if (!isChecklist(g)) { toast('Select a checklist first', 'err'); return null; }
  const items = (g.clItems || []).filter(Boolean);
  if (items.length < 2) { toast('This list has a single row - nothing to split', 'err'); return null; }
  const parts = g._objects || [];
  if (parts.length !== items.length * 3) {
    // buildCheckList pushes exactly circle, tick, textbox per row. If that no
    // longer holds, the rows cannot be told apart and splitting would scatter
    // the list - better to refuse than to wreck the layout.
    toast('This list cannot be split - it was not built row by row', 'err');
    return null;
  }

  const opts = { width: g.clWidth || 300, size: g.clSize || 22, color: g.clColor || '#161616' };
  const matrix = g.calcTransformMatrix();
  const idx = editor.canvas.getObjects().indexOf(g);
  const rows = [];

  items.forEach((text, i) => {
    const ziel = circleCentre(parts[i * 3], matrix);
    const ng = buildCheckList([text], opts);
    if (!ng) return;
    // The timing travels along, so a motion already set is not lost. The
    // start is then staggered per row - that is the whole point.
    ng.set({ ...zustandVon(g), left: ziel.x, top: ziel.y });
    // Measure instead of trusting the arithmetic: the new row is placed
    // roughly, then shifted so that ITS circle sits exactly where the old one
    // sat. Everything else in a row is fixed relative to that circle, so one
    // anchor point aligns the whole row - and no assumption about matching
    // bounding boxes has to hold.
    ng.setCoords();
    const ist = circleCentre(ng._objects[0], ng.calcTransformMatrix());
    ng.set({ left: ng.left + (ziel.x - ist.x), top: ng.top + (ziel.y - ist.y) });
    ng.setCoords();
    rows.push(ng);
  });
  if (!rows.length) return null;

  editor.canvas.remove(g);
  rows.forEach((ng, i) => {
    editor.canvas.add(ng);
    if (idx >= 0) ng.moveTo(idx + i);
  });
  editor.canvas.setActiveObject(rows[0]);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  return rows;
}

export function rebuildChecklist(g, items, over = {}) {
  const c = g.getCenterPoint();
  const ng = buildCheckList(items, {
    width: over.width || g.clWidth || 300,
    size:  over.size  || g.clSize  || 22,
    color: over.color || g.clColor || '#161616',
  });
  if (!ng) return null;
  ng.set({ ...zustandVon(g), left: c.x, top: c.y });
  const idx = editor.canvas.getObjects().indexOf(g);
  editor.canvas.remove(g);
  editor.canvas.add(ng);
  if (idx >= 0) ng.moveTo(idx);
  editor.canvas.setActiveObject(ng);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  return ng;
}

function startChecklistEdit(g) {
  if (!isChecklist(g)) return;
  wegDamit(document.getElementById('tb-edit'));
  const p = g.getCenterPoint();
  const cEl = editor.canvas.upperCanvasEl, r = cEl.getBoundingClientRect();
  const k = r.width / editor.canvas.getWidth();
  const vt = editor.canvas.viewportTransform || [1, 0, 0, 1, 0, 0], zoom = editor.canvas.getZoom();
  const x = r.left + (p.x * zoom + vt[4]) * k, y = r.top + (p.y * zoom + vt[5]) * k;
  const box = document.createElement('div');
  box.id = 'tb-edit';
  box.style.cssText = `position:fixed;left:${x}px;top:${y}px;transform:translate(-50%,-50%);
    z-index:9999;background:#fff;border:2px solid #F56E28;border-radius:8px;padding:8px;
    box-shadow:0 6px 20px rgba(0,0,0,.3);display:flex;flex-direction:column;gap:5px;width:320px;`;
  box.innerHTML = `
    <div style="font-size:11px;color:#666">One line = one check:</div>
    <textarea id="cl-e-body" rows="4" style="font-size:13px;padding:5px;border:1px solid #ccc;border-radius:4px;resize:vertical;font-family:inherit"></textarea>
    <div style="display:flex;gap:8px;align-items:center;font-size:11px;color:#666">
      <label style="display:flex;gap:3px;align-items:center">Font size
        <input type="number" id="cl-e-size" min="8" step="1" style="width:56px;padding:3px;border:1px solid #ccc;border-radius:4px"></label>
      <label style="display:flex;gap:3px;align-items:center">Width
        <input type="number" id="cl-e-width" min="60" step="10" style="width:64px;padding:3px;border:1px solid #ccc;border-radius:4px"></label>
    </div>
    <div style="font-size:11px;color:#888">Ctrl+Enter = done, Esc = cancel</div>`;
  document.body.appendChild(box);
  const bi = box.querySelector('#cl-e-body'), si = box.querySelector('#cl-e-size'), wi = box.querySelector('#cl-e-width');
  bi.value = (g.clItems || []).join('\n'); si.value = g.clSize || 22; wi.value = g.clWidth || 300;
  bi.focus();
  status('Edit checklist – one line per check, Ctrl+Enter = done.');
  let done = false;
  const finish = save => {
    if (done) return; done = true;
    const items = bi.value.split('\n').map(s => s.trim()).filter(Boolean);
    const sz = Math.max(8, +si.value || g.clSize || 22);
    const wd = Math.max(60, +wi.value || g.clWidth || 300);
    wegDamit(box);
    if (save && items.length) rebuildChecklist(g, items, { size: sz, width: wd });
    status('Ready.');
  };
  box.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); finish(true); }
  });
  setTimeout(() => {
    document.addEventListener('mousedown', function out(ev) {
      if (!box.contains(ev.target)) { document.removeEventListener('mousedown', out); finish(true); }
    });
  }, 50);
}

// ---- Bundling SVG texts into text blocks ---------------------------------
// Fabric does not read <tspan>: multi-line SVG text has to arrive as separate
// <text> elements. Otherwise everything sticks together on one line. So that
// this does not become one object per line in the Studio, we join lines that
// sit under each other back into ONE text block (double-click to edit).
function textZeilenBuendeln(texte) {
  const info = texte.map(o => {
    const c = o.getCenterPoint();
    const fs = o.fontSize || 16;
    const w = (o.width || 0) * (o.scaleX || 1);
    const gew = String(o.fontWeight || '');
    return { o, x: c.x, y: c.y, fs, w, fett: gew === 'bold' || parseInt(gew, 10) >= 600 };
  });
  info.sort((a, b) => (a.x - b.x) || (a.y - b.y));

  const gruppen = [];
  for (const t of info) {
    const g = gruppen[gruppen.length - 1];
    const letzte = g && g[g.length - 1];
    const gleicheSpalte = letzte && Math.abs(t.x - letzte.x) <= 40;
    const dichtDrunter  = letzte && (t.y - letzte.y) > 0 && (t.y - letzte.y) <= 2.4 * Math.max(t.fs, letzte.fs);
    if (gleicheSpalte && dichtDrunter) g.push(t);
    else gruppen.push([t]);
  }
  return gruppen;
}

function textblockAusGruppe(g, s, offX, offY) {
  const kopfZeilen = [], textZeilen = [];
  const kopfEnde = g.findIndex(t => !t.fett);
  g.forEach((t, i) => {
    const txt = (t.o.text || '').trim();
    if (!txt) return;
    (kopfEnde === -1 || i < kopfEnde ? kopfZeilen : textZeilen).push(txt);
  });
  const head = kopfZeilen.join(' ');
  const body = textZeilen.join('\n');
  if (!head && !body) return null;

  const kopfFs = (g.find(t => t.fett) || g[0]).fs;
  const textFs = (g.find(t => !t.fett) || g[0]).fs;
  // buildTextblock works out body text as 0.74 x size. Without a heading the
  // size therefore has to be scaled up, so the text comes out right.
  const size = head ? kopfFs * s : (textFs * s) / 0.74;
  const breite = Math.max(...g.map(t => t.w)) * s;

  const tb = buildTextblock(head, body, {
    width: Math.max(120, Math.round(breite * 1.12)),
    size: Math.max(8, Math.round(size)),
    color: g[0].o.fill || '#111111',
    align: 'center',
  });
  if (!tb) return null;

  const yMitte = (g[0].y + g[g.length - 1].y) / 2;
  tb.set({ left: offX + g[0].x * s, top: offY + yMitte * s, svgPart: true });
  tb.setCoords();
  return tb;
}

// ---- SVG importieren: zerlegt in einzelne Ebenen -------------------------
export async function importSvgText(svgText, asGroup) {
  // If something is already on the artboard, the import would stack on top of
  // it (duplicate images and texts). Ask first whether to clear it.
  if (editor.canvas.getObjects().length) {
    const leeren = await modal(
      'Clear the canvas first?',
      'There are already elements on the canvas. Without clearing, the SVG is placed on top – then images and text overlap.',
      [
        { label: '🧹 Clear and insert', value: true },
        { label: 'Place on top', value: false },
      ]);
    if (leeren) editor.clearAll();
  }
  return new Promise(resolve => {
    fabric.loadSVGFromString(svgText, (objects, options) => {
      const objs = (objects || []).filter(Boolean);
      if (!objs.length) { status('SVG contained no readable shapes.', '#dc3545'); return resolve(0); }

      // Auf die Canvas-Groesse einpassen (90 %, mittig)
      const sw = options?.width || editor.width;
      const sh = options?.height || editor.height;
      const s = Math.min(editor.width / sw, editor.height / sh) * 0.9;
      const offX = (editor.width - sw * s) / 2;
      const offY = (editor.height - sh * s) / 2;

      if (asGroup) {
        const g = fabric.util.groupSVGElements(objs, options);
        g.set({
          left: editor.width / 2, top: editor.height / 2,
          originX: 'center', originY: 'center',
          scaleX: (g.scaleX || 1) * s, scaleY: (g.scaleY || 1) * s,
          shapeKind: 'svg',
        });
        editor.canvas.add(g);
        editor.canvas.setActiveObject(g);
      } else {
        // Handle texts separately: lines sitting under each other are bundled
        // into ONE text block - one object per icon instead of five.
        const texte  = objs.filter(o => o.type === 'text' && (o.text || '').trim());
        const formen = objs.filter(o => !texte.includes(o));

        formen.forEach((o, i) => {
          o.set({
            left: offX + (o.left || 0) * s,
            top:  offY + (o.top  || 0) * s,
            scaleX: (o.scaleX || 1) * s,
            scaleY: (o.scaleY || 1) * s,
            shapeKind: o.shapeKind || 'svg',
            svgPart: i + 1,
          });
          o.setCoords();
          editor.canvas.add(o);
        });

        let anzahl = formen.length;
        for (const g of textZeilenBuendeln(texte)) {
          const tb = textblockAusGruppe(g, s, offX, offY);
          if (tb) { editor.canvas.add(tb); anzahl++; continue; }
          // Notnagel: falls das Bündeln scheitert, Zeilen einzeln übernehmen.
          g.forEach(t => {
            t.o.set({
              left: offX + (t.o.left || 0) * s, top: offY + (t.o.top || 0) * s,
              scaleX: (t.o.scaleX || 1) * s, scaleY: (t.o.scaleY || 1) * s,
              shapeKind: 'svg', svgPart: true,
            });
            t.o.setCoords();
            editor.canvas.add(t.o);
            anzahl++;
          });
        }
        editor.canvas.requestRenderAll();
        editor.snapshot();
        return resolve(anzahl);
      }
      editor.canvas.requestRenderAll();
      editor.snapshot();
      resolve(1);
    });
  });
}


/* ---- Marker: a sign you place yourself ---------------------------------
   A frame gives an effect an area; a marker is the opposite - one point, set
   by hand. It is an ordinary group, so it can be dragged, scaled and sorted in
   the layers like everything else. The blinking is the Pulse motion we already
   have, not a second system. */
function buildMarker(txt, fill, textColor) {
  const r = 26;
  const stiel = new fabric.Rect({
    width: 4, height: r * 2.0, rx: 2, ry: 2, fill: '#0A4D52', opacity: 0.35,
    originX: 'center', originY: 'top', left: 3, top: r * 0.55, angle: 8,
  });
  const kreis = new fabric.Circle({ radius: r, fill, originX: 'center', originY: 'center', left: 0, top: 0 });
  const glanz = new fabric.Circle({
    radius: r * 0.3, fill: '#ffffff', opacity: 0.45,
    originX: 'center', originY: 'center', left: -r * 0.28, top: -r * 0.32,
  });
  const label = new fabric.Text(String(txt || '?'), {
    fontSize: r * 1.1, fontWeight: 'bold', fontFamily: 'Roboto, Arial, sans-serif',
    fill: textColor, originX: 'center', originY: 'center', left: 0, top: 0,
  });
  return new fabric.Group([stiel, kreis, glanz, label], {
    originX: 'center', originY: 'center', shapeKind: 'marker',
  });
}

function isMarker(o) { return !!(o && o.shapeKind === 'marker'); }

/* ---- Question web: question marks you place, tied by threads -------------
   Each question mark is an element of its own, so it is dragged like any other
   one; the threads and the texts are painted by media.js from where the
   question marks stand. The settings sit on every node of a web alike. */
const frageRadius = () => Math.max(12, Math.round(Math.min(editor.width, editor.height) * 0.028));
export function frageZeichenFuer(o, i) { const z = o.qwebSign || '?'; return z === '#' ? String(i + 1) : z; }
function buildFrage(zeichen, farbe, r) {
  const kreis = new fabric.Circle({ radius: r, fill: farbe, originX: 'center', originY: 'center', left: 0, top: 0 });
  const text = new fabric.Text(zeichen, {
    fontSize: r * 1.15, fontWeight: 'bold', fontFamily: 'Roboto, Arial, sans-serif',
    fill: '#ffffff', originX: 'center', originY: 'center', left: 0, top: r * 0.04,
  });
  return new fabric.Group([kreis, text], { originX: 'center', originY: 'center', shapeKind: media.FRAGE });
}
function frageKnoten(props, x, y) {
  const g = buildFrage('?', props.qwebColor || '#F56E28', frageRadius());
  Object.assign(g, props);
  g.set({ left: x, top: y });
  return g;
}
export function netzVon(o) { return media.fragenNetze(editor).get(o.qwebId || 'q') || [o]; }

/* Duplicate and Delete keep question webs and spotlights in order. A copy of
   one member joins its web or spotlight at the end, with the next number; a
   copy of a whole web or spotlight becomes one of its own. Deleting closes the
   gaps, so the numbers and signs run 1, 2, 3 again. */
const GRUPPEN_ARTEN = [
  { ist: media.istFrageKnoten, id: 'qwebId', nr: 'qwebNr', vorsilbe: 'q', gruppen: () => media.fragenNetze(editor),
    ordnen: k => netzAktualisieren(k) },
  { ist: media.istSpot, id: 'spotId', nr: 'spotNr', vorsilbe: 's', gruppen: () => media.spotGruppen(editor),
    ordnen: k => spotOrdnenAnwenden(k) },
];
// Order, sign and colour after any change - the numbers follow the list.
export function netzAktualisieren(knoten) {
  knoten.forEach((o, i) => {
    o.qwebNr = i;
    o._objects?.[0]?.set('fill', o.qwebColor || '#F56E28');
    o._objects?.[1]?.set('text', frageZeichenFuer(o, i));
    o.dirty = true;
  });
  editor.canvas.requestRenderAll();
}
export function netzEinstellen(knoten, schluessel, wert) {
  knoten.forEach(o => { o[schluessel] = wert; });
  netzAktualisieren(knoten);
  editor.snapshot();
  renderAnimBar(); renderLayers();
}
export function addFragenNetz() {
  const id = 'q' + Date.now().toString(36);
  const W = editor.width, H = editor.height;
  // A zigzag down the left half: the texts sit to the right of their
  // question marks and do not run into the next one.
  const stellen = [[0.30, 0.30, 'Which version?'], [0.60, 0.46, 'Who was trained?'],
                   [0.34, 0.64, 'Where is the evidence?']];
  const knoten = stellen.map(([fx, fy, text], i) => {
    const o = frageKnoten({ ...media.FRAGE_STANDARD, qwebId: id, qwebNr: i, qwebText: text, startAt: 0 },
                          Math.round(W * fx), Math.round(H * fy));
    o.scale(markenGroesse());
    editor.canvas.add(o);
    return o;
  });
  netzAktualisieren(knoten);
  editor.canvas.setActiveObject(knoten[0]);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  renderLayers(); renderAnimBar();
  toast('Question web added - drag the question marks to the gaps; texts and look are under the canvas.');
  return knoten;
}
export function frageDazu(knoten) {
  const e = knoten[0];
  const mx = knoten.reduce((a, o) => a + o.getCenterPoint().x, 0) / knoten.length;
  const my = knoten.reduce((a, o) => a + o.getCenterPoint().y, 0) / knoten.length;
  const props = { qwebId: e.qwebId, qwebNr: knoten.length, qwebText: '', startAt: e.startAt || 0 };
  Object.keys(media.FRAGE_STANDARD).forEach(k => { props[k] = e[k]; });
  const o = frageKnoten(props, Math.round(mx + frageRadius() * 3), Math.round(my + frageRadius() * 2));
  o.scale(e.scaleX || 1);
  editor.canvas.add(o);
  netzAktualisieren([...knoten, o]);
  editor.snapshot();
  renderLayers(); renderAnimBar();
  return o;
}

/* ---- Spotlight: click an element, the frame goes round it ----------------
   "Spotlight" in the Effects tab waits for one click on the picture. The
   Studio finds the element there - icon and text together - and lays the
   frame round it (media.spotElemente). Elements selected beforehand (icon and
   text as elements of their own) get their frame at once. Esc cancels. */
let _spotWahl = null, _spotListe = [], _spotCursor = null;
export function spotStarten(gruppe = null) {
  const aktiv = editor.canvas.getActiveObject();
  if (!gruppe && aktiv && !media.istEffektRahmen(aktiv)
      && !(aktiv.type === 'activeSelection' && aktiv.getObjects().some(media.istEffektRahmen))) {
    const b = aktiv.getBoundingRect(true, true);
    // Something small selected: that is the element. The whole picture as one
    // image is not - then it is the click that says which part.
    if (b.width * b.height < editor.width * editor.height * 0.5) {
      const rand = 8;
      return spotSetzen({ x: b.left - rand, y: b.top - rand, w: b.width + 2 * rand, h: b.height + 2 * rand }, null);
    }
  }
  _spotListe = media.spotElemente(editor);
  _spotWahl = { gruppe };
  _spotCursor = [editor.canvas.defaultCursor, editor.canvas.hoverCursor];
  editor.canvas.discardActiveObject();
  editor.canvas.skipTargetFind = true;
  editor.canvas.selection = false;
  editor.canvas.defaultCursor = 'crosshair'; editor.canvas.hoverCursor = 'crosshair';
  editor.canvas.requestRenderAll();
  toast('Click an icon or its text in the picture - the frame goes round both. Esc cancels.');
  return null;
}
function spotWahlEnde() {
  if (!_spotWahl) return;
  _spotWahl = null;
  editor.canvas.skipTargetFind = false;
  editor.canvas.selection = true;
  if (_spotCursor) { editor.canvas.defaultCursor = _spotCursor[0]; editor.canvas.hoverCursor = _spotCursor[1]; }
}
function spotSetzen(box, gruppe) {
  const o = media.addSpot(editor, box, gruppe);
  if (gruppe) spotOrdnenAnwenden([...gruppe, o]);
  editor.snapshot(); renderLayers(); renderAnimBar();
  if (!gruppe) toast('Spotlight set - the settings are under the canvas.');
  return o;
}
// The numbers follow the chosen order; "As clicked" keeps them as they are.
function spotOrdnenAnwenden(k) {
  const art = media.spotWert(k[0], 'spotReihe');
  const boxen = k.slice().sort((a, b) => (a.spotNr || 0) - (b.spotNr || 0)).map(o => {
    const b = o.getBoundingRect(true, true);
    return { x: b.left, y: b.top, w: b.width, h: b.height, o };
  });
  const reihe = art === 'klick' ? boxen : media.spotOrdnen(boxen, art);
  reihe.forEach((b, i) => { b.o.spotNr = i; });
  editor.canvas.requestRenderAll();
}
export function spotEinstellen(k, schluessel, wert) {
  k.forEach(o => { o[schluessel] = wert; });
  if (schluessel === 'spotReihe') spotOrdnenAnwenden(k);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  renderAnimBar(); renderLayers();
}
// Every element of the picture into this spotlight - the ones not framed yet.
export function spotAlle(k) {
  const liste = media.spotElemente(editor);
  if (!liste.length) { toast('No elements found in this picture - add them one by one with + Spot.', 'err'); return; }
  const drin = e => k.some(o => {
    const b = o.getBoundingRect(true, true), cx = e.x + e.w / 2, cy = e.y + e.h / 2;
    return cx >= b.left && cx <= b.left + b.width && cy >= b.top && cy <= b.top + b.height;
  });
  const gruppe = k.slice();
  liste.filter(e => !drin(e)).forEach(e => { gruppe.push(media.addSpot(editor, e, gruppe)); });
  if (media.spotWert(k[0], 'spotReihe') === 'klick') gruppe.forEach(o => { o.spotReihe = 'links'; });
  spotOrdnenAnwenden(gruppe);
  editor.canvas.setActiveObject(gruppe[0]);
  editor.snapshot(); renderLayers(); renderAnimBar();
  toast(gruppe.length + ' spots - one after another, round the circle.');
}


function fxWortfeld() {
  const eigen = document.getElementById('fx-text-input');
  if (eigen && eigen.value.trim()) return eigen;
  const alt = document.getElementById('text-input');
  if (alt && alt.value.trim()) return alt;
  return eigen || alt;
}

export function addMarker() {
  const inp = fxWortfeld();
  const typed = inp?.value.trim();
  const fill = formFarbe();
  let textColor = document.getElementById('text-color')?.value || '#ffffff';
  if (hexNorm(textColor) === hexNorm(fill)) textColor = autoContrast(fill);
  const g = buildMarker(typed || '?', fill, textColor);
  g.set({ left: editor.width / 2, top: editor.height / 2 });
  g.scale(markenGroesse());
  // Blinking from the first second: that is what a marker is for.
  g.anim = { type: 'pulse', dur: 1400 };
  media.setStart(g, 0);
  editor.canvas.add(g);
  editor.canvas.setActiveObject(g);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  if (inp) inp.value = '';
  if (!typed) startBadgeEdit(g);
  renderLayers(); renderAnimBar();
  return g;
}

/* ---- Stamp: your word, pressed on -------------------------------------
   No wooden stamp comes down: the imprint simply appears and stays, which is
   what keeps the text underneath readable. Appearing is the Fade in motion. */
function buildStempel(txt, farbe) {
  const wort = String(txt || 'Approved').toUpperCase();
  const fs = 30;
  const label = new fabric.Text(wort, {
    fontSize: fs, fontWeight: 'bold', fontFamily: 'Roboto, Arial, sans-serif',
    fill: farbe, originX: 'center', originY: 'center', left: 0, top: 0,
    charSpacing: 40,
  });
  const w = Math.max(150, label.width + fs * 0.9);
  const h = fs * 1.9;
  const rahmen = new fabric.Rect({
    width: w, height: h, rx: fs * 0.22, ry: fs * 0.22,
    fill: '', stroke: farbe, strokeWidth: Math.max(2, fs * 0.09),
    originX: 'center', originY: 'center', left: 0, top: 0,
  });
  const innen = new fabric.Rect({
    width: w - fs * 0.26, height: h - fs * 0.26, rx: fs * 0.16, ry: fs * 0.16,
    fill: '', stroke: farbe, strokeWidth: Math.max(1, fs * 0.035), opacity: 0.8,
    originX: 'center', originY: 'center', left: 0, top: 0,
  });
  return new fabric.Group([rahmen, innen, label], {
    originX: 'center', originY: 'center', shapeKind: 'stamp', angle: -12,
  });
}

function isStempel(o) { return !!(o && o.shapeKind === 'stamp'); }

export function addStempel() {
  const inp = fxWortfeld();
  const typed = inp?.value.trim();
  const farbe = formFarbe();
  const g = buildStempel(typed || 'Approved', farbe);
  g.set({ left: editor.width / 2, top: editor.height * 0.62 });
  g.scale(markenGroesse());
  g.anim = { type: 'fadeIn', dur: 400 };
  media.setStart(g, 600);
  editor.canvas.add(g);
  editor.canvas.setActiveObject(g);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  if (inp) inp.value = '';
  if (!typed) startBadgeEdit(g);
  renderLayers(); renderAnimBar();
  return g;
}

// ---- Writing text straight in the badge (double-click, or right after creating it) ----
export function isBadge(o) { return !!(o && typeof o.shapeKind === 'string' && o.shapeKind.startsWith('badge-')); }

function rebuildBadge(g, txt) {
  const old = g._objects || [];
  const c = g.getCenterPoint();
  let ng;
  if (isMarker(g)) {
    ng = buildMarker(txt, old[1]?.fill || formFarbe(), old[3]?.fill || '#ffffff');
  } else if (isStempel(g)) {
    ng = buildStempel(txt, old[0]?.stroke || formFarbe());
  } else {
    const kind = g.shapeKind.replace('badge-', '');
    const fill = old[0]?.fill || formFarbe();
    const textColor = old[1]?.fill || '#ffffff';
    ng = buildBadge(kind, txt, fill, textColor);
  }
  ng.set({ ...zustandVon(g), left: c.x, top: c.y });
  const idx = editor.canvas.getObjects().indexOf(g);
  editor.canvas.remove(g);
  editor.canvas.add(ng);
  if (idx >= 0) ng.moveTo(idx);
  editor.canvas.setActiveObject(ng);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  return ng;
}

function startBadgeEdit(g) {
  if (!isBadge(g) && !isMarker(g) && !isStempel(g)) return;
  wegDamit(document.getElementById('badge-edit'));
  const cur = g._objects?.[1]?.text || '';
  const cEl = editor.canvas.upperCanvasEl;
  const r = cEl.getBoundingClientRect();
  const k = r.width / editor.canvas.getWidth();
  const p = g.getCenterPoint();
  const vt = editor.canvas.viewportTransform || [1, 0, 0, 1, 0, 0];
  const zoom = editor.canvas.getZoom();
  const x = r.left + (p.x * zoom + vt[4]) * k;
  const y = r.top + (p.y * zoom + vt[5]) * k;

  const inp = document.createElement('input');
  inp.id = 'badge-edit';
  inp.type = 'text';
  inp.value = cur;
  inp.style.cssText = `position:fixed;left:${x}px;top:${y}px;transform:translate(-50%,-50%);
    z-index:9999;min-width:120px;max-width:60vw;text-align:center;font-weight:700;font-size:15px;
    padding:6px 10px;border:2px solid #F56E28;border-radius:8px;background:#fff;color:#222;
    box-shadow:0 4px 14px rgba(0,0,0,.25);outline:none;`;
  document.body.appendChild(inp);
  inp.focus(); inp.select();
  status('Type text, Enter = done (Esc = cancel).');

  let done = false;
  const finish = save => {
    if (done) return; done = true;
    const v = inp.value.trim();
    wegDamit(inp);
    if (save && v && v !== cur) rebuildBadge(g, v);
    status('Ready.');
  };
  inp.onkeydown = e => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  };
  inp.onblur = () => finish(true);
}

// Rigid SVG text -> an editable text field, only once it is really to be changed.
// Every measurement is taken over 1:1, so nothing shifts or collapses.
function textZuIText(o) {
  const t = new fabric.IText(o.text || '', {
    left: o.left, top: o.top,
    originX: o.originX, originY: o.originY,
    scaleX: o.scaleX, scaleY: o.scaleY, angle: o.angle,
    fontSize: o.fontSize, fontFamily: o.fontFamily,
    fontWeight: o.fontWeight, fontStyle: o.fontStyle,
    fill: o.fill, textAlign: o.textAlign,
    charSpacing: o.charSpacing || 0,
    lineHeight: o.lineHeight || 1.16,
    shapeKind: o.shapeKind, svgPart: o.svgPart,
    editable: true,
  });
  const idx = editor.canvas.getObjects().indexOf(o);
  editor.canvas.remove(o);
  editor.canvas.add(t);
  if (idx >= 0) t.moveTo(idx);
  editor.canvas.setActiveObject(t);
  t.enterEditing();
  t.selectAll();
  editor.canvas.requestRenderAll();
  return t;
}


/* ---- Size of the marks ---------------------------------------------------
   One slider for marker, stamp and badges: it sizes the selected one, and the
   next one that is added. Dragging the corners still works as before - the
   slider just follows along when a mark is selected. */
export function istMarke(o) { return isMarker(o) || isStempel(o) || isBadge(o) || media.istFrageKnoten(o); }
// Around the centre: scaling from the top-left corner walks a mark off the
// word it was placed over.
export function groesseSetzen(o, s) {
  const mitte = o.getCenterPoint();
  o.scale(s);
  o.setPositionByOrigin(mitte, 'center', 'center');
  o.setCoords();
}
export function markenGroesse() {
  const v = +document.getElementById('fx-mark-size')?.value;
  return v > 0 ? v / 100 : 1;
}

/* ---- Hexagon pattern ------------------------------------------------------
   Hexagon outlines as in the Octotrial templates: "Corners" lays a loose
   cluster into two (or four) corners, "Stamp" sets one per click. Each is a
   plain element (fabric.Polygon, hexDeko: true) right at the back, so it can
   be dragged, sized, deleted and animated like any other. The settings in
   Build → Hexagon pattern apply to the next ones and to the selected ones.
   Colour "auto" is the ground a touch lighter (darker on a light ground) -
   the template's lines are #0a949a on #008591. */
export const istHex = o => !!(o && o.hexDeko);
const _hexWahl = { ecken: 'tr-bl', kipp: 'zufall', linie: 2.5, fuell: 'nein', farbe: 'auto' };
let _hexStempel = null;   // pick mode: { cursor }

function hexEinstellung() {
  const zahl = (id, std) => { const v = +document.getElementById(id)?.value; return v > 0 ? v : std; };
  return { ..._hexWahl, groesse: zahl('hex-groesse', 60), deck: zahl('hex-deck', 100) };
}
// Radius in picture pixels: the slider is the same on every canvas size.
const hexRadius = (groesse, faktor = 1) => groesse * 1.8 * faktor * Math.min(editor.width, editor.height) / 1080;

// The colour of the ground at (x, y): the background image if there is one,
// otherwise the background colour.
let _grundBild = null;   // { quelle, w, h, ctx }
function grundBei(x, y) {
  const cv = editor.canvas, W = editor.width, H = editor.height;
  const bild = cv.backgroundImage;
  if (bild && bild.render) {
    if (!_grundBild || _grundBild.quelle !== bild || _grundBild.w !== W || _grundBild.h !== H) {
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      if (typeof cv.backgroundColor === 'string' && cv.backgroundColor) { ctx.fillStyle = cv.backgroundColor; ctx.fillRect(0, 0, W, H); }
      try { bild.render(ctx); } catch (e) { /* not drawable - the colour stays */ }
      _grundBild = { quelle: bild, w: W, h: H, ctx };
    }
    try {
      const d = _grundBild.ctx.getImageData(Math.min(W - 1, Math.max(0, Math.round(x))), Math.min(H - 1, Math.max(0, Math.round(y))), 1, 1).data;
      if (d[3] > 20) return [d[0], d[1], d[2]];
    } catch (e) { /* tainted - fall through to the colour */ }
  }
  const f = typeof cv.backgroundColor === 'string' && cv.backgroundColor ? cv.backgroundColor : '#ffffff';
  const m = /^#?([0-9a-f]{6})$/i.exec(hexNorm(f));
  if (!m) return [255, 255, 255];
  const n = parseInt(m[1], 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}
function autoFarbe(x, y) {
  const [r, g, b] = grundBei(x, y);
  const hell = (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6;
  const k = hell ? -0.08 : 0.06;           // on cream a shade darker, on teal a shade lighter
  const f = v => Math.round(k > 0 ? v + (255 - v) * k : v * (1 + k));
  return '#' + [r, g, b].map(v => f(v).toString(16).padStart(2, '0')).join('');
}

function hexAussehen(o, e) {
  const farbe = e.farbe === 'auto' ? autoFarbe(o.left, o.top) : e.farbe;
  const s = Math.min(editor.width, editor.height) / 1080;
  const voll = e.fuell === 'ja';
  o.set({ fill: voll ? farbe : '', stroke: voll ? '' : farbe, strokeWidth: voll ? 0 : e.linie * 2 * s,
          opacity: e.deck / 100 });
  o.hexAuto = e.farbe === 'auto';
  o.hexFuell = e.fuell;
  o.hexLinie = e.linie;
}

function neuesHex(x, y, e, faktor = 1) {
  const r = hexRadius(e.groesse, faktor);
  const o = new fabric.Polygon(hexPoints(r), {
    left: x, top: y, originX: 'center', originY: 'center',
    angle: e.kipp === 'zufall' ? (Math.random() - 0.5) * 28 : 0,
    strokeUniform: true, strokeLineJoin: 'round',
    shapeKind: 'hexdeko', hexDeko: true, hexR: r,
  });
  hexAussehen(o, e);
  return o;
}
// Right at the back - behind text, images and every other shape.
function nachHinten(liste) {
  liste.slice().reverse().forEach(o => editor.canvas.sendToBack(o));
}

export function hexEcken() {
  const e = hexEinstellung();
  const W = editor.width, H = editor.height;
  editor.canvas.getObjects().filter(o => o.hexEcke).forEach(o => editor.canvas.remove(o));
  const plaetze = { 'tr-bl': ['tr', 'bl'], 'tl-br': ['tl', 'br'], alle: ['tr', 'bl', 'tl', 'br'] }[e.ecken] || ['tr', 'bl'];
  const z = (a, b) => a + Math.random() * (b - a);
  // As in the template: a big one half beyond the edge, a middle one beside
  // it, a small one further out - with a little play every time.
  const muster = [[0.07, 0.13, 0.15], [0.26, 0.10, 0.075], [0.40, 0.035, 0.035]];
  const k = e.groesse / 60, M = Math.min(W, H);
  const neu = [];
  plaetze.forEach(p => {
    const rechts = p.includes('r'), unten = p.includes('b');
    muster.forEach(([mx, my, mr]) => {
      const [ax, ay] = unten ? [my, mx] : [mx, my];      // at the bottom the cluster runs up the side
      const x = (rechts ? W - ax * M * k : ax * M * k) + z(-0.02, 0.02) * M;
      const y = (unten ? H - ay * M * k : ay * M * k) + z(-0.02, 0.02) * M;
      const o = neuesHex(x, y, e, mr * 10 * z(0.9, 1.1));   // radius = mr x the shorter side at size 60
      o.hexEcke = true;
      editor.canvas.add(o);
      neu.push(o);
    });
  });
  nachHinten(neu);
  editor.canvas.discardActiveObject();
  editor.canvas.requestRenderAll();
  editor.snapshot();
  renderLayers(); renderAnimBar();
  status('⬡ ' + neu.length + ' hexagons in the corners – click again for another arrangement.', '#198754');
  return neu;
}

export function hexAlleWeg() {
  const weg = editor.canvas.getObjects().filter(istHex);
  if (!weg.length) { toast('No hexagons on the picture.'); return 0; }
  weg.forEach(o => editor.canvas.remove(o));
  editor.canvas.discardActiveObject();
  editor.canvas.requestRenderAll();
  editor.snapshot();
  renderLayers(); renderAnimBar();
  status(weg.length + ' hexagon(s) removed.', '#198754');
  return weg.length;
}

// Auto-coloured hexagons follow a new ground colour or background image.
export function hexFarbenNachziehen() {
  _grundBild = null;
  let n = 0;
  editor.canvas.getObjects().filter(o => istHex(o) && o.hexAuto).forEach(o => {
    const f = autoFarbe(o.left, o.top);
    o.set(o.hexFuell === 'ja' ? { fill: f } : { stroke: f });
    n++;
  });
  if (n) editor.canvas.requestRenderAll();
  return n;
}

// ---- Stamp: every click sets one ------------------------------------------
export function hexStempel(an = !_hexStempel) {
  const cv = editor.canvas;
  const knopf = document.getElementById('hex-stempel-btn');
  if (an && !_hexStempel) {
    _hexStempel = { cursor: [cv.defaultCursor, cv.hoverCursor] };
    cv.discardActiveObject();
    cv.skipTargetFind = true; cv.selection = false;
    cv.defaultCursor = 'crosshair'; cv.hoverCursor = 'crosshair';
    knopf?.classList.add('on');
    status('🖈 Stamp: click on the picture. Shift+click bigger, Alt+click removes one, Esc ends.');
  } else if (!an && _hexStempel) {
    [cv.defaultCursor, cv.hoverCursor] = _hexStempel.cursor;
    _hexStempel = null;
    cv.skipTargetFind = false; cv.selection = true;
    cv.clearContext(cv.contextTop);
    knopf?.classList.remove('on');
    status('Stamp ended.');
  }
  cv.requestRenderAll();
  return !!_hexStempel;
}
// The next hexagon, dashed, where the pointer is (on the top layer only).
function hexGeist(p, groesser) {
  const cv = editor.canvas, ctx = cv.contextTop;
  cv.clearContext(ctx);
  if (!p) return;
  const v = cv.viewportTransform, rs = cv.getRetinaScaling ? cv.getRetinaScaling() : 1;
  const r = hexRadius(hexEinstellung().groesse, groesser ? 1.6 : 1);
  ctx.save();
  ctx.setTransform(v[0] * rs, v[1] * rs, v[2] * rs, v[3] * rs, v[4] * rs, v[5] * rs);
  ctx.beginPath();
  hexPoints(r).forEach((q, i) => (i ? ctx.lineTo(p.x + q.x, p.y + q.y) : ctx.moveTo(p.x + q.x, p.y + q.y)));
  ctx.closePath();
  ctx.setLineDash([8 / (cv.getZoom() || 1), 6 / (cv.getZoom() || 1)]);
  ctx.lineWidth = 2 / (cv.getZoom() || 1);
  ctx.strokeStyle = 'rgba(255,255,255,0.85)'; ctx.stroke();
  ctx.strokeStyle = 'rgba(0,0,0,0.35)'; ctx.lineDashOffset = 7 / (cv.getZoom() || 1); ctx.stroke();
  ctx.restore();
}
function hexStempelKlick(e) {
  const p = editor.canvas.getPointer(e.e);
  if (e.e.altKey) {
    const treffer = editor.canvas.getObjects().filter(istHex).reverse()
      .find(o => Math.hypot(o.left - p.x, o.top - p.y) < (o.hexR || 50) * (o.scaleX || 1));
    if (!treffer) { status('No hexagon under the pointer.'); return; }
    editor.canvas.remove(treffer);
  } else {
    const o = neuesHex(p.x, p.y, hexEinstellung(), e.e.shiftKey ? 1.6 : 1);
    editor.canvas.add(o);
    nachHinten([o]);
  }
  editor.canvas.requestRenderAll();
  editor.snapshot();
  renderLayers(); renderAnimBar();
  status('🖈 ' + editor.canvas.getObjects().filter(istHex).length + ' hexagon(s) – keep clicking, Esc ends.');
}

// The settings change the selected hexagons too.
function ausgewaehlteHexe() { return editor.activeAll().filter(istHex); }
function aufAuswahl(fn) {
  const hexe = ausgewaehlteHexe();
  if (!hexe.length) return false;
  hexe.forEach(fn);
  editor.canvas.requestRenderAll();
  return true;
}
function hexBedienung() {
  const e = () => hexEinstellung();
  const aus = (id, text) => { const r = document.getElementById(id), o = document.getElementById(id + '-out');
                               if (r && o) o.textContent = text(+r.value); };
  const zeigen = () => {
    aus('hex-groesse', v => Math.round(hexRadius(v) * 2) + ' px');
    aus('hex-deck', v => v + ' %');
  };
  zeigen();
  const groesse = document.getElementById('hex-groesse');
  if (groesse) {
    groesse.oninput = () => {
      zeigen();
      aufAuswahl(o => {
        const mitte = o.getCenterPoint();
        o.scale(hexRadius(e().groesse) / (o.hexR || 1));
        o.setPositionByOrigin(mitte, 'center', 'center');
        o.setCoords();
      });
    };
    groesse.onchange = () => { if (ausgewaehlteHexe().length) editor.snapshot(); };
  }
  const deck = document.getElementById('hex-deck');
  if (deck) {
    deck.oninput = () => { zeigen(); aufAuswahl(o => o.set('opacity', e().deck / 100)); };
    deck.onchange = () => { if (ausgewaehlteHexe().length) editor.snapshot(); };
  }
  const segment = (id, key, zahl, anwenden) => {
    const s = document.getElementById(id);
    if (!s) return;
    s.addEventListener('click', ev => {
      const b = ev.target.closest('button[data-v]');
      if (!b) return;
      s.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      _hexWahl[key] = zahl ? +b.dataset.v : b.dataset.v;
      if (anwenden && aufAuswahl(o => hexAussehen(o, { ...e(), farbe: o.hexAuto ? 'auto' : (o.stroke || o.fill), [key]: _hexWahl[key] }))) editor.snapshot();
    });
  };
  segment('hex-ecken-art', 'ecken');
  segment('hex-kipp', 'kipp');
  segment('hex-linie', 'linie', true, true);
  segment('hex-fuell', 'fuell', false, true);
  hexFarbenBauen();
  // Selecting a hexagon shows its settings.
  const folgen = () => {
    const o = ausgewaehlteHexe()[0];
    if (!o) return;
    if (groesse && o.hexR) { groesse.value = Math.round(o.hexR * (o.scaleX || 1) / hexRadius(1)); }
    if (deck) deck.value = Math.round((o.opacity ?? 1) * 100);
    zeigen();
  };
  editor.canvas.on('selection:created', folgen);
  editor.canvas.on('selection:updated', folgen);
}
// auto + the brand colours. Rebuilt when the palette may have changed.
export function hexFarbenBauen() {
  const box = document.getElementById('hex-farben');
  if (!box) return;
  box.innerHTML = '';
  const knopf = (wert, farbe) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'fx-swatch' + (wert === 'auto' ? ' fx-swatch-auto' : '') + (_hexWahl.farbe === wert ? ' on' : '');
    if (wert === 'auto') { b.textContent = 'auto'; b.title = 'A touch lighter than the ground'; }
    else { b.style.background = farbe; b.title = farbe; }
    b.dataset.v = wert;
    b.onclick = () => {
      _hexWahl.farbe = wert;
      box.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      if (aufAuswahl(o => hexAussehen(o, { ...hexEinstellung(), fuell: o.hexFuell || 'nein', linie: o.hexLinie || 2.5 }))) editor.snapshot();
    };
    box.appendChild(b);
  };
  knopf('auto');
  bg.getPalette().forEach(f => knopf(f, f));
}

export function initElemente(ed, { farbe }) {
  editor = ed;
  if (farbe) formFarbe = farbe;
  // Hexagon pattern: the stamp's clicks and pointer, Esc, and the panel.
  editor.canvas.on('mouse:down', e => { if (_hexStempel) hexStempelKlick(e); });
  editor.canvas.on('mouse:move', e => { if (_hexStempel) hexGeist(editor.canvas.getPointer(e.e), e.e.shiftKey); });
  editor.canvas.on('mouse:out', () => { if (_hexStempel) hexGeist(null); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && _hexStempel) { e.preventDefault(); hexStempel(false); }
  });
  hexBedienung();
  {
    const btn = document.getElementById('svg-import-btn');
    const inp = document.getElementById('svg-file-input');
    if (btn && inp) {
      btn.onclick = e => { e.preventDefault(); inp.value = ''; inp.click(); };
      inp.onchange = async () => {
        const f = inp.files?.[0];
        if (!f) return;
        status('Reading SVG…');
        try {
          const text = await f.text();
          const asGroup = !!document.getElementById('svg-as-group')?.checked;
          const n = await importSvgText(text, asGroup);
          if (n) status(asGroup ? 'SVG inserted as 1 object.' : `SVG inserted: ${n} layer(s).`, '#198754');
        } catch (err) {
          console.error(err);
          status('SVG could not be read: ' + err.message, '#dc3545');
        }
      };
    }
  }

  editor.nachDuplikat((quellen, kopien) => {
    const neu = new Set(kopien);
    GRUPPEN_ARTEN.forEach(art => {
      const jeGruppe = new Map();
      kopien.forEach((c, i) => {
        if (!art.ist(c)) return;
        const id = c[art.id] || art.vorsilbe;
        if (!jeGruppe.has(id)) jeGruppe.set(id, []);
        jeGruppe.get(id).push(c);
      });
      const gruppen = art.gruppen();
      jeGruppe.forEach((cs, id) => {
        const alte = (gruppen.get(id) || []).filter(o => !neu.has(o));
        cs.sort((a, b) => (a[art.nr] || 0) - (b[art.nr] || 0));
        if (cs.length >= alte.length) {
          const neueId = art.vorsilbe + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
          cs.forEach((c, j) => { c[art.id] = neueId; c[art.nr] = j; });
        } else {
          cs.forEach((c, j) => { c[art.nr] = alte.length + j; });
        }
      });
      jeGruppe.forEach(cs => art.ordnen(art.gruppen().get(cs[0][art.id]) || cs));
    });
  });

  editor.nachLoeschen(weg => {
    GRUPPEN_ARTEN.forEach(art => {
      const ids = new Set(weg.filter(art.ist).map(o => o[art.id] || art.vorsilbe));
      if (!ids.size) return;
      const gruppen = art.gruppen();
      ids.forEach(id => {
        const rest = gruppen.get(id);
        if (!rest) return;
        rest.forEach((o, j) => { o[art.nr] = j; });
        art.ordnen(rest);
      });
    });
  });

  editor.canvas.on('mouse:down', e => {
    if (!_spotWahl) return;
    const { gruppe } = _spotWahl;
    spotWahlEnde();
    const p = editor.canvas.getPointer(e.e);
    let box = media.spotElementBei(_spotListe, p.x, p.y);
    if (!box) {
      const w = Math.round(editor.width * 0.22), h = Math.round(editor.height * 0.16);
      box = { x: p.x - w / 2, y: p.y - h / 2, w, h };
      toast('No element found here - the frame sits where you clicked; drag its corners to fit.');
    }
    spotSetzen(box, gruppe);
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && _spotWahl) { spotWahlEnde(); editor.canvas.requestRenderAll(); toast('Spotlight: cancelled.'); }
  });

  editor.canvas.on('mouse:dblclick', e => {
    const o = e.target;
    if (isBadge(o) || isMarker(o) || isStempel(o)) startBadgeEdit(o);
    else if (isChecklist(o)) startChecklistEdit(o);
    else if (isTextblock(o)) startTextblockEdit(o);
    else if (o && o.type === 'text') { textZuIText(o); status('Edit text, then click beside it.'); }
  });
}
