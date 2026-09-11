// library.js – rechte Sidebar:
//   OBEN: Upload nach Studio_Work/Upload (mit Vorschau + Löschen).
//   MITTE: Assets aus Nextcloud als anhakbare Ordner-Struktur. Angehakte Ordner
//          (auch Überordner rekursiv) zeigen ihre Bilder gesammelt im Raster.
//   UNTEN: fertige Studio-Ausgaben Images / GIFs / Videos zum Weiterbearbeiten.
import { URLS, getCookie, CONFIG } from './config.js';
import { toast, readJson } from './util.js';

// Async work kicked off from a sync handler. Without this the rejection reaches
// the global handler in studio.html and paints a red banner over the page for
// what is usually a failed background refresh.
const guard = (p, what) => Promise.resolve(p).catch(e => console.error('[library] ' + what + ':', e));

// Fehlermeldungen landen im DOM – nie ungeprüft.
const esc = t => String(t).replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

// ── Kacheln erst laden, wenn man sie sieht ──────────────────────────────────
// A tile shows the full-size file: a saved output is a 1080x1080 PNG, an asset
// can be larger still. Forty tiles in the grid meant forty full downloads and
// forty full-size bitmaps in memory every time the Studio opened - before the
// canvas got a single frame. Now a tile carries its address in data-src and
// only fetches once it comes near the viewport.
const _sichtbar = (typeof IntersectionObserver === 'function')
  ? new IntersectionObserver((eintraege, beob) => {
      for (const e of eintraege) {
        if (!e.isIntersecting) continue;
        beob.unobserve(e.target);
        const url = e.target.dataset.src;
        if (url) { delete e.target.dataset.src; e.target.src = url; }
      }
    }, { rootMargin: '400px' })
  : null;

// Ohne IntersectionObserver (sehr alte Browser) wird sofort geladen - langsam,
// aber nie leer.
function spaetLaden(el, url) {
  if (!_sichtbar) { el.src = url; return; }
  el.loading = 'lazy';
  el.decoding = 'async';
  el.dataset.src = url;
  _sichtbar.observe(el);
}

// Gleichzeitige Ordnerabrufe begrenzen. Jeder geht über Django weiter an
// Nextcloud; fünfzig auf einmal treffen einen Server mit wenigen
// Arbeitsprozessen, und dann steht alles. Die Grenze gilt global und nicht je
// Aufruf - ein verschachtelter Baum multipliziert sonst jede Ebene mit der
// nächsten, und aus "sechs parallel" werden hundert.
const GRENZE = 6;
let _offen = 0;
const _warteschlange = [];

function _weiter() {
  while (_offen < GRENZE && _warteschlange.length) {
    _offen++;
    _warteschlange.shift()();
  }
}

// Gibt ein Versprechen zurück, das sich auflöst, sobald ein Platz frei ist.
function _platz() {
  return new Promise(ok => { _warteschlange.push(ok); _weiter(); });
}

function _frei() { _offen--; _weiter(); }

// Ruft `arbeit` für jeden Eintrag auf und behält die Reihenfolge der Ergebnisse
// bei. Die Drosselung steckt in fetchFolder, nicht hier.
function parallel(liste, arbeit) {
  return Promise.all(liste.map(arbeit));
}

let _editor = null;

// SVGs müssen zerlegt eingefügt werden, nicht als flaches Bild.
// Der Studio-Teil meldet dazu einen Handler an (siehe studio.js).
let _svgHandler = null;
export function setSvgHandler(fn) { _svgHandler = fn; }
const istSvg = (u) => /\.svg(\?|$)/i.test(String(u || ''));

