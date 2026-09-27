// studio.js – Einstiegspunkt. Verdrahtet DOM ↔ Module.
import { CONFIG } from './config.js';
import { Editor, fabric } from './editor.js';
import { toast, status, modal, wegDamit, esc, hexNorm } from './util.js';
import * as bg from './background.js';
import * as io from './io.js';
// Namespace import: if an export is missing (because the browser has an old
// library.js in its cache, say), the whole module does NOT die here.
import * as lib from './library.js';
const { initLibrary } = lib;
import * as media from './media.js';
import { removeBackground, floodFillTransparent, recolorRegion, recolorSimilarAll, removeColorGlobal, hasCheckerboardBorder, removeCheckerboard } from './cutout.js';
import * as retouch from './retouch.js';
import { buildContext } from './toolbar.js';
import { mountShell, initUi } from './ui.js';
import { initElemente, isTextblock, netzVon, istMarke, spotStarten, spotEinstellen, rebuildTextblock, netzEinstellen, markenGroesse, isChecklist, isBadge, groesseSetzen, autoContrast, spotAlle, splitChecklist, rebuildChecklist, netzAktualisieren, importSvgText, frageZeichenFuer, frageDazu, buildTextblock, buildCheckList, addTextblock, addStempel, addMarker, addFragenNetz, addBadge } from './elements.js';
import { initAnimBar, renderLayers, renderAnimBar, planeUiAufbau, layerLabel, oeffneEffekte } from './animbar.js';

// Build rail, mode panels and the media panel from the declaration in
// toolbar.js. This has to happen BEFORE anything below looks an element up by
// id — every control the rest of this file talks to is created right here.
mountShell();

// Wraps one step of the start-up. Without this, ONE error anywhere in the long
// start sequence broke everything after it - wiring up the buttons included.
// The result was a page on which simply nothing responded any more.
function boot(name, fn) {
  try { return fn(); }
  catch (e) {
    console.error('[studio] Init step “' + name + '” failed:', e);
    if (window.studioZeigeFehler) {
      window.studioZeigeFehler('Part of the Studio could not start: ' + name,
                               e.message || String(e));
    }
    return null;
  }
}

// In some browser and privacy settings, localStorage throws on mere access
// (private mode, blocked cookies, embedded page). That used to bring the whole
// page to a standstill.
const ls = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* egal */ } },
};

const canvasEl = document.getElementById('main-canvas');
if (!canvasEl) {
  // Stop here. Carrying on threw a second, confusing error out of Fabric on top
  // of the accurate message below, and killed the rest of this module with it.
  if (window.studioZeigeFehler) {
    window.studioZeigeFehler('Canvas missing.', 'The element #main-canvas is not in the page layout.', true);
  }
  throw new Error('Studio: #main-canvas is missing – nothing to attach the editor to.');
}
const editor = new Editor(canvasEl);
window._studioEditor = editor;   // für Debugging in der Konsole

// ---- Canvas in den festen Rahmen einpassen -------------------------------
function fit() {
  const host = document.querySelector('.canvas-host');
  if (!host) return;
  // Lower bound: if the host is invisible just now (clientWidth 0), negative
  // sizes would come out - the browser turns those into a billion-pixel bitmap
  // and the tab crashes.
  const w = Math.max(120, host.clientWidth - 16);
  const h = Math.max(120, host.clientHeight - 16);
  editor._lastFit = { w, h };
  editor.fitTo(w, h);
  // Fabric remembers where the canvas is. When the canvas moves (a panel opens
  // or closes, the page scrolls), clicks with the eyedropper or rectangle
  // would otherwise land beside their target.
  editor.canvas.calcOffset();
}
window.addEventListener('resize', fit);
window.addEventListener('scroll', () => editor.canvas.calcOffset(), { passive: true });
requestAnimationFrame(fit);
// Reacts even when the size changes without the window changing (a collapsed
// panel, say) - the rAF alone sometimes fired too early.
if (window.ResizeObserver) {
  const _host = document.querySelector('.canvas-host');
  if (_host) {
    // Decouple through requestAnimationFrame: fit() changes the canvas size
    // itself and would trigger the observer again straight away. The browser
    // reports that as "ResizeObserver loop completed with undelivered
    // notifications" - harmless, but it ended up in the error banner and
    // looked like a real fault.
    let geplant = false;
    new ResizeObserver(() => {
      if (geplant) return;
      geplant = true;
      requestAnimationFrame(() => { geplant = false; fit(); });
    }).observe(_host);
  }
}

// Briefly show the zoom level (x relative to the fit).
function zeigeZoom(z) {
  const f = z || editor.zoomFactor();
  status(`Zoom ${Math.round(f * 100)} %`, '#888');
}

// ---- Sidebar-Sektionen ein-/ausklappen (Freistellen-Panel bleibt offen) ---
document.querySelectorAll('.sidebar-section h3').forEach(h => {
  if (h.parentElement.id === 'retouch-section') return;   // immer aufgeklappt
  h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
});

// ---- Canvas background colour ('' = transparent) -------------------------
// ONE way to set the background colour. There used to be two colour pickers
// with the same id: one set only the colour, the other also deleted the
// background image - indistinguishable to the user, and the image vanished
// unexpectedly. Now the image stays; if it hides the colour, the Studio says so.
// verdeckt, weist das Studio darauf hin.
function setCanvasFarbe(farbe) {
  // Set the background *colour* only - do NOT touch an existing background
  // *image* (your teal template, for instance), or it disappears unexpectedly.
  // If the image hides the colour, the Studio points that out; removing it is
  // a deliberate act through "🚫 Remove background image".
  editor.canvas.backgroundColor = farbe || '';
  editor.canvas.requestRenderAll();
  editor.snapshot();
  const pick = document.getElementById('bg-color');
  if (pick && farbe) pick.value = farbe;
  if (farbe && editor.canvas.backgroundImage) {
    status(`Background: ${farbe} – still covered by the background image (Canvas → Image: “🚫 Remove” shows it)`, '#B26A00');
  } else {
    status(farbe ? `Background: ${farbe}` : 'Background transparent.', '#198754');
  }
}
{
  const pick = document.getElementById('bg-color');
  if (pick) pick.oninput = () => setCanvasFarbe(pick.value);
}

