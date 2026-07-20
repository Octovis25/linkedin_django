// studio.js – Einstiegspunkt. Verdrahtet DOM ↔ Module.
import { CONFIG } from './config.js';
import { Editor, fabric } from './editor.js';
import { toast, status, modal } from './util.js';
import * as bg from './background.js';
import * as io from './io.js';
// Namensraum-Import: Fehlt ein Export (z. B. weil der Browser eine alte
// library.js aus dem Cache hat), stirbt hier NICHT das ganze Modul.
import * as lib from './library.js';
const { initLibrary, refreshOutput } = lib;
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
function setCanvasFarbe(farbe) {
  editor.canvas.backgroundColor = farbe || '';
  editor.canvas.requestRenderAll();
  editor.snapshot();
  const pick = document.getElementById('bg-color');
  if (pick && farbe) pick.value = farbe;
  status(farbe ? `Hintergrund: ${farbe}` : 'Hintergrund transparent.', '#198754');
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
    const ende = val => { back.remove(); resolve(val); };
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
    if (localStorage.getItem(key) === '1') wrap.classList.add(hideCls);

    const paint = () => {
      const aus = wrap.classList.contains(hideCls);
      btn.textContent = aus ? pfeile[1] : pfeile[0];
      btn.classList.toggle('aus', aus);
      btn.title = aus ? 'Leiste festpinnen (schwebt beim Überfahren)' : 'Leiste ausklappen – Canvas wird größer';
    };
    paint();

    btn.onclick = e => {
      e.preventDefault();
      wrap.classList.toggle(hideCls);
      wrap.classList.remove(peekCls);
      localStorage.setItem(key, wrap.classList.contains(hideCls) ? '1' : '0');
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
    o._objects[0].set('fill', col);
    const t = o._objects[1];
    if (_hex(t.fill) === _hex(col)) t.set('fill', autoContrast(col));
    editor.canvas.requestRenderAll(); editor.snapshot();
  }
  else if (o && o.shapeKind) { o.set(o.fill ? 'fill' : 'stroke', col); editor.canvas.requestRenderAll(); editor.snapshot(); }
});

// Eigenes Textfarben-Feld: überschreibt die Palette für Text/Badge-Beschriftung
{
  const tc = document.getElementById('text-color');
  if (tc) tc.oninput = () => {
    currentTextColor = tc.value;
    const o = editor.active();
    if (o && o.type === 'textbox') { o.set('fill', tc.value); editor.canvas.requestRenderAll(); editor.snapshot(); }
    else if (isBadge(o)) { o._objects[1].set('fill', tc.value); editor.canvas.requestRenderAll(); editor.snapshot(); }
  };
}