// Einfügen: bei SVG über den Import, sonst als Bild.
async function einfuegen(item, opts) {
  const url = item.url || item;
  const name = item.name || url;
  if (istSvg(name) || istSvg(url)) {
    if (!_svgHandler) { toast('SVG-Import nicht bereit – bitte Seite neu laden', 'err'); return; }
    try {
      const res = await fetch(url, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const text = await res.text();
      const n = await _svgHandler(text, false, opts);
      toast(n ? `SVG inserted: ${n} layer(s)` : 'SVG contained no shapes', n ? 'ok' : 'err');
    } catch (e) {
      console.error(e);
      toast('SVG-Fehler: ' + e.message, 'err');
    }
    return;
  }
  try { await _editor.addImageUrl(url, opts); }
  catch { toast('Image error', 'err'); }
}

// Angehakte Ordner-Pfade (relativ zu Octotrial_Assets) + aufgeklappte Ordner.
const _checked = new Set();
const _expanded = new Set();
// Cache: Ordnerpfad → { subfolders:[names], items:[bilder] }. '' = oberste Ebene.
const _cache = new Map();

let _outputTab = 'Images';

export function initLibrary(editor) {
  _editor = editor;
  // Suche filtert die aktuell angezeigten Bilder (aus den angehakten Ordnern).
  const search = document.getElementById('lib-search');
  if (search) {
    let t;
    search.oninput = () => { clearTimeout(t); t = setTimeout(() => guard(refreshImages(), 'search refresh'), 250); };
  }
  document.querySelectorAll('#output-tabs [data-out]').forEach(btn => {
    btn.onclick = () => { _outputTab = btn.dataset.out; highlightOutput(); guard(loadOutput(), 'output tab'); };
  });
  highlightOutput();
  guard(loadTree(), 'asset tree');
  guard(loadOutput(), 'output list');
  enableCanvasDrop();
  initUpload();
  // Nach dem Speichern die Ausgaben-Liste auffrischen und auf den passenden
  // Tab springen (Bild→Images, GIF→GIFs, Video→Videos).
  window.addEventListener('studio:output-changed', e => {
    const tab = e.detail?.tab;
    if (tab && ['Images', 'GIFs', 'Videos'].includes(tab)) {
      _outputTab = tab;
      highlightOutput();
    }
    guard(loadOutput(), 'output refresh after save');
  });
}

// ── Upload nach Studio_Work/Upload + Vorschau ───────────────────────────────
function initUpload() {
  const btn = document.getElementById('upload-btn');
  const input = document.getElementById('upload-input');
  const statusEl = document.getElementById('upload-status');
  if (!btn || !input) return;
  // #upload-status may be absent; the upload itself must still work.
  const melde = txt => { if (statusEl) statusEl.textContent = txt; };
  btn.onclick = () => input.click();
  guard(loadUploads(), 'uploads');
  input.onchange = async () => {
    const files = [...input.files];
    input.value = '';
    for (const file of files) {
      melde(`Lade ${file.name}…`);
      try {
        const fd = new FormData();
        fd.append('file', file);
        const r = await fetch(URLS.upload, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCookie('csrftoken') },
          body: fd,
        });
        const d = await readJson(r);
        if (d.ok) melde(`✓ ${file.name} uploaded`);
        else { melde(`✗ ${d.error || 'Fehler'}`); toast('Upload fehlgeschlagen', 'err'); }
      } catch (e) {
        melde('✗ Fehler');
        toast('Upload-Fehler', 'err');
      }
    }
    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
    guard(loadUploads(), 'uploads');
  };
}