// ---- Small dialog for a freely entered canvas size -----------------------
function askSize(w0, h0) {
  return new Promise(resolve => {
    const back = document.createElement('div');
    back.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:9998;
      display:flex;align-items:center;justify-content:center;`;
    back.innerHTML = `
      <div style="background:#fff;border-radius:10px;padding:16px;width:280px;box-shadow:0 10px 40px rgba(0,0,0,.3)">
        <div style="font-weight:700;color:#0E7C86;margin-bottom:10px">Custom canvas size</div>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
          <label style="font-size:.75rem;color:#666">Width</label>
          <input type="number" id="cs-w" value="${w0}" min="50" max="6000"
                 style="width:80px;padding:5px;border:1px solid #ccc;border-radius:4px">
          <label style="font-size:.75rem;color:#666">Height</label>
          <input type="number" id="cs-h" value="${h0}" min="50" max="6000"
                 style="width:80px;padding:5px;border:1px solid #ccc;border-radius:4px">
        </div>
        <div style="display:flex;gap:6px;justify-content:flex-end">
          <button id="cs-no" class="tbtn">Cancel</button>
          <button id="cs-ok" class="tbtn primary">Apply</button>
        </div>
      </div>`;
    document.body.appendChild(back);
    const wi = back.querySelector('#cs-w'), hi = back.querySelector('#cs-h');
    wi.focus(); wi.select();
    const ende = val => { wegDamit(back); resolve(val); };
    back.querySelector('#cs-ok').onclick = () => {
      const w = Math.round(+wi.value), h = Math.round(+hi.value);
      ende(w >= 50 && h >= 50 ? [w, h] : null);
    };
    back.querySelector('#cs-no').onclick = () => ende(null);
    back.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.key === 'Enter') back.querySelector('#cs-ok').click();
      if (e.key === 'Escape') ende(null);
    });
  });
}

// ---- Unpinning the panels: full canvas, tools on demand ------------------
// Click on the handle = panel away for good / pinned again.
// While it is away, it floats over the canvas when the handle is hovered.
{
  const wrap = document.querySelector('.studio-wrap');
  const setup = (btnId, hideCls, peekCls, panelSel, pfeile) => {
    const btn = document.getElementById(btnId);
    const panel = document.querySelector(panelSel);
    if (!btn || !panel || !wrap) return;
    const key = 'studio-' + hideCls;
    if (ls.get(key) === '1') wrap.classList.add(hideCls);

    const paint = () => {
      const aus = wrap.classList.contains(hideCls);
      btn.textContent = aus ? pfeile[1] : pfeile[0];
      btn.classList.toggle('aus', aus);
      btn.title = aus ? 'Pin the bar (floats on hover)' : 'Expand the bar – canvas gets larger';
    };
    paint();

    btn.onclick = e => {
      e.preventDefault();
      wrap.classList.toggle(hideCls);
      wrap.classList.remove(peekCls);
      ls.set(key, wrap.classList.contains(hideCls) ? '1' : '0');
      paint();
      setTimeout(() => window.dispatchEvent(new Event('resize')), 200);
    };

    // Show it when the handle is hovered
    btn.addEventListener('mouseenter', () => {
      if (wrap.classList.contains(hideCls)) wrap.classList.add(peekCls);
    });
    // Ausblenden, wenn Maus die schwebende Leiste verlässt
    let t = null;
    const weg = () => { t = setTimeout(() => wrap.classList.remove(peekCls), 350); };
    const bleib = () => { if (t) { clearTimeout(t); t = null; } };
    panel.addEventListener('mouseenter', bleib);
    panel.addEventListener('mouseleave', weg);
    btn.addEventListener('mouseleave', weg);
    btn.addEventListener('mouseenter', bleib);
  };
  setup('toggle-left', 'hide-left', 'peek-left', '.studio-sidebar', ['‹', '›']);
  setup('toggle-right', 'hide-right', 'peek-right', '.studio-right', ['›', '‹']);
}

// ---- Farbpaletten ---------------------------------------------------------
let currentTextColor = document.getElementById('text-color')?.value || '#ffffff';
let currentShapeColor = '#F56E28';

// One shared palette for text AND shapes.
bg.renderPalette(document.getElementById('palette-row'), col => {
  currentTextColor = col;
  currentShapeColor = col;
  const picker = document.getElementById('text-color'); if (picker) picker.value = col;
  const rc = document.getElementById('recolor-color'); if (rc) rc.value = col;   // Umfärben nutzt dieselbe Farbe
  const o = editor.active();
  if (o && o.type === 'textbox') { o.set('fill', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
  else if (isBadge(o)) {
    // Badge: Palette färbt die Scheibe, Text bleibt lesbar
    // A badge restored from an older canvas_json can be missing its label child.
    o._objects?.[0]?.set('fill', col);
    const t = o._objects?.[1];
    if (t && hexNorm(t.fill) === hexNorm(col)) t.set('fill', autoContrast(col));
    editor.canvas.requestRenderAll(); editor.snapshot();
  }
  else if (media.istSpot(o)) {
    // A spotlight is one thing, however many frames: its frame colour for all.
    spotEinstellen(media.spotGruppeVon(editor, o), 'fxColor', col);
  }
  else if (media.istEffektRahmen(o)) {
    // The frame itself has no colour to show - its effect gets it.
    if (o.fx !== 'magnifier') { o.fxColor = col; editor.canvas.requestRenderAll(); editor.snapshot(); renderAnimBar(); }
  }
  else if (media.istFrageKnoten(o)) {
    netzEinstellen(netzVon(o), 'qwebColor', col);
  }
  else if (o && o.shapeKind === 'marker') {
    o._objects?.[1]?.set('fill', col);
    const t = o._objects?.[3];
    if (t && hexNorm(t.fill) === hexNorm(col)) t.set('fill', autoContrast(col));
    editor.canvas.requestRenderAll(); editor.snapshot();
  }
  else if (o && o.shapeKind === 'stamp') {
    o._objects?.[0]?.set('stroke', col); o._objects?.[1]?.set('stroke', col); o._objects?.[2]?.set('fill', col);
    editor.canvas.requestRenderAll(); editor.snapshot();
  }
  else if (o && o.shapeKind) { o.set(o.fill ? 'fill' : 'stroke', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
});

// (The second background colour picker is gone - see setCanvasFarbe.)

// Eigenes Textfarben-Feld: überschreibt die Palette für Text/Badge-Beschriftung
{
  const tc = document.getElementById('text-color');
  if (tc) tc.oninput = () => {
    currentTextColor = tc.value;
    const o = editor.active();
    if (o && o.type === 'textbox') { o.set('fill', tc.value); editor.canvas.requestRenderAll(); editor.snapshot(); }
    else if (isBadge(o) && o._objects?.[1]) { o._objects[1].set('fill', tc.value); editor.canvas.requestRenderAll(); editor.snapshot(); }
    else if (isTextblock(o)) { rebuildTextblock(o, o.tbHead || '', o.tbBody || '', { color: tc.value }); }
    else if (isChecklist(o)) { rebuildChecklist(o, o.clItems || [], { color: tc.value }); }
  };
}

// The remembered save format (image|gif|video). After the first choice it does
// not ask again - the button saves quietly in the same format.
// When an existing output is opened, take over the format it used.
let _saveKind = CONFIG.libData?.kind && CONFIG.libData.kind !== 'image'
                ? CONFIG.libData.kind : null;
// Opened from a post whose medium was built here: save in that medium again,
// without asking every time. Only with a saved layout - a video uploaded from
// the PC leaves an empty artboard, and saving that as a video in one click
// would replace the real one. ▾ Format still picks another format.
let _saveKindVomPost = false;
if (!_saveKind && !CONFIG.libData && CONFIG.postData?.canvas_json) {
  const p = CONFIG.postData;
  _saveKind = p.video ? 'video' : p.gif ? 'gif' : p.image ? 'image' : null;
  _saveKindVomPost = !!_saveKind;
}
// The save button says which format it will write.
function saveKnopfZeigt(kind) {
  const btn = document.querySelector('[data-act="save-as"], [data-act="save-existing"]');
  if (!btn || !kind) return;
  btn.textContent = kind === 'gif' ? '💾 Save GIF' : kind === 'video' ? '💾 Save video' : '💾 Save image';
  btn.title = 'Saves as ' + (kind === 'image' ? 'an image (PNG)' : kind === 'gif' ? 'a GIF' : 'a video')
            + '. For another format: ▾ Format (or Shift+Click).';
}
let _speichertGerade = false;
async function speichereAls(kind) {
  // A second click during a save opened a second name dialog and produced two
  // outputs. The guard in io.saveImage covers only the image path; GIF and
  // video ran unchecked.
  if (_speichertGerade) { toast('Already saving…', 'err'); return; }
  _speichertGerade = true;
  try {
    await _speichereAls(kind);
  } finally {
    _speichertGerade = false;
  }
}

async function _speichereAls(kind) {
  _saveKind = kind;
  let ok;
  if (kind === 'gif')        ok = await media.exportGif(editor);
  else if (kind === 'video') ok = await media.exportVideo(editor);
  // The outputs list refreshes itself on "studio:output-changed" (io.js) -
  // the extra call here loaded both lists a second time after every save.
  else ok = await io.saveImage(editor);
  // Nothing saved (still loading, cancelled, failed)? Then no success message
  // either - it used to overwrite the actual reason immediately.
  if (!ok) return;
  // Rename the button, so it is clear: from now on it saves directly.
  // Look for both possible states: as soon as an output is open the attribute
  // is "save-existing" - the old selector then found nothing.
  saveKnopfZeigt(kind);
}

// ---- Toolbar-Aktionen (data-act) -----------------------------------------
const actions = {
  'save-as':   async () => {
    const titleEl = document.getElementById('title-input');
    if (!titleEl || !titleEl.value.trim()) {
      if (titleEl) { titleEl.style.border = '2px solid #dc3545'; titleEl.focus(); }
      status('⚠️ Please enter a title first!', '#dc3545');
      setTimeout(() => { if (titleEl) titleEl.style.border = ''; }, 2500);
      return;
    }
    // Ask for the format only the first time (or after ▾ Format) and remember it.
    let kind = _saveKind;
    // Taken over from a post that carries an image - but animations were added
    // since. Saving quietly as a PNG would drop them, so ask this once.
    if (kind === 'image' && _saveKindVomPost && media.hasAnimations(editor)) kind = null;
    if (!kind) {
      kind = await modal('Save as…', 'What would you like to save?', [
        { label: '🖼 Image (PNG)', value: 'image' },
        { label: '🎞 GIF (animated)', value: 'gif' },
        { label: '🎬 Video (animated)', value: 'video' },
      ]);
      if (!kind) return;   // cancelled
    }
    _saveKindVomPost = false;
    await speichereAls(kind);
  },
  'add-magnifier': () => {
    const lupe = media.addEffektRahmen(editor, 'magnifier');
    oeffneEffekte();
    renderLayers(); renderAnimBar();
    toast('Magnifier added - drag its window over the text; way, glass and speed are under the canvas.');
    return lupe;
  },
  'add-marker': () => addMarker(),
  'add-stamp': () => addStempel(),
  'add-qweb': () => { oeffneEffekte(); return addFragenNetz(); },
  'add-spot': () => { oeffneEffekte(); return spotStarten(); },

  // Format bewusst neu wählen (fragt wieder).
  'save-as-new': async () => { _saveKind = null; _saveKindVomPost = false; await actions['save-as'](); },
  // Vorhandene Ausgabe: nur speichern (gleiches Format, überschreibt).
  'save-existing': async () => {
    if (_speichertGerade) { toast('Already saving…', 'err'); return; }
    let kind = _saveKind || CONFIG.libData?.kind || 'image';
    // Animations set, but the file is a PNG? A still image used to be saved
    // quietly, and the animations were not in the result.
    if (kind === 'image' && media.hasAnimations(editor)) {
      const wahl = await modal('Animations found',
        'This element has animations, but the opened file is an image. How to save?',
        [ { label: '🖼 As image (no animation)', value: 'image' },
          { label: '🎞 As GIF',                    value: 'gif' },
          { label: '🎬 As video',                  value: 'video' },
          { label: 'Cancel',                    value: null } ]);
      if (!wahl) return;
      kind = wahl;
      _saveKind = wahl;
    }
    _speichertGerade = true;
    try {
      if (kind === 'gif') await media.exportGif(editor);
      else if (kind === 'video') await media.exportVideo(editor);
      else await io.saveImage(editor);
    } finally {
      _speichertGerade = false;
    }
  },
  download:    async () => {
    // The same format as for saving (▾ Format). Nothing chosen yet:
    // animiert → GIF, sonst → PNG.
    const kind = _saveKind || (media.hasAnimations(editor) ? 'gif' : 'image');
    if (kind === 'gif')        await media.downloadGif(editor);
    else if (kind === 'video') await media.downloadVideo(editor);
    else                       io.downloadImage(editor);
  },
  'new':       async () => {
    const ok = await modal('Start over?', 'Clears the editor (all elements and the background). Anything not saved is lost.', [
      { label: '🆕 Yes, new editor', value: true },
      { label: 'Cancel', value: false },
    ]);
    if (!ok) return;
    editor.clearAll();
    // Cut the tie to the output opened before: otherwise "save" would have
    // overwritten the old file with the new, empty design - and the warning
    // from an earlier load failure would have kept appearing.
    CONFIG.libData = null;
    io.merkeNamen(null);       // neuer Entwurf → auch der Name wird neu vergeben
    setTemplateId(null);
    editor._ladefehler = false;
    _saveKind = null;
    _saveKindVomPost = false;
    editor.resetHistory();
    {
      const b = document.querySelector('[data-act="save-existing"], [data-act="save-as"]');
      if (b) { b.textContent = '💾 Save as…'; b.dataset.act = 'save-as'; b.title = 'Choose format and save'; }
    }
    const t = document.getElementById('title-input'); if (t) t.value = '';
    if (location.search) history.replaceState(null, '', '/library/studio/');
    window.dispatchEvent(new CustomEvent('studio:geladen'));   // Stand gilt als sauber
    status('New, empty editor.', '#888');
  },
  undo:        () => editor.undo(),
  redo:        () => editor.redo(),
  grid: () => {
    const an = editor.toggleGrid();
    renderSelBar();   // Knopf-Zustand oben aktualisieren
    status(an ? 'Grid on – for alignment only, not saved.' : 'Grid off.', '#888');
  },
  maximize: () => {
    const wrap = document.querySelector('.studio-wrap');
    if (!wrap) return;
    const gross = !wrap.classList.contains('maxi');
    wrap.classList.toggle('maxi', gross);
    // Put both panels into the floating state - the edge handles stay visible,
    // and hovering brings the tools back.
    const tl = document.getElementById('toggle-left');
    const tr = document.getElementById('toggle-right');
    if (wrap.classList.contains('hide-left')  !== gross) tl?.click();
    if (wrap.classList.contains('hide-right') !== gross) tr?.click();
    renderSelBar();
    setTimeout(() => window.dispatchEvent(new Event('resize')), 220);
    status(gross ? 'Large canvas – tools via the edge handles (‹ ›).' : 'Normal view.', '#888');
  },
  'set-as-bg': () => {
    const o = editor.active();
    if (!o || o.type !== 'image') { toast('Select an image first', 'err'); return; }
    editor.canvas.remove(o);
    o.set({ left: 0, top: 0, originX: 'left', originY: 'top',
            scaleX: editor.width / o.width, scaleY: editor.height / o.height, selectable: false, evented: false });
    editor.canvas.setBackgroundImage(o, editor.canvas.renderAll.bind(editor.canvas));
    editor.snapshot();
    bg.updateBgInfo?.(editor);
    status('Image set as background.', '#198754');
  },
  'add-textblock': () => addTextblock(),
  'add-checktext': () => {
    const txt = (document.getElementById('tb-head')?.value.trim())
             || (document.getElementById('text-input')?.value.trim()) || 'Your text';
    const g = buildTextblock(txt, '', {
      width: +(document.getElementById('tb-width')?.value || 260),
      size:  +(document.getElementById('tb-size')?.value || 19),
      color: document.getElementById('text-color')?.value || '#161616',
      align: 'left', check: true,
    });
    if (!g) return;
    editor.canvas.add(g);
    editor.canvas.setActiveObject(g);
    editor.canvas.requestRenderAll();
    editor.snapshot();
    status('Check + text inserted – double-click to edit, scale at the corner.', '#198754');
  },
  'split-checklist': () => {
    const rows = splitChecklist(editor.active());
    if (rows) status(rows.length + ' rows - each one now has its own Motion and Start.', '#198754');
  },
  'add-checklist': () => {
    const g = buildCheckList(['First line', 'Second line', 'Third line'], {
      width: +(document.getElementById('tb-width')?.value || 300),
      size:  +(document.getElementById('tb-size')?.value || 22),
      color: document.getElementById('text-color')?.value || '#161616',
    });
    if (!g) return;
    editor.canvas.add(g);
    editor.canvas.setActiveObject(g);
    editor.canvas.requestRenderAll();
    editor.snapshot();
    status('Triple check inserted – double-click: one line per check. Scale at the corner.', '#198754');
  },
  'add-text':  () => {
    // Read every field optionally: if one is missing from the scaffold, text
    // should still be inserted instead of the action dying on a TypeError.
    const inp = document.getElementById('text-input');
    editor.addText((inp?.value || '').trim() || 'Text', {
      fontSize: Math.max(6, +(document.getElementById('font-size')?.value) || 32),
      fontWeight: document.getElementById('font-weight')?.value || 'bold',
      color: document.getElementById('text-color')?.value || currentTextColor,
    });
    if (inp) inp.value = '';
  },
  'canvas-size': async () => {
    const choice = await modal('Canvas size', 'Choose format', [
      { label: '1080 × 1080 (square)', value: [1080, 1080] },
      { label: '1080 × 1350 (LinkedIn portrait)', value: [1080, 1350] },
      { label: '1024 × 1536 (portrait 2:3)', value: [1024, 1536] },
      { label: '1200 × 628 (link)', value: [1200, 628] },
      { label: '1920 × 1080 (video)', value: [1920, 1080] },
      { label: '✏️ Custom size…', value: 'frei' },
    ]);
    if (!choice) return;
    if (choice === 'frei') {
      const eigen = await askSize(editor.width, editor.height);
      if (eigen) { editor.setSize(eigen[0], eigen[1]); fit(); bg.updateBgInfo(editor); }
      return;
    }
    editor.setSize(choice[0], choice[1]); fit(); bg.updateBgInfo(editor);
  },
  'clear-bg':  () => bg.clearBackground(editor),
  'bg-creme':       () => setCanvasFarbe('#FBF8F0'),
  'bg-weiss':       () => setCanvasFarbe('#FFFFFF'),
  'bg-transparent': () => setCanvasFarbe(''),
  'clear-all': async () => {
    const ok = await modal('Clear everything?', 'Removes all elements and the background from the canvas.', [
      { label: '🧹 Yes, clear', value: true },
      { label: 'Cancel', value: false },
    ]);
    if (ok) editor.clearAll();
  },
  'zoom-in':    () => zeigeZoom(editor.zoom('in')),
  'zoom-out':   () => zeigeZoom(editor.zoom('out')),
  'zoom-reset': () => zeigeZoom(editor.zoom('reset')),
  duplicate:   () => editor.duplicateSelected(),
  group:       () => { if (editor.group()) { renderSelBar(); status('Glued into a group.', '#198754'); } },
  ungroup:     () => { if (editor.ungroup()) { renderSelBar(); status('Group dissolved.', '#888'); } },
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
    if (!o) { toast('No image', 'err'); return; }
    status('🧩 Removing checkerboard pattern…');
    try {
      const out = await removeCheckerboard(o._element);
      if (!out) { status('No checkerboard pattern found – image unchanged', '#888'); return; }
      o.bgRemoved = true; o._work = null;
      retouch.replaceElement(o, out); editor.snapshot();
      status('✅ Pattern removed', 'green');
    } catch (e) { status('❌ ' + (e.message || 'Error'), 'red'); }
  },
  'restore-post': async () => {
    if (!CONFIG.postData?.canvas_json) return;
    if (!window.studioDarfVerlassen || window.studioDarfVerlassen()) {
      status('⏳ Loading draft…');
      await ladeCanvas(CONFIG.postData.canvas_json);
      status('Ready.', '#888');
    }
  },
  'post-bg':      () => CONFIG.postData?.id && bg.setBackgroundImage(editor, `/library/studio/api/post-image/${CONFIG.postData.id}/`),
  'post-overlay': () => CONFIG.postData?.id && editor.addImageUrl(`/library/studio/api/post-image/${CONFIG.postData.id}/`),
  'go-back': async (btn) => {
    // Always navigate back to the page we came from, in the same tab.
    // (window.close() used to be tried - that closed the tab and left the user
    // outside the site.) Unsaved changes are caught by the beforeunload guard.
    // The planner is where posts are worked on, so that is where leaving the
    // Studio leads. The full overview lists everything including what is long
    // published - a strange place to land after drawing.
    let url = (btn && btn.getAttribute('data-back')) || '/planner/';
    // Allow targets on this site only; otherwise fall back to the planner.
    if (!/^\//.test(url) || url.indexOf('/library/studio') !== -1) url = '/planner/';
    const postId = CONFIG.postId || (CONFIG.postData && CONFIG.postData.id);
    if (postId) {
      // With a post attached, "back" has two meanings and only the user knows
      // which one: to the post this belongs to, or away from it - an empty
      // canvas that is tied to nothing. Following the referrer answered
      // neither: the Studio opens in a tab of its own, so it landed on a second
      // copy of the very page the post is already open in.
      const wahl = await modal('Leave the Studio', 'Where do you want to go?', [
        { label: '\u2190 To post #' + postId, value: 'post' },
        { label: '\ud83c\udd95 Empty canvas', value: 'blank' },
        { label: 'Stay here', value: false },
      ]);
      if (!wahl) return;
      // Back to the post means back to the list you came from. Without a
      // `back` the post page falls back to the full overview - which is sorted
      // newest first, so it opens on what is already published. That is never
      // where someone who was just drawing wants to end up, so the overview is
      // the one origin we refuse; anything else in the planner is kept.
      const ueberblick = /\/planner\/uebersicht\//i.test(url);
      const herkunft = (!ueberblick && /^\/planner\//i.test(url)) ? url : '/planner/';
      // The empty canvas is also the only way to let go of the post: without
      // post_id in the address nothing is attached any more, and the next save
      // goes to the library.
      url = (wahl === 'post')
        ? ('/planner/?edit=' + encodeURIComponent(postId)
           + '&back=' + encodeURIComponent(herkunft))
        : '/library/studio/';
    }
    window.location.href = url;
  },
  'copy-from-post': () => copyImageFromPost(),
  'open-post-file': (btn) => {
    const url = btn && btn.dataset.url;
    if (!url) return;
    editor.addImageUrl(url, { fill: true });
    status('File loaded from the post – now edit and save.', '#198754');
  },
  'save-template': () => saveAsTemplate(),
  'new-template': async () => {
    const ok = await modal('New template', 'Clears the canvas so you can build a new template – background, logo, text fields. Unsaved work is lost.', [
      { label: '➕ Yes, new template', value: true },
      { label: 'Cancel', value: false },
    ]);
    if (!ok) return;
    editor.clearAll();
    setTemplateId(null);   // frische Vorlage → beim Speichern neu anlegen
    const t = document.getElementById('title-input'); if (t) t.value = '';
    status('Build a template: background, logo, text fields – then “💾 Save” under Template.', '#888');
  },
};

// Aktuelle Leinwand als wiederverwendbare Vorlage speichern.
async function saveAsTemplate() {
  // Is the editor still loading? Then the artboard would be half empty - and an
  // "update template" would have overwritten the existing template with that
  // empty state. There was no getting it back.
  if (editor._locked) {
    status('⏳ Still loading – please wait a moment', 'red');
    toast('The template is still loading', 'err');
    return;
  }
  if (editor._ladefehler) {
    const weiter = window.confirm(
      'Warning: the current content was not fully loaded when opened.\n\n' +
      'Saving would replace the template with this incomplete state.\n\nSave anyway?');
    if (!weiter) return;
  }
  // One source of truth for the template currently loaded - no matter whether
  // it was opened from the management page (?template=…) or by clicking a tile.
  const boundId = currentTemplateId();
  let updateExisting = false;
  if (boundId) {
    const choice = await modal('Save template',
      'You have an existing template open. Update this template – or save as a new template?',
      [ { label: '💾 Update this template', value: 'update' },
        { label: '➕ Save as new template',   value: 'new' },
        { label: 'Cancel',                       value: null } ]);
    if (!choice) return;
    updateExisting = (choice === 'update');
  }
  const vorschlag = (document.getElementById('title-input')?.value || '').trim()
                    || CONFIG.tplData?.title || 'New template';
  const title = window.prompt(updateExisting ? 'Template name (will be updated):'
                                             : 'Name of the new template:', vorschlag);
  if (title === null) return;                 // abgebrochen
  // Avoid duplicate names (only when creating a new one).
  if (!updateExisting) {
    try {
      const r = await fetch(CONFIG.urls?.apiTemplates || '/library/studio/api/templates/');
      const dj = await r.json();
      const clash = (dj.templates || []).some(
        t => (t.title || '').trim().toLowerCase() === title.trim().toLowerCase());
      if (clash) {
        const go = await modal('Name already taken',
          `A template named “${title.trim()}” already exists. Do you still want to create a second one with the same name?`,
          [ { label: 'Cancel (choose a different name)', value: null },
            { label: 'Create it anyway',                  value: true } ]);
        if (!go) return;
      }
    } catch (e) { /* Prüfung ist nur Komfort – bei Fehler normal weiter */ }
  }
  // Turn open brush and marking states into real images - a canvas as an image
  // element does not survive serialisation into the canvas_json.
  await retouch.vorschauenUebernehmen(editor.canvas);
  let dataUrl, canvasJson;
  try {
    retouch.beendeVorschauen(editor.canvas);               // rote Markierung nie mitspeichern
    const el = editor.exportLeinwand(1);                   // one render (ohne Raster)
    const preview = Editor.vorschauAus(el, 0.4);
    dataUrl = el.toDataURL('image/png');
    canvasJson = io.buildCanvasJson(editor, preview);      // Layout: Hintergrund + Logo + Textfelder
  } catch (e) { toast('Export failed', 'err'); status('❌ Export failed', 'red'); return; }
  // An empty artboard is nearly always a slip (clicked too early) and would
  // replace a working template with nothing.
  if (updateExisting && !editor.realObjects().length && !editor.canvas.backgroundImage) {
    const weiter = window.confirm('The canvas is empty.\n\n' +
      'The existing template would be replaced by an empty one.\n\nReally continue?');
    if (!weiter) { status('Cancelled', 'red'); return; }
  }
  status('💾 Saving template…');
  try {
    const res = await fetch(CONFIG.urls?.saveTemplate || '/library/studio/template/save-canvas/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _cookie('csrftoken') },
      body: JSON.stringify({ dataUrl, canvasJson, title: title.trim(),
                             width: editor.width, height: editor.height,
                             tplId: updateExisting ? boundId : undefined }),
    });
    if (!res.ok) {
      // Without this check, res.json() choked on the HTML error page and the
      // user saw "SyntaxError: Unexpected token '<'".
      const grund = res.status === 413 ? 'Template too large for the server'
                  : res.status === 403 ? 'Session expired – please sign in again'
                  : 'Server error ' + res.status;
      toast(grund, 'err'); status('❌ ' + grund, 'red'); return;
    }
    const d = await res.json();
    if (d.ok) {
      setTemplateId(d.id);   // ab jetzt weiter dieselbe Vorlage aktualisieren
      toast(d.updated ? 'Template updated' : 'Template saved', 'ok');
      status(d.updated ? '✅ Template updated.' : '✅ Saved as template.', '#198754');
      // Mark the state as saved - otherwise the Studio asked about unsaved
      // changes even straight after saving a template.
      window.dispatchEvent(new CustomEvent('studio:vorlage-gespeichert'));
      bg.loadTemplateList(editor);
    } else { toast('Error: ' + (d.error || ''), 'err'); status('❌ ' + (d.error || 'Error'), 'red'); }
  } catch (e) { toast('Save failed', 'err'); status('❌ ' + (e.message || e), 'red'); }
}
function _cookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? decodeURIComponent(m.pop()) : '';
}

// Take over an existing image from another post. It is placed on the artboard;
// saving then creates a copy that is attached to THIS post.
async function copyImageFromPost() {
  let posts = [];
  try {
    const res = await fetch(CONFIG.urls?.postsWithImages || '/library/studio/api/posts-with-images/',
      { credentials: 'same-origin' });
    const d = await res.json();
    posts = (d && d.ok && d.posts) || [];
  } catch (e) { toast('Posts could not be loaded', 'err'); return; }
  if (!posts.length) { toast('No posts with an image found', 'err'); return; }

  const ov = document.createElement('div');
  ov.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center';
  const box = document.createElement('div');
  box.style.cssText = 'background:#fff;border-radius:12px;padding:16px;width:min(680px,92vw);max-height:82vh;overflow:auto;box-shadow:0 10px 40px rgba(0,0,0,.35)';
  box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
    + '<strong style="font-size:15px;color:#0E7C86">Take image from another post</strong>'
    + '<button id="cfp-x" class="tbtn">✕</button></div>'
    + '<input id="cfp-q" placeholder="Search…" style="width:100%;padding:6px 8px;border:1px solid #ccc;border-radius:6px;margin-bottom:10px;box-sizing:border-box">'
    + '<div id="cfp-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px"></div>';
  ov.appendChild(box); document.body.appendChild(ov);
  const grid = box.querySelector('#cfp-grid');
  const render = q => {
    grid.innerHTML = '';
    posts.filter(p => !q || (p.title || '').toLowerCase().includes(q)).forEach(p => {
      const card = document.createElement('div');
      card.style.cssText = 'cursor:pointer;border:1px solid #e2e5e8;border-radius:8px;padding:5px;text-align:center';
      card.innerHTML = `<img src="${p.thumb}" loading="lazy" style="width:100%;height:90px;object-fit:cover;border-radius:6px;background:#f0f1f3">`
        + `<div style="font-size:11px;color:#555;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.title)}</div>`;
      card.onclick = () => { wegDamit(ov); ladeBildVonPost(p); };
      grid.appendChild(card);
    });
  };
  render('');
  box.querySelector('#cfp-q').addEventListener('input', e => render(e.target.value.toLowerCase().trim()));
  box.querySelector('#cfp-x').onclick = () => wegDamit(ov);
  ov.addEventListener('click', e => { if (e.target === ov) wegDamit(ov); });
}
async function ladeBildVonPost(p) {
  try {
    await editor.addImageUrl(p.thumb, {});   // same-origin Proxy → kein Tainting
    status(`Image taken from “${p.title}”. “Save” stores it as a copy on this post.`, '#198754');
  } catch (e) { toast('Image could not be loaded', 'err'); }
}