// Gemerktes Speicher-Format (image|gif|video). Nach der ersten Wahl wird nicht
// mehr gefragt – der Knopf speichert still im gleichen Format.
let _saveKind = null;
async function speichereAls(kind) {
  _saveKind = kind;
  if (kind === 'gif')        await media.exportGif(editor);
  else if (kind === 'video') await media.exportVideo(editor);
  else { await io.saveImage(editor); refreshOutput(); }
  // Knopf umbenennen, damit klar ist: ab jetzt wird direkt gespeichert.
  const btn = document.querySelector('[data-act="save-as"]');
  if (btn) {
    const lbl = kind === 'gif' ? '💾 GIF speichern' : kind === 'video' ? '💾 Video speichern' : '💾 Speichern';
    btn.textContent = lbl;
    btn.title = 'Speichert im gleichen Format. Für ein anderes Format Umschalt+Klick.';
  }
  status('Gespeichert.', '#198754');
}

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
    // Format nur beim ersten Mal (oder nach „als…") abfragen und merken.
    let kind = _saveKind;
    if (!kind) {
      kind = await modal('Speichern als…', 'Was möchtest du speichern?', [
        { label: '🖼 Bild (PNG)', value: 'image' },
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
  grid: () => {
    const an = editor.toggleGrid();
    renderSelBar();   // Knopf-Zustand oben aktualisieren
    status(an ? 'Raster an – nur zum Ausrichten, wird nicht mitgespeichert.' : 'Raster aus.', '#888');
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
    status(gross ? 'Große Fläche – Werkzeuge über die Randgriffe (‹ ›).' : 'Normale Ansicht.', '#888');
  },
  'set-as-bg': () => {
    const o = editor.active();
    if (!o || o.type !== 'image') { toast('Erst ein Bild wählen', 'err'); return; }
    editor.canvas.remove(o);
    o.set({ left: 0, top: 0, originX: 'left', originY: 'top',
            scaleX: editor.width / o.width, scaleY: editor.height / o.height, selectable: false, evented: false });
    editor.canvas.setBackgroundImage(o, editor.canvas.renderAll.bind(editor.canvas));
    editor.snapshot();
    bg.updateBgInfo?.(editor);
    status('Bild als Hintergrund gesetzt.', '#198754');
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
    status('Haken + Text eingefügt – Doppelklick zum Ändern, an der Ecke skalieren.', '#198754');
  },
  'add-checklist': () => {
    const g = buildCheckList(['Erste Zeile', 'Zweite Zeile', 'Dritte Zeile'], {
      width: +(document.getElementById('tb-width')?.value || 300),
      size:  +(document.getElementById('tb-size')?.value || 22),
      color: document.getElementById('text-color')?.value || '#161616',
    });
    if (!g) return;
    editor.canvas.add(g);
    editor.canvas.setActiveObject(g);
    editor.canvas.requestRenderAll();
    editor.snapshot();
    status('Dreihaken eingefügt – Doppelklick: eine Zeile je Haken. An der Ecke skalieren.', '#198754');
  },
  'add-text':  () => {
    const inp = document.getElementById('text-input');
    editor.addText(inp.value.trim() || 'Text', {
      fontSize: Math.max(6, +document.getElementById('font-size').value || 32),
      fontWeight: document.getElementById('font-weight').value,
      color: document.getElementById('text-color')?.value || currentTextColor,
    });
    inp.value = '';
  },
  'canvas-size': async () => {
    const choice = await modal('Canvas-Größe', 'Format wählen', [
      { label: '1080 × 1080 (Quadrat)', value: [1080, 1080] },
      { label: '1080 × 1350 (LinkedIn Hochformat)', value: [1080, 1350] },
      { label: '1024 × 1536 (Hochformat 2:3)', value: [1024, 1536] },
      { label: '1200 × 628 (Link)', value: [1200, 628] },
      { label: '1920 × 1080 (Video)', value: [1920, 1080] },
      { label: '✏️ Eigene Größe…', value: 'frei' },
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
    const ok = await modal('Alles löschen?', 'Entfernt alle Elemente und den Hintergrund vom Canvas.', [
      { label: '🧹 Ja, leeren', value: true },
      { label: 'Abbrechen', value: false },
    ]);
    if (ok) editor.clearAll();
  },
  'export-gif':   () => media.exportGif(editor),
  'export-video': () => media.exportVideo(editor),
  'zoom-in':    () => zeigeZoom(editor.zoom('in')),
  'zoom-out':   () => zeigeZoom(editor.zoom('out')),
  'zoom-reset': () => zeigeZoom(editor.zoom('reset')),
  duplicate:   () => editor.duplicateSelected(),
  group:       () => { if (editor.group()) { renderSelBar(); status('Zu einer Gruppe verklebt.', '#198754'); } },
  ungroup:     () => { if (editor.ungroup()) { renderSelBar(); status('Gruppierung gelöst.', '#888'); } },
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
  'copy-from-post': () => copyImageFromPost(),
  'open-post-file': (btn) => {
    const url = btn && btn.dataset.url;
    if (!url) return;
    editor.addImageUrl(url, { fill: true });
    status('Datei vom Post geladen – jetzt bearbeiten und speichern.', '#198754');
  },
  'save-template': () => saveAsTemplate(),
  'new-template': async () => {
    const ok = await modal('Neue Vorlage', 'Leert die Arbeitsfläche, damit du eine neue Vorlage baust – Hintergrund, Logo, Textfelder. Nicht Gespeichertes geht verloren.', [
      { label: '➕ Ja, neue Vorlage', value: true },
      { label: 'Abbrechen', value: false },
    ]);
    if (!ok) return;
    editor.clearAll();
    _editingTemplateId = null;   // frische Vorlage → beim Speichern neu anlegen
    const t = document.getElementById('title-input'); if (t) t.value = '';
    status('Vorlage bauen: Hintergrund, Logo, Textfelder – dann „💾 Vorlage speichern".', '#888');
  },
};

// Aktuelle Leinwand als wiederverwendbare Vorlage speichern.
async function saveAsTemplate() {
  const vorschlag = (document.getElementById('title-input')?.value || '').trim() || 'Neue Vorlage';
  const title = window.prompt('Name der Vorlage:', vorschlag);
  if (title === null) return;                 // abgebrochen
  let dataUrl, canvasJson;
  try {
    const preview = editor.exportDataURL({ multiplier: 0.4 });
    dataUrl = editor.exportDataURL({ multiplier: 1 });     // Vorschau-PNG (ohne Raster)
    canvasJson = io.buildCanvasJson(editor, preview);      // Layout: Hintergrund + Logo + Textfelder
  } catch (e) { toast('Export fehlgeschlagen', 'err'); return; }
  status('💾 Vorlage wird gespeichert…');
  try {
    const res = await fetch(CONFIG.urls?.saveTemplate || '/library/studio/template/save-canvas/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _cookie('csrftoken') },
      body: JSON.stringify({ dataUrl, canvasJson, title: title.trim(),
                             width: editor.width, height: editor.height,
                             tplId: _editingTemplateId || undefined }),
    });
    const d = await res.json();
    if (d.ok) {
      _editingTemplateId = d.id;   // ab jetzt weiter dieselbe Vorlage aktualisieren
      toast(d.updated ? 'Vorlage aktualisiert' : 'Vorlage gespeichert', 'ok');
      status(d.updated ? '✅ Vorlage aktualisiert.' : '✅ Als Vorlage gespeichert.', '#198754');
      bg.loadTemplateList(editor);
    } else { toast('Fehler: ' + (d.error || ''), 'err'); status('❌ ' + (d.error || 'Fehler'), 'red'); }
  } catch (e) { toast('Speichern fehlgeschlagen', 'err'); status('❌ ' + e, 'red'); }
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
  } catch (e) { toast('Posts konnten nicht geladen werden', 'err'); return; }
  if (!posts.length) { toast('Keine Posts mit Bild gefunden', 'err'); return; }

  const ov = document.createElement('div');
  ov.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center';
  const box = document.createElement('div');
  box.style.cssText = 'background:#fff;border-radius:12px;padding:16px;width:min(680px,92vw);max-height:82vh;overflow:auto;box-shadow:0 10px 40px rgba(0,0,0,.35)';
  box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
    + '<strong style="font-size:15px;color:#0E7C86">Bild von anderem Post übernehmen</strong>'
    + '<button id="cfp-x" class="tbtn">✕</button></div>'
    + '<input id="cfp-q" placeholder="Suchen…" style="width:100%;padding:6px 8px;border:1px solid #ccc;border-radius:6px;margin-bottom:10px;box-sizing:border-box">'
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
      card.onclick = () => { ov.remove(); ladeBildVonPost(p); };
      grid.appendChild(card);
    });
  };
  render('');
  box.querySelector('#cfp-q').addEventListener('input', e => render(e.target.value.toLowerCase().trim()));
  box.querySelector('#cfp-x').onclick = () => ov.remove();
  ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
}
async function ladeBildVonPost(p) {
  try {
    await editor.addImageUrl(p.thumb, {});   // same-origin Proxy → kein Tainting
    status(`Bild von „${p.title}" übernommen. „Speichern" legt es als Kopie an diesem Post ab.`, '#198754');
  } catch (e) { toast('Bild konnte nicht geladen werden', 'err'); }
}