async function loadUploads() {
  const grid = document.getElementById('upload-grid');
  if (!grid) return;
  grid.innerHTML = '<span class="no-templates">Loading…</span>';
  try {
    const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent('Studio_Work/Upload'));
    const d = await readJson(r);
    grid.innerHTML = '';
    const items = d.items || [];
    if (!items.length) { grid.innerHTML = '<span class="no-templates">Nothing uploaded yet.</span>'; return; }
    items.forEach(item => {
      const wrap = document.createElement('div');
      wrap.className = 'lib-tile';
      const img = document.createElement('img');
      img.className = 'lib-thumb';
      img.src = item.url;
      img.title = item.title || item.name || '';
      img.draggable = true;
      img.onerror = () => { img.style.opacity = .3; };
      img.onclick = () => einfuegen(item);
      img.addEventListener('dragstart', e => e.dataTransfer.setData('text/studio-url', item.url));
      const del = document.createElement('button');
      del.className = 'tile-del';
      del.textContent = '✕';
      del.title = 'Delete upload';
      del.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm('Really delete this uploaded image?')) return;
        del.disabled = true;
        try {
          const fd = new FormData();
          fd.append('nc_path', item.nc_path);
          const r = await fetch(URLS.uploadDelete, {
            method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body: fd,
          });
          const dd = await readJson(r);
          if (dd.ok) { wrap.remove(); if (!grid.querySelector('.lib-tile')) grid.innerHTML = '<span class="no-templates">Nothing uploaded yet.</span>'; }
          else { toast('Delete failed', 'err'); del.disabled = false; }
        } catch (err) { toast('Error while deleting', 'err'); del.disabled = false; }
      };
      wrap.appendChild(img);
      wrap.appendChild(del);
      grid.appendChild(wrap);
    });
  } catch (e) {
    // Grund zeigen statt „Fehler": readJson unterscheidet abgelaufene Sitzung,
    // Serverfehler und unerwartete Antwort – genau das will man hier lesen.
    grid.innerHTML = '<span class="no-templates">' + esc(e?.message || 'Could not load.') + '</span>';
  }
}

// ── Assets: anhakbarer Ordnerbaum ───────────────────────────────────────────
// Holt Inhalt eines Ordners (gecacht). path '' = oberste Ebene.
// Läuft derselbe Ordner gerade schon? Seit die Unterordner gleichzeitig geholt
// werden, fragen sonst mehrere Aufrufe denselben Pfad parallel ab und der
// Cache greift bei keinem von ihnen.
const _laufend = new Map();

async function fetchFolder(path) {
  if (_cache.has(path)) return _cache.get(path);
  if (_laufend.has(path)) return _laufend.get(path);
  const lauf = (async () => {
    let data = { subfolders: [], items: [] };
    await _platz();
    try {
      if (path === '') {
        const r = await fetch(URLS.ncFolders);
        const d = await readJson(r);
        data = { subfolders: (d.folders || []).map(f => f.name), items: [] };
      } else {
        const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(path));
        const d = await readJson(r);
        data = { subfolders: (d.subfolders || []).map(f => f.name), items: d.items || [] };
      }
    } catch (e) { /* leer lassen */ }
    finally { _frei(); }
    _cache.set(path, data);
    _laufend.delete(path);
    return data;
  })();
  _laufend.set(path, lauf);
  return lauf;
}

async function loadTree() {
  const tree = document.getElementById('lib-tree');
  if (!tree) return;
  tree.innerHTML = '<span class="no-templates">Loading…</span>';
  const root = await fetchFolder('');
  tree.innerHTML = '';
  if (!root.subfolders.length) { tree.innerHTML = '<span class="no-templates">No folders.</span>'; return; }
  for (const name of root.subfolders) tree.appendChild(await makeRow(name, name, 0));
}

