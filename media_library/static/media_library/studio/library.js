// library.js – rechte Sidebar:
//   OBEN: Upload nach Studio_Work/Upload (mit Vorschau + Löschen).
//   MITTE: Assets aus Nextcloud als anhakbare Ordner-Struktur. Angehakte Ordner
//          (auch Überordner rekursiv) zeigen ihre Bilder gesammelt im Raster.
//   UNTEN: fertige Studio-Ausgaben Images / GIFs / Videos zum Weiterbearbeiten.
import { URLS, getCookie } from './config.js';
import { toast } from './util.js';

let _editor = null;

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
    search.oninput = () => { clearTimeout(t); t = setTimeout(refreshImages, 250); };
  }
  document.querySelectorAll('#output-tabs [data-out]').forEach(btn => {
    btn.onclick = () => { _outputTab = btn.dataset.out; highlightOutput(); loadOutput(); };
  });
  highlightOutput();
  loadTree();        // Assets-Ordnerbaum laden
  loadOutput();      // Output-Auswahl laden
  enableCanvasDrop();
  initUpload();
}

// ── Upload nach Studio_Work/Upload + Vorschau ───────────────────────────────
function initUpload() {
  const btn = document.getElementById('upload-btn');
  const input = document.getElementById('upload-input');
  const statusEl = document.getElementById('upload-status');
  if (!btn || !input) return;
  btn.onclick = () => input.click();
  loadUploads();
  input.onchange = async () => {
    const files = [...input.files];
    input.value = '';
    for (const file of files) {
      statusEl.textContent = `Lade ${file.name}…`;
      try {
        const fd = new FormData();
        fd.append('file', file);
        const r = await fetch(URLS.upload, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCookie('csrftoken') },
          body: fd,
        });
        const d = await r.json();
        if (d.ok) statusEl.textContent = `✓ ${file.name} hochgeladen`;
        else { statusEl.textContent = `✗ ${d.error || 'Fehler'}`; toast('Upload fehlgeschlagen', 'err'); }
      } catch (e) {
        statusEl.textContent = '✗ Fehler';
        toast('Upload-Fehler', 'err');
      }
    }
    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
    loadUploads();
  };
}

async function loadUploads() {
  const grid = document.getElementById('upload-grid');
  if (!grid) return;
  grid.innerHTML = '<span class="no-templates">Lädt…</span>';
  try {
    const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent('Studio_Work/Upload'));
    const d = await r.json();
    grid.innerHTML = '';
    const items = d.items || [];
    if (!items.length) { grid.innerHTML = '<span class="no-templates">Noch nichts hochgeladen.</span>'; return; }
    items.forEach(item => {
      const wrap = document.createElement('div');
      wrap.className = 'lib-tile';
      const img = document.createElement('img');
      img.className = 'lib-thumb';
      img.src = item.url;
      img.title = item.title || item.name || '';
      img.draggable = true;
      img.onerror = () => { img.style.opacity = .3; };
      img.onclick = () => _editor.addImageUrl(item.url).catch(() => toast('Bild-Fehler', 'err'));
      img.addEventListener('dragstart', e => e.dataTransfer.setData('text/studio-url', item.url));
      const del = document.createElement('button');
      del.className = 'tile-del';
      del.textContent = '✕';
      del.title = 'Upload löschen';
      del.onclick = async (e) => {
        e.stopPropagation();
        del.disabled = true;
        try {
          const fd = new FormData();
          fd.append('nc_path', item.nc_path);
          const r = await fetch(URLS.uploadDelete, {
            method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body: fd,
          });
          const dd = await r.json();
          if (dd.ok) { wrap.remove(); if (!grid.querySelector('.lib-tile')) grid.innerHTML = '<span class="no-templates">Noch nichts hochgeladen.</span>'; }
          else { toast('Löschen fehlgeschlagen', 'err'); del.disabled = false; }
        } catch (err) { toast('Fehler beim Löschen', 'err'); del.disabled = false; }
      };
      wrap.appendChild(img);
      wrap.appendChild(del);
      grid.appendChild(wrap);
    });
  } catch (e) {
    grid.innerHTML = '<span class="no-templates">Fehler beim Laden.</span>';
  }
}

// ── Assets: anhakbarer Ordnerbaum ───────────────────────────────────────────
// Holt Inhalt eines Ordners (gecacht). path '' = oberste Ebene.
async function fetchFolder(path) {
  if (_cache.has(path)) return _cache.get(path);
  let data = { subfolders: [], items: [] };
  try {
    if (path === '') {
      const r = await fetch(URLS.ncFolders);
      const d = await r.json();
      data = { subfolders: (d.folders || []).map(f => f.name), items: [] };
    } else {
      const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(path));
      const d = await r.json();
      data = { subfolders: (d.subfolders || []).map(f => f.name), items: d.items || [] };
    }
  } catch (e) { /* leer lassen */ }
  _cache.set(path, data);
  return data;
}