document.addEventListener('click', e => {
  const btn = e.target.closest('[data-act]');
  if (btn && actions[btn.dataset.act]) { e.preventDefault(); actions[btn.dataset.act](btn); }
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

  const dflt = (kind === 'circle' || kind === 'hex') ? '1' : 'Titel';
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
    tbHead: head, tbBody: body, tbCheck: check,
  });
  return g;
}

function addTextblock() {
  const head = document.getElementById('tb-head')?.value.trim() || '';
  const body = document.getElementById('tb-body')?.value.trim() || '';
  if (!head && !body) { status('Bitte Überschrift oder Text eingeben.', '#dc3545'); return; }
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
  status('Textblock eingefügt – Doppelklick zum Ändern.', '#198754');
}

function isTextblock(o) { return !!(o && o.shapeKind === 'textblock'); }

function rebuildTextblock(g, head, body, over = {}) {
  const c = g.getCenterPoint();
  const col = g._objects?.[0]?.fill || '#111111';
  const ng = buildTextblock(head, body, {
    width: over.width || g.tbWidth || 260,
    size:  over.size  || g.tbSize  || 19,
    color: col, align: g.tbAlign || 'center', check: !!g.tbCheck,
  });
  if (!ng) return null;
  ng.set({ left: c.x, top: c.y, angle: g.angle, scaleX: g.scaleX, scaleY: g.scaleY,
           anim: g.anim, fx: g.fx });
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
  document.getElementById('tb-edit')?.remove();
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
    <input type="text" id="tb-e-head" placeholder="Überschrift" style="font-weight:700;font-size:14px;padding:5px;border:1px solid #ccc;border-radius:4px">
    <textarea id="tb-e-body" placeholder="Text" rows="3" style="font-size:13px;padding:5px;border:1px solid #ccc;border-radius:4px;resize:vertical;font-family:inherit"></textarea>
    <div style="display:flex;gap:8px;align-items:center;font-size:11px;color:#666">
      <label style="display:flex;gap:3px;align-items:center">Schriftgröße
        <input type="number" id="tb-e-size" min="8" step="1" style="width:56px;padding:3px;border:1px solid #ccc;border-radius:4px">
      </label>
      <label style="display:flex;gap:3px;align-items:center">Breite
        <input type="number" id="tb-e-width" min="60" step="10" style="width:64px;padding:3px;border:1px solid #ccc;border-radius:4px">
      </label>
    </div>
    <div style="font-size:11px;color:#888">Strg+Enter = fertig, Esc = abbrechen</div>`;
  document.body.appendChild(box);
  const hi = box.querySelector('#tb-e-head'), bi = box.querySelector('#tb-e-body');
  const si = box.querySelector('#tb-e-size'), wi = box.querySelector('#tb-e-width');
  hi.value = g.tbHead || ''; bi.value = g.tbBody || '';
  si.value = g.tbSize || 19; wi.value = g.tbWidth || 260;
  hi.focus(); hi.select();
  status('Textblock bearbeiten – Größe/Breite anpassbar, Strg+Enter = fertig.');

  let done = false;
  const finish = save => {
    if (done) return; done = true;
    const h = hi.value.trim(), b = bi.value.trim();
    const sz = Math.max(8, +si.value || g.tbSize || 19);
    const wd = Math.max(60, +wi.value || g.tbWidth || 260);
    box.remove();
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
  (items.length ? items : ['Zeile']).forEach(txt => {
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
    color: g.clColor || '#161616',
  });
  if (!ng) return null;
  ng.set({ left: c.x, top: c.y, angle: g.angle, scaleX: g.scaleX, scaleY: g.scaleY, anim: g.anim, fx: g.fx });
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
  document.getElementById('tb-edit')?.remove();
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
    <div style="font-size:11px;color:#888">Strg+Enter = fertig, Esc = abbrechen</div>`;
  document.body.appendChild(box);
  const bi = box.querySelector('#cl-e-body'), si = box.querySelector('#cl-e-size'), wi = box.querySelector('#cl-e-width');
  bi.value = (g.clItems || []).join('\n'); si.value = g.clSize || 22; wi.value = g.clWidth || 300;
  bi.focus();
  status('Haken-Liste bearbeiten – eine Zeile je Haken, Strg+Enter = fertig.');
  let done = false;
  const finish = save => {
    if (done) return; done = true;
    const items = bi.value.split('\n').map(s => s.trim()).filter(Boolean);
    const sz = Math.max(8, +si.value || g.clSize || 22);
    const wd = Math.max(60, +wi.value || g.clWidth || 300);
    box.remove();
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
      'Fläche zuerst leeren?',
      'Auf der Arbeitsfläche liegen schon Elemente. Ohne Leeren wird das SVG darübergelegt – dann liegen Bilder und Texte doppelt aufeinander.',
      [
        { label: '🧹 Leeren und einfügen', value: true },
        { label: 'Darüberlegen', value: false },
      ]);
    if (leeren) editor.clearAll();
  }
  return new Promise(resolve => {
    fabric.loadSVGFromString(svgText, (objects, options) => {
      const objs = (objects || []).filter(Boolean);
      if (!objs.length) { status('SVG enthielt keine lesbaren Formen.', '#dc3545'); return resolve(0); }

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
        if (n) status(asGroup ? 'SVG als 1 Objekt eingefügt.' : `SVG eingefügt: ${n} Ebene(n).`, '#198754');
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
           anim: g.anim, fx: g.fx });
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
  document.getElementById('badge-edit')?.remove();
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
  status('Text eintippen, Enter = fertig (Esc = abbrechen).');

  let done = false;
  const finish = save => {
    if (done) return; done = true;
    const v = inp.value.trim();
    inp.remove();
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
  else if (o && o.type === 'text') { textZuIText(o); status('Text ändern, dann daneben klicken.'); }
});

document.addEventListener('click', e => {
  const bb = e.target.closest('[data-badge]');
  if (bb) { e.preventDefault(); addBadge(bb.dataset.badge); return; }
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
let _keepRatio = true;

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
  const first = objs[0];
  const sw = first ? Math.round(first.getScaledWidth()) : '';
  const sh = first ? Math.round(first.getScaledHeight()) : '';
  const fc = first ? first.getCenterPoint() : null;
  const cx = fc ? Math.round(fc.x) : '';
  const cy = fc ? Math.round(fc.y) : '';
  const maxi = document.querySelector('.studio-wrap')?.classList.contains('maxi');
  bar.innerHTML = `
    <button class="tbtn ${editor.gridOn ? 'primary' : ''}" data-act="grid" title="Raster zum Ausrichten ein-/ausblenden (wird nicht mitgespeichert)">▦ Raster</button>
    <button class="tbtn" data-act="zoom-out" title="Verkleinern">🔍−</button>
    <button class="tbtn" data-act="zoom-reset" title="Zoom zurücksetzen">⤢</button>
    <button class="tbtn" data-act="zoom-in" title="Vergrößern">🔍+</button>
    <button class="tbtn ${maxi ? 'primary' : ''}" data-act="maximize" title="Arbeitsfläche groß: Leisten weg, Fläche füllt den Bildschirm">⛶ Groß</button>
    <span style="width:8px"></span>
    ${hasSel ? `<span class="sel-active" title="Aktives Element">${activeLabel}</span>` : ''}
    ${hasSel ? `<span class="sel-size" title="Größe in Pixel${objs.length > 1 ? ' – gilt für alle ausgewählten Elemente' : ''}">
        B <input type="number" id="sel-w" class="sel-num" min="1" step="1" value="${sw}">
        H <input type="number" id="sel-h" class="sel-num" min="1" step="1" value="${sh}">
        <button class="tbtn" id="sel-lock" title="${_keepRatio ? 'Seitenverhältnis bleibt erhalten – klicken zum Entsperren' : 'Breite/Höhe frei – klicken zum Sperren'}">${_keepRatio ? '🔗' : '🔓'}</button>
      </span>` : ''}
    ${hasSel ? `<span class="sel-size" title="Mittelpunkt in Pixel${objs.length > 1 ? ' – setzt alle auf dieselbe Stelle' : ''}">
        X <input type="number" id="sel-x" class="sel-num" step="1" value="${cx}">
        Y <input type="number" id="sel-y" class="sel-num" step="1" value="${cy}">
      </span>` : ''}
    ${objs.length > 1 ? `<span class="sel-size" title="Angleichen und verteilen">
        <button class="tbtn" id="same-size" title="Alle auf die Größe des zuerst gewählten bringen">⧉ gleich groß</button>
        <button class="tbtn" id="dist-h" title="Waagerecht gleichmäßig verteilen">↔≡</button>
        <button class="tbtn" id="dist-v" title="Senkrecht gleichmäßig verteilen">↕≡</button>
      </span>` : ''}
    <button class="tbtn" data-act="duplicate" title="Duplizieren (Strg+D)" ${d}>📋</button>
    ${objs.length > 1 ? `<button class="tbtn" data-act="group" title="Ausgewählte Teile zu einer Gruppe verkleben">🔗 Gruppieren</button>` : ''}
    ${editor.isGroup() ? `<button class="tbtn" data-act="ungroup" title="Gruppierung wieder lösen">✂ Lösen</button>` : ''}
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
    <button class="tbtn danger" data-act="delete" title="Löschen (Entf)" ${d}>🗑</button>
    ${hasSel ? '' : '<span class="hint" style="margin-left:8px">Element wählen zum Bearbeiten</span>'}
  `;
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
  if (mehrere) editor.canvas.discardActiveObject();
  fn(list);
  list.forEach(o => o.setCoords());
  if (mehrere) {
    const sel = new fabric.ActiveSelection(list, { canvas: editor.canvas });
    editor.canvas.setActiveObject(sel);
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
    if (editor.activeAll().length < 3) { status('Zum Verteilen mindestens 3 Elemente wählen.', '#dc3545'); return; }
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
    if (editor.activeAll().length < 2) { status('Mindestens 2 Elemente wählen.', '#dc3545'); return; }
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
  if (o.type === 'image')   return '🖼 Bild ' + i;
  if (o.shapeKind === 'textblock') return '📝 ' + (o.tbHead || o.tbBody || 'Textblock').slice(0, 14);
  if (o.type === 'textbox') return '✏️ ' + (o.text || 'Text').slice(0, 14);
  if (o.svgPart)            return '📐 SVG-Teil ' + o.svgPart;
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
  const sb = document.querySelector('[data-act="save-as"]');
  if (sb) sb.addEventListener('click', e => {
    if (e.shiftKey) { e.preventDefault(); e.stopImmediatePropagation(); actions['save-as-new'](); }
  }, true);
}

// ---- Selektion-Events koppeln --------------------------------------------
['selection:created', 'selection:updated', 'selection:cleared'].forEach(ev =>
  editor.canvas.on(ev, () => {
    if (ev === 'selection:cleared' && _tool !== 'off' && !_suppressClear
        && !['rect', 'mark', 'paint', 'erase', 'restore'].includes(_tool)) setTool('off');
    renderSelBar(); renderAnimPanel(); updateRetouchPanel(); renderLayers(); renderAnimBar();
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
// Bibliothek erkennt SVGs selbst und schickt sie durch den Import statt sie
// als flaches Bild einzusetzen.
if (typeof lib.setSvgHandler === 'function') {
  lib.setSvgHandler((text, asGroup) => importSvgText(text, asGroup));
}
initLibrary(editor);
renderSelBar();
updateRetouchPanel();

// Vorlage zum Bearbeiten geöffnet? Merken, damit „Vorlage speichern" sie AKTUALISIERT.
let _editingTemplateId = CONFIG.tplData?.id || null;

// Titel vorausfüllen (beim Weiterbearbeiten bleibt der Name erhalten).
{
  const t = CONFIG.libData?.title || CONFIG.postData?.title || CONFIG.tplData?.title || '';
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
    const post = CONFIG.postData, lib = CONFIG.libData, tpl = CONFIG.tplData;
    // Vorlage bearbeiten: Größe der Vorlage setzen und Layout laden.
    if (tpl?.canvas_json) {
      if (tpl.width && tpl.height) { editor.setSize(tpl.width, tpl.height); fit(); }
      io.restoreCanvas(editor, tpl.canvas_json);
      status('Vorlage wird bearbeitet – „💾 Vorlage speichern" aktualisiert sie.', '#0E7C86');
      return;
    }
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
