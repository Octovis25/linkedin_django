// studio.js – Einstiegspunkt. Verdrahtet DOM ↔ Module.
import { CONFIG } from './config.js';
import { Editor, fabric } from './editor.js';
import { toast, status, modal } from './util.js';
import * as bg from './background.js';
import * as io from './io.js';
import { initLibrary, refreshOutput } from './library.js';
import * as media from './media.js';
import { removeBackground, floodFillTransparent, recolorRegion, recolorSimilarAll, removeColorGlobal, hasCheckerboardBorder, removeCheckerboard } from './cutout.js';
import * as retouch from './retouch.js';

const canvasEl = document.getElementById('main-canvas');
const editor = new Editor(canvasEl);
window._studioEditor = editor;   // für Debugging in der Konsole

// ---- Canvas in den festen Rahmen einpassen -------------------------------
function fit() {
  const host = document.querySelector('.canvas-host');
  if (!host) return;
  const w = host.clientWidth - 16;
  const h = host.clientHeight - 16;
  editor._lastFit = { w, h };
  editor.fitTo(w, h);
}
window.addEventListener('resize', fit);
requestAnimationFrame(fit);

// ---- Sidebar-Sektionen ein-/ausklappen (Freistellen-Panel bleibt offen) ---
document.querySelectorAll('.sidebar-section h3').forEach(h => {
  if (h.parentElement.id === 'retouch-section') return;   // immer aufgeklappt
  h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
});

// ---- Farbpaletten ---------------------------------------------------------
let currentTextColor = document.getElementById('text-color')?.value || '#ffffff';
let currentShapeColor = '#F56E28';

