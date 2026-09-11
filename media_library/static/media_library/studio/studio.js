// studio.js – Einstiegspunkt. Verdrahtet DOM ↔ Module.
import { CONFIG } from './config.js';
import { Editor, fabric } from './editor.js';
import { toast, status, modal, wegDamit } from './util.js';
import * as bg from './background.js';
import * as io from './io.js';
// Namensraum-Import: Fehlt ein Export (z. B. weil der Browser eine alte
// library.js aus dem Cache hat), stirbt hier NICHT das ganze Modul.
import * as lib from './library.js';
const { initLibrary, refreshOutput } = lib;
import * as media from './media.js';
import { removeBackground, floodFillTransparent, recolorRegion, recolorSimilarAll, removeColorGlobal, hasCheckerboardBorder, removeCheckerboard } from './cutout.js';
import * as retouch from './retouch.js';
import { buildContext } from './toolbar.js';
import { mountShell, initUi } from './ui.js';

// Build rail, mode panels and the media panel from the declaration in
// toolbar.js. This has to happen BEFORE anything below looks an element up by
// id — every control the rest of this file talks to is created right here.
mountShell();

// Kapselt einen Initialisierungsschritt. Ohne das brach EIN Fehler irgendwo in
// der langen Startsequenz alles Folgende ab – inklusive der Knopf-Verdrahtung.
// Ergebnis war eine Seite, auf der schlicht nichts mehr reagierte.
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

// localStorage wirft in manchen Browser-/Datenschutzeinstellungen schon beim
// bloßen Zugriff (Privatmodus, blockierte Cookies, eingebettete Seite). Das
// legte früher die gesamte Seite still.
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
  // Untergrenze: Ist der Host gerade unsichtbar (clientWidth 0), kämen negative
  // Maße heraus – der Browser macht daraus eine Milliarden-Pixel-Bitmap und der
  // Tab stürzt ab.
  const w = Math.max(120, host.clientWidth - 16);
  const h = Math.max(120, host.clientHeight - 16);
  editor._lastFit = { w, h };
  editor.fitTo(w, h);
  // Fabric merkt sich die Canvas-Position. Verschiebt sich der Canvas (Leiste
  // auf/zu, Scrollen), trafen Klicks mit Pipette/Rechteck sonst danebem.
  editor.canvas.calcOffset();
}
window.addEventListener('resize', fit);
window.addEventListener('scroll', () => editor.canvas.calcOffset(), { passive: true });
requestAnimationFrame(fit);
// Reagiert auch dann, wenn sich die Größe ohne Fensteränderung ändert
// (z.B. eingeklappte Leiste) – das rAF allein feuerte manchmal zu früh.
if (window.ResizeObserver) {
  const _host = document.querySelector('.canvas-host');
  if (_host) {
    // Über requestAnimationFrame entkoppeln: fit() ändert selbst die
    // Canvas-Größe und würde den Beobachter sofort erneut auslösen. Der Browser
    // meldet das als „ResizeObserver loop completed with undelivered
    // notifications" – harmlos, aber es landete im Fehlerbanner und sah aus
    // wie ein echter Fehler.
    let geplant = false;
    new ResizeObserver(() => {
      if (geplant) return;
      geplant = true;
      requestAnimationFrame(() => { geplant = false; fit(); });
    }).observe(_host);
  }
}

// Zoom-Stand kurz anzeigen (× über der Einpassung).
function zeigeZoom(z) {
  const f = z || editor.zoomFactor();
  status(`Zoom ${Math.round(f * 100)} %`, '#888');
}

// ---- Sidebar-Sektionen ein-/ausklappen (Freistellen-Panel bleibt offen) ---
document.querySelectorAll('.sidebar-section h3').forEach(h => {
  if (h.parentElement.id === 'retouch-section') return;   // immer aufgeklappt
  h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
});

// ---- Canvas-Hintergrundfarbe ('' = transparent) --------------------------
// EIN Weg für die Hintergrundfarbe. Früher gab es zwei Farbwähler mit derselben
// id: einer setzte nur die Farbe, der andere löschte zusätzlich das
// Hintergrundbild – für den Nutzer nicht unterscheidbar, und das Bild
// verschwand unerwartet. Jetzt bleibt das Bild liegen; wenn es die Farbe
// verdeckt, weist das Studio darauf hin.
function setCanvasFarbe(farbe) {
  // Nur die Hintergrund*farbe* setzen – ein vorhandenes Hintergrund*bild*
  // (z. B. dein Teal-Template) NICHT anfassen, sonst verschwindet es unerwartet.
  // Verdeckt das Bild die Farbe, weist das Studio darauf hin; entfernen kann man
  // es bewusst über „🚫 Remove background image".
  editor.canvas.backgroundColor = farbe || '';
  editor.canvas.requestRenderAll();
  editor.snapshot();
  const pick = document.getElementById('bg-color');
  if (pick && farbe) pick.value = farbe;
  if (farbe && editor.canvas.backgroundImage) {
    status(`Background: ${farbe} – still covered by the background image (use “🚫 Remove background image” to show it)`, '#B26A00');
  } else {
    status(farbe ? `Background: ${farbe}` : 'Background transparent.', '#198754');
  }
}
{
  const pick = document.getElementById('bg-color');
  if (pick) pick.oninput = () => setCanvasFarbe(pick.value);
}

