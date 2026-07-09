// library.js – rechte Sidebar, neu:
//   OBEN: Assets aus Nextcloud als Ordner-Browser (rein/raus navigieren),
//         Elemente per Klick oder Drag&Drop in den Canvas.
//   UNTEN: fertige Studio-Ausgaben Images / GIFs / Videos zum Weiterbearbeiten.
import { URLS, getCookie } from './config.js';
import { toast } from './util.js';

let _editor = null;

// Aktueller Pfad im Assets-Browser, relativ zu Octotrial_Assets.
// [] = oberste Ebene (Top-Level-Ordner).
let _path = [];

// Ausgabe-Ordner (relativ zu Octotrial_Assets) für die untere Auswahl.
// Muss zu den Speicherzielen in views.py passen (studio_save).
const OUTPUT = {
  Images: 'Studio_Work/Bilder',
  GIFs:   'Studio_Work/Bewegte_Bilder',
  Videos: 'Studio_Work/Bewegte_Bilder',
};
let _outputTab = 'Images';

export function initLibrary(editor) {
  _editor = editor;
  // Suche filtert den aktuellen Ordner
  const search = document.getElementById('lib-search');
  if (search) {
    let t;
    search.oninput = () => { clearTimeout(t); t = setTimeout(browse, 300); };
  }
  // Output-Tabs
  document.querySelectorAll('#output-tabs [data-out]').forEach(btn => {
    btn.onclick = () => { _outputTab = btn.dataset.out; highlightOutput(); loadOutput(); };
  });
  highlightOutput();
  browse();          // Assets-Wurzel laden
  loadOutput();      // Output-Auswahl laden
  enableCanvasDrop();
  initUpload();
}

// ── Upload nach Studio_Work/Upload + direkt einfügen ────────────────────────
function initUpload() {
  const btn = document.getElementById('upload-btn');
  const input = document.getElementById('upload-input');
  const statusEl = document.getElementById('upload-status');
  if (!btn || !input) return;
  btn.onclick = () => input.click();
  loadUploads();     // schon vorhandene Uploads sofort anzeigen
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
        if (d.ok) {
          // NICHT in den Canvas laden – erscheint nur als Vorschau im Assets-Browser.
          statusEl.textContent = `✓ ${file.name} hochgeladen`;
        } else {
          statusEl.textContent = `✗ ${d.error || 'Fehler'}`;
          toast('Upload fehlgeschlagen', 'err');
        }
      } catch (e) {
        statusEl.textContent = '✗ Fehler';
        toast('Upload-Fehler', 'err');
      }
    }
    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
    loadUploads();   // Vorschau-Raster unter dem Knopf aktualisieren
  };
}

// Zeigt den Inhalt von Studio_Work/Upload als Vorschau-Kacheln (nur Vorschau;
// Klick/Drag fügt bei Bedarf in den Canvas ein).
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

// ── Assets-Browser ─────────────────────────────────────────────────────────
async function browse() {
  const grid = document.getElementById('lib-grid');
  const crumb = document.getElementById('lib-crumb');
  const q = document.getElementById('lib-search')?.value || '';
  grid.innerHTML = '<span class="no-templates">Lädt…</span>';

  // Breadcrumb (Pfad + Zurück)
  renderCrumb(crumb);

  try {
    if (_path.length === 0) {
      // Oberste Ebene: Top-Level-Ordner der Assets
      const r = await fetch(URLS.ncFolders);
      const d = await r.json();
      grid.innerHTML = '';
      renderFolders(grid, (d.folders || []).map(f => f.name));
      if (!(d.folders || []).length) grid.innerHTML = '<span class="no-templates">Keine Ordner.</span>';
    } else {
      // In einem Ordner: Unterordner + Bilder
      const folder = _path.join('/');
      const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(folder) + '&q=' + encodeURIComponent(q));
      const d = await r.json();
      grid.innerHTML = '';
      renderFolders(grid, (d.subfolders || []).map(f => f.name));
      renderImages(grid, d.items || []);
      if (!(d.subfolders || []).length && !(d.items || []).length) {
        grid.innerHTML += '<span class="no-templates">Ordner ist leer.</span>';
      }
    }
  } catch (e) {
    grid.innerHTML = '<span class="no-templates">Fehler beim Laden.</span>';
  }
}

function renderCrumb(crumb) {
  if (!crumb) return;
  crumb.innerHTML = '';
  const root = document.createElement('button');
  root.className = 'crumb-btn';
  root.textContent = '📁 Assets';
  root.onclick = () => { _path = []; browse(); };
  crumb.appendChild(root);
  _path.forEach((seg, i) => {
    const sep = document.createElement('span'); sep.textContent = ' / '; sep.style.color = '#aaa';
    crumb.appendChild(sep);
    const b = document.createElement('button');
    b.className = 'crumb-btn';
    b.textContent = seg;
    b.onclick = () => { _path = _path.slice(0, i + 1); browse(); };
    crumb.appendChild(b);
  });
}

function renderFolders(grid, names) {
  names.forEach(name => {
    const tile = document.createElement('div');
    tile.className = 'lib-folder';
    tile.innerHTML = `<div class="lib-folder-icon">📁</div><div class="lib-folder-name">${name}</div>`;
    tile.title = name;
    tile.onclick = () => { _path.push(name); browse(); };
    grid.appendChild(tile);
  });
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
    // Aus der DB (nur echte Studio-Speicherungen) – enthält Canvas-Daten
    // zum vollen Weiterbearbeiten. Klick öffnet den kompletten Canvas.
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
      // Klick → kompletten Canvas mit allen Ebenen wiederherstellen (weiterbearbeiten).
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
