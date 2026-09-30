// entwuerfe.js - prepared drafts.
// Videos and pictures prepared outside the Studio (by Claude, say) arrive as a
// Studio draft in Nextcloud: Studio_Work/Drafts/<name>.json plus a preview
// <name>.png. A name that starts with "post<id>_" belongs to that post. The
// Studio offers them in two places: a button in the post banner when the post
// has one, and the "Drafts" tab in the media panel for all of them.
// Opening one puts it on the canvas like a template - one undo step - and
// saving works as always, for the post the Studio was opened for.
import { URLS, CONFIG } from './config.js';
import { toast, status, modal, readJson, esc } from './util.js';

export const DRAFT_FOLDER = 'Studio_Work/Drafts';
const MERKEN_MS = 5 * 60 * 1000;     // one folder listing per five minutes

let _liste = null, _geholt = 0, _laden = null;

// "post140_2026-10-05_hidden_workload.png" -> its parts.
export function entwurfAus(item) {
  const name = item.name || '';
  if (!/\.png$/i.test(name) || /_(preview|snap|obj\d+)\.png$/i.test(name)) return null;
  const stamm = name.replace(/\.png$/i, '');
  const m = stamm.match(/^post(\d+)_(?:(\d{4}-\d{2}-\d{2})_)?(.*)$/i);
  const rest = (m ? m[3] : stamm).replace(/_/g, ' ').trim();
  return {
    stamm,
    post: m ? +m[1] : null,
    datum: m && m[2] ? m[2] : '',
    titel: rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : stamm,
    bild: item.thumb || item.url,
    json: String(item.nc_path || '').replace(/\.png$/i, '.json'),
  };
}

export async function holeEntwuerfe(neu = false) {
  if (!neu && _liste && Date.now() - _geholt < MERKEN_MS) return _liste;
  if (!URLS.ncBrowse) return [];
  const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(DRAFT_FOLDER));
  const d = await readJson(r);
  _liste = (d.items || []).map(entwurfAus).filter(Boolean)
    // By post date, the next one first; drafts without a date at the end.
    .sort((a, b) => (a.datum || '9999').localeCompare(b.datum || '9999') || a.titel.localeCompare(b.titel));
  _geholt = Date.now();
  return _liste;
}

const TAGE = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONATE = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function datumText(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T12:00:00');
  return isNaN(d) ? iso : `${TAGE[d.getDay()]} ${d.getDate()} ${MONATE[d.getMonth()]}`;
}

function aktuellerPost() { return CONFIG.postId || (CONFIG.postData && CONFIG.postData.id) || null; }

async function oeffnen(e) {
  const ok = await modal(`Open “${esc(e.titel)}”?`,
    'What is on the canvas now is replaced. Undo brings it back.',
    [{ label: 'Cancel', value: false }, { label: 'Open draft', value: true }]);
  if (!ok) return false;
  status('⏳ Loading draft…');
  try {
    const r = await fetch(URLS.ncImage + '?p=' + encodeURIComponent(e.json), { credentials: 'same-origin' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const text = await r.text();
    const zustand = JSON.parse(text);            // unreadable -> the catch below, canvas untouched
    const geladen = await _laden(text);
    // A prepared video knows how long it should run.
    const sek = +zustand.videoLength;
    if (geladen && sek > 0) {
      window._videoLen = String(sek);
      const el = document.getElementById('video-length');
      if (el) el.value = String(sek);
    }
    status(geladen ? 'Draft “' + e.titel + '” opened.' : '⚠️ Draft opened, but not everything could be loaded.',
           geladen ? '#198754' : '#854F0B');
    return geladen;
  } catch (err) {
    console.warn('[drafts] open', err);
    status('❌ Draft could not be opened', 'red');
    toast('Draft could not be opened: ' + err.message, 'err');
    return false;
  }
}

function kachel(e, fuerDiesen) {
  const k = document.createElement('button');
  k.type = 'button';
  k.className = 'draft-tile';
  k.dataset.draft = e.stamm;
  k.title = 'Open this draft on the canvas';
  k.innerHTML = `<img src="${esc(e.bild)}" alt="" loading="lazy">
    <span class="draft-text"><b>${esc(e.titel)}</b>
    <small>${[e.post ? '#' + e.post : '', datumText(e.datum)].filter(Boolean).map(esc).join(' · ')}</small>
    ${fuerDiesen ? '<span class="draft-chip">for this post</span>' : ''}</span>`;
  k.querySelector('img').onerror = function () { this.style.visibility = 'hidden'; };
  k.onclick = () => oeffnen(e);
  return k;
}

export async function zeigeEntwuerfe(neu = false) {
  const grid = document.getElementById('draft-grid');
  if (!grid) return;
  grid.innerHTML = '<span class="no-templates">Loading…</span>';
  let liste;
  try { liste = await holeEntwuerfe(neu); }
  catch (err) {
    grid.innerHTML = '<span class="no-templates">Drafts could not be loaded.</span>';
    console.warn('[drafts] list', err);
    return;
  }
  grid.innerHTML = '';
  if (!liste.length) {
    grid.innerHTML = '<span class="no-templates">No prepared drafts in ' + esc(DRAFT_FOLDER) + '.</span>';
    return;
  }
  const pid = aktuellerPost();
  const eigene = liste.filter(e => pid && e.post === pid), andere = liste.filter(e => !(pid && e.post === pid));
  const kopf = t => { const h = document.createElement('h4'); h.className = 'draft-head'; h.textContent = t; return h; };
  if (eigene.length) { grid.append(kopf('For this post')); eigene.forEach(e => grid.append(kachel(e, true))); }
  if (andere.length) { if (eigene.length) grid.append(kopf('Other drafts')); andere.forEach(e => grid.append(kachel(e, false))); }
}

// The button in the post banner - only when a draft for this post exists.
async function knopfFuerPost() {
  const pid = aktuellerPost();
  const banner = document.querySelector('.post-banner');
  if (!pid || !banner) return;
  let liste;
  try { liste = await holeEntwuerfe(); } catch (err) { return; }   // no button, no noise
  const e = liste.find(x => x.post === pid);
  if (!e || document.getElementById('open-draft-btn')) return;
  let leiste = banner.querySelector('.post-actions');
  if (!leiste) { leiste = document.createElement('div'); leiste.className = 'post-actions'; banner.appendChild(leiste); }
  const b = document.createElement('button');
  b.type = 'button'; b.id = 'open-draft-btn'; b.className = 'tbtn primary';
  b.textContent = '✏️ Open prepared draft';
  b.title = 'Open “' + e.titel + '” from ' + DRAFT_FOLDER;
  b.onclick = () => oeffnen(e);
  leiste.prepend(b);
}

// laden(json) puts a draft on the canvas and resolves true when complete.
export function initEntwuerfe(laden) {
  _laden = laden;
  const tabs = document.getElementById('media-tabs');
  if (tabs) tabs.addEventListener('click', ev => {
    const btn = ev.target.closest('[data-media="drafts"]');
    if (btn) zeigeEntwuerfe();
  });
  const neu = document.getElementById('draft-reload');
  if (neu) neu.onclick = () => zeigeEntwuerfe(true);
  knopfFuerPost();
}