// ---- Kleiner Dialog für eine frei eingegebene Canvas-Größe ---------------
function askSize(w0, h0) {
  return new Promise(resolve => {
    const back = document.createElement('div');
    back.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:9998;
      display:flex;align-items:center;justify-content:center;`;
    back.innerHTML = `
      <div style="background:#fff;border-radius:10px;padding:16px;width:280px;box-shadow:0 10px 40px rgba(0,0,0,.3)">
        <div style="font-weight:700;color:#0E7C86;margin-bottom:10px">Eigene Canvas-Größe</div>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
          <label style="font-size:.75rem;color:#666">Breite</label>
          <input type="number" id="cs-w" value="${w0}" min="50" max="6000"
                 style="width:80px;padding:5px;border:1px solid #ccc;border-radius:4px">
          <label style="font-size:.75rem;color:#666">Höhe</label>
          <input type="number" id="cs-h" value="${h0}" min="50" max="6000"
                 style="width:80px;padding:5px;border:1px solid #ccc;border-radius:4px">
        </div>
        <div style="display:flex;gap:6px;justify-content:flex-end">
          <button id="cs-no" class="tbtn">Abbrechen</button>
          <button id="cs-ok" class="tbtn primary">Übernehmen</button>
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

// ---- Leisten ausklappen: Canvas voll, Werkzeuge auf Zuruf ----------------
// Klick auf den Griff = Leiste dauerhaft weg / wieder fest.
// Ist sie weg, schwebt sie beim Überfahren des Griffs über dem Canvas.
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

    // Einblenden beim Überfahren des Griffs
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

// Eine gemeinsame Palette für Text UND Formen.
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
    if (t && _hex(t.fill) === _hex(col)) t.set('fill', autoContrast(col));
    editor.canvas.requestRenderAll(); editor.snapshot();
  }
  else if (o && o.shapeKind) { o.set(o.fill ? 'fill' : 'stroke', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
});

// (Der zweite Hintergrund-Farbwähler ist entfallen – siehe setCanvasFarbe.)

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

// Gemerktes Speicher-Format (image|gif|video). Nach der ersten Wahl wird nicht
// mehr gefragt – der Knopf speichert still im gleichen Format.
// Beim Öffnen einer vorhandenen Ausgabe das dort verwendete Format übernehmen.
let _saveKind = CONFIG.libData?.kind && CONFIG.libData.kind !== 'image'
                ? CONFIG.libData.kind : null;
let _speichertGerade = false;
async function speichereAls(kind) {
  // Ein zweiter Klick während des Speicherns öffnete einen zweiten
  // Namensdialog und erzeugte zwei Ausgaben. Der Guard in io.saveImage deckt
  // nur den Bild-Weg ab, GIF und Video liefen ungebremst.
  if (_speichertGerade) { toast('Speichert bereits…', 'err'); return; }
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
  else { ok = await io.saveImage(editor); refreshOutput(); }
  // Nichts gespeichert (lädt noch, abgebrochen, Fehler)? Dann auch keine
  // Erfolgsmeldung – die überschrieb vorher sofort die eigentliche Begründung.
  if (!ok) return;
  // Knopf umbenennen, damit klar ist: ab jetzt wird direkt gespeichert.
  // Beide möglichen Zustände suchen: sobald eine Ausgabe geöffnet ist, heißt
  // das Attribut „save-existing" – der alte Selektor griff dann ins Leere.
  const btn = document.querySelector('[data-act="save-as"], [data-act="save-existing"]');
  if (btn) {
    const lbl = kind === 'gif' ? '💾 GIF speichern' : kind === 'video' ? '💾 Video speichern' : '💾 Speichern';
    btn.textContent = lbl;
    btn.title = 'Saves in the same format. Shift+Click for a different format.';
  }
}

// ---- Toolbar-Aktionen (data-act) -----------------------------------------
const actions = {
  save:        async () => {
    if (_speichertGerade) { toast('Speichert bereits…', 'err'); return; }
    _speichertGerade = true;
    try { await io.saveImage(editor); refreshOutput(); } finally { _speichertGerade = false; }
  },
  'save-as':   async () => {
    const titleEl = document.getElementById('title-input');
    if (!titleEl || !titleEl.value.trim()) {
      if (titleEl) { titleEl.style.border = '2px solid #dc3545'; titleEl.focus(); }
      status('⚠️ Please enter a title first!', '#dc3545');
      setTimeout(() => { if (titleEl) titleEl.style.border = ''; }, 2500);
      return;
    }
    // Format nur beim ersten Mal (oder nach „als…") abfragen und merken.
    let kind = _saveKind;
    if (!kind) {
      kind = await modal('Save as…', 'What would you like to save?', [
        { label: '🖼 Image (PNG)', value: 'image' },
        { label: '🎞 GIF (mit Animationen)', value: 'gif' },
        { label: '🎬 Video (mit Animationen)', value: 'video' },
      ]);
      if (!kind) return;   // abgebrochen
    }
    await speichereAls(kind);
  },
  // Format bewusst neu wählen (fragt wieder).
  'save-as-new': async () => { _saveKind = null; await actions['save-as'](); },
  // Vorhandene Ausgabe: nur speichern (gleiches Format, überschreibt).
  'save-existing': async () => {
    if (_speichertGerade) { toast('Speichert bereits…', 'err'); return; }
    let kind = _saveKind || CONFIG.libData?.kind || 'image';
    // Animationen gesetzt, aber die Datei ist ein PNG? Vorher wurde still ein
    // Standbild gespeichert und die Animationen waren im Ergebnis nicht drin.
    if (kind === 'image' && media.hasAnimations(editor)) {
      const wahl = await modal('Animationen erkannt',
        'This element has animations, but the opened file is an image. How to save?',
        [ { label: '🖼 As image (no animation)', value: 'image' },
          { label: '🎞 Als GIF',                   value: 'gif' },
          { label: '🎬 Als Video',                 value: 'video' },
          { label: 'Cancel',                    value: null } ]);
      if (!wahl) return;
      kind = wahl;
      _saveKind = wahl;
    }
    _speichertGerade = true;
    try {
      if (kind === 'gif') await media.exportGif(editor);
      else if (kind === 'video') await media.exportVideo(editor);
      else { await io.saveImage(editor); refreshOutput(); }
    } finally {
      _speichertGerade = false;
    }
  },
  download:    async () => {
    // Gleiches Format wie beim Speichern (▾ Format). Noch nichts gewählt:
    // animiert → GIF, sonst → PNG.
    const kind = _saveKind || (media.hasAnimations(editor) ? 'gif' : 'image');
    if (kind === 'gif')        await media.downloadGif(editor);
    else if (kind === 'video') await media.downloadVideo(editor);
    else                       io.downloadImage(editor);
  },
  'new':       async () => {
    const ok = await modal('Neu anfangen?', 'Leert den Editor (alle Elemente + Hintergrund). Nicht Gespeichertes geht verloren.', [
      { label: '🆕 Ja, neuer Editor', value: true },
      { label: 'Cancel', value: false },
    ]);
    if (!ok) return;
    editor.clearAll();
    // Bindung an die zuvor geöffnete Ausgabe lösen: sonst hätte „Speichern"
    // die alte Datei mit dem neuen, leeren Entwurf überschrieben – und die
    // Warnung eines früheren Ladefehlers wäre weiter erschienen.
    CONFIG.libData = null;
    io.merkeNamen(null);       // neuer Entwurf → auch der Name wird neu vergeben
    setTemplateId(null);
    editor._ladefehler = false;
    _saveKind = null;
    editor.resetHistory();
    {
      const b = document.querySelector('[data-act="save-existing"]');
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
    // Beide Leisten in den schwebenden Zustand bringen – die Randgriffe bleiben
    // sichtbar, per Überfahren tauchen die Werkzeuge wieder auf.
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
             || (document.getElementById('text-input')?.value.trim()) || 'Dein Text';
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
    // Alle Felder optional lesen: fehlt eines im Gerüst, soll trotzdem Text
    // eingefügt werden statt die Aktion mit einem TypeError abzubrechen.
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
      { label: '1080 × 1080 (Quadrat)', value: [1080, 1080] },
      { label: '1080 × 1350 (LinkedIn Hochformat)', value: [1080, 1350] },
      { label: '1024 × 1536 (Hochformat 2:3)', value: [1024, 1536] },
      { label: '1200 × 628 (Link)', value: [1200, 628] },
      { label: '1920 × 1080 (Video)', value: [1920, 1080] },
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
  'export-gif':   () => media.exportGif(editor),
  'export-video': () => media.exportVideo(editor),
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
    status('🧩 Entferne Schachbrettmuster…');
    try {
      const out = await removeCheckerboard(o._element);
      if (!out) { status('No checkerboard pattern found – image unchanged', '#888'); return; }
      o.bgRemoved = true; o._work = null;
      retouch.replaceElement(o, out); editor.snapshot();
      status('✅ Pattern removed', 'green');
    } catch (e) { status('❌ ' + (e.message || 'Fehler'), 'red'); }
  },
  'restore-post': async () => {
    if (!CONFIG.postData?.canvas_json) return;
    if (!window.studioDarfVerlassen || window.studioDarfVerlassen()) {
      status('⏳ Loading draft…');
      await io.restoreCanvas(editor, CONFIG.postData.canvas_json);
      status('Bereit.', '#888');
    }
  },
  'post-bg':      () => CONFIG.postData?.id && bg.setBackgroundImage(editor, `/library/studio/api/post-image/${CONFIG.postData.id}/`),
  'post-overlay': () => CONFIG.postData?.id && editor.addImageUrl(`/library/studio/api/post-image/${CONFIG.postData.id}/`),
  'go-back': (btn) => {
    // Immer im gleichen Tab zur Herkunftsseite navigieren. (Früher wurde
    // window.close() versucht – das schloss den Tab und man landete außerhalb
    // der Seite.) Bei ungespeicherten Änderungen greift der beforeunload-Schutz.
    let url = (btn && btn.getAttribute('data-back')) || '/planner/uebersicht/';
    // Nur seiteneigene Ziele zulassen; sonst sichere Übersicht.
    if (!/^\//.test(url) || url.indexOf('/library/studio') !== -1) url = '/planner/uebersicht/';
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
    status('Build a template: background, logo, text fields – then “💾 Save template”.', '#888');
  },
};

// Aktuelle Leinwand als wiederverwendbare Vorlage speichern.
async function saveAsTemplate() {
  // Lädt der Editor noch? Dann wäre die Fläche halb leer – und ein „Vorlage
  // aktualisieren" hätte die bestehende Vorlage mit dem leeren Stand
  // überschrieben. Das war unwiederbringlich.
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
  // Eine Quelle der Wahrheit für die aktuell geladene Vorlage – egal ob sie über
  // die Verwaltung (?template=…) oder per Klick auf eine Kachel geöffnet wurde.
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
  // Doppelte Namen vermeiden (nur beim Neuanlegen).
  if (!updateExisting) {
    try {
      const r = await fetch(CONFIG.urls?.apiTemplates || '/library/studio/api/templates/');
      const dj = await r.json();
      const clash = (dj.templates || []).some(
        t => (t.title || '').trim().toLowerCase() === title.trim().toLowerCase());
      if (clash) {
        const go = await modal('Name schon vergeben',
          `A template named “${title.trim()}” already exists. Do you still want to create a second one with the same name?`,
          [ { label: 'Cancel (choose a different name)', value: null },
            { label: 'Trotzdem anlegen',                 value: true } ]);
        if (!go) return;
      }
    } catch (e) { /* Prüfung ist nur Komfort – bei Fehler normal weiter */ }
  }
  // Offene Pinsel-/Markierungsstände in echte Bilder umwandeln – ein Canvas als
  // Bild-Element überlebt die Serialisierung ins canvas_json nicht.
  await retouch.vorschauenUebernehmen(editor.canvas);
  let dataUrl, canvasJson;
  try {
    retouch.beendeVorschauen(editor.canvas);               // rote Markierung nie mitspeichern
    const preview = editor.exportDataURL({ multiplier: 0.4 });
    dataUrl = editor.exportDataURL({ multiplier: 1 });     // Vorschau-PNG (ohne Raster)
    canvasJson = io.buildCanvasJson(editor, preview);      // Layout: Hintergrund + Logo + Textfelder
  } catch (e) { toast('Export fehlgeschlagen', 'err'); status('❌ Export fehlgeschlagen', 'red'); return; }
  // Leere Fläche ist fast immer ein Versehen (z.B. zu früh geklickt) und würde
  // eine funktionierende Vorlage durch nichts ersetzen.
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
      // Ohne diese Prüfung scheiterte res.json() an der HTML-Fehlerseite und der
      // Nutzer sah „SyntaxError: Unexpected token '<'".
      const grund = res.status === 413 ? 'Template too large for the server'
                  : res.status === 403 ? 'Sitzung abgelaufen – bitte neu anmelden'
                  : 'Server-Fehler ' + res.status;
      toast(grund, 'err'); status('❌ ' + grund, 'red'); return;
    }
    const d = await res.json();
    if (d.ok) {
      setTemplateId(d.id);   // ab jetzt weiter dieselbe Vorlage aktualisieren
      toast(d.updated ? 'Template updated' : 'Template saved', 'ok');
      status(d.updated ? '✅ Template updated.' : '✅ Saved as template.', '#198754');
      // Stand als gespeichert markieren – sonst fragte das Studio auch direkt
      // nach dem Speichern einer Vorlage noch nach ungespeicherten Änderungen.
      window.dispatchEvent(new CustomEvent('studio:vorlage-gespeichert'));
      bg.loadTemplateList(editor);
    } else { toast('Fehler: ' + (d.error || ''), 'err'); status('❌ ' + (d.error || 'Fehler'), 'red'); }
  } catch (e) { toast('Save failed', 'err'); status('❌ ' + (e.message || e), 'red'); }
}
function _cookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? decodeURIComponent(m.pop()) : '';
}

// Bestehendes Bild eines anderen Posts übernehmen. Es wird auf die Leinwand
// gelegt; beim Speichern entsteht eine Kopie, die an DIESEN Post gehängt wird.
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
  const esc = s => String(s || '').replace(/[<>&"]/g, m => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[m]));
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
    // Die meisten Aktionen sind async. Ohne dieses catch blieb bei einem Fehler
    // nur „💾 Speichert…" stehen – für den Nutzer sah das aus wie ein Hänger.
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
  status('✂ Stelle frei…');
  try {
    const cleaned = await removeBackground(o._element, { tol: 55 });
    // removeBackground schützt helle, farbneutrale Pixel bewusst (Weiß, Off-White,
    // Hellgrau), damit weiße Bildinhalte wie Kittel oder Icons stehen bleiben.
    // Bei weißem oder kariertem Hintergrund bleibt deshalb ALLES stehen – der
    // Knopf sah dann aus, als täte er nichts. Jetzt sagt er, was los ist.
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
    status('✅ Freigestellt', 'green');
  } catch (e) {
    status('❌ Freistellen fehlgeschlagen', 'red');
    toast(e.message || 'Fehler beim Freistellen', 'err');
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

// Gibt das aktuelle Werkzeug-Ziel frei. Wichtig nach dem Laden einer Datei oder
// nach Undo: die alten Objekte sind dann nicht mehr auf dem Canvas, halten aber
// über _work/_mask/_origImg mehrere Vollbild-Canvas im Speicher fest.
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

// Gibt die Arbeitsfläche wieder frei: Objekte anklickbar, Auswahl möglich,
// normaler Mauszeiger. Bleibt einer dieser Schalter hängen, wirkt das Studio
// komplett eingefroren, obwohl technisch alles läuft.
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

// Zielbild bestimmen: aktives Bild, sonst das oberste Bild auf dem Canvas.
function targetImage() {
  const a = editor.active();
  if (a && a.type === 'image') return a;
  const imgs = editor.realObjects().filter(x => x.type === 'image');
  return imgs.length ? imgs[imgs.length - 1] : null;
}

function setTool(tool) {
  // Zeigt _toolTarget noch auf ein Objekt, das inzwischen ersetzt wurde
  // (Vorlage geladen, Strg+Z)? Dann ist es verwaist: Werkzeuge taten anschließend
  // still gar nichts mehr. Aufräumen und neu bestimmen.
  if (_toolTarget && _toolTarget.canvas !== editor.canvas) freeToolTarget();

  const o = targetImage();
  if (tool !== 'off' && !o) {
    // WICHTIG: erst die Arbeitsfläche entsperren, dann abbrechen. Vorher kehrte
    // die Funktion hier zurück, während skipTargetFind/selection vom vorherigen
    // Zieh-Werkzeug noch gesetzt waren – dann ließ sich gar nichts mehr
    // anklicken, und jeder Rettungsversuch über einen anderen Werkzeug-Knopf
    // lief in genau dieses return.
    werkzeugFlagsZuruecksetzen();
    _tool = 'off';
    toast('No image present – insert an image first', 'err');
    return;
  }
  // Beim Verlassen des Markier-Modus offene (nicht angewendete) Markierung verwerfen.
  if ((_tool === 'mark' || _tool === 'rect') && _toolTarget && retouch.hasMask(_toolTarget)) {
    retouch.clearMask(_toolTarget);
    retouch.commitWork(_toolTarget).then(() => editor.canvas.requestRenderAll())
      .catch(e => console.warn('commitWork beim Werkzeugwechsel:', e));
  }
  // Rote Markierungs-Vorschau beenden, sonst bleibt sie im Bild stehen.
  retouch.beendeVorschauen(editor.canvas);
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
  // Pinselgröße nur bei den Werkzeugen zeigen, die sie auch benutzen.
  const brushRow = document.getElementById('brush-row');
  if (brushRow) brushRow.style.display = ['paint', 'erase', 'restore', 'mark'].includes(tool) ? 'flex' : 'none';
  // Aktives Werkzeug hervorheben – vorher war nicht erkennbar, welches an ist.
  document.querySelectorAll('#retouch-body [data-tool]').forEach(b => {
    b.classList.toggle('primary', b.dataset.tool === tool && tool !== 'off');
  });
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
    setToolStatus('💧 Background colour removed – keep clicking or turn the tool off');
  } catch (e) { setToolStatus('❌ Fehler'); }
}

async function doSwapAt(o, px, py) {
  const hex = document.getElementById('recolor-color')?.value || '#ffffff';
  try {
    // Zusammenhängende Fläche ab dem Klickpunkt umfärben ("näheres Umfeld").
    const out = await recolorRegion(o._element, px, py, hex, 40);
    o._work = null;
    retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('🎨 Colour swapped – keep clicking or turn the tool off');
  } catch (e) { console.error('Farbtausch:', e); setToolStatus('❌ Fehler'); }
}

// doRecolorAt ist entfallen: die Funktion war bis auf die Toleranz identisch
// mit doSwapAt (beide recolorRegion). Zwei Knöpfe für dieselbe Sache.

// Alle farbähnlichen Flächen im GANZEN Bild ab dem Klickpunkt umfärben
// (z. B. alle roten Stellen auf einmal). Nutzt dieselbe gewählte Farbe wie
// „Recolour area". Transparenz bleibt erhalten.
// Pipette: nimmt die Farbe an der Klickstelle vom SICHTBAREN Canvas auf
// (inkl. Hintergrundfarbe und beliebiger Bilder) und setzt sie als Umfärb-Farbe.
// So wählt man die Zielfarbe per Klick statt über die Palette.
function _showRecolorSwatch(hex) {
  const sw = document.getElementById('recolor-swatch');
  if (sw) { sw.style.background = hex || 'transparent'; sw.title = hex ? ('picked colour: ' + hex) : 'no colour picked'; }
}

// Einen einzelnen Pixel aus einem fabric-Bildobjekt an der Szenen-Position pt lesen.
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

// Farbe an der Klickstelle bestimmen – robust und ohne getaintete Gesamt-Canvas:
// 1) Bild-Objekt unter dem Klick, 2) Hintergrundbild, 3) Hintergrundfarbe.
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

// Umfärben mit der zuvor aufgenommenen Farbe: entweder nur die zusammenhängende
// Fläche (all=false) oder alle gleichfarbigen Flächen im Bild (all=true).
async function doRecolorWith(o, px, py, hex, all) {
  try {
    const out = all ? await recolorSimilarAll(o._element, px, py, hex, 45)
                    : await recolorRegion(o._element, px, py, hex, 40);
    o._work = null; retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('🎨 Recoloured – click more areas, or press the tool button again to pick a new colour');
  } catch (e) { console.error('Recolour:', e); setToolStatus('❌ Error'); }
}

async function doSwapAllAt(o, px, py) {
  const hex = document.getElementById('recolor-color')?.value || '#ffffff';
  try {
    const out = await recolorSimilarAll(o._element, px, py, hex, 45);
    o._work = null;
    retouch.replaceElement(o, out); editor.snapshot();
    setToolStatus('🎨 All matching areas recoloured – keep clicking or turn the tool off');
  } catch (e) { console.error('Recolour all:', e); setToolStatus('❌ Error'); }
}

// Ein Pinselschritt. `endgueltig` nur beim Loslassen der Maustaste:
// Vorher wurde bei JEDER Mausbewegung ein Vollauflösungs-PNG kodiert
// (bei einem 12-Megapixel-Bild ~200 ms pro Tick, 60 Ticks pro Strich). Die
// Aufrufe stapelten sich, der Browser stand minutenlang, und weil sie in
// beliebiger Reihenfolge zurückkamen, verschwanden Striche wieder.
// Während des Ziehens zeigen wir jetzt direkt die Arbeits-Canvas (kostenlos).
async function paintAt(o, px, py, endgueltig = false) {
  if (_tool === 'mark') {
    retouch.markAt(o, px, py, _brush);
    retouch.renderMaskPreview(o);
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
    setToolStatus('✅ Area selected → “🗑 Delete” or “🎨 Recolour”');
  };
  ov.addEventListener('pointerup', finish);
  ov.addEventListener('pointercancel', finish);
})();

editor.canvas.on('mouse:down', async (opt) => {
  if (_tool === 'off' || !_toolTarget) return;
  // Kombiniertes Umfärben in EINEM Werkzeug: 1. Klick nimmt die Farbe auf
  // (von irgendwo – z. B. dem Petrol-Hintergrund), danach färben Klicks die
  // angeklickte Fläche im Bild um. Kein zweiter Knopf nötig.
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
  // Strich abgeschlossen: jetzt EINMAL den echten Bildstand erzeugen und eine
  // Undo-Stufe setzen – nicht 60-mal während des Ziehens.
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
  // Werkzeuge immer anzeigen, aber ohne Bild sichtbar STILLLEGEN. Vorher waren
  // sie voll bedienbar und jeder Klick lief in einen kurzen Toast – von außen
  // sah das aus, als täten die Knöpfe schlicht nichts.
  body.style.display = 'block';
  body.classList.toggle('is-disabled', !isImg);
  hint.style.display = isImg ? 'none' : 'block';
  document.querySelectorAll('#retouch-body [data-tool]').forEach(b =>
    b.classList.toggle('primary', b.dataset.tool === _tool && _tool !== 'off'));
}

// ---- Kreis/Banner mit Text (Füllfarbe = Palette, Textfarbe = Textfarben-Feld) ----
const _hex = c => String(c || '').trim().toLowerCase();
// Weiß oder Dunkelgrau – je nachdem, was auf der Füllfarbe lesbar ist
function autoContrast(fill) {
  const m = /^#?([0-9a-f]{6})$/i.exec(_hex(fill));
  if (!m) return '#ffffff';
  const n = parseInt(m[1], 16);
  const lum = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  return lum > 0.6 ? '#1a1a1a' : '#ffffff';
}

// Wabe: Sechseck mit Spitze oben
const hexPoints = r => Array.from({ length: 6 }, (_, i) => {
  const a = (Math.PI / 3) * i - Math.PI / 2;
  return { x: r * Math.cos(a), y: r * Math.sin(a) };
});

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
    // Text muss in die schmalere Breite der Wabe passen -> Radius großzügiger
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

function addBadge(kind) {
  const inp = document.getElementById('text-input');
  const typed = inp?.value.trim();
  const fill = currentShapeColor;
  let textColor = document.getElementById('text-color')?.value || '#ffffff';
  // Gemeinsame Palette färbt beides gleich -> Text wäre unsichtbar. Dann automatisch.
  if (_hex(textColor) === _hex(fill)) textColor = autoContrast(fill);

  const dflt = (kind === 'circle' || kind === 'hex') ? '1' : 'Title';
  const g = buildBadge(kind, typed || dflt, fill, textColor);
  g.set({ left: editor.width / 2, top: editor.height / 2 });
  editor.canvas.add(g);
  editor.canvas.setActiveObject(g);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  if (inp) inp.value = '';
  if (!typed) startBadgeEdit(g);   // nichts vorgetippt -> gleich losschreiben
}

// ---- Textblock: Überschrift + Fließtext als EIN Objekt --------------------
function buildTextblock(head, body, opts) {
  const w = opts.width, size = opts.size, col = opts.color;
  const check = !!opts.check;
  const align = opts.align || (check ? 'left' : 'center');
  const parts = [];
  // Bei Haken den Text nach rechts einrücken, damit Platz für den Haken ist.
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

function addTextblock() {
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

function isTextblock(o) { return !!(o && o.shapeKind === 'textblock'); }

function rebuildTextblock(g, head, body, over = {}) {
  const c = g.getCenterPoint();
  const firstText = (g._objects || []).find(x => x.type === 'textbox');
  const col = over.color || g.tbColor || (firstText && firstText.fill) || '#111111';
  const ng = buildTextblock(head, body, {
    width: over.width || g.tbWidth || 260,
    size:  over.size  || g.tbSize  || 19,
    color: col, align: g.tbAlign || 'center', check: !!g.tbCheck,
  });
  if (!ng) return null;
  ng.set({ left: c.x, top: c.y, angle: g.angle, scaleX: g.scaleX, scaleY: g.scaleY,
           anim: g.anim, fx: g.fx, fxDelay: g.fxDelay, startAt: g.startAt });
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
      <label style="display:flex;gap:3px;align-items:center">Schriftgröße
        <input type="number" id="tb-e-size" min="8" step="1" style="width:56px;padding:3px;border:1px solid #ccc;border-radius:4px">
      </label>
      <label style="display:flex;gap:3px;align-items:center">Breite
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
    status('Bereit.');
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
function isChecklist(o) { return !!(o && o.shapeKind === 'checklist'); }

function buildCheckList(items, opts) {
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

function rebuildChecklist(g, items, over = {}) {
  const c = g.getCenterPoint();
  const ng = buildCheckList(items, {
    width: over.width || g.clWidth || 300,
    size:  over.size  || g.clSize  || 22,
    color: over.color || g.clColor || '#161616',
  });
  if (!ng) return null;
  ng.set({ left: c.x, top: c.y, angle: g.angle, scaleX: g.scaleX, scaleY: g.scaleY, anim: g.anim, fx: g.fx, fxDelay: g.fxDelay, startAt: g.startAt });
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
    <div style="font-size:11px;color:#666">Eine Zeile = ein Haken:</div>
    <textarea id="cl-e-body" rows="4" style="font-size:13px;padding:5px;border:1px solid #ccc;border-radius:4px;resize:vertical;font-family:inherit"></textarea>
    <div style="display:flex;gap:8px;align-items:center;font-size:11px;color:#666">
      <label style="display:flex;gap:3px;align-items:center">Schriftgröße
        <input type="number" id="cl-e-size" min="8" step="1" style="width:56px;padding:3px;border:1px solid #ccc;border-radius:4px"></label>
      <label style="display:flex;gap:3px;align-items:center">Breite
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
    status('Bereit.');
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

// ---- SVG-Texte zu Textblöcken bündeln ------------------------------------
// Fabric liest <tspan> nicht: mehrzeilige SVG-Texte müssen als einzelne
// <text>-Elemente vorliegen. Sonst klebt alles in einer Zeile. Damit daraus
// im Studio nicht pro Zeile ein Objekt wird, fassen wir untereinander
// stehende Zeilen wieder zu EINEM Textblock zusammen (Doppelklick = ändern).
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
  // buildTextblock rechnet den Fließtext als 0,74 × Größe. Ohne Überschrift
  // muss die Größe also hochgerechnet werden, damit der Text stimmt.
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
async function importSvgText(svgText, asGroup) {
  // Liegt schon etwas auf der Fläche, würde sich der Import darüberstapeln
  // (doppelte Bilder/Texte). Vorher fragen, ob geleert werden soll.
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
        // Texte getrennt behandeln: untereinander stehende Zeilen werden zu
        // EINEM Textblock gebündelt – ein Objekt pro Icon statt fünf.
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

{
  const btn = document.getElementById('svg-import-btn');
  const inp = document.getElementById('svg-file-input');
  if (btn && inp) {
    btn.onclick = e => { e.preventDefault(); inp.value = ''; inp.click(); };
    inp.onchange = async () => {
      const f = inp.files?.[0];
      if (!f) return;
      status('SVG wird gelesen…');
      try {
        const text = await f.text();
        const asGroup = !!document.getElementById('svg-as-group')?.checked;
        const n = await importSvgText(text, asGroup);
        if (n) status(asGroup ? 'SVG inserted as 1 object.' : `SVG inserted: ${n} layer(s).`, '#198754');
      } catch (err) {
        console.error(err);
        status('SVG konnte nicht gelesen werden: ' + err.message, '#dc3545');
      }
    };
  }
}

// ---- Text direkt im Badge schreiben (Doppelklick oder direkt nach dem Anlegen) ----
function isBadge(o) { return !!(o && typeof o.shapeKind === 'string' && o.shapeKind.startsWith('badge-')); }

function rebuildBadge(g, txt) {
  const kind = g.shapeKind.replace('badge-', '');
  const old = g._objects || [];
  const fill = old[0]?.fill || currentShapeColor;
  const textColor = old[1]?.fill || '#ffffff';
  const c = g.getCenterPoint();
  const ng = buildBadge(kind, txt, fill, textColor);
  ng.set({ left: c.x, top: c.y, angle: g.angle, scaleX: g.scaleX, scaleY: g.scaleY,
           anim: g.anim, fx: g.fx, fxDelay: g.fxDelay, startAt: g.startAt });
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
  if (!isBadge(g)) return;
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
    status('Bereit.');
  };
  inp.onkeydown = e => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  };
  inp.onblur = () => finish(true);
}

// Starrer SVG-Text -> editierbares Textfeld, erst wenn man ihn wirklich ändern will.
// Alle Maße werden 1:1 übernommen, damit nichts verrutscht oder zusammenfällt.
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

editor.canvas.on('mouse:dblclick', e => {
  const o = e.target;
  if (isBadge(o)) startBadgeEdit(o);
  else if (isChecklist(o)) startChecklistEdit(o);
  else if (isTextblock(o)) startTextblockEdit(o);
  else if (o && o.type === 'text') { textZuIText(o); status('Edit text, then click beside it.'); }
});

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
// Escape beendet das aktive Werkzeug – der schnelle Weg zurück, wenn sich die
// Arbeitsfläche „festgefahren" anfühlt.
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
  // Der Regler lief linear von 3 bis 120 px — damit lagen die feinen Größen auf
  // den ersten Millimetern und waren praktisch nicht treffbar. Jetzt ist die
  // Reglerstellung quadratisch auf die Pixelgröße abgebildet: die untere Hälfte
  // des Wegs deckt 1–30 px ab, die obere den Rest bis 120.
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
}

// ---- Größe per Zahl setzen (bei Mehrfachauswahl: für alle) -----------------
// Fabric packt eine Mehrfachauswahl in eine temporäre Gruppe; Änderungen an den
// Kindern greifen darin nicht sauber. Deshalb: Auswahl lösen, ändern, neu setzen.
function mitAuswahl(fn) {
  const list = editor.activeAll();
  if (!list.length) return 0;
  const war = editor.active();
  const mehrere = war && war.type === 'activeSelection';
  // Das kurzzeitige Ab- und Wiederanwählen löste drei komplette Neuaufbauten
  // der Auswahlleiste aus – dabei wurde das Eingabefeld gelöscht, in dessen
  // eigenem Handler wir gerade standen (Wert sprang zurück). Hier unterdrückt.
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
      // Vorbild = größtes Element, das ist berechenbar und unabhängig von der Klickreihenfolge
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
    if (n) status(`${n} Elemente auf ${Math.round(ziel)} px gebracht.`, '#198754');
  };
}

// ---- Ebenen-Liste ---------------------------------------------------------
function layerLabel(o, i) {
  if (o.type === 'image')   return '🖼 Image ' + i;
  if (o.shapeKind === 'textblock') return '📝 ' + (o.tbHead || o.tbBody || 'Text block').slice(0, 14);
  if (o.type === 'textbox') return '✏️ ' + (o.text || 'Text').slice(0, 14);
  if (o.svgPart)            return '📐 SVG part ' + o.svgPart;
  if (o.shapeKind)          return '🔷 Shape ' + i;
  return 'Element ' + i;
}
function renderLayers() {
  const list = document.getElementById('layers-list');
  if (!list) return;
  const objs = editor.realObjects();
  if (!objs.length) { list.innerHTML = '<span class="no-templates">No elements yet.</span>'; return; }
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
// Das frühere Seitenleisten-Panel „Animation" (#anim-panel) ist entfallen:
// Die Leiste unter dem Canvas (renderAnimBar) bietet dasselbe – Bewegung,
// Effekt, Tempo, Start – und das für jedes Element auf einen Blick.
// Der Container #anim-panel existierte im Gerüst ohnehin nie, das Panel war
// also toter Doppel-Code.

// ---- Animations-Leiste unter dem Canvas (pro Element ein Effekt) ----------
function renderAnimBar() {
  const bar = document.getElementById('anim-bar');
  if (!bar) return;
  const objs = editor.realObjects();
  if (!objs.length) { bar.innerHTML = '<span class="hint">Add elements to animate them.</span>'; return; }
  bar.innerHTML = '';
  const head = document.createElement('div'); head.className = 'anim-bar-head';
  const title = document.createElement('span');
  title.className = 'anim-bar-title'; title.textContent = '🎬 Animation je Element';

  // Videolänge – gilt fürs ganze GIF/Video (nicht pro Element).
  const lenWrap = document.createElement('label');
  lenWrap.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:.75rem;color:#555;margin-left:auto';
  lenWrap.appendChild(document.createTextNode('🎬 Video length'));
  const lenInp = document.createElement('input');
  lenInp.type = 'number'; lenInp.id = 'video-length'; lenInp.min = 0; lenInp.max = 15; lenInp.step = 0.5;
  lenInp.placeholder = 'auto';
  lenInp.style.cssText = 'width:58px;padding:3px;border:1px solid #ccc;border-radius:4px';
  lenInp.title = 'Total length of GIF/video in seconds. Empty = automatic.';
  if (window._videoLen != null) lenInp.value = window._videoLen;
  lenInp.oninput = () => { window._videoLen = lenInp.value; };
  lenWrap.appendChild(lenInp);
  lenWrap.appendChild(document.createTextNode('Sek.'));

  const prevTop = document.createElement('button');
  prevTop.className = 'tbtn primary'; prevTop.textContent = '▶ Preview';
  prevTop.style.marginLeft = '10px';
  prevTop.onclick = () => media.previewAnimation(editor);
  head.appendChild(title); head.appendChild(lenWrap); head.appendChild(prevTop);
  bar.appendChild(head);

  objs.forEach((o, idx) => {
    const row = document.createElement('div'); row.className = 'anim-row';

    // Vorschaubild des Elements
    const th = document.createElement('img'); th.className = 'anim-thumb';
    th.title = layerLabel(o, idx + 1) + ' – select';
    th.onclick = () => editor.selectObj(o);
    // Vorschaubild aus dem Cache. Ohne Cache wurde bei JEDEM Klick und jedem
    // Verschieben jedes Element neu als PNG gerastert – bei 25 Elementen
    // sekundenlange Hänger pro Mausklick.
    try {
      if (!o.__thumb) {
        const dim = Math.max(o.getScaledWidth?.() || o.width || 1, o.getScaledHeight?.() || o.height || 1);
        o.__thumb = o.toDataURL({ format: 'png', multiplier: Math.min(1, 64 / Math.max(dim, 1)) });
      }
      th.src = o.__thumb;
    } catch (e) { th.style.background = '#dfe3e6'; }

    // Regler-Spalte (untereinander)
    const col = document.createElement('div'); col.className = 'anim-col';

    const selRow = document.createElement('label'); selRow.className = 'anim-ctl';
    selRow.innerHTML = '<span>Motion</span>';
    const sel = document.createElement('select'); sel.className = 'field';
    media.ANIM_TYPES.forEach(t => {
      const op = document.createElement('option'); op.value = t;
      op.textContent = media.ANIM_LABELS[t] || t;
      if ((o.anim?.type || 'none') === t) op.selected = true; sel.appendChild(op);
    });
    sel.onchange = () => {
      const t = sel.value;
      o.anim = (t && t !== 'none')
        ? { type: t, dur: o.anim?.dur || 1200 }
        : null;
      media.setStart(o, media.startOf(o));   // eine Quelle fuer beide Systeme
      editor.snapshot();
    };
    selRow.appendChild(sel);

    const fxRow = document.createElement('label'); fxRow.className = 'anim-ctl';
    fxRow.innerHTML = '<span>Effect</span>';
    const fxsel = document.createElement('select'); fxsel.className = 'field';
    media.EFFECTS.forEach(t => {
      const op = document.createElement('option'); op.value = t;
      op.textContent = media.EFFECT_LABELS[t] || t;
      if ((o.fx || 'none') === t) op.selected = true; fxsel.appendChild(op);
    });
    fxsel.onchange = () => {
      const v = fxsel.value;
      o.fx = (v && v !== 'none') ? v : null;
      // Keep the effect on the same Start as the motion, so one slider drives both.
      media.setStart(o, media.startOf(o));
      editor.snapshot();
    };
    fxRow.appendChild(fxsel);

    // Tempo + Start (Verzögerung) nebeneinander
    const timeRow = document.createElement('div'); timeRow.className = 'anim-ctl anim-time';
    const durWrap = document.createElement('label'); durWrap.className = 'anim-time-item';
    durWrap.innerHTML = '<span>Speed</span>';
    const dur = document.createElement('input');
    dur.type = 'range'; dur.className = 'tl-slider'; dur.min = 300; dur.max = 4000; dur.step = 100;
    dur.value = o.anim?.dur || 1200; dur.title = 'Speed (duration)';
    dur.oninput = () => { if (o.anim) o.anim.dur = +dur.value; };
    dur.onchange = () => editor.snapshot();
    durWrap.appendChild(dur);

    const delWrap = document.createElement('label'); delWrap.className = 'anim-time-item';
    delWrap.innerHTML = '<span>Start</span>';
    const del = document.createElement('input');
    del.type = 'range'; del.className = 'tl-slider'; del.min = 0; del.max = 3000; del.step = 100;
    del.value = media.startOf(o);
    del.title = 'Start delay: when motion and effect begin';
    // One slider, both systems. It used to write only into o.anim.delay, so
    // with Motion = none it silently did nothing at all.
    del.oninput = () => media.setStart(o, del.value);
    del.onchange = () => editor.snapshot();
    delWrap.appendChild(del);

    timeRow.appendChild(durWrap); timeRow.appendChild(delWrap);

    col.appendChild(selRow); col.appendChild(fxRow); col.appendChild(timeRow);
    row.appendChild(th); row.appendChild(col);
    bar.appendChild(row);
  });
}

// ---- Schriftgröße nachträglich ändern ------------------------------------
// Gilt für markierten Text: einfaches Textobjekt direkt, Textblock über Neubau.
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

// Auswahl geändert → aktuelles Feld mit der Größe des markierten Texts füllen.
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
    // Nur eingreifen, wenn gerade Text markiert ist – sonst gilt der Wert für neuen Text.
    const hatText = editor.activeAll().some(x => istTextObj(x) || isTextblock(x));
    if (hatText) schriftGroesseAufAuswahl(+fs.value);
  });
}

// Umschalt+Klick auf „Speichern" fragt das Format neu ab.
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
    // _suppressClear schützt vor Umbauten, die selbst kurz die Auswahl
    // aufheben (z.B. Breite/Höhe bei Mehrfachauswahl setzen). Ohne den Schutz
    // schaltete sich das aktive Werkzeug beim Tippen in ein Zahlenfeld ab.
    if (_suppressClear) return;
    if (ev === 'selection:cleared' && _tool !== 'off'
        && !['rect', 'mark', 'paint', 'erase', 'restore'].includes(_tool)) setTool('off');
    renderSelBar(); updateRetouchPanel();
    planeUiAufbau();                      // Ebenen + Animationsleiste gebündelt
    if (ev !== 'selection:cleared') syncFontSizeInput();
  }));

