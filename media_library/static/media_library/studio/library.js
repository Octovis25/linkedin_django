// library.js - the right-hand sidebar:
//   TOP:    upload into Studio_Work/Upload (with preview and delete).
//   MIDDLE: assets from Nextcloud as a tickable folder tree. Ticked folders
//           (parents recursively too) show their images together in the grid.
//   BOTTOM: finished Studio outputs - images / GIFs / videos - to work on again.
import { URLS, getCookie, CONFIG } from './config.js';
import { toast, readJson } from './util.js';

// Async work kicked off from a sync handler. Without this the rejection reaches
// the global handler in studio.html and paints a red banner over the page for
// what is usually a failed background refresh.
const guard = (p, what) => Promise.resolve(p).catch(e => console.error('[library] ' + what + ':', e));

// Fehlermeldungen landen im DOM – nie ungeprüft.
const esc = t => String(t).replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

// ── Load tiles only once they can be seen ──────────────────────────────────
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

// Without IntersectionObserver (very old browsers) everything loads at once:
// slow, but never blank.
function spaetLaden(el, url) {
  if (!_sichtbar) { el.src = url; return; }
  el.loading = 'lazy';
  el.decoding = 'async';
  el.dataset.src = url;
  _sichtbar.observe(el);
}

// Limit how many folder requests run at once. Each one goes through Django on
// to Nextcloud; fifty at a time overwhelm a server with few worker processes
// and everything stalls. The limit is global, not per call - otherwise a
// nested tree multiplies every level by the next one and "six at a time"
// quietly becomes a hundred.
const GRENZE = 6;
let _offen = 0;
const _warteschlange = [];

function _weiter() {
  while (_offen < GRENZE && _warteschlange.length) {
    _offen++;
    _warteschlange.shift()();
  }
}

// Returns a promise that resolves as soon as a slot is free.
function _platz() {
  return new Promise(ok => { _warteschlange.push(ok); _weiter(); });
}

function _frei() { _offen--; _weiter(); }

// Calls `arbeit` for every entry and keeps the order of the results. The
// throttling lives in fetchFolder, not here.
function parallel(liste, arbeit) {
  return Promise.all(liste.map(arbeit));
}

let _editor = null;

// SVGs have to be inserted taken apart, not as one flat image.
// The Studio side registers a handler for that (see studio.js).
let _svgHandler = null;
export function setSvgHandler(fn) { _svgHandler = fn; }
const istSvg = (u) => /\.svg(\?|$)/i.test(String(u || ''));

// Insert: an SVG goes through the import, anything else as an image.
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

// Ticked folder paths (relative to Octotrial_Assets) and expanded folders.
const _checked = new Set();
const _expanded = new Set();
// Cache: Ordnerpfad → { subfolders:[names], items:[bilder] }. '' = oberste Ebene.
const _cache = new Map();

let _outputTab = 'Images';

export function initLibrary(editor) {
  _editor = editor;
  // The search box filters the images currently shown (from the ticked folders).
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
  // After a save, refresh the outputs list and jump to the matching tab
  // (image → Images, GIF → GIFs, video → Videos).
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
      // Kachel: verkleinerte Fassung. Eingefügt wird weiterhin item.url.
      img.src = item.thumb || item.url;
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
        } catch (err) {
          // Show the reason, not "Error while deleting". Now that the server
          // says WHY a deletion failed - locked file, refused sign-in, Nextcloud
          // out of reach - it would be a waste to swallow it again here.
          toast(err?.message || 'Error while deleting', 'err');
          del.disabled = false;
        }
      };
      wrap.appendChild(img);
      wrap.appendChild(del);
      grid.appendChild(wrap);
    });
  } catch (e) {
    // Grund zeigen statt „Fehler": readJson unterscheidet abgelaufene Sitzung,
    // A server error and an unexpected answer - exactly what one wants to read.
    grid.innerHTML = '<span class="no-templates">' + esc(e?.message || 'Could not load.') + '</span>';
  }
}

// ── Assets: anhakbarer Ordnerbaum ───────────────────────────────────────────
// Holt Inhalt eines Ordners (gecacht). path '' = oberste Ebene.
// Is this same folder already being fetched? Since subfolders are fetched at
// the same time, several calls would otherwise ask for one path in parallel
// and the cache would help none of them.
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

// Collects every image in a folder and its subfolders, recursively.
// The subfolders of one level are fetched at the same time, not one after the
// other: the wait used to be the sum of all folder requests, and a tree with
// thirty folders added up to twenty seconds. The order in the grid stays the
// same - the folder itself first, then its subfolders in turn - because every
// level puts its results back together in the old order.
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

// Shows the images of all ticked folders (recursively) in the grid.
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
    // Append first, then load - the observer needs the element in the document,
    // otherwise it never intersects it.
    // item.thumb is the scaled-down image from the server (about 15 KB instead
    // of 1.5 MB). It is for the TILE only: inserting into the canvas still uses
    // item.url, or a 240-pixel image would suddenly land on the artboard.
    spaetLaden(img, item.thumb || item.url);
  });
}