// Baut eine Ordnerzeile (Pfeil + Checkbox + Name) inkl. Kindercontainer.
async function makeRow(name, path, depth) {
  const wrap = document.createElement('div');

  const row = document.createElement('div');
  row.className = 'lib-trow';
  row.style.paddingLeft = (depth * 14 + 2) + 'px';

  const exp = document.createElement('span');
  exp.className = 'fexp';
  exp.textContent = _expanded.has(path) ? '▾' : '▸';

  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = _checked.has(path);

  const label = document.createElement('span');
  label.className = 'fname';
  label.textContent = '📁 ' + name;

  const kids = document.createElement('div');
  kids.className = 'lib-kids';
  kids.style.display = _expanded.has(path) ? 'block' : 'none';

  const expand = async () => {
    if (_expanded.has(path)) {
      _expanded.delete(path); kids.style.display = 'none'; exp.textContent = '▸';
    } else {
      _expanded.add(path); exp.textContent = '▾'; kids.style.display = 'block';
      if (!kids.dataset.loaded) {
        kids.dataset.loaded = '1';
        const d = await fetchFolder(path);
        if (!d.subfolders.length) {
          const empty = document.createElement('div');
          empty.className = 'no-templates';
          empty.style.paddingLeft = (depth * 14 + 20) + 'px';
          empty.textContent = 'keine Unterordner';
          kids.appendChild(empty);
        } else {
          for (const sub of d.subfolders) kids.appendChild(await makeRow(sub, path + '/' + sub, depth + 1));
        }
      }
    }
  };
  exp.onclick = () => guard(expand(), 'expand folder');
  label.onclick = () => guard(expand(), 'expand folder');
  cb.onchange = () => {
    if (cb.checked) _checked.add(path); else _checked.delete(path);
    guard(refreshImages(), 'folder selection');
  };

  row.appendChild(exp);
  row.appendChild(cb);
  row.appendChild(label);
  wrap.appendChild(row);
  wrap.appendChild(kids);
  return wrap;
}

// Sammelt rekursiv alle Bilder aus einem Ordner und seinen Unterordnern.
// Die Unterordner einer Ebene werden gleichzeitig geholt, nicht nacheinander:
// vorher war die Wartezeit die Summe aller Ordnerabrufe, und bei einem Baum mit
// dreissig Ordnern kamen so schnell zwanzig Sekunden zusammen. Die Reihenfolge
// im Raster bleibt dieselbe - erst der Ordner selbst, dann seine Unterordner
// der Reihe nach - weil jede Ebene ihre Ergebnisse in der alten Ordnung
// zusammensetzt.
async function gatherImages(path, seen, depth = 0) {
  if (depth > 6) return [];
  const d = await fetchFolder(path);
  const eigene = [];
  for (const it of d.items) {
    const key = it.nc_path || it.url;
    if (!seen.has(key)) { seen.add(key); eigene.push(it); }
  }
  const kinder = await parallel(d.subfolders,
    sub => gatherImages(path + '/' + sub, seen, depth + 1));
  return eigene.concat(...kinder);
}

// Zeigt die Bilder aller angehakten Ordner (rekursiv) im Raster.
async function refreshImages() {
  const grid = document.getElementById('lib-grid');
  if (!grid) return;
  if (!_checked.size) { grid.innerHTML = '<span class="no-templates">Tick folders to display.</span>'; return; }
  grid.innerHTML = '<span class="no-templates">Loading…</span>';
  const seen = new Set();
  const acc = [].concat(...await parallel([..._checked], p => gatherImages(p, seen)));
  const q = (document.getElementById('lib-search')?.value || '').toLowerCase();
  const items = q ? acc.filter(it => (it.title || it.name || '').toLowerCase().includes(q)) : acc;
  grid.innerHTML = '';
  if (!items.length) { grid.innerHTML = '<span class="no-templates">No images found.</span>'; return; }
  renderImages(grid, items);
}

function renderImages(grid, items) {
  items.forEach(item => {
    const img = document.createElement('img');
    img.className = 'lib-thumb';
    img.title = item.title || item.name || '';
    img.draggable = true;
    img.onerror = () => { img.style.opacity = .3; img.title += ' (nicht ladbar)'; };
    img.onclick = () => einfuegen(item);
    img.addEventListener('dragstart', e => e.dataTransfer.setData('text/studio-url', item.url));
    grid.appendChild(img);
    // Erst anhängen, dann laden - der Beobachter braucht das Element im Dokument,
    // sonst schneidet er es nie.
    spaetLaden(img, item.url);
  });
}

// ── Untere Auswahl: fertige Ausgaben ────────────────────────────────────────
function highlightOutput() {
  document.querySelectorAll('#output-tabs [data-out]').forEach(b =>
    b.classList.toggle('primary', b.dataset.out === _outputTab));
}