// Größen- und Positionsfelder mitführen, wenn per Maus geschoben/skaliert wird
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

// Vorschaubild eines Elements verwerfen, sobald es verändert wurde – nur dann
// muss es neu gerastert werden.
editor.canvas.on('object:modified', e => { if (e?.target) e.target.__thumb = null; });

// ---- Undo/Redo-Buttons aktiv/inaktiv --------------------------------------
// Die Neuaufbauten von Ebenen- und Animationsleiste werden gebündelt: Ein
// einzelner Klick löste vorher mehrere komplette Neuaufbauten hintereinander
// aus (Auswahl geleert → gesetzt → Snapshot).
let _uiTimer = null;
function planeUiAufbau() {
  if (_uiTimer) return;
  _uiTimer = requestAnimationFrame(() => {
    _uiTimer = null;
    try { renderLayers(); renderAnimBar(); }
    catch (e) { console.error('[studio] UI-Aufbau:', e); }
  });
}

editor.onChange(() => {
  const u = document.querySelector('[data-act="undo"]');
  const r = document.querySelector('[data-act="redo"]');
  if (u) u.disabled = !editor.canUndo();
  if (r) r.disabled = !editor.canRedo();
  bg.updateBgInfo(editor);
  // Sicherheitsnetz: Ist das Zielbild des aktiven Werkzeugs verschwunden
  // (Leeren, Strg+Z, Vorlage geladen), war die Arbeitsfläche danach gesperrt –
  // nichts ließ sich mehr anklicken, und das Werkzeug malte unsichtbar auf ein
  // totes Objekt weiter.
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
      status('✨ Muster erkannt – entferne nur das Schachbrett…');
      const cleaned = await removeCheckerboard(img._element);   // nur Muster weg, Weiß bleibt
      // null = es wurde nichts gefunden. Früher kam hier das unveränderte Bild
      // zurück und wurde trotzdem als „bearbeitet" übernommen – ein 2-MB-JPEG
      // wurde so zu ~25 MB base64 in jedem Undo-Schritt und im Entwurf.
      if (cleaned) {
        img.bgRemoved = true; img._work = null;
        retouch.replaceElement(img, cleaned); editor.snapshot();
        status('✅ Pattern removed', 'green');
      } else {
        status('Bereit.', '#888');
      }
    }
  } catch (e) { console.warn('Muster-Erkennung:', e); status('Bereit.', '#888'); }
  return img;
};