// One place that turns a failed action into something the user can read. Every
// async handler routes its rejection here; anything that does not ends up in the
// global handler instead, which paints a red banner over the whole page.
function reportActionError(err, what = 'action') {
  console.error('[studio] ' + what + ' failed:', err);
  status('❌ ' + (err?.message || err), 'red');
  toast(err?.message || 'Action failed', 'err');
}
// Runs fn and keeps every failure — sync throw or async rejection — off the
// global handler. Use this wherever a promise would otherwise be dropped.
function safely(fn, what) {
  try { return Promise.resolve(fn()).catch(err => reportActionError(err, what)); }
  catch (err) { reportActionError(err, what); return Promise.resolve(); }
}

document.addEventListener('click', e => {
  const btn = e.target.closest('[data-act]');
  if (btn && actions[btn.dataset.act]) {
    e.preventDefault();
    // Most actions are async. Without this catch, an error left only
    // "💾 Saving…" on screen - which looked like a hang to the user.
    safely(() => actions[btn.dataset.act](btn), 'action “' + btn.dataset.act + '”');
  }
  const shape = e.target.closest('[data-shape]');
  if (shape) {
    e.preventDefault();
    try { editor.addShape(shape.dataset.shape, currentShapeColor); }
    catch (err) { console.error(err); toast('Shape could not be inserted', 'err'); }
  }
});