// Ausgabe-Ordner in Nextcloud (relativ zu Octotrial_Assets) – wie die Assets
// zeigen wir hier DIREKT den Ordnerinhalt an (nicht die DB), damit wirklich
// alles auftaucht, was gespeichert wurde.
const OUTPUT_FOLDERS = {
  Images: 'Studio_Work/Output/Images',
  GIFs:   'Studio_Work/Output/GIFs',
  Videos: 'Studio_Work/Output/Videos',
};

async function loadOutput() {
  const grid = document.getElementById('output-grid');
  if (!grid) return;
  grid.innerHTML = '<span class="no-templates">Loading…</span>';
  const folder = OUTPUT_FOLDERS[_outputTab] || OUTPUT_FOLDERS.Images;
  try {
    // NC-Ordner (zeigt alles). Fehlschlag hier = echter Fehler.
    const rNc = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(folder));
    const d = await readJson(rNc);
    // DB-Liste (liefert die bewährte lib_item-ID zum Öffnen). Fehlschlag ignorieren.
    let db = {};
    try { const rDb = await fetch(URLS.apiSaved); db = await readJson(rDb); } catch (e) { /* egal */ }
    const dbList = _outputTab === 'Images' ? (db.images || [])
                 : _outputTab === 'GIFs'   ? (db.anim_images || [])
                 :                            (db.videos || []);
    // Titel → DB-ID (zum Öffnen über den bewährten Weg).
    // Vergleich normalisiert: Die Ordnerauflistung macht aus dem Dateinamen
    // „Header_Q3.png" den Titel „Header Q3" (Unterstrich → Leerzeichen), der
    // Datenbank-Titel heißt aber „Header_Q3". Ohne diese Angleichung fand kein
    // einziger Name mit Unterstrich mehr seinen Eintrag – die Kachel öffnete
    // dann über den Dateipfad und verlor den Bezug zur Ausgabe.
    const norm = s => String(s || '').trim().toLowerCase().replace(/[\s_]+/g, '_');
    const idByTitle = {};
    dbList.forEach(it => { if (it.title) idByTitle[norm(it.title)] = it.id; });

    // Hilfsdateien (Vorschau/Snapshot/ausgelagerte Objektbilder) nicht anzeigen.
    const items = (d.items || []).filter(it => !/_preview\.|_snap\.|_obj\d+\./i.test(it.name || ''));
    grid.innerHTML = '';
    if (!items.length) { grid.innerHTML = '<span class="no-templates">Nothing saved.</span>'; return; }
    const isVideo = _outputTab === 'Videos';
    items.forEach(item => {
      const el = isVideo ? document.createElement('video') : document.createElement('img');
      el.className = 'lib-thumb';
      // Videos laden sofort: sie holen mit preload="metadata" nur den Kopf der
      // Datei, und es sind wenige. Bilder sind die Last - die werden gestundet,
      // sobald die Kachel im Dokument haengt (weiter unten).
      if (isVideo) el.src = item.url;
      el.title = item.title || item.name || '';
      // A thumbnail whose file will not load is greyed out instead of sitting
      // there looking healthy — for videos it used to stay a black rectangle.
      el.onerror = () => {
        el.style.opacity = .3;
        el.title = (el.title || item.name || '') + ' – preview could not be loaded';
      };
      if (isVideo) {
        el.muted = true; el.loop = true; el.playsInline = true; el.preload = 'metadata';
        el.style.background = '#000';
        el.addEventListener('loadeddata', () => { try { el.currentTime = 0.1; } catch (e) {} });
        // play() returns a promise. When the file is unreachable it rejects with
        // "The element has no supported sources." — unhandled, that reached the
        // global handler and threw a red error banner over a hover.
        el.addEventListener('mouseenter', () => {
          const p = el.play();
          if (p && p.catch) p.catch(() => { el.onerror(); });
        });
        el.addEventListener('mouseleave', () => { try { el.pause(); } catch (e) {} });
      }
      // Öffnen: bevorzugt über die DB-ID (bewährter Weg, stellt Canvas wieder her),
      // sonst über den NC-Pfad.
      // Über den Dateinamen-Stamm suchen (nicht über den aufbereiteten Titel):
      // der Stamm ist das, was auch in der Datenbank als Name steht.
      const stamm = String(item.name || '').replace(/\.[^.]+$/, '');
      const dbId = idByTitle[norm(stamm)] ?? idByTitle[norm(item.title)];
      el.onclick = () => {
        // Nachfragen, bevor ungespeicherte Arbeit durch die Navigation verloren geht.
        if (typeof window.studioDarfVerlassen === 'function' && !window.studioDarfVerlassen()) return;
        location.href = dbId
          ? '/library/studio/?lib_item=' + dbId
          : '/library/studio/?nc_path=' + encodeURIComponent(item.nc_path);
      };
      // Kachel mit Löschen-Knopf
      const tile = document.createElement('div'); tile.className = 'lib-tile';
      // aktuell im Editor geöffnete Ausgabe hervorheben (über NC-Pfad, sonst DB-ID)
      const openNc = CONFIG.libData?.nc_path;
      if ((openNc && item.nc_path && openNc === item.nc_path) ||
          (CONFIG.libData?.item_id && dbId && String(CONFIG.libData.item_id) === String(dbId))) {
        tile.classList.add('active');
      }
      tile.appendChild(el);
      const del = document.createElement('button');
      del.className = 'tile-del'; del.textContent = '✕'; del.title = 'Delete output';
      del.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm('Really delete this output? This also removes the file from Nextcloud.')) return;
        del.disabled = true;
        try {
          const fd = new FormData(); fd.append('nc_path', item.nc_path);
          const r = await fetch(URLS.outputDelete, { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body: fd });
          const dd = await readJson(r);
          if (dd.ok) {
            tile.remove();
            if (!grid.querySelector('.lib-tile')) grid.innerHTML = '<span class="no-templates">Nothing saved.</span>';
          } else { toast(dd.error || 'Delete failed', 'err'); del.disabled = false; }
        } catch (err) { toast('Error while deleting', 'err'); del.disabled = false; }
      };
      tile.appendChild(del);
      grid.appendChild(tile);
      // Jetzt haengt die Kachel im Dokument - ab hier kann der Beobachter sie
      // schneiden und das Bild holen, sobald sie in die Naehe des Sichtbereichs
      // kommt.
      if (!isVideo) spaetLaden(el, item.url);
    });
  } catch (e) {
    // Grund zeigen statt „Fehler": readJson unterscheidet abgelaufene Sitzung,
    // Serverfehler und unerwartete Antwort – genau das will man hier lesen.
    grid.innerHTML = '<span class="no-templates">' + esc(e?.message || 'Could not load.') + '</span>';
  }
}

// ── Drag & Drop auf den Canvas ──────────────────────────────────────────────
function enableCanvasDrop() {
  const wrap = document.getElementById('canvas-wrap');
  if (!wrap) return;
  wrap.addEventListener('dragover', e => { e.preventDefault(); wrap.classList.add('drag-over'); });
  wrap.addEventListener('dragleave', () => wrap.classList.remove('drag-over'));
  wrap.addEventListener('drop', e => {
    e.preventDefault();
    wrap.classList.remove('drag-over');
    const url = e.dataTransfer.getData('text/studio-url');
    if (!url) return;
    const rect = wrap.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (_editor.width / rect.width);
    const y = (e.clientY - rect.top) * (_editor.height / rect.height);
    einfuegen({ url, name: url }, { x, y });
  });
}

// Nach dem Speichern aufrufbar, um die Output-Auswahl zu aktualisieren.
export function refreshOutput() { guard(loadOutput(), 'output refresh'); }