// ---- Init -----------------------------------------------------------------
// Jeder Schritt einzeln gekapselt: Ein Fehler in der Vorlagenliste darf nicht
// mehr dazu führen, dass Bibliothek, Titel und das Laden der Datei ausfallen.
boot('Template list', () => bg.loadTemplateList(editor));
// Bibliothek erkennt SVGs selbst und schickt sie durch den Import statt sie
// als flaches Bild einzusetzen.
boot('SVG handler', () => {
  if (typeof lib.setSvgHandler === 'function') {
    lib.setSvgHandler((text, asGroup) => importSvgText(text, asGroup));
  }
});
boot('Library', () => {
  if (typeof initLibrary !== 'function') throw new Error('initLibrary fehlt (alte library.js im Browser-Cache? Strg+F5)');
  initLibrary(editor);
});
boot('Selection bar', () => renderSelBar());
boot('Retouch panel', () => updateRetouchPanel());
boot('Shell', () => initUi());

// Aktuell geladene Vorlage – EINE Quelle der Wahrheit auf dem Editor-Objekt,
// egal ob über die Verwaltung (?template=…) oder per Kachel-Klick (applyTemplate)
// geöffnet. „Vorlage speichern" fragt dann, ob aktualisiert oder neu angelegt wird.
function currentTemplateId() { return editor._templateId || null; }
function setTemplateId(id)   { editor._templateId = id || null; }
if (CONFIG.tplData?.id) setTemplateId(CONFIG.tplData.id);