// Eine gemeinsame Palette für Text UND Formen.
bg.renderPalette(document.getElementById('palette-row'), col => {
  currentTextColor = col;
  currentShapeColor = col;
  const picker = document.getElementById('text-color'); if (picker) picker.value = col;
  const rc = document.getElementById('recolor-color'); if (rc) rc.value = col;   // Umfärben nutzt dieselbe Farbe
  const o = editor.active();
  if (o && o.type === 'textbox') { o.set('fill', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
  else if (o && o.shapeKind) { o.set(o.fill ? 'fill' : 'stroke', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
});

// ---- Toolbar-Aktionen (data-act) -----------------------------------------
const actions = {
  save:        async () => { await io.saveImage(editor); refreshOutput(); },
  'save-as':   async () => {
    const titleEl = document.getElementById('title-input');
    if (!titleEl || !titleEl.value.trim()) {
      if (titleEl) { titleEl.style.border = '2px solid #dc3545'; titleEl.focus(); }
      status('⚠️ Bitte zuerst einen Titel eingeben!', '#dc3545');
      setTimeout(() => { if (titleEl) titleEl.style.border = ''; }, 2500);
      return;
    }
    const choice = await modal('Speichern als…', 'Was möchtest du speichern?', [
      { label: '🖼 Bild (PNG)', value: 'image' },
      { label: '🎞 GIF (mit Animationen)', value: 'gif' },
      { label: '🎬 Video (mit Animationen)', value: 'video' },
    ]);
    if (choice === 'image')      { await io.saveImage(editor); refreshOutput(); }
    else if (choice === 'gif')   { await media.exportGif(editor); }
    else if (choice === 'video') { await media.exportVideo(editor); }
  },
  // Vorhandene Ausgabe: nur speichern (gleiches Format, überschreibt).
  'save-existing': async () => {
    const kind = CONFIG.libData?.kind;
    if (kind === 'gif') await media.exportGif(editor);
    else if (kind === 'video') await media.exportVideo(editor);
    else { await io.saveImage(editor); refreshOutput(); }
  },
  download:    () => io.downloadImage(editor),
  'new':       async () => {
    const ok = await modal('Neu anfangen?', 'Leert den Editor (alle Elemente + Hintergrund). Nicht Gespeichertes geht verloren.', [
      { label: '🆕 Ja, neuer Editor', value: true },
      { label: 'Abbrechen', value: false },
    ]);
    if (!ok) return;
    editor.clearAll();
    const t = document.getElementById('title-input'); if (t) t.value = '';
    if (location.search) history.replaceState(null, '', '/library/studio/');
    status('Neuer, leerer Editor.', '#888');
  },
  undo:        () => editor.undo(),
  redo:        () => editor.redo(),
  'add-text':  () => {
    const inp = document.getElementById('text-input');
    editor.addText(inp.value.trim() || 'Text', {
      fontSize: +document.getElementById('font-size').value,
      fontWeight: document.getElementById('font-weight').value,
      color: currentTextColor,
    });
    inp.value = '';
  },
  'canvas-size': async () => {
    const choice = await modal('Canvas-Größe', 'Format wählen', [
      { label: '1080 × 1080 (Quadrat)', value: [1080, 1080] },
      { label: '1200 × 628 (Link)', value: [1200, 628] },
      { label: '1080 × 1350 (Portrait)', value: [1080, 1350] },
      { label: '1920 × 1080 (Video)', value: [1920, 1080] },
    ]);
    if (choice) { editor.setSize(choice[0], choice[1]); fit(); bg.updateBgInfo(editor); }
  },
  'clear-bg':  () => bg.clearBackground(editor),
  'clear-all': async () => {
    const ok = await modal('Alles löschen?', 'Entfernt alle Elemente und den Hintergrund vom Canvas.', [
      { label: '🧹 Ja, leeren', value: true },
      { label: 'Abbrechen', value: false },
    ]);
    if (ok) editor.clearAll();
  },
  'export-gif':   () => media.exportGif(editor),
  'export-video': () => media.exportVideo(editor),
  'zoom-in':    () => editor.zoom('in'),
  'zoom-out':   () => editor.zoom('out'),
  'zoom-reset': () => editor.zoom('reset'),
  duplicate:   () => editor.duplicateSelected(),
  delete:      () => editor.deleteSelected(),
  'flip-h':    () => editor.flip('h'),
  'flip-v':    () => editor.flip('v'),
  forward:     () => editor.bringForward(),
  backward:    () => editor.sendBackward(),
  'align-left':   () => editor.align('left'),
  'align-centerH':() => editor.align('centerH'),
  'align-right':  () => editor.align('right'),
  'align-top':    () => editor.align('top'),
  'align-centerV':() => editor.align('centerV'),
  'align-bottom': () => editor.align('bottom'),
  'text-left':   () => setTextAlign('left'),
  'text-center': () => setTextAlign('center'),
  'text-right':  () => setTextAlign('right'),
  cutout:      () => doCutout(),
  'checker-remove': async () => {
    const o = targetImage();
    if (!o) { toast('Kein Bild', 'err'); return; }
    status('🧩 Entferne Schachbrettmuster…');
    try {
      const out = await removeCheckerboard(o._element);
      o.bgRemoved = true; o._work = null;
      retouch.replaceElement(o, out); editor.snapshot();
      status('✅ Muster entfernt', 'green');
    } catch (e) { status('❌ Fehler', 'red'); }
  },
  'restore-post': () => { if (CONFIG.postData?.canvas_json) io.restoreCanvas(editor, CONFIG.postData.canvas_json); },
  'post-bg':      () => CONFIG.postData?.id && bg.setBackgroundImage(editor, `/library/studio/api/post-image/${CONFIG.postData.id}/`),
  'post-overlay': () => CONFIG.postData?.id && editor.addImageUrl(`/library/studio/api/post-image/${CONFIG.postData.id}/`),
};

document.addEventListener('click', e => {
  const btn = e.target.closest('[data-act]');
  if (btn && actions[btn.dataset.act]) { e.preventDefault(); actions[btn.dataset.act](); }
  const shape = e.target.closest('[data-shape]');
  if (shape) { e.preventDefault(); editor.addShape(shape.dataset.shape, currentShapeColor); }
});

// Textausrichtung des aktiven Textfelds setzen.
function setTextAlign(align) {
  const o = editor.active();
  if (!o || o.type !== 'textbox') { toast('Erst ein Textfeld wählen', 'err'); return; }
  o.set('textAlign', align);
  editor.canvas.requestRenderAll();
  editor.snapshot();
}

// ---- Freistellen ----------------------------------------------------------
async function doCutout() {
  const o = editor.active();
  if (!o || o.type !== 'image') { toast('Erst ein Bild wählen', 'err'); return; }
  status('✂ Stelle frei…');
  try {
    const cleaned = await removeBackground(o._element, { tol: 55 });
    o.bgRemoved = true; o._work = null;
    retouch.replaceElement(o, cleaned);
    editor.snapshot();
    status('✅ Freigestellt', 'green');
  } catch (e) {
    status('❌ Freistellen fehlgeschlagen', 'red');
    toast(e.message || 'Fehler beim Freistellen', 'err');
  }
}

// ==== Freistellen & Korrektur-Werkzeuge ====================================
let _tol = 50;
let _brush = 20;
let _tool = 'off';       // 'off' | 'fill' | 'recolor' | 'paint' | 'mark' | 'rect' | 'erase' | 'restore'
let _toolTarget = null;
let _painting = false;
let _suppressClear = false;

// Zielbild bestimmen: aktives Bild, sonst das oberste Bild auf dem Canvas.
function targetImage() {
  const a = editor.active();
  if (a && a.type === 'image') return a;
  const imgs = editor.realObjects().filter(x => x.type === 'image');
  return imgs.length ? imgs[imgs.length - 1] : null;
}

function setTool(tool) {
  const o = targetImage();
  if (tool !== 'off' && !o) { toast('Kein Bild vorhanden – erst ein Bild einfügen', 'err'); return; }
  // Beim Verlassen des Markier-Modus offene (nicht angewendete) Markierung verwerfen.
  if ((_tool === 'mark' || _tool === 'rect') && _toolTarget && retouch.hasMask(_toolTarget)) {
    retouch.clearMask(_toolTarget);
    retouch.commitWork(_toolTarget).then(() => editor.canvas.requestRenderAll());
  }
  if (typeof clearSelRect === 'function') clearSelRect();
  _tool = tool;
  _toolTarget = tool === 'off' ? null : o;
  const active = tool !== 'off';
  editor.canvas.defaultCursor = active ? 'crosshair' : 'default';
  // Nur ZIEH-Werkzeuge lassen den Canvas Objekte ignorieren (damit Ziehen malt
  // statt verschiebt). Klick-Werkzeuge (Radierer/Umfärben) verhalten sich normal
  // – Bild bleibt anklickbar, Auswahl + Leiste bleiben erhalten.
  const dragTool = ['mark', 'rect', 'paint', 'erase', 'restore'].includes(tool);
  editor.canvas.skipTargetFind = dragTool;
  editor.canvas.selection = !active;
  // Zieh-Werkzeuge: aktives Objekt abwählen, sonst verschiebt das Ziehen das Bild
  // statt ein Rechteck aufzuziehen. (Werkzeug bleibt an – siehe selection:cleared-Guard.)
  if (dragTool) editor.canvas.discardActiveObject();
  editor.canvas.requestRenderAll();
  const hints = {
    fill: 'In eine Fläche klicken → wird transparent (durchsichtig)',
    pick: 'Hintergrundfarbe anklicken → diese Farbe wird ÜBERALL transparent',
    swap: 'In eine Farbfläche klicken → dieser Bereich bekommt die gewählte Farbe',
    recolor: 'Bereich anklicken → wird in die gewählte Farbe umgefärbt',
    paint: 'Über das Bild malen → in gewählter Farbe (nur wo Bild ist)',
    mark: 'Fläche grob rot übermalen, dann unten „umfärben" oder „entfernen"',
    rect: 'Rechteck über die Fläche ziehen, dann unten „umfärben" oder „entfernen"',
    erase: 'Über das Bild wischen → wird transparent',
    restore: 'Über das Bild wischen → Original kommt zurück',
    off: 'Werkzeug aus',
  };
  setToolStatus(hints[tool] || '');
  const isMark = (tool === 'mark' || tool === 'rect');
  const colorRow = document.getElementById('recolor-color-row');
  if (colorRow) colorRow.style.display = (tool === 'recolor' || tool === 'paint' || tool === 'swap' || isMark) ? 'flex' : 'none';
  const markRow = document.getElementById('mark-apply-row');
  if (markRow) markRow.style.display = isMark ? 'flex' : 'none';
  // Rechteck-Zeichenebene nur beim Rechteck-Werkzeug aktiv (Style direkt gesetzt,
  // unabhängig von der CSS – cache-fest).
  const ov = document.getElementById('rect-overlay');
  if (ov) ov.style.display = (tool === 'rect') ? 'block' : 'none';
  updateRetouchPanel();
}

function setToolStatus(msg) {
  const el = document.getElementById('tool-status');
  if (el) el.textContent = msg;
}

// Klick-Koordinate → Bild-Pixel des Zielbildes (robust via Transform-Matrix).
function imgPixel(o, e) {
  const pointer = editor.canvas.getPointer(e);
  const inv = fabric.util.invertTransform(o.calcTransformMatrix());
  const p = fabric.util.transformPoint(pointer, inv);
  const el = o._element;
  const W = el.naturalWidth || el.width;
  const H = el.naturalHeight || el.height;
  return { px: p.x + W / 2, py: p.y + H / 2 };
}

async function doFillAt(o, px, py) {
  try {
    const cleaned = await floodFillTransparent(o._element, px, py, _tol);
    o.bgRemoved = true; o._work = null;
    retouch.replaceElement(o, cleaned); editor.snapshot();
  } catch (e) { setToolStatus('❌ Fehler'); }
}

async function doPickAt(o, px, py) {
  try {
    const out = await removeColorGlobal(o._element, px, py, 42);
    o.bgRemoved = true; o._work = null;
    retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('💧 Hintergrundfarbe entfernt – weiter klicken oder Werkzeug aus');
  } catch (e) { setToolStatus('❌ Fehler'); }
}

async function doSwapAt(o, px, py) {
  const hex = document.getElementById('recolor-color')?.value || '#ffffff';
  try {
    // Zusammenhängende Fläche ab dem Klickpunkt umfärben ("näheres Umfeld").
    const out = await recolorRegion(o._element, px, py, hex, 40);
    o._work = null;
    retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('🎨 Farbe getauscht – weiter klicken oder Werkzeug aus');
  } catch (e) { console.error('Farbtausch:', e); setToolStatus('❌ Fehler'); }
}

async function doRecolorAt(o, px, py) {
  const hex = document.getElementById('recolor-color')?.value || '#ffffff';
  try {
    const out = await recolorRegion(o._element, px, py, hex, _tol);
    o._work = null;
    retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('🎨 Umgefärbt – weiter klicken oder Werkzeug aus');
  } catch (e) { setToolStatus('❌ Fehler'); }
}

async function paintAt(o, px, py) {
  if (_tool === 'mark') {
    retouch.markAt(o, px, py, _brush);
    retouch.renderMaskPreview(o);
    editor.canvas.requestRenderAll();
    return;
  }
  const origImg = _tool === 'restore' ? await retouch.getOriginal(o) : null;
  const color = _tool === 'paint' ? (document.getElementById('recolor-color')?.value || '#ffffff') : null;
  retouch.brushAt(o, px, py, _brush, _tool, origImg, color);
  await retouch.commitWork(o);
  editor.canvas.requestRenderAll();
}

// Markierung anwenden (am Stück umfärben oder entfernen).
async function applyMark(mode) {
  const o = _toolTarget || targetImage();
  if (!o || o.type !== 'image') { toast('Erst markieren', 'err'); return; }
  const color = document.getElementById('recolor-color')?.value || '#ffffff';

  // Rechteck-Auswahl → direkt den Bereich bearbeiten (zuverlässig).
  if (_rectStart && _rectEnd) {
    const { px: x0, py: y0 } = _rectStart;
    const { px: x1, py: y1 } = _rectEnd;
    if (mode === 'recolor') await retouch.recolorRect(o, x0, y0, x1, y1, color);
    else await retouch.removeRect(o, x0, y0, x1, y1);
    clearSelRect();
    editor.canvas.requestRenderAll(); editor.snapshot();
    setToolStatus(mode === 'recolor' ? '🎨 Bereich umgefärbt' : '🗑 Bereich entfernt');
    return;
  }
  // Freihand-Maske
  if (!retouch.hasMask(o)) { toast('Nichts markiert – erst Rechteck ziehen oder frei markieren', 'err'); return; }
  await retouch.applyMask(o, mode, color);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  setToolStatus(mode === 'recolor' ? '🎨 Markierung umgefärbt' : '🗑 Markierung entfernt');
}

let _rectStart = null;   // Bild-Pixel Startpunkt
let _rectEnd = null;     // Bild-Pixel Endpunkt
let _selRect = null;     // (alt, ungenutzt)
let _mqStart = null;     // Marquee-Start in Overlay-Pixeln
let _mqDrawing = false;

function clearSelRect() {
  if (_selRect) { editor.canvas.remove(_selRect); _selRect = null; }
  const mq = document.getElementById('rect-marquee'); if (mq) mq.style.display = 'none';
  _mqDrawing = false;
  _rectStart = _rectEnd = null;
}

// ---- Rechteck-Auswahl über die eigene Zeichenebene (#rect-overlay) --------
(function initRectOverlay() {
  const ov = document.getElementById('rect-overlay');
  if (!ov) return;
  // Kritische Styles direkt setzen (unabhängig von evtl. gecachter CSS).
  Object.assign(ov.style, {
    position: 'absolute', left: '0', top: '0', right: '0', bottom: '0',
    zIndex: '30', cursor: 'crosshair', display: 'none',
  });
  function marquee() {
    let mq = document.getElementById('rect-marquee');
    if (!mq) {
      mq = document.createElement('div'); mq.id = 'rect-marquee';
      Object.assign(mq.style, {
        position: 'absolute', border: '2px solid #F56E28',
        background: 'rgba(245,110,40,0.22)', pointerEvents: 'none', boxSizing: 'border-box',
      });
      ov.appendChild(mq);
    }
    return mq;
  }
  function draw(mq, a, b) {
    mq.style.left = Math.min(a.x, b.x) + 'px';
    mq.style.top = Math.min(a.y, b.y) + 'px';
    mq.style.width = Math.abs(b.x - a.x) + 'px';
    mq.style.height = Math.abs(b.y - a.y) + 'px';
  }
  ov.addEventListener('pointerdown', ev => {
    if (_tool !== 'rect' || !_toolTarget) return;
    ev.preventDefault();
    try { ov.setPointerCapture(ev.pointerId); } catch (e) {}
    const r = ov.getBoundingClientRect();
    _mqStart = { x: ev.clientX - r.left, y: ev.clientY - r.top };
    _rectStart = imgPixel(_toolTarget, ev);
    _rectEnd = _rectStart;
    const mq = marquee(); mq.style.display = 'block'; draw(mq, _mqStart, _mqStart);
    _mqDrawing = true;
  });
  ov.addEventListener('pointermove', ev => {
    if (!_mqDrawing) return;
    const r = ov.getBoundingClientRect();
    draw(marquee(), _mqStart, { x: ev.clientX - r.left, y: ev.clientY - r.top });
    _rectEnd = imgPixel(_toolTarget, ev);
  });
  const finish = ev => {
    if (!_mqDrawing) return;
    _mqDrawing = false;
    _rectEnd = imgPixel(_toolTarget, ev);
    setToolStatus('✅ Bereich gewählt → „🗑 Löschen" oder „🎨 Umfärben"');
  };
  ov.addEventListener('pointerup', finish);
  ov.addEventListener('pointercancel', finish);
})();

editor.canvas.on('mouse:down', async (opt) => {
  if (_tool === 'off' || !_toolTarget) return;
  const { px, py } = imgPixel(_toolTarget, opt.e);
  if (_tool === 'fill') { await doFillAt(_toolTarget, px, py); return; }
  if (_tool === 'recolor') { await doRecolorAt(_toolTarget, px, py); return; }
  if (_tool === 'swap') { await doSwapAt(_toolTarget, px, py); return; }
  if (_tool === 'pick') { await doPickAt(_toolTarget, px, py); return; }
  if (_tool === 'rect') {
    clearSelRect();
    _rectStart = { px, py };
    const p = editor.canvas.getPointer(opt.e);
    _selRect = new fabric.Rect({
      left: p.x, top: p.y, width: 0, height: 0,
      fill: 'rgba(245,110,40,0.25)', stroke: '#F56E28', strokeWidth: 1,
      selectable: false, evented: false, excludeFromExport: true,
    });
    _selRect._snap = true;   // Hilfsobjekt: nicht in Ebenen/Export
    _selRect._scStart = { x: p.x, y: p.y };
    editor.canvas.add(_selRect); editor.canvas.bringToFront(_selRect);
    _painting = true;
    return;
  }
  _painting = true;
  await paintAt(_toolTarget, px, py);
});
editor.canvas.on('mouse:move', async (opt) => {
  if (!_painting || _tool === 'off' || !_toolTarget) return;
  const { px, py } = imgPixel(_toolTarget, opt.e);
  if (_tool === 'rect') {
    if (_selRect) {
      const p = editor.canvas.getPointer(opt.e);
      const s = _selRect._scStart;
      _selRect.set({
        left: Math.min(s.x, p.x), top: Math.min(s.y, p.y),
        width: Math.abs(p.x - s.x), height: Math.abs(p.y - s.y),
      });
      _rectEnd = { px, py };
      editor.canvas.requestRenderAll();
    }
    return;
  }
  await paintAt(_toolTarget, px, py);
});
editor.canvas.on('mouse:up', () => {
  if (_painting) { _painting = false; }
});

// Korrektur-Panel je nach Auswahl aktualisieren.
function updateRetouchPanel() {
  const isImg = !!targetImage();
  const hint = document.getElementById('retouch-hint');
  const body = document.getElementById('retouch-body');
  if (!hint || !body) return;
  // Werkzeuge IMMER anzeigen; Hinweis nur, wenn kein Bild gewählt ist.
  body.style.display = 'block';
  hint.style.display = isImg ? 'none' : 'block';
  document.querySelectorAll('#retouch-body [data-tool]').forEach(b =>
    b.classList.toggle('primary', b.dataset.tool === _tool && _tool !== 'off'));
}

document.addEventListener('click', e => {
  const tb = e.target.closest('#retouch-body [data-tool]');
  if (tb) { e.preventDefault(); setTool(tb.dataset.tool); }
  const mb = e.target.closest('#retouch-body [data-mark]');
  if (mb) { e.preventDefault(); applyMark(mb.dataset.mark); }
});
{
  const brushS = document.getElementById('brush-slider');
  if (brushS) brushS.oninput = () => { _brush = +brushS.value; document.getElementById('brush-val').textContent = _brush; };
}

// ---- Element-Leiste: IMMER sichtbar, Buttons inaktiv wenn nichts gewählt ---
function renderSelBar() {
  const bar = document.getElementById('sel-bar');
  const objs = editor.activeAll();
  const hasSel = objs.length > 0;
  const isImg = objs.length === 1 && objs[0].type === 'image';
  const d = hasSel ? '' : 'disabled';
  const dImg = isImg ? '' : 'disabled';
  const activeLabel = !hasSel ? ''
    : (objs.length > 1 ? `${objs.length} Elemente`
       : layerLabel(objs[0], editor.realObjects().indexOf(objs[0]) + 1));
  bar.innerHTML = `
    ${hasSel ? `<span class="sel-active" title="Aktives Element">${activeLabel}</span>` : ''}
    <button class="tbtn" data-act="duplicate" title="Duplizieren (Strg+D)" ${d}>📋</button>
    <button class="tbtn" data-act="flip-h" title="Horizontal spiegeln" ${d}>↔</button>
    <button class="tbtn" data-act="flip-v" title="Vertikal spiegeln" ${d}>↕</button>
    <button class="tbtn" data-act="forward" title="Nach vorne" ${d}>⬆</button>
    <button class="tbtn" data-act="backward" title="Nach hinten" ${d}>⬇</button>
    <span style="width:8px"></span>
    <button class="tbtn" data-act="align-left" title="Links" ${d}>⬅</button>
    <button class="tbtn" data-act="align-centerH" title="Horizontal zentrieren" ${d}>↔|</button>
    <button class="tbtn" data-act="align-right" title="Rechts" ${d}>➡</button>
    <button class="tbtn" data-act="align-top" title="Oben" ${d}>⬆|</button>
    <button class="tbtn" data-act="align-centerV" title="Vertikal zentrieren" ${d}>↕|</button>
    <button class="tbtn" data-act="align-bottom" title="Unten" ${d}>⬇|</button>
    <span style="width:8px"></span>
    <button class="tbtn" data-act="cutout" title="Hintergrund automatisch entfernen" ${dImg}>✂ Freistellen</button>
    <span style="width:8px"></span>
    <button class="tbtn danger" data-act="delete" title="Löschen (Entf)" ${d}>🗑</button>
    ${hasSel ? '' : '<span class="hint" style="margin-left:8px">Element wählen zum Bearbeiten</span>'}
  `;
}

// ---- Ebenen-Liste ---------------------------------------------------------
function layerLabel(o, i) {
  if (o.type === 'image')   return '🖼 Bild ' + i;
  if (o.type === 'textbox') return '✏️ ' + (o.text || 'Text').slice(0, 14);
  if (o.shapeKind)          return '🔷 Form ' + i;
  return 'Element ' + i;
}
function renderLayers() {
  const list = document.getElementById('layers-list');
  if (!list) return;
  const objs = editor.realObjects();
  if (!objs.length) { list.innerHTML = '<span class="no-templates">Noch keine Elemente.</span>'; return; }
  const active = editor.active();
  list.innerHTML = '';
  // Oben = vorderste Ebene → Reihenfolge umkehren.
  objs.slice().reverse().forEach((o, ri) => {
    const i = objs.length - ri;
    const row = document.createElement('div');
    row.className = 'layer-row' + (o === active ? ' active' : '');
    const name = document.createElement('span');
    name.className = 'layer-name';
    name.textContent = layerLabel(o, i);
    name.onclick = () => { editor.selectObj(o); };
    const up = document.createElement('button');
    up.className = 'layer-btn'; up.textContent = '⬆'; up.title = 'Nach vorne';
    up.onclick = (e) => { e.stopPropagation(); editor.moveObj(o, 'up'); renderLayers(); };
    const down = document.createElement('button');
    down.className = 'layer-btn'; down.textContent = '⬇'; down.title = 'Nach hinten';
    down.onclick = (e) => { e.stopPropagation(); editor.moveObj(o, 'down'); renderLayers(); };
    row.appendChild(name); row.appendChild(up); row.appendChild(down);
    list.appendChild(row);
  });
}

// ---- Animations-Panel -----------------------------------------------------
function renderAnimPanel() {
  const panel = document.getElementById('anim-panel');
  if (!panel) return;
  const o = editor.active();
  if (!o) { panel.innerHTML = '<p class="no-templates">Wähle ein Element, um es zu animieren.</p>'; return; }
  const cur = o.anim?.type || 'none';
  panel.innerHTML = `
    <label class="tl-row">Effekt:
      <select id="anim-type" class="field" style="flex:1">
        ${media.ANIM_TYPES.map(t => `<option value="${t}" ${t === cur ? 'selected' : ''}>${media.ANIM_LABELS[t] || t}</option>`).join('')}
      </select>
    </label>
    <div class="tl-row">Dauer <input id="anim-dur" type="range" class="tl-slider" min="300" max="4000" step="100" value="${o.anim?.dur || 1200}"><span id="anim-dur-val">${o.anim?.dur || 1200}ms</span></div>
    <div class="tl-row">Verzög. <input id="anim-delay" type="range" class="tl-slider" min="0" max="3000" step="100" value="${o.anim?.delay || 0}"><span id="anim-delay-val">${o.anim?.delay || 0}ms</span></div>
    <button class="tbtn primary" id="anim-preview" style="width:100%;margin-top:6px">▶ Vorschau</button>
  `;
  const apply = () => {
    const type = document.getElementById('anim-type').value;
    const dur = +document.getElementById('anim-dur').value;
    const delay = +document.getElementById('anim-delay').value;
    document.getElementById('anim-dur-val').textContent = dur + 'ms';
    document.getElementById('anim-delay-val').textContent = delay + 'ms';
    media.setAnim(editor, type, dur, delay);
  };
  panel.querySelector('#anim-type').onchange = apply;
  panel.querySelector('#anim-dur').oninput = apply;
  panel.querySelector('#anim-delay').oninput = apply;
  panel.querySelector('#anim-preview').onclick = () => media.previewAnimation(editor);
}

// ---- Animations-Leiste unter dem Canvas (pro Element ein Effekt) ----------
function renderAnimBar() {
  const bar = document.getElementById('anim-bar');
  if (!bar) return;
  const objs = editor.realObjects();
  if (!objs.length) { bar.innerHTML = '<span class="hint">Elemente hinzufügen, um sie zu animieren.</span>'; return; }
  bar.innerHTML = '';
  const head = document.createElement('div'); head.className = 'anim-bar-head';
  const title = document.createElement('span');
  title.className = 'anim-bar-title'; title.textContent = '🎬 Animation je Element';
  const prevTop = document.createElement('button');
  prevTop.className = 'tbtn primary'; prevTop.textContent = '▶ Vorschau';
  prevTop.onclick = () => media.previewAnimation(editor);
  head.appendChild(title); head.appendChild(prevTop);
  bar.appendChild(head);

  objs.forEach((o, idx) => {
    const row = document.createElement('div'); row.className = 'anim-row';

    // Vorschaubild des Elements
    const th = document.createElement('img'); th.className = 'anim-thumb';
    th.title = layerLabel(o, idx + 1) + ' – auswählen';
    th.onclick = () => editor.selectObj(o);
    try {
      const dim = Math.max(o.getScaledWidth?.() || o.width || 1, o.getScaledHeight?.() || o.height || 1);
      th.src = o.toDataURL({ format: 'png', multiplier: Math.min(1, 90 / Math.max(dim, 1)) });
    } catch (e) { th.style.background = '#dfe3e6'; }

    // Regler-Spalte (untereinander)
    const col = document.createElement('div'); col.className = 'anim-col';

    const selRow = document.createElement('label'); selRow.className = 'anim-ctl';
    selRow.innerHTML = '<span>Bewegung</span>';
    const sel = document.createElement('select'); sel.className = 'field';
    media.ANIM_TYPES.forEach(t => {
      const op = document.createElement('option'); op.value = t;
      op.textContent = media.ANIM_LABELS[t] || t;
      if ((o.anim?.type || 'none') === t) op.selected = true; sel.appendChild(op);
    });
    sel.onchange = () => {
      const t = sel.value;
      o.anim = (t && t !== 'none') ? { type: t, dur: o.anim?.dur || 1200, delay: o.anim?.delay || 0 } : null;
      editor.snapshot(); renderAnimPanel();
    };
    selRow.appendChild(sel);

    const fxRow = document.createElement('label'); fxRow.className = 'anim-ctl';
    fxRow.innerHTML = '<span>Effekt</span>';
    const fxsel = document.createElement('select'); fxsel.className = 'field';
    media.EFFECTS.forEach(t => {
      const op = document.createElement('option'); op.value = t;
      op.textContent = media.EFFECT_LABELS[t] || t;
      if ((o.fx || 'none') === t) op.selected = true; fxsel.appendChild(op);
    });
    fxsel.onchange = () => { const v = fxsel.value; o.fx = (v && v !== 'none') ? v : null; editor.snapshot(); };
    fxRow.appendChild(fxsel);

    // Tempo + Start (Verzögerung) nebeneinander
    const timeRow = document.createElement('div'); timeRow.className = 'anim-ctl anim-time';
    const durWrap = document.createElement('label'); durWrap.className = 'anim-time-item';
    durWrap.innerHTML = '<span>Tempo</span>';
    const dur = document.createElement('input');
    dur.type = 'range'; dur.className = 'tl-slider'; dur.min = 300; dur.max = 4000; dur.step = 100;
    dur.value = o.anim?.dur || 1200; dur.title = 'Tempo (Dauer)';
    dur.oninput = () => { if (o.anim) o.anim.dur = +dur.value; };
    dur.onchange = () => editor.snapshot();
    durWrap.appendChild(dur);

    const delWrap = document.createElement('label'); delWrap.className = 'anim-time-item';
    delWrap.innerHTML = '<span>Start</span>';
    const del = document.createElement('input');
    del.type = 'range'; del.className = 'tl-slider'; del.min = 0; del.max = 3000; del.step = 100;
    del.value = o.anim?.delay || 0; del.title = 'Start-Verzögerung: wann der Effekt einsetzt';
    del.oninput = () => { if (o.anim) o.anim.delay = +del.value; };
    del.onchange = () => editor.snapshot();
    delWrap.appendChild(del);

    timeRow.appendChild(durWrap); timeRow.appendChild(delWrap);

    col.appendChild(selRow); col.appendChild(fxRow); col.appendChild(timeRow);
    row.appendChild(th); row.appendChild(col);
    bar.appendChild(row);
  });
}

// ---- Selektion-Events koppeln --------------------------------------------
['selection:created', 'selection:updated', 'selection:cleared'].forEach(ev =>
  editor.canvas.on(ev, () => {
    if (ev === 'selection:cleared' && _tool !== 'off' && !_suppressClear
        && !['rect', 'mark', 'paint', 'erase', 'restore'].includes(_tool)) setTool('off');
    renderSelBar(); renderAnimPanel(); updateRetouchPanel(); renderLayers(); renderAnimBar();
  }));

// ---- Undo/Redo-Buttons aktiv/inaktiv --------------------------------------
editor.onChange(() => {
  const u = document.querySelector('[data-act="undo"]');
  const r = document.querySelector('[data-act="redo"]');
  if (u) u.disabled = !editor.canUndo();
  if (r) r.disabled = !editor.canRedo();
  bg.updateBgInfo(editor);
  renderLayers(); renderAnimBar();
});

// ---- Auto-Integration: eingebackenes Rautenmuster beim Einfügen entfernen --
const _origAddImg = editor.addImageUrl.bind(editor);
editor.addImageUrl = async (url, opts) => {
  const img = await _origAddImg(url, opts);
  try {
    if (!opts?.silent && img && img._element && hasCheckerboardBorder(img._element)) {
      status('✨ Muster erkannt – entferne nur das Schachbrett…');
      const cleaned = await removeCheckerboard(img._element);   // nur Muster weg, Weiß bleibt
      img.bgRemoved = true; img._work = null;
      retouch.replaceElement(img, cleaned); editor.snapshot();
      status('✅ Muster entfernt', 'green');
    }
  } catch (e) { /* still */ }
  return img;
};

// ---- Init -----------------------------------------------------------------
bg.loadTemplateList(editor);
initLibrary(editor);
renderSelBar();
updateRetouchPanel();

// Titel vorausfüllen (beim Weiterbearbeiten bleibt der Name erhalten).
{
  const t = CONFIG.libData?.title || CONFIG.postData?.title || '';
  const ti = document.getElementById('title-input');
  if (ti && t) ti.value = t;
}

// Vorhandene Ausgabe geöffnet? → Knopf „Speichern" (gleiches Format) statt „Speichern als…".
if (CONFIG.libData?.item_id || CONFIG.libData?.nc_path) {
  const b = document.querySelector('[data-act="save-as"]');
  if (b) { b.textContent = '💾 Speichern'; b.dataset.act = 'save-existing'; b.title = 'Vorhandene Ausgabe im gleichen Format überschreiben'; }
}

(function restoreInitial() {
  try {
    const post = CONFIG.postData, lib = CONFIG.libData;
    if (post?.canvas_json) { io.restoreCanvas(editor, post.canvas_json); return; }
    if (lib?.canvas_json)  { io.restoreCanvas(editor, lib.canvas_json); return; }
    if (lib?.image_url)    { editor.addImageUrl(lib.image_url, { silent: true, fill: true }); }
  } catch (e) { console.warn('restoreInitial:', e); editor._locked = false; }
})();

// Sicherstellen, dass Elemente normal anklickbar/auswählbar sind (kein Werkzeug/
// keine Zeichenebene blockiert die Auswahl nach dem Laden).
_tool = 'off';
editor.canvas.skipTargetFind = false;
editor.canvas.selection = true;
{ const ov = document.getElementById('rect-overlay'); if (ov) ov.style.display = 'none'; }
editor.canvas.getObjects().forEach(o => { if (!o._snap) { o.selectable = true; o.evented = true; } });
editor.canvas.requestRenderAll();

status('Bereit.', '#888');