// Textausrichtung des aktiven Textfelds setzen.
function setTextAlign(align) {
  const o = editor.active();
  if (!o || o.type !== 'textbox') { toast('Select a text field first', 'err'); return; }
  o.set('textAlign', align);
  editor.canvas.requestRenderAll();
  editor.snapshot();
}

// ---- Freistellen ----------------------------------------------------------
async function doCutout() {
  const o = editor.active();
  if (!o || o.type !== 'image') { toast('Select an image first', 'err'); return; }
  status('✂ Removing background…');
  try {
    const cleaned = await removeBackground(o._element, { tol: 55 });
    // removeBackground deliberately protects light, colour-neutral pixels
    // (white, off-white, light grey), so white content such as a coat or icons
    // stays. On a white or chequered background EVERYTHING therefore stays -
    // and the button looked as if it did nothing. Now it says what is going on.
    const eckeOffen = (() => {
      try {
        const c = document.createElement('canvas');
        c.width = cleaned.width; c.height = cleaned.height;
        const cx = c.getContext('2d'); cx.drawImage(cleaned, 0, 0);
        const a = (x, y) => cx.getImageData(x, y, 1, 1).data[3];
        return [a(0, 0), a(c.width - 1, 0), a(0, c.height - 1), a(c.width - 1, c.height - 1)]
          .some(v => v === 0);
      } catch (e) { return true; }
    })();
    if (!eckeOffen) {
      status('Nothing removed: the background is white or very light, and white is '
           + 'protected so white content survives. Use Erase → “Whole colour” and '
           + 'click the background.', '#B26A00');
      toast('Background looks white – use Erase → Whole colour', 'err');
      return;
    }
    o.bgRemoved = true; o._work = null;
    retouch.replaceElement(o, cleaned);
    editor.snapshot();
    status('✅ Background removed', 'green');
  } catch (e) {
    status('❌ Removing the background failed', 'red');
    toast(e.message || 'Cutting out failed', 'err');
  }
}

// ==== Freistellen & Korrektur-Werkzeuge ====================================
let _tol = 50;
let _brush = 6;   // feine Vorgabe; der Regler bildet quadratisch auf 1–120 px ab
let _tool = 'off';       // 'off' | 'fill' | 'pick' | 'paint' | 'mark' | 'rect' | 'erase' | 'restore' | 'recolorpick' | 'recolorpickall'
let _toolTarget = null;
let _recolorPickColor = null;   // beim Umfärben zuerst per Klick aufgenommene Farbe
let _painting = false;
let _suppressClear = false;

// Releases the current tool target. Important after loading a file or after an
// undo: the old objects are no longer on the canvas, but they still hold
// several full-size canvases in memory through _work/_mask/_origImg.
function freeToolTarget() {
  const o = _toolTarget;
  _toolTarget = null;
  _painting = false;
  // A rectangle drag that is still running has to end here too. It used to keep
  // its own flag, so pointermove carried on reading pixels from an image that
  // had just been taken away — undo or loading a template mid-drag was enough.
  _mqDrawing = false;
  if (!o) return;
  o._work = null; o._mask = null; o._origImg = null; o._origPromise = null; o._prevCv = null;
}