// Titel vorausfüllen (beim Weiterbearbeiten bleibt der Name erhalten).
{
  const t = CONFIG.libData?.title || CONFIG.postData?.title || CONFIG.tplData?.title || '';
  const ti = document.getElementById('title-input');
  if (ti && t) ti.value = t;
}

// Vorhandene Ausgabe geöffnet? → Knopf „Speichern" (gleiches Format) statt „Speichern als…".
if (CONFIG.libData?.item_id || CONFIG.libData?.nc_path) {
  const b = document.querySelector('[data-act="save-as"]');
  if (b) { b.textContent = '💾 Save'; b.dataset.act = 'save-existing'; b.title = 'Overwrite the existing output in the same format'; }
}

(async function restoreInitial() {
  try {
    const post = CONFIG.postData, libD = CONFIG.libData, tpl = CONFIG.tplData;
    // frisch=true: die Historie beginnt beim GELADENEN Zustand. Ohne das wäre
    // der leere Canvas von vor dem Laden der älteste Undo-Schritt – ein
    // versehentliches Strg+Z hätte alles gelöscht.
    if (tpl?.canvas_json) {
      if (tpl.width && tpl.height) { editor.setSize(tpl.width, tpl.height); fit(); }
      status('⏳ Loading template…');
      if (await io.restoreCanvas(editor, tpl.canvas_json, { frisch: true })) {
        status('Editing template – “💾 Save template” updates it.', '#0E7C86');
      }
      return;
    }
    // Nur bei vollständigem Laden „Bereit." melden. Vorher überschrieb diese
    // Meldung sofort jede rote Warnung („nicht alle Bilder geladen", „Daten
    // unlesbar") – der Nutzer hielt den halbleeren Editor für seine Datei.
    if (post?.canvas_json) {
      status('⏳ Loading draft…');
      if (await io.restoreCanvas(editor, post.canvas_json, { frisch: true })) status('Bereit.', '#888');
      return;
    }
    if (libD?.canvas_json) {
      status('⏳ Loading draft…');
      if (await io.restoreCanvas(editor, libD.canvas_json, { frisch: true })) status('Bereit.', '#888');
      return;
    }
    if (libD?.image_url) {
      // Schlägt das Laden fehl (Datei in Nextcloud gelöscht), blieb der Editor
      // früher stumm leer – und der nächste „Speichern"-Klick überschrieb den
      // Eintrag mit einem leeren Bild.
      try {
        await editor.addImageUrl(libD.image_url, { silent: true, fill: true });
        editor.resetHistory();
        status('Bereit.', '#888');
      } catch (e) {
        editor._ladefehler = true;
        status('❌ Image could not be loaded – file may be missing in Nextcloud', 'red');
        toast('Image not found', 'err');
      }
    } else {
      status('Bereit.', '#888');
    }
  } catch (e) {
    console.warn('restoreInitial:', e);
    editor._locked = false;
    editor._ladefehler = true;
    status('❌ Draft could not be loaded', 'red');
  } finally {
    // Der Stand direkt nach dem Öffnen gilt als „gespeichert".
    window.dispatchEvent(new CustomEvent('studio:geladen'));
  }
})();