async function loadTree() {
  const tree = document.getElementById('lib-tree');
  if (!tree) return;
  tree.innerHTML = '<span class="no-templates">Lädt…</span>';
  const root = await fetchFolder('');
  tree.innerHTML = '';
  if (!root.subfolders.length) { tree.innerHTML = '<span class="no-templates">Keine Ordner.</span>'; return; }
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
  exp.onclick = expand;
  label.onclick = expand;
  cb.onchange = () => {
    if (cb.checked) _checked.add(path); else _checked.delete(path);
    refreshImages();
  };

  row.appendChild(exp);
  row.appendChild(cb);
  row.appendChild(label);
  wrap.appendChild(row);
  wrap.appendChild(kids);
  return wrap;
}

// Sammelt rekursiv alle Bilder aus einem Ordner und seinen Unterordnern.
async function gatherImages(path, acc, seen, depth = 0) {
  if (depth > 6) return;
  const d = await fetchFolder(path);
  for (const it of d.items) {
    const key = it.nc_path || it.url;
    if (!seen.has(key)) { seen.add(key); acc.push(it); }
  }
  for (const sub of d.subfolders) await gatherImages(path + '/' + sub, acc, seen, depth + 1);
}

// Zeigt die Bilder aller angehakten Ordner (rekursiv) im Raster.
async function refreshImages() {
  const grid = document.getElementById('lib-grid');
  if (!grid) return;
  if (!_checked.size) { grid.innerHTML = '<span class="no-templates">Ordner anhaken zum Anzeigen.</span>'; return; }
  grid.innerHTML = '<span class="no-templates">Lädt…</span>';
  const acc = [], seen = new Set();
  for (const p of _checked) await gatherImages(p, acc, seen);
  const q = (document.getElementById('lib-search')?.value || '').toLowerCase();
  const items = q ? acc.filter(it => (it.title || it.name || '').toLowerCase().includes(q)) : acc;
  grid.innerHTML = '';
  if (!items.length) { grid.innerHTML = '<span class="no-templates">Keine Bilder gefunden.</span>'; return; }
  renderImages(grid, items);
}

function renderImages(grid, items) {
  items.forEach(item => {
    const img = document.createElement('img');
    img.className = 'lib-thumb';
    img.src = item.url;
    img.title = item.title || item.name || '';
    img.draggable = true;
    img.onerror = () => { img.style.opacity = .3; img.title += ' (nicht ladbar)'; };
    img.onclick = () => _editor.addImageUrl(item.url).catch(() => toast('Bild-Fehler', 'err'));
    img.addEventListener('dragstart', e => e.dataTransfer.setData('text/studio-url', item.url));
    grid.appendChild(img);
  });
}

// ── Untere Auswahl: fertige Ausgaben ────────────────────────────────────────
function highlightOutput() {
  document.querySelectorAll('#output-tabs [data-out]').forEach(b =>
    b.classList.toggle('primary', b.dataset.out === _outputTab));
}

async function loadOutput() {
  const grid = document.getElementById('output-grid');
  if (!grid) return;
  grid.innerHTML = '<span class="no-templates">Lädt…</span>';
  try {
    const r = await fetch(URLS.apiSaved);
    const d = await r.json();
    let items;
    if (_outputTab === 'Images')      items = d.images || [];
    else if (_outputTab === 'GIFs')   items = d.anim_images || [];
    else                              items = d.videos || [];
    grid.innerHTML = '';
    if (!items.length) { grid.innerHTML = '<span class="no-templates">Nichts gespeichert.</span>'; return; }
    items.forEach(item => {
      const isVideo = _outputTab === 'Videos';
      const el = isVideo ? document.createElement('video') : document.createElement('img');
      el.className = 'lib-thumb';
      el.src = item.url;
      el.title = item.title || '';
      if (isVideo) { el.muted = true; el.loop = true; el.addEventListener('mouseenter', () => el.play()); el.addEventListener('mouseleave', () => el.pause()); }
      el.onclick = () => { location.href = '/library/studio/?lib_item=' + item.id; };
      grid.appendChild(el);
    });
  } catch (e) {
    grid.innerHTML = '<span class="no-templates">Fehler beim Laden.</span>';
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
    _editor.addImageUrl(url, { x, y }).catch(() => toast('Bild-Fehler', 'err'));
  });
}

// Nach dem Speichern aufrufbar, um die Output-Auswahl zu aktualisieren.
export function refreshOutput() { loadOutput(); }