// Gives the artboard back: objects clickable, selection possible, normal mouse
// pointer. If one of these switches stays stuck, the Studio feels completely
// frozen although technically everything is running.
function werkzeugFlagsZuruecksetzen() {
  editor.canvas.skipTargetFind = false;
  editor.canvas.selection = true;
  editor.canvas.defaultCursor = 'default';
  const ov = document.getElementById('rect-overlay');
  if (ov) ov.style.display = 'none';
  document.querySelectorAll('#retouch-body [data-tool]').forEach(b => b.classList.remove('primary'));
  ['brush-row', 'recolor-color-row', 'mark-apply-row'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  editor.canvas.requestRenderAll();
}

// Work out the target image: the active image, else the topmost one on the canvas.
function targetImage() {
  const a = editor.active();
  if (a && a.type === 'image') return a;
  const imgs = editor.realObjects().filter(x => x.type === 'image');
  return imgs.length ? imgs[imgs.length - 1] : null;
}

function setTool(tool) {
  // Is _toolTarget still pointing at an object that has since been replaced
  // (template loaded, Ctrl+Z)? Then it is orphaned: the tools afterwards did
  // nothing at all, quietly. Clear it and work it out again.
  if (_toolTarget && _toolTarget.canvas !== editor.canvas) freeToolTarget();

  const o = targetImage();
  if (tool !== 'off' && !o) {
    // IMPORTANT: unlock the artboard first, then give up. This used to return
    // here while skipTargetFind/selection from the previous drag tool were
    // still set - after that nothing could be clicked at all, and every
    // attempt to rescue it through another tool button ran into this very
    // return.
    werkzeugFlagsZuruecksetzen();
    _tool = 'off';
    toast('No image present – insert an image first', 'err');
    return;
  }
  // On leaving marking mode, discard an open (unapplied) marking.
  if ((_tool === 'mark' || _tool === 'rect') && _toolTarget && retouch.hasMask(_toolTarget)) {
    retouch.clearMask(_toolTarget);
    retouch.commitWork(_toolTarget).then(() => editor.canvas.requestRenderAll())
      .catch(e => console.warn('commitWork beim Werkzeugwechsel:', e));
  }
  // End the red marking preview, or it stays visible in the image.
  retouch.beendeVorschauen(editor.canvas);
  if (typeof clearSelRect === 'function') clearSelRect();
  _tool = tool;
  _toolTarget = tool === 'off' ? null : o;
  const active = tool !== 'off';
  editor.canvas.defaultCursor = active ? 'crosshair' : 'default';
  // Only DRAG tools make the canvas ignore objects (so dragging paints instead
  // of moving). Click tools (eraser, recolour) behave normally - the image
  // stays clickable, selection and toolbar are kept.
  const dragTool = ['mark', 'rect', 'paint', 'erase', 'restore'].includes(tool);
  editor.canvas.skipTargetFind = dragTool;
  editor.canvas.selection = !active;
  // Drag tools: deselect the active object, or dragging moves the image instead
  // of drawing a rectangle. (The tool stays on - see the selection:cleared guard.)
  if (dragTool) editor.canvas.discardActiveObject();
  editor.canvas.requestRenderAll();
  // Umfärb-Werkzeuge: beim Aktivieren Aufnahme-Zustand zurücksetzen (1. Klick = Farbe).
  if (tool === 'recolorpick' || tool === 'recolorpickall') {
    _recolorPickColor = null;
    const sw = document.getElementById('recolor-swatch'); if (sw) sw.style.background = 'transparent';
  }
  const hints = {
    fill: 'Click an area → becomes transparent',
    pick: 'Click a background colour → that colour becomes transparent EVERYWHERE',
    recolorpick: 'First click the colour you want (e.g. the background), then click the area(s) in the image to recolour',
    recolorpickall: 'First click the colour you want, then click a colour in the image to recolour ALL matching areas',
    paint: 'Paint over the image → in the chosen colour (only where there is image)',
    mark: 'Roughly paint an area red, then “recolour” or “remove” below',
    rect: 'Drag a rectangle over the area, then “recolour” or “remove” below',
    erase: 'Wipe over the image → becomes transparent',
    restore: 'Wipe over the image → the original comes back',
    off: 'Tool off',
  };
  setToolStatus(hints[tool] || '');
  const isMark = (tool === 'mark' || tool === 'rect');
  const colorRow = document.getElementById('recolor-color-row');
  if (colorRow) colorRow.style.display = (tool === 'paint' || isMark) ? 'flex' : 'none';
  const markRow = document.getElementById('mark-apply-row');
  if (markRow) markRow.style.display = isMark ? 'flex' : 'none';
  // Show the brush size only for the tools that actually use it.
  const brushRow = document.getElementById('brush-row');
  if (brushRow) brushRow.style.display = ['paint', 'erase', 'restore', 'mark'].includes(tool) ? 'flex' : 'none';
  // Highlight the active tool - before, there was no telling which one was on.
  document.querySelectorAll('#retouch-body [data-tool]').forEach(b => {
    b.classList.toggle('primary', b.dataset.tool === tool && tool !== 'off');
  });
  // The rectangle drawing layer is active only for the rectangle tool (style set
  // directly, independent of the CSS - cache-proof).
  const ov = document.getElementById('rect-overlay');
  if (ov) ov.style.display = (tool === 'rect') ? 'block' : 'none';
  updateRetouchPanel();
}

function setToolStatus(msg) {
  const el = document.getElementById('tool-status');
  if (el) el.textContent = msg;
}

// Click coordinate → image pixel of the target image (robustly, via the transform matrix).
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
  } catch (e) { setToolStatus('❌ Error – nothing changed'); }
}

async function doPickAt(o, px, py) {
  try {
    const out = await removeColorGlobal(o._element, px, py, 42);
    o.bgRemoved = true; o._work = null;
    retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('💧 Background colour removed – keep clicking or turn the tool off');
  } catch (e) { setToolStatus('❌ Error – nothing changed'); }
}

// Eyedropper: takes the colour at the click point from the VISIBLE canvas
// (background colour and any images included) and sets it as the recolour
// colour. So the target colour is picked by clicking instead of from the palette.
function _showRecolorSwatch(hex) {
  const sw = document.getElementById('recolor-swatch');
  if (sw) { sw.style.background = hex || 'transparent'; sw.title = hex ? ('picked colour: ' + hex) : 'no colour picked'; }
}

// Read a single pixel from a fabric image object at the scene position pt.
function _samplePixelFromObject(o, pt) {
  try {
    const el = o._element; if (!el) return null;
    const inv = fabric.util.invertTransform(o.calcTransformMatrix());
    const p = fabric.util.transformPoint(pt, inv);
    const W = el.naturalWidth || el.width, H = el.naturalHeight || el.height;
    const x = Math.round(p.x + W / 2), y = Math.round(p.y + H / 2);
    if (x < 0 || y < 0 || x >= W || y >= H) return null;
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(el, 0, 0, W, H);
    const d = ctx.getImageData(x, y, 1, 1).data;
    if (d[3] === 0) return null;   // transparente Stelle
    return '#' + [d[0], d[1], d[2]].map(v => v.toString(16).padStart(2, '0')).join('');
  } catch (_) { return null; }
}

// Work out the colour at the click point - robustly and without a tainted whole
// canvas: 1) image object under the click, 2) background image, 3) background colour.
function pickCanvasColor(e) {
  const canvas = editor.canvas;
  const pt = canvas.getPointer(e);
  let hex = null;
  const obj = canvas.findTarget ? canvas.findTarget(e, false) : null;
  if (obj && obj.type === 'image') hex = _samplePixelFromObject(obj, pt);
  if (!hex && canvas.backgroundImage && canvas.backgroundImage._element) hex = _samplePixelFromObject(canvas.backgroundImage, pt);
  if (!hex && canvas.backgroundColor && typeof canvas.backgroundColor === 'string' && canvas.backgroundColor[0] === '#') hex = canvas.backgroundColor;
  if (!hex) { setToolStatus('Couldn’t read a colour there – click directly on a coloured area or image'); return null; }
  _showRecolorSwatch(hex);
  return hex;
}

// Recolour with the colour picked up earlier: either the connected area only
// (all=false) or every area of that colour in the image (all=true).
async function doRecolorWith(o, px, py, hex, all) {
  try {
    const out = all ? await recolorSimilarAll(o._element, px, py, hex, 45)
                    : await recolorRegion(o._element, px, py, hex, 40);
    o._work = null; retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('🎨 Recoloured – click more areas, or press the tool button again to pick a new colour');
  } catch (e) { console.error('Recolour:', e); setToolStatus('❌ Error'); }
}

// One brush step. `endgueltig` only when the mouse button is released:
// a full-resolution PNG used to be encoded on EVERY mouse move (about 200 ms
// per tick on a 12-megapixel image, 60 ticks per stroke). The calls piled up,
// the browser stood still for minutes, and because they came back in any
// order, strokes disappeared again.
// While dragging we now show the working canvas directly, which costs nothing.
async function paintAt(o, px, py, endgueltig = false) {
  if (_tool === 'mark') {
    retouch.markAt(o, px, py, _brush);
    const r = _brush + 2;
    retouch.renderMaskPreview(o, { x: px - r, y: py - r, w: 2 * r, h: 2 * r });
    editor.canvas.requestRenderAll();
    return;
  }
  let origImg = null;
  if (_tool === 'restore') {
    try {
      origImg = await retouch.getOriginal(o);
    } catch (e) {
      setToolStatus('❌ Original image not available – “Restore” doesn’t work here');
      _painting = false;
      return;
    }
  }
  const color = _tool === 'paint' ? (document.getElementById('recolor-color')?.value || '#ffffff') : null;
  retouch.brushAt(o, px, py, _brush, _tool, origImg, color);
  if (endgueltig) await retouch.commitWork(o);   // teuer: nur einmal am Strichende
  else retouch.showWork(o);                      // billig: Arbeits-Canvas anzeigen
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
    setToolStatus(mode === 'recolor' ? '🎨 Area recoloured' : '🗑 Area removed');
    return;
  }
  // Freihand-Maske
  if (!retouch.hasMask(o)) { toast('Nothing marked – first drag a rectangle or mark freely', 'err'); return; }
  await retouch.applyMask(o, mode, color);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  setToolStatus(mode === 'recolor' ? '🎨 Selection recoloured' : '🗑 Selection removed');
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
    if (!_mqDrawing || !_toolTarget) return;
    const r = ov.getBoundingClientRect();
    draw(marquee(), _mqStart, { x: ev.clientX - r.left, y: ev.clientY - r.top });
    _rectEnd = imgPixel(_toolTarget, ev);
  });
  const finish = ev => {
    if (!_mqDrawing) return;
    _mqDrawing = false;
    if (!_toolTarget) return;
    _rectEnd = imgPixel(_toolTarget, ev);
    setToolStatus('✅ Area selected → “🗑 Delete area” or “🎨 Recolour area”');
  };
  ov.addEventListener('pointerup', finish);
  ov.addEventListener('pointercancel', finish);
})();

editor.canvas.on('mouse:down', async (opt) => {
  if (_tool === 'off' || !_toolTarget) return;
  // Combined recolouring in ONE tool: the first click picks up the colour
  // (from anywhere - the petrol background, say), after that clicks recolour
  // the area clicked in the image. No second button needed.
  if (_tool === 'recolorpick' || _tool === 'recolorpickall') {
    if (_recolorPickColor == null) {
      const hex = pickCanvasColor(opt.e);
      if (hex) { _recolorPickColor = hex; setToolStatus('🎨 Colour ' + hex + ' – now click the area(s) to recolour'); }
      return;
    }
    const { px, py } = imgPixel(_toolTarget, opt.e);
    await doRecolorWith(_toolTarget, px, py, _recolorPickColor, _tool === 'recolorpickall');
    return;
  }
  const { px, py } = imgPixel(_toolTarget, opt.e);
  if (_tool === 'fill') { await doFillAt(_toolTarget, px, py); return; }
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
  // Fabric calls this handler and throws the returned promise away, so a
  // rejection here would be unhandled by construction — hence safely().
  await safely(() => paintAt(_toolTarget, px, py), 'brush');
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
  await safely(() => paintAt(_toolTarget, px, py), 'brush');
});
editor.canvas.on('mouse:up', async () => {
  if (!_painting) return;
  _painting = false;
  // Stroke finished: now build the real image state ONCE and set an undo step -
  // not 60 times while dragging.
  if (_toolTarget && ['paint', 'erase', 'restore'].includes(_tool)) {
    try {
      await retouch.commitWork(_toolTarget);
      editor.snapshot();
    } catch (e) {
      console.error('commitWork:', e);
      setToolStatus('❌ Change could not be applied');
    }
  }
});