// ── Untere Auswahl: fertige Ausgaben ────────────────────────────────────────
function highlightOutput() {
  document.querySelectorAll('#output-tabs [data-out]').forEach(b =>
    b.classList.toggle('primary', b.dataset.out === _outputTab));
}

// Output folders in Nextcloud (relative to Octotrial_Assets). Only the fallback
// now, for older servers that do not know the combined endpoint.
const OUTPUT_FOLDERS = {
  Images: 'Studio_Work/Output/Images',
  GIFs:   'Studio_Work/Output/GIFs',
  Videos: 'Studio_Work/Output/Videos',
};

// When an output is attached to a post, the server MOVES the file out of the
// Studio folder into the Planner folder. Until September 2026 this list read
// only the Studio folder - so every output that had ever hung on a post had
// vanished from here, although it still existed. The combined endpoint reads
// both places and merges them.
async function holeAusgaben() {
  if (URLS.apiOutputs) {
    const r = await fetch(URLS.apiOutputs + '?kind=' + encodeURIComponent(_outputTab));
    return await readJson(r);
  }
  // Older server: at least show the Studio folder.
  const folder = OUTPUT_FOLDERS[_outputTab] || OUTPUT_FOLDERS.Images;
  const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(folder));
  return await readJson(r);
}

async function loadOutput() {
  const grid = document.getElementById('output-grid');
  if (!grid) return;
  grid.innerHTML = '<span class="no-templates">Loading…</span>';
  try {
    const d = await holeAusgaben();
    // DB-Liste (liefert die bewährte lib_item-ID zum Öffnen). Fehlschlag ignorieren.
    let db = {};
    try { const rDb = await fetch(URLS.apiSaved); db = await readJson(rDb); } catch (e) { /* egal */ }
    const dbList = _outputTab === 'Images' ? (db.images || [])
                 : _outputTab === 'GIFs'   ? (db.anim_images || [])
                 :                            (db.videos || []);
    // Title → database id (the proven way to open an output).
    // The comparison is normalised: the folder listing turns the file name
    // "Header_Q3.png" into the title "Header Q3" (underscore → space), while
    // the database title is "Header_Q3". Without lining the two up, no name
    // with an underscore found its entry any more - the tile then opened via
    // the file path and lost its link to the output.
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
      // Videos load straight away: with preload="metadata" they only fetch the
      // head of the file, and there are few of them. Images are the load - those
      // are deferred once the tile is in the document (further down).
      if (isVideo) el.src = item.url;
      // "on post" means: the file sits in the Planner folder because it hangs on
      // a post. That is worth showing - otherwise one wonders why some outputs
      // behave differently.
      el.title = (item.title || item.name || '') + (item.am_post ? ' · am Post' : '');
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
      // Opening: by database id where possible (the proven way, it restores the
      // canvas), otherwise by Nextcloud path.
      // Look it up by the file-name stem, not by the tidied-up title: the stem is
      // what the database holds as the name.
      const stamm = String(item.name || '').replace(/\.[^.]+$/, '');
      const dbId = idByTitle[norm(stamm)] ?? idByTitle[norm(item.title)];
      el.onclick = () => {
        // Ask first, before navigating away loses unsaved work.
        if (typeof window.studioDarfVerlassen === 'function' && !window.studioDarfVerlassen()) return;
        location.href = dbId
          ? '/library/studio/?lib_item=' + dbId
          : '/library/studio/?nc_path=' + encodeURIComponent(item.nc_path);
      };
      // Kachel mit Löschen-Knopf
      const tile = document.createElement('div'); tile.className = 'lib-tile';
      // Highlight the output currently open in the editor (by NC path, else by id)
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
        } catch (err) {
          // Show the reason, not "Error while deleting". Now that the server
          // says WHY a deletion failed - locked file, refused sign-in, Nextcloud
          // out of reach - it would be a waste to swallow it again here.
          toast(err?.message || 'Error while deleting', 'err');
          del.disabled = false;
        }
      };
      tile.appendChild(del);
      grid.appendChild(tile);
      // The tile hangs in the document now - from here the observer can see it
      // and fetch the image as soon as it comes near the visible area.
      if (!isVideo) spaetLaden(el, item.thumb || item.url);
    });
  } catch (e) {
    // Grund zeigen statt „Fehler": readJson unterscheidet abgelaufene Sitzung,
    // A server error and an unexpected answer - exactly what one wants to read.
    grid.innerHTML = '<span class="no-templates">' + esc(e?.message || 'Could not load.') + '</span>';
  }
}

// ── Drag and drop onto the canvas ──────────────────────────────────────────
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

// Call after saving to refresh the outputs picker.
export function refreshOutput() { guard(loadOutput(), 'output refresh'); }
