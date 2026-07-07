// studio.js – Einstiegspunkt. Verdrahtet DOM ↔ Module.
import { CONFIG } from './config.js';
import { Editor } from './editor.js';
import { toast, status, modal } from './util.js';
import * as bg from './background.js';
import * as io from './io.js';
import { initLibrary } from './library.js';
import * as media from './media.js';
import { hasTransparency, removeBackground } from './cutout.js';

const canvasEl = document.getElementById('main-canvas');
const editor = new Editor(canvasEl);
window._studioEditor = editor;   // für Debugging in der Konsole

// ---- Canvas in den festen Rahmen einpassen -------------------------------
function fit() {
  const host = document.querySelector('.canvas-host');
  if (!host) return;
  const w = host.clientWidth - 16;
  const h = host.clientHeight - 16;
  editor._lastFit = { w, h };   // merken, damit setSize wieder einpasst
  editor.fitTo(w, h);
}
window.addEventListener('resize', fit);
// nach dem ersten Layout einpassen (clientHeight steht erst dann korrekt)
requestAnimationFrame(fit);

// ---- Sidebar-Sektionen ein-/ausklappen -----------------------------------
document.querySelectorAll('.sidebar-section h3').forEach(h =>
  h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed')));

// ---- Farbpaletten ---------------------------------------------------------
let currentTextColor = document.getElementById('text-color')?.value || '#ffffff';
let currentShapeColor = '#F56E28';

bg.renderPalette(document.getElementById('palette-row'), col => {
  currentTextColor = col;
  const picker = document.getElementById('text-color'); if (picker) picker.value = col;
  const o = editor.active();
  if (o && o.type === 'textbox') { o.set('fill', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
});
bg.renderPalette(document.getElementById('shape-palette-row'), col => {
  currentShapeColor = col;
  const o = editor.active();
  if (o && o.shapeKind) { o.set(o.fill ? 'fill' : 'stroke', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
});

// ---- Toolbar-Aktionen (data-act) -----------------------------------------
const actions = {
  save:        () => io.saveImage(editor),
  download:    () => io.downloadImage(editor),
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
  'export-gif':   () => media.exportGif(editor),
  'export-video': () => media.exportVideo(editor),
  // Element-Kontextaktionen
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
  cutout:      () => doCutout(),
  // Post-Banner
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

// ---- Freistellen ----------------------------------------------------------
async function doCutout() {
  const o = editor.active();
  if (!o || o.type !== 'image') { toast('Erst ein Bild wählen', 'err'); return; }
  status('✂ Stelle frei…');
  try {
    const cleaned = await removeBackground(o._element);
    o.setElement(cleaned);
    o.bgRemoved = true;
    editor.canvas.requestRenderAll();
    editor.snapshot();
    status('✅ Freigestellt', 'green');
  } catch (e) {
    status('❌ Freistellen fehlgeschlagen', 'red');
    toast(e.message || 'Fehler beim Freistellen', 'err');
  }
}

// ---- Kontextleiste bei Auswahl -------------------------------------------
function renderSelBar() {
  const bar = document.getElementById('sel-bar');
  const objs = editor.activeAll();
  if (!objs.length) {
    bar.innerHTML = '<span class="hint">Kein Element ausgewählt · Bild hierher ziehen oder aus der Bibliothek wählen</span>';
    return;
  }
  const isImg = objs.length === 1 && objs[0].type === 'image';
  bar.innerHTML = `
    <button class="tbtn" data-act="duplicate" title="Duplizieren (Strg+D)">📋</button>
    <button class="tbtn" data-act="flip-h" title="Horizontal spiegeln">↔</button>
    <button class="tbtn" data-act="flip-v" title="Vertikal spiegeln">↕</button>
    <button class="tbtn" data-act="forward" title="Nach vorne">⬆</button>
    <button class="tbtn" data-act="backward" title="Nach hinten">⬇</button>
    <span style="width:8px"></span>
    <button class="tbtn" data-act="align-left" title="Links">⬅</button>
    <button class="tbtn" data-act="align-centerH" title="Horizontal zentrieren">↔|</button>
    <button class="tbtn" data-act="align-right" title="Rechts">➡</button>
    <button class="tbtn" data-act="align-top" title="Oben">⬆|</button>
    <button class="tbtn" data-act="align-centerV" title="Vertikal zentrieren">↕|</button>
    <button class="tbtn" data-act="align-bottom" title="Unten">⬇|</button>
    ${isImg ? '<span style="width:8px"></span><button class="tbtn" data-act="cutout" title="Hintergrund entfernen">✂ Freistellen</button>' : ''}
    <span style="width:8px"></span>
    <button class="tbtn danger" data-act="delete" title="Löschen (Entf)">🗑</button>
  `;
}

// ---- Animations-Panel -----------------------------------------------------
function renderAnimPanel() {
  const panel = document.getElementById('anim-panel');
  const o = editor.active();
  if (!o) { panel.innerHTML = '<p class="no-templates">Wähle ein Element, um es zu animieren.</p>'; return; }
  const cur = o.anim?.type || 'none';
  panel.innerHTML = `
    <label class="tl-row">Effekt:
      <select id="anim-type" class="field" style="flex:1">
        ${media.ANIM_TYPES.map(t => `<option value="${t}" ${t === cur ? 'selected' : ''}>${t}</option>`).join('')}
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

// ---- Selektion-Events koppeln --------------------------------------------
['selection:created', 'selection:updated', 'selection:cleared'].forEach(ev =>
  editor.canvas.on(ev, () => { renderSelBar(); renderAnimPanel(); }));

// ---- Undo/Redo-Buttons aktiv/inaktiv --------------------------------------
editor.onChange(() => {
  document.querySelector('[data-act="undo"]').disabled = !editor.canUndo();
  document.querySelector('[data-act="redo"]').disabled = !editor.canRedo();
  bg.updateBgInfo(editor);
});

// ---- Bild einfügen → ggf. Freistell-Dialog --------------------------------
async function offerCutout(imgObj) {
  if (hasTransparency(imgObj._element)) { imgObj.bgRemoved = true; return; }
  const choice = await modal('Bild-Optionen', 'Was möchtest du mit diesem Bild tun?', [
    { label: '📌 So lassen', value: 'keep' },
    { label: '✂ Hintergrund entfernen', value: 'cut' },
  ]);
  if (choice === 'cut') {
    editor.canvas.setActiveObject(imgObj);
    doCutout();
  }
}
// addImageUrl-Hook: nach dem Einfügen Dialog anbieten
const _origAdd = editor.addImageUrl.bind(editor);
editor.addImageUrl = async (url, opts) => {
  const img = await _origAdd(url, opts);
  if (!opts?.silent) offerCutout(img);
  return img;
};

// ---- Init: Templates, Bibliothek, evtl. gespeicherten Canvas laden --------
bg.loadTemplateList(editor);
initLibrary(editor);
renderSelBar();

(function restoreInitial() {
  const post = CONFIG.postData, lib = CONFIG.libData;
  if (post?.canvas_json) { io.restoreCanvas(editor, post.canvas_json); return; }
  if (lib?.canvas_json)  { io.restoreCanvas(editor, lib.canvas_json); return; }
  if (lib?.image_url)    { editor.addImageUrl(lib.image_url, { silent: true }); }
})();

status('Bereit.', '#888');