// Sicherstellen, dass Elemente normal anklickbar/auswählbar sind (kein Werkzeug/
// keine Zeichenebene blockiert die Auswahl nach dem Laden).
// ---- Zoomen mit Strg+Mausrad über der Arbeitsfläche ----------------------
// Für feines Retuschieren: erst heranzoomen, dann mit kleinem Pinsel arbeiten.
// Ohne Strg scrollt das Rad weiter die Seite — sonst bleibt man beim Scrollen
// versehentlich im Bild hängen.
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
// Kein status('Bereit.') mehr an dieser Stelle: restoreInitial läuft async
// weiter, und „Bereit." überschrieb dann sofort das „⏳ wird geladen…" –
// obwohl Speichern in dem Moment noch abgelehnt wurde. Die Meldung setzt
// jetzt restoreInitial selbst, wenn wirklich alles da ist.

// ---- Schutz vor versehentlichem Verlassen --------------------------------
// Ein Klick auf eine Kachel in der rechten Leiste navigierte sofort weg und
// verwarf alles Ungespeicherte – ohne jede Rückfrage.
// editor._rev zählt jede Änderung monoton hoch. Die Länge der Historie taugt
// dafür nicht: die ist gedeckelt und steht ab ~30 Schritten still – danach hätte
// die Rückfrage nie mehr ausgelöst.
let _gespeichertStand = editor._rev;
function ungespeicherteAenderungen() {
  return editor._rev > 0 && editor._rev !== _gespeichertStand;
}
function alsGespeichertMerken() { _gespeichertStand = editor._rev; }
window.addEventListener('studio:output-changed', alsGespeichertMerken);
// Nach dem Laden einer Datei/Vorlage ist der Stand „wie gespeichert" – sonst
// fragte das Studio direkt nach dem Öffnen nach ungespeicherten Änderungen.
window.addEventListener('studio:geladen', alsGespeichertMerken);
// Auch das Speichern einer Vorlage macht den Stand sauber.
window.addEventListener('studio:vorlage-gespeichert', alsGespeichertMerken);
window.addEventListener('beforeunload', e => {
  if (!ungespeicherteAenderungen()) return;
  e.preventDefault();
  e.returnValue = '';   // Browser zeigt seine Standard-Rückfrage
});
// Für Navigation innerhalb der Seite (Kachel-Klicks in library.js).
window.studioDarfVerlassen = function () {
  if (!ungespeicherteAenderungen()) return true;
  return window.confirm('There are unsaved changes.\n\n' +
                        'Really leave? The changes will be lost.');
};

// „Bereit." setzt ausschließlich restoreInitial – und nur, wenn wirklich alles
// geladen ist. Diese Zeile überschrieb sonst rote Ladefehler-Meldungen
// (auch bei einem Parse-Fehler, wo _locked nie gesetzt wird).