// Korrektur-Panel je nach Auswahl aktualisieren.
function updateRetouchPanel() {
  const isImg = !!targetImage();
  const hint = document.getElementById('retouch-hint');
  const body = document.getElementById('retouch-body');
  if (!hint || !body) return;
  // Always show the tools, but visibly DISABLE them without an image. They used
  // to be fully operable and every click ran into a brief toast - from outside
  // that looked as if the buttons simply did nothing.
  body.style.display = 'block';
  body.classList.toggle('is-disabled', !isImg);
  hint.style.display = isImg ? 'none' : 'block';
  document.querySelectorAll('#retouch-body [data-tool]').forEach(b =>
    b.classList.toggle('primary', b.dataset.tool === _tool && _tool !== 'off'));
}

// Badges, text blocks, checklists, SVG import and the marks live in elements.js.
initElemente(editor, { farbe: () => currentShapeColor });

document.addEventListener('click', e => {
  const bb = e.target.closest('[data-badge]');
  if (bb) { e.preventDefault(); addBadge(bb.dataset.badge); return; }
  const tb = e.target.closest('#retouch-body [data-tool]');
  if (tb) { e.preventDefault(); setTool(tb.dataset.tool); }
  const mb = e.target.closest('#retouch-body [data-mark]');
  // applyMark is async and is called from a sync listener: without the catch a
  // failed retouch surfaces as an unhandled rejection, i.e. a red banner.
  if (mb) { e.preventDefault(); safely(() => applyMark(mb.dataset.mark), 'retouch “' + mb.dataset.mark + '”'); }
});
// Escape ends the active tool - the quick way back when the artboard feels
// "stuck".
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || _tool === 'off') return;
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
  if (document.querySelector('.studio-modal-bg')) return;   // Dialog hat Vorrang
  e.preventDefault();
  setTool('off');
  setToolStatus('Tool ended (Esc).');
});

{
  // The slider ran linearly from 3 to 120 px - which put the fine sizes in the
  // first few millimetres, practically impossible to hit. The slider position
  // is now mapped to the pixel size quadratically: the lower half of the track
  // covers 1-30 px, the upper half everything up to 120.
  const MIN_PX = 1, MAX_PX = 120;
  const zuPixel = (v) => Math.max(MIN_PX,
    Math.round(MIN_PX + Math.pow(v / 100, 2) * (MAX_PX - MIN_PX)));
  const brushS = document.getElementById('brush-slider');
  const brushV = document.getElementById('brush-val');
  if (brushS) {
    _brush = zuPixel(+brushS.value);
    if (brushV) brushV.textContent = _brush + ' px';
    brushS.oninput = () => {
      _brush = zuPixel(+brushS.value);
      if (brushV) brushV.textContent = _brush + ' px';   // ohne Guard warf das hier
    };
  }
}

// ---- Element-Leiste: IMMER sichtbar, Buttons inaktiv wenn nichts gewählt ---
let _keepRatio = true;

function renderSelBar() {
  const bar = document.getElementById('sel-bar');
  if (!bar) return;   // without this guard a missing element tore down the
                      // whole start-up sequence (file load, title, status)
  const objs = editor.activeAll();
  const first = objs[0];
  const centre = first ? first.getCenterPoint() : null;
  // Which groups appear is decided by the `when` rules in toolbar.js, not by
  // display toggles scattered through this file.
  bar.innerHTML = buildContext({
    hasSel:    objs.length > 0,
    count:     objs.length,
    isImg:     objs.length === 1 && objs[0].type === 'image',
    isGroup:   editor.isGroup(),
    isChecklist: objs.length === 1 && isChecklist(objs[0])
                 && (objs[0].clItems || []).length > 1,
    // Plain text only. A text block or a checklist keeps its weight: it is
    // part of how those are built, and their text is not in activeAll().
    isText:    objs.some(istTextObj),
    fontWeight: gewichtVon(objs.find(istTextObj)),
    label:     !objs.length ? ''
               : (objs.length > 1 ? objs.length + ' elements'
                  : layerLabel(objs[0], editor.realObjects().indexOf(objs[0]) + 1)),
    w:         first ? Math.round(first.getScaledWidth()) : '',
    h:         first ? Math.round(first.getScaledHeight()) : '',
    x:         centre ? Math.round(centre.x) : '',
    y:         centre ? Math.round(centre.y) : '',
    keepRatio: _keepRatio,
    gridOn:    !!editor.gridOn,
    maxi:      !!document.querySelector('.studio-wrap')?.classList.contains('maxi'),
  });
  wireSizeFields();
  wireWeightField();
}

// The bar is rebuilt on every change of selection, so the handler is attached
// anew each time - the old element is gone by then.
function wireWeightField() {
  const fw = document.getElementById('sel-font-weight');
  if (fw) fw.onchange = () => schriftStaerkeAufAuswahl(fw.value);
}

// ---- Setting the size by number (with a multi-selection: for all) ---------
// Fabric wraps a multi-selection in a temporary group; changes to the children
// do not take cleanly inside it. So: break the selection, change, set it again.
function mitAuswahl(fn) {
  const list = editor.activeAll();
  if (!list.length) return 0;
  const war = editor.active();
  const mehrere = war && war.type === 'activeSelection';
  // Deselecting and reselecting briefly triggered three complete rebuilds of
  // the selection bar - which deleted the very input field whose handler we
  // were standing in (the value jumped back). Suppressed here.
  _suppressClear = true;
  try {
    if (mehrere) editor.canvas.discardActiveObject();
    fn(list);
    list.forEach(o => { o.setCoords(); o.__thumb = null; });
    if (mehrere) {
      const sel = new fabric.ActiveSelection(list, { canvas: editor.canvas });
      editor.canvas.setActiveObject(sel);
    }
  } finally {
    _suppressClear = false;
  }
  editor.canvas.requestRenderAll();
  editor.snapshot();
  return list.length;
}

function wireSizeFields() {
  const wi = document.getElementById('sel-w');
  const hi = document.getElementById('sel-h');
  const lk = document.getElementById('sel-lock');
  if (lk) lk.onclick = e => { e.preventDefault(); _keepRatio = !_keepRatio; renderSelBar(); };
  if (!wi || !hi) return;

  const apply = dim => {
    const wv = +wi.value, hv = +hi.value;
    if (dim === 'w' && !(wv > 0)) return;
    if (dim === 'h' && !(hv > 0)) return;
    let f = null;
    mitAuswahl(list => {
      list.forEach(o => {
        if (_keepRatio) {
          if (dim === 'w') o.scaleToWidth(wv); else o.scaleToHeight(hv);
        } else {
          if (dim === 'w') o.scaleX = (wv / o.getScaledWidth())  * o.scaleX;
          else             o.scaleY = (hv / o.getScaledHeight()) * o.scaleY;
        }
      });
      f = list[0];
    });
    if (f) { wi.value = Math.round(f.getScaledWidth()); hi.value = Math.round(f.getScaledHeight()); }
  };
  wi.onchange = () => apply('w');
  hi.onchange = () => apply('h');
  const enter = e => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } };
  wi.onkeydown = enter; hi.onkeydown = enter;

  // ---- Position per Zahl (Mittelpunkt) ----
  const xi = document.getElementById('sel-x');
  const yi = document.getElementById('sel-y');
  if (xi && yi) {
    const move = () => {
      const nx = +xi.value, ny = +yi.value;
      if (!isFinite(nx) || !isFinite(ny)) return;
      mitAuswahl(list => {
        list.forEach(o => o.setPositionByOrigin(new fabric.Point(nx, ny), 'center', 'center'));
      });
    };
    xi.onchange = move; yi.onchange = move;
    xi.onkeydown = enter; yi.onkeydown = enter;
  }

  // ---- Gleichmäßig verteilen ----
  const dist = axis => {
    if (editor.activeAll().length < 3) { status('Select at least 3 elements to distribute.', '#dc3545'); return; }
    const n = mitAuswahl(list => {
      const key = axis === 'h' ? 'x' : 'y';
      const items = list.map(o => ({ o, c: o.getCenterPoint() })).sort((a, b) => a.c[key] - b.c[key]);
      const from = items[0].c[key], to = items[items.length - 1].c[key];
      const step = (to - from) / (items.length - 1);
      items.forEach((it, i) => {
        const p = it.o.getCenterPoint();
        const np = axis === 'h' ? new fabric.Point(from + step * i, p.y)
                                : new fabric.Point(p.x, from + step * i);
        it.o.setPositionByOrigin(np, 'center', 'center');
      });
    });
    if (n) status(`${n} Elemente ${axis === 'h' ? 'waagerecht' : 'senkrecht'} verteilt.`, '#198754');
  };
  const dh = document.getElementById('dist-h'), dv = document.getElementById('dist-v');
  if (dh) dh.onclick = e => { e.preventDefault(); dist('h'); };
  if (dv) dv.onclick = e => { e.preventDefault(); dist('v'); };

  // ---- Alle auf gleiche Größe (Vorbild = zuerst gewähltes Element) ----
  const ss = document.getElementById('same-size');
  if (ss) ss.onclick = e => {
    e.preventDefault();
    if (editor.activeAll().length < 2) { status('Select at least 2 elements.', '#dc3545'); return; }
    let ziel = 0;
    const n = mitAuswahl(list => {
      // The model is the largest element: predictable, and independent of click order
      const vorbild = list.reduce((a, b) => (b.getScaledWidth() > a.getScaledWidth() ? b : a), list[0]);
      const zW = vorbild.getScaledWidth(), zH = vorbild.getScaledHeight();
      ziel = zW;
      list.forEach(o => {
        if (o === vorbild) return;
        const mitte = o.getCenterPoint();          // Mittelpunkt halten, sonst wandern sie
        if (_keepRatio) o.scaleToWidth(zW);
        else { o.scaleX = zW / o.width; o.scaleY = zH / o.height; }
        o.setPositionByOrigin(mitte, 'center', 'center');
      });
    });
    if (n) status(`${n} element(s) set to ${Math.round(ziel)} px.`, '#198754');
  };
}


// The layer list, the animation bar and the frame hints live in animbar.js.
initAnimBar(editor, { netzVon, netzAktualisieren, netzEinstellen, frageDazu, frageZeichenFuer,
                      spotStarten, spotEinstellen, spotAlle });

/* ---- The Effects tab: live tiles -----------------------------------------
   One small picture per effect, drawn by the same painter as the artboard, so
   a tile never promises something the picture will not do. A click lays the
   effect over the image as a frame; everything else is set in the bar under
   the canvas, in one place.

   The tiles only run while the tab is open: nine animations ticking along
   while someone retouches an image is work nobody asked for. */
