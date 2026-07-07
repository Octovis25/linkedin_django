// library.js – rechte Seitenleiste: Bibliothek (DB), Nextcloud, geteilter Pool.
// Klick fügt Bild als Element ein; Drag & Drop auf den Canvas ebenfalls.
import { URLS } from './config.js';
import { toast } from './util.js';

let _editor = null;
let _tab = 'db';

export function initLibrary(editor) {
  _editor = editor;
  document.querySelectorAll('#lib-tabs [data-tab]').forEach(btn => {
    btn.onclick = () => { _tab = btn.dataset.tab; highlightTab(); loadGrid(); };
  });
  const search = document.getElementById('lib-search');
  if (search) {
    let t;
    search.oninput = () => { clearTimeout(t); t = setTimeout(loadGrid, 300); };
  }
  highlightTab();
  loadGrid();
  loadSaved();
  enableCanvasDrop();
}

function highlightTab() {
  document.querySelectorAll('#lib-tabs [data-tab]').forEach(b =>
    b.classList.toggle('primary', b.dataset.tab === _tab));
}

async function loadGrid() {
  const grid = document.getElementById('lib-grid');
  const q = document.getElementById('lib-search')?.value || '';
  grid.innerHTML = '<span class="no-templates">Lädt…</span>';
  try {
    let items = [];
    if (_tab === 'db') {
      const r = await fetch(URLS.apiLibrary + '?q=' + encodeURIComponent(q));
      items = (await r.json()).items || [];
    } else if (_tab === 'shared') {
      const r = await fetch(URLS.sharedAssets + '?q=' + encodeURIComponent(q));
      const d = await r.json();
      items = (d.assets || d.items || []).map(a => ({ id: a.id, title: a.title || a.name, url: a.url }));
    } else if (_tab === 'nc') {
      const r = await fetch(URLS.ncBrowse + '?q=' + encodeURIComponent(q));
      const d = await r.json();
      items = (d.files || d.items || []).map(f => ({ title: f.name, url: f.url || (URLS.ncImage + '?p=' + encodeURIComponent(f.path)) }));
    }
    renderGrid(grid, items);
  } catch (e) {
    grid.innerHTML = '<span class="no-templates">Fehler beim Laden.</span>';
  }
}

function renderGrid(grid, items) {
  grid.innerHTML = '';
  if (!items.length) { grid.innerHTML = '<span class="no-templates">Nichts gefunden.</span>'; return; }
  items.forEach(item => {
    const img = document.createElement('img');
    img.className = 'lib-thumb';
    img.src = item.url;
    img.title = item.title || '';
    img.draggable = true;
    img.dataset.url = item.url;
    img.onerror = () => { img.style.opacity = .3; img.title += ' (nicht ladbar)'; };
    img.onclick = () => _editor.addImageUrl(item.url).catch(() => toast('Bild konnte nicht geladen werden', 'err'));
    img.addEventListener('dragstart', e => e.dataTransfer.setData('text/studio-url', item.url));
    grid.appendChild(img);
  });
}

async function loadSaved() {
  const grid = document.getElementById('saved-grid');
  if (!grid) return;
  try {
    const r = await fetch(URLS.apiSaved);
    const d = await r.json();
    const all = [...(d.images || []), ...(d.anim_images || [])];
    grid.innerHTML = '';
    all.forEach(item => {
      const img = document.createElement('img');
      img.className = 'lib-thumb';
      img.src = item.url;
      img.title = item.title || '';
      img.onclick = () => { location.href = '/library/studio/?lib_item=' + item.id; };
      grid.appendChild(img);
    });
    if (!all.length) grid.innerHTML = '<span class="no-templates">Noch nichts gespeichert.</span>';
  } catch (e) { /* still */ }
}

function enableCanvasDrop() {
  const wrap = document.getElementById('canvas-wrap');
  if (!wrap) return;
  wrap.addEventListener('dragover', e => { e.preventDefault(); wrap.classList.add('drag-over'); });
  wrap.addEventListener('dragleave', () => wrap.classList.remove('drag-over'));
  wrap.addEventListener('drop', async e => {
    e.preventDefault();
    wrap.classList.remove('drag-over');
    const url = e.dataTransfer.getData('text/studio-url');
    if (url) {
      const rect = wrap.getBoundingClientRect();
      const scaleX = _editor.width / rect.width, scaleY = _editor.height / rect.height;
      const x = (e.clientX - rect.left) * scaleX, y = (e.clientY - rect.top) * scaleY;
      _editor.addImageUrl(url, { x, y }).catch(() => toast('Bild-Fehler', 'err'));
    }
  });
}