const FX_KACHELN = media.EFFECTS.filter(f => f !== 'none' && f !== 'magnifier');
let _kachelLauf = null;

function kachelnBauen() {
  const box = document.getElementById('fx-tiles');
  if (!box || box.dataset.gebaut) return;
  box.dataset.gebaut = '1';
  box.innerHTML = '';
  FX_KACHELN.forEach(fx => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'fx-tile'; b.dataset.fx = fx;
    const name = (media.EFFECT_LABELS[fx] || fx).replace(/^\S+\s/, '');
    b.title = 'Lay ' + name + ' over the picture';
    const c = document.createElement('canvas'); c.width = 132; c.height = 60;
    const n = document.createElement('span'); n.textContent = name;
    b.appendChild(c); b.appendChild(n);
    b.onclick = () => {
      media.addEffektRahmen(editor, fx);
      oeffneEffekte();
      renderLayers(); renderAnimBar();
      toast(name + ' added - colour, area and speed are under the canvas.');
    };
    box.appendChild(b);
  });
}

function kachelnLaufen() {
  const panel = document.querySelector('[data-panel="effects"]');
  if (!panel || panel.hidden) { _kachelLauf = null; return; }
  kachelnBauen();
  const t = performance.now() / 2.5;
  document.querySelectorAll('#fx-tiles .fx-tile').forEach(b => {
    const c = b.querySelector('canvas');
    const ctx = c.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#0E7C86'; ctx.fillRect(0, 0, c.width, c.height);
    // two pale sheets, so the effect has something to lie over
    ctx.fillStyle = 'rgba(255,255,255,0.18)';
    ctx.fillRect(c.width * 0.18, c.height * 0.22, c.width * 0.26, c.height * 0.5);
    ctx.fillRect(c.width * 0.52, c.height * 0.3, c.width * 0.28, c.height * 0.46);
    try { media.malEffektVorschau(ctx, b.dataset.fx, c.width, c.height, t, null); }
    catch (e) { /* a tile that cannot draw stays plain - the effect still works */ }
  });
  _kachelLauf = requestAnimationFrame(kachelnLaufen);
}

function kachelnStarten() { if (!_kachelLauf) _kachelLauf = requestAnimationFrame(kachelnLaufen); }
document.getElementById('mode-rail')?.addEventListener('click', () => setTimeout(kachelnStarten, 0));
kachelnStarten();

{
  const regler = document.getElementById('fx-mark-size');
  const aus = document.getElementById('fx-mark-size-out');
  const zeigen = () => { if (aus && regler) aus.textContent = regler.value + '%'; };
  if (regler) {
    regler.oninput = () => {
      zeigen();
      const o = editor.active();
      if (media.istFrageKnoten(o)) { netzVon(o).forEach(k => groesseSetzen(k, markenGroesse())); editor.canvas.requestRenderAll(); }
      else if (istMarke(o)) { groesseSetzen(o, markenGroesse()); editor.canvas.requestRenderAll(); }
    };
    regler.onchange = () => { if (istMarke(editor.active())) editor.snapshot(); };
    const folgen = () => {
      const o = editor.active();
      if (istMarke(o)) { regler.value = Math.round((o.scaleX || 1) * 100); zeigen(); }
    };
    editor.canvas.on('selection:created', folgen);
    editor.canvas.on('selection:updated', folgen);
    editor.canvas.on('object:modified', folgen);
  }
}

// ---- Changing the font size afterwards -----------------------------------
// Applies to selected text: a plain text object directly, a text block by rebuild.
function istTextObj(o) { return !!o && (o.type === 'text' || o.type === 'i-text' || o.type === 'textbox'); }

function schriftGroesseAufAuswahl(size) {
  size = Math.max(6, Math.round(size || 0));
  if (!size) return;
  const list = editor.activeAll();
  let geaendert = 0;
  list.forEach(o => {
    if (isTextblock(o)) {
      o.tbSize = size;
      rebuildTextblock(o, o.tbHead || '', o.tbBody || '', { size });
      geaendert++;
    } else if (istTextObj(o)) {
      o.set('fontSize', size);
      o.setCoords();
      geaendert++;
    }
  });
  if (geaendert) { editor.canvas.requestRenderAll(); editor.snapshot(); }
}


// ---- Changing the font weight afterwards ---------------------------------
// The Normal/Bold field used to be read in exactly one place: when a NEW text
// was created. Switching it with something selected did nothing at all, so
// text stayed bold however often one tried - and since 'bold' is the default
// for new text, "it is always bold" was the whole experience.
//
// This deliberately touches plain text only, not text blocks or checklists.
// In those the weight is part of how they are built - a text block's heading
// is bold so it reads as a heading - and changing the object as a whole would
// flatten that. A single row of a checklist can be had through the
// "Split rows" button, which turns each row into an element of its own.
function schriftStaerkeAufAuswahl(gewicht) {
  gewicht = (gewicht === 'normal') ? 'normal' : 'bold';
  let geaendert = 0;
  editor.activeAll().forEach(o => {
    // Children of a group are not in activeAll(), so a block or a list is
    // passed over here without needing a check of its own.
    if (istTextObj(o)) {
      o.set('fontWeight', gewicht);
      o.setCoords();
      geaendert++;
    }
  });
  if (geaendert) { editor.canvas.requestRenderAll(); editor.snapshot(); }
  return geaendert;
}

// Bold or not? The templates carry the number 700, hand-made text carries the
// word - both have to read as Bold, or the field would tell a different story
// than the canvas.
function gewichtVon(o) {
  const gew = String((o && o.fontWeight) || 'normal');
  return (gew === 'bold' || parseInt(gew, 10) >= 600) ? 'bold' : 'normal';
}

// Selection changed -> show the weight the selected text actually has, instead
// of whatever was picked last.
function syncFontWeightInput() {
  const fw = document.getElementById('font-weight');
  if (!fw) return;
  const o = editor.activeAll().find(istTextObj);
  if (!o) return;
  fw.value = gewichtVon(o);
}

{
  const fw = document.getElementById('font-weight');
  if (fw) fw.addEventListener('change', () => {
    // With nothing selected the field keeps its old meaning: it is the setting
    // for the next text that gets created.
    if (editor.activeAll().some(istTextObj)) schriftStaerkeAufAuswahl(fw.value);
  });
}

// Selection changed → fill the field with the size of the selected text.
function syncFontSizeInput() {
  const fs = document.getElementById('font-size');
  if (!fs) return;
  const o = editor.activeAll().find(x => istTextObj(x) || isTextblock(x));
  if (!o) return;
  const val = isTextblock(o) ? (o.tbSize || 19) : Math.round(o.fontSize || 0);
  if (val) fs.value = val;
}

{
  const fs = document.getElementById('font-size');
  if (fs) fs.addEventListener('input', () => {
    // Only step in while text is selected - otherwise the value applies to new text.
    const hatText = editor.activeAll().some(x => istTextObj(x) || isTextblock(x));
    if (hatText) schriftGroesseAufAuswahl(+fs.value);
  });
}

// Shift+click on "Save" asks for the format again.
{
  const sb = document.getElementById('save-btn');
  if (sb) sb.addEventListener('click', e => {
    // stopImmediatePropagation deliberately bypasses the dispatcher above — so
    // this path needs its own guard, or an export error escapes unhandled.
    if (e.shiftKey) {
      e.preventDefault(); e.stopImmediatePropagation();
      safely(() => actions['save-as-new'](), 'action “save-as-new”');
    }
  }, true);
}

// ---- Selektion-Events koppeln --------------------------------------------
['selection:created', 'selection:updated', 'selection:cleared'].forEach(ev =>
  editor.canvas.on(ev, () => {
    // _suppressClear guards against rebuilds that briefly clear the selection
    // themselves (setting width or height on a multi-selection, say). Without
    // it, the active tool switched itself off while typing into a number field.
    if (_suppressClear) return;
    if (ev === 'selection:cleared' && _tool !== 'off'
        && !['rect', 'mark', 'paint', 'erase', 'restore'].includes(_tool)) setTool('off');
    renderSelBar(); updateRetouchPanel();
    planeUiAufbau();                      // Ebenen + Animationsleiste gebündelt
    if (ev !== 'selection:cleared') { syncFontSizeInput(); syncFontWeightInput(); }
  }));

// Keep the size and position fields in step while dragging or scaling with the mouse
['object:modified', 'object:scaling', 'object:moving'].forEach(ev =>
  editor.canvas.on(ev, () => {
    const o = editor.activeAll()[0];
    if (!o) return;
    const wi = document.getElementById('sel-w'), hi = document.getElementById('sel-h');
    const xi = document.getElementById('sel-x'), yi = document.getElementById('sel-y');
    const tippt = el => el && document.activeElement === el;
    if (wi && hi && !tippt(wi) && !tippt(hi)) {
      wi.value = Math.round(o.getScaledWidth());
      hi.value = Math.round(o.getScaledHeight());
    }
    if (xi && yi && !tippt(xi) && !tippt(yi)) {
      const act = editor.active();
      const c = (act && act.type === 'activeSelection' ? act : o).getCenterPoint();
      xi.value = Math.round(c.x);
      yi.value = Math.round(c.y);
    }
  }));

// Drop an element's preview image as soon as it changes - only then does it
// have to be rasterised again.
editor.canvas.on('object:modified', e => { if (e?.target) e.target.__thumb = null; });
// Colour, text and style changes go through the selection and end in a
// snapshot, not in object:modified - the preview then kept the old colour.
function vorschauVergessen() {
  const a = editor.canvas.getActiveObject();
  if (!a) return;
  (a.type === 'activeSelection' ? a.getObjects() : [a]).forEach(o => { o.__thumb = null; });
}

// ---- Undo/redo buttons enabled or disabled --------------------------------
// The rebuilds of the layer bar and the animation bar are batched: a single
// click used to trigger several complete rebuilds one after another
// (selection cleared → set → snapshot).

editor.onChange(() => {
  vorschauVergessen();
  const u = document.querySelector('[data-act="undo"]');
  const r = document.querySelector('[data-act="redo"]');
  if (u) u.disabled = !editor.canUndo();
  if (r) r.disabled = !editor.canRedo();
  bg.updateBgInfo(editor);
  // Safety net: if the target image of the active tool has vanished (cleared,
  // Ctrl+Z, template loaded), the artboard was locked afterwards - nothing
  // could be clicked any more, and the tool went on painting invisibly onto a
  // dead object.
  if (_tool !== 'off' && (!_toolTarget || _toolTarget.canvas !== editor.canvas)) {
    freeToolTarget();
    _tool = 'off';
    werkzeugFlagsZuruecksetzen();
    setToolStatus('Tool ended – the edited image is no longer there.');
  }
  planeUiAufbau();
});

// ---- Auto-Integration: eingebackenes Rautenmuster beim Einfügen entfernen --
const _origAddImg = editor.addImageUrl.bind(editor);
editor.addImageUrl = async (url, opts) => {
  const img = await _origAddImg(url, opts);
  try {
    if (!opts?.silent && img && img._element && hasCheckerboardBorder(img._element)) {
      status('✨ Pattern found – removing only the checkerboard…');
      const cleaned = await removeCheckerboard(img._element);   // nur Muster weg, Weiß bleibt
      // null = nothing was found. This used to return the unchanged image, which
      // was taken as "edited" all the same - a 2 MB JPEG so became about 25 MB
      // of base64 in every undo step and in the saved design.
      if (cleaned) {
        img.bgRemoved = true; img._work = null;
        retouch.replaceElement(img, cleaned); editor.snapshot();
        status('✅ Pattern removed', 'green');
      } else {
        status('Ready.', '#888');
      }
    }
  } catch (e) { console.warn('Muster-Erkennung:', e); status('Ready.', '#888'); }
  return img;
};

// ---- Init -----------------------------------------------------------------
// Every step wrapped on its own: an error in the template list must no longer
// take down the library, the title and the loading of the file with it.
boot('Template list', () => bg.loadTemplateList(editor));
// The library recognises SVGs itself and sends them through the import instead
// of placing them as a flat image.
boot('SVG handler', () => {
  if (typeof lib.setSvgHandler === 'function') {
    lib.setSvgHandler((text, asGroup) => importSvgText(text, asGroup));
  }
});
boot('Library', () => {
  if (typeof initLibrary !== 'function') throw new Error('initLibrary missing (old library.js in the browser cache? Ctrl+F5)');
  initLibrary(editor);
});
boot('Selection bar', () => renderSelBar());
boot('Retouch panel', () => updateRetouchPanel());
boot('Shell', () => initUi());

// The template currently loaded - ONE source of truth on the editor object, no
// matter whether it was opened from the management page (?template=…) or by
// clicking a tile (applyTemplate). "Save template" then asks whether to update
// an existing template or create a new one.
function currentTemplateId() { return editor._templateId || null; }
function setTemplateId(id)   { editor._templateId = id || null; }
if (CONFIG.tplData?.id) setTemplateId(CONFIG.tplData.id);

// Pre-fill the title (the name is kept when carrying on editing).
{
  const t = CONFIG.libData?.title || CONFIG.postData?.title || CONFIG.tplData?.title || '';
  const ti = document.getElementById('title-input');
  if (ti && t) ti.value = t;
}

// Vorhandene Ausgabe geöffnet? → Knopf „Speichern" (gleiches Format) statt „Speichern als…".
if (CONFIG.libData?.item_id || CONFIG.libData?.nc_path) {
  const b = document.querySelector('[data-act="save-as"]');
  if (b) { b.textContent = '💾 Save'; b.dataset.act = 'save-existing'; b.title = 'Overwrite the existing output in the same format'; }
} else if (_saveKindVomPost) {
  saveKnopfZeigt(_saveKind);
}

// Fabric builds an image object even when its source answers 404: the element
// is on the artboard, the picture is not, and the result looks exactly like an
// empty draft. Counting them is the only way to tell those two apart - and the
// difference decides whether the user should rebuild or go looking for a file.
/* Every way a drawing comes onto the artboard runs through here, so the old
   element effects are converted in ONE place. Four call sites used to restore
   directly - a conversion added to three of them would have been a bug waiting
   in the fourth. */
async function ladeCanvas(json, opts) {
  const ok = await io.restoreCanvas(editor, json, opts);
  if (ok) {
    const umgewandelt = media.rahmenAusAltenEffekten(editor);
    if (umgewandelt) {
      renderLayers(); renderAnimBar();
      toast(umgewandelt + ' effect' + (umgewandelt === 1 ? '' : 's')
            + ' turned into effect frames - they can be moved now.');
    }
  }
  return ok;
}

function fehlendeBilder() {
  return editor.realObjects().filter(o => o && o.type === 'image'
    && !(o._element && o._element.naturalWidth > 0)).length;
}

(async function restoreInitial() {
  try {
    const post = CONFIG.postData, libD = CONFIG.libData, tpl = CONFIG.tplData;
    // frisch=true: the history starts at the LOADED state. Without it, the empty
    // canvas from before the load would be the oldest undo step - and an
    // accidental Ctrl+Z would have wiped everything.
    if (tpl?.canvas_json) {
      if (tpl.width && tpl.height) { editor.setSize(tpl.width, tpl.height); fit(); }
      status('⏳ Loading template…');
      if (await ladeCanvas(tpl.canvas_json, { frisch: true })) {
        status('Editing template – “💾 Save” under Template updates it.', '#0E7C86');
      }
      return;
    }
    // Report "Ready." only on a complete load. This message used to overwrite
    // any red warning immediately ("not all images loaded", "data unreadable")
    // - and the user took the half-empty editor for their file.
    if (post?.canvas_json) {
      status('⏳ Loading draft…');
      if (await ladeCanvas(post.canvas_json, { frisch: true })) {
        const fehlen = fehlendeBilder();
        status(fehlen
          ? '⚠️ ' + fehlen + ' image(s) in this draft point at a file that is no longer there.'
          : 'Ready.', fehlen ? '#854F0B' : '#888');
      }
      return;
    }
    // No design saved for this post - but the picture hanging on it can still
    // be put on the canvas. Opening the Studio from a post and finding an empty
    // board is the one thing nobody expects; it happens whenever the image was
    // attached in the post rather than built here. A GIF or a video is left to
    // the buttons in the banner: flattening either one onto the canvas and
    // saving over it would cost the animation.
    if (post?.image_url) {
      try {
        await editor.addImageUrl(post.image_url, { silent: true, fill: true });
        editor.resetHistory();
        status('Image from the post – edit and save.', '#888');
      } catch (e) {
        editor._ladefehler = true;
        status('❌ Image could not be loaded – file may be missing in Nextcloud', 'red');
        toast('Image not found', 'err');
      }
      return;
    }
    // Nothing was built here, but something hangs on the post. A GIF can at
    // least be shown: addImageUrl takes its first frame. A video cannot, so
    // there the line below is all there is - still better than a blank artboard
    // that explains nothing.
    const animDatei = (post && (post.gif || post.video)) || '';
    const animUrl = (post && (post.gif ? post.gif_url : post.video_url)) || '';
    if (animDatei && animUrl) {
      if (/\.gif$/i.test(animDatei)) {
        try {
          await editor.addImageUrl(animUrl, { silent: true, fill: true });
          editor.resetHistory();
          status('⚠️ Still frame of the animated file on this post. Saving as an '
               + 'image replaces it – the animation goes back to your outputs.', '#854F0B');
        } catch (e) {
          editor._ladefehler = true;
          status('❌ The file on this post could not be loaded', 'red');
          toast('File not found', 'err');
        }
      } else {
        status('This post carries a video that was not built here. '
             + 'Open it from the banner above.', '#854F0B');
      }
      return;
    }
    if (libD?.canvas_json) {
      status('⏳ Loading draft…');
      if (await ladeCanvas(libD.canvas_json, { frisch: true })) status('Ready.', '#888');
      return;
    }
    if (libD?.image_url) {
      // When the load fails (file deleted in Nextcloud), the editor used to sit
      // there silently empty - and the next click on "save" overwrote the entry
      // with an empty image.
      try {
        await editor.addImageUrl(libD.image_url, { silent: true, fill: true });
        editor.resetHistory();
        status('Ready.', '#888');
      } catch (e) {
        editor._ladefehler = true;
        status('❌ Image could not be loaded – file may be missing in Nextcloud', 'red');
        toast('Image not found', 'err');
      }
    } else {
      status('Ready.', '#888');
    }
  } catch (e) {
    console.warn('restoreInitial:', e);
    editor._locked = false;
    editor._ladefehler = true;
    status('❌ Draft could not be loaded', 'red');
  } finally {
    // The state right after opening counts as "saved".
    window.dispatchEvent(new CustomEvent('studio:geladen'));
  }
})();

// Make sure elements are normally clickable and selectable (no tool and no
// drawing layer blocking the selection after a load).
// ---- Zooming with Ctrl+wheel over the artboard ---------------------------
// For fine retouching: zoom in first, then work with a small brush.
// Without Ctrl the wheel still scrolls the page - otherwise scrolling keeps
// getting caught in the image.
boot('Wheel zoom', () => {
  const host = document.querySelector('.canvas-host');
  if (!host) return;
  host.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    zeigeZoom(editor.zoom(e.deltaY < 0 ? 'in' : 'out'));
    editor.canvas.calcOffset();   // sonst treffen Pipette und Rechteck daneben
  }, { passive: false });
});

boot('Release selection', () => {
  _tool = 'off';
  editor.canvas.skipTargetFind = false;
  editor.canvas.selection = true;
  const ov = document.getElementById('rect-overlay'); if (ov) ov.style.display = 'none';
  editor.canvas.getObjects().forEach(o => { if (!o._snap) { o.selectable = true; o.evented = true; } });
  editor.canvas.requestRenderAll();
});
// No status('Ready.') here any more: restoreInitial carries on asynchronously,
// and "Ready." then overwrote the "⏳ loading…" straight away - while saving
// was still being refused at that moment. restoreInitial now sets the message
// itself, once everything really is there.

// ---- Guard against leaving by accident ------------------------------------
// A click on a tile in the right-hand panel used to navigate away at once and
// discard everything unsaved - without asking.
// editor._rev counts every change, only ever upwards. The length of the history
// is no use for that: it is capped and stands still past about 30 steps - after
// which the prompt would never have fired again.
let _gespeichertStand = editor._rev;
function ungespeicherteAenderungen() {
  return editor._rev > 0 && editor._rev !== _gespeichertStand;
}
function alsGespeichertMerken() { _gespeichertStand = editor._rev; }
window.addEventListener('studio:output-changed', alsGespeichertMerken);
// After loading a file or template the state is "as saved" - otherwise the
// Studio asked about unsaved changes right after opening.
window.addEventListener('studio:geladen', alsGespeichertMerken);
// Saving a template also makes the state clean.
window.addEventListener('studio:vorlage-gespeichert', alsGespeichertMerken);
window.addEventListener('beforeunload', e => {
  if (!ungespeicherteAenderungen()) return;
  e.preventDefault();
  e.returnValue = '';   // Browser zeigt seine Standard-Rückfrage
});
// For navigation within the page (tile clicks in library.js).
window.studioDarfVerlassen = function () {
  if (!ungespeicherteAenderungen()) return true;
  return window.confirm('There are unsaved changes.\n\n' +
                        'Really leave? The changes will be lost.');
};

// "Ready." is set by restoreInitial alone - and only when everything really is
// loaded. This line used to overwrite red loading-error messages (including on
// a parse error, where _locked is never set).
