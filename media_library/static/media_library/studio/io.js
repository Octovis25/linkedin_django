// io.js - saving and loading. Builds the PNG plus canvas_json and talks to the
// existing Django backend (studio_save). A reload rebuilds the Fabric state exactly.
import { URLS, POST_ID, CONFIG, getCookie, proxyUrl } from './config.js';
import { toast, status, readJson } from './util.js';
import { fabric, EXTRA_PROPS } from './editor.js';
import { beendeVorschauen, vorschauenUebernehmen } from './retouch.js';
import { vorschlagAusInhalt, vergebeneNamen, eindeutig, entschaerfe, frageNachNamen } from './namen.js';

// Makes sure a unique name is settled BEFORE anything is saved.
// The name is the design's identity - the image, GIF and video of one design
// share it. So it is asked for once and then stays.
//
// Returns: the name, or null if the user cancelled.
// Remembers the name for this session even when CONFIG.libData does not carry
// it. Needed while working on a planner post: there the server sends no
// libData, so every save looked like a first save - and the name picked up a
// _2, _3, _4 … every single time.
let _festerName = null;
export function merkeNamen(n) { _festerName = n || null; }

export async function nameSicherstellen(editor) {
  const feld = document.getElementById('title-input');
  const eingetippt = (feld?.value || '').trim();
  // Welcher Name gilt aktuell als „meiner"? Reihenfolge: in dieser Sitzung
  // vergeben → vom Server geladen → beim Post hinterlegter Titel.
  const gespeicherterName = (_festerName || CONFIG.libData?.title
                             || (POST_ID ? CONFIG.postData?.title : '') || '').trim();
  const schonGespeichert = !!(_festerName || CONFIG.libData?.item_id
                              || CONFIG.libData?.nc_path || (POST_ID && gespeicherterName));

  // Title field empty but a name already exists? Keep that one instead of
  // creating the design a second time under a new name.
  if (schonGespeichert && !eingetippt && gespeicherterName) {
    const n = entschaerfe(gespeicherterName);
    if (feld) feld.value = n;
    _festerName = n;
    return n;
  }

  if (schonGespeichert && eingetippt && entschaerfe(eingetippt) === entschaerfe(gespeicherterName)) {
    const n = entschaerfe(eingetippt);
    if (feld) feld.value = n;
    _festerName = n;
    return n;                                 // unverändert → nichts zu tun
  }

  status('⏳ Checking names…');
  const belegt = await vergebeneNamen();

  // Renaming an existing output: only check, do not ask again.
  if (schonGespeichert && eingetippt) {
    const sauber = entschaerfe(eingetippt);
    const eigenKlein = entschaerfe(gespeicherterName).toLowerCase();
    if (sauber && (!belegt.has(sauber.toLowerCase()) || sauber.toLowerCase() === eigenKlein)) {
      if (feld) feld.value = sauber;
      _festerName = sauber;
      return sauber;
    }
    // Kollision beim Umbenennen → nachfragen statt still zu überschreiben.
    const gewaehlt = await frageNachNamen({
      vorschlag: eindeutig(sauber, belegt, gespeicherterName), belegt, eigener: gespeicherterName,
      titel: 'Name schon vergeben',
      hinweis: `“${sauber}” already belongs to another output. Please choose a different name.`,
    });
    if (!gewaehlt) { status('Rename cancelled – nothing saved', 'red'); return null; }
    if (feld) feld.value = gewaehlt;
    _festerName = gewaehlt;
    return gewaehlt;
  }

  // First save: ask for the name, suggesting one built from the content.
  let vorschlag = entschaerfe(eingetippt) || vorschlagAusInhalt(editor)
                  || entschaerfe(CONFIG.postData?.title || '');
  if (!vorschlag) {
    // No text in the design and no post title → fall back to numbering.
    let n = 1;
    while (belegt.has(('Draft_' + n).toLowerCase())) n++;
    vorschlag = 'Draft_' + n;
  }
  vorschlag = eindeutig(vorschlag, belegt, null);

  const gewaehlt = await frageNachNamen({ vorschlag, belegt, eigener: null });
  if (!gewaehlt) { status('Save cancelled', 'red'); return null; }
  if (feld) { feld.value = gewaehlt; feld.style.border = ''; }
  _festerName = gewaehlt;
  return gewaehlt;
}

// Fabric-Objekttypen, die sich sicher wiederherstellen lassen.
function _klassOk(type) {
  if (!type || typeof type !== 'string') return false;
  const name = type.split('-').map(s => s.charAt(0).toUpperCase() + s.slice(1)).join('');
  return !!(fabric && fabric[name] && typeof fabric[name].fromObject === 'function');
}

// The same list as undo/redo - there used to be two lists here, and they drifted
// apart (see editor.js).
const FABRIC_PROPS = EXTRA_PROPS;

// Is a save running right now? Stops a second click on "Save" from creating a
// second library entry and a second file.
let _saving = false;
export function istAmSpeichern() { return _saving; }

// Is the editor loading a file? Saving or exporting at that moment would write
// a half-filled canvas over the original.
function ladeGuard(editor) {
  if (editor._locked) {
    status('⏳ Still loading – please wait a moment', 'red');
    toast('The draft is still loading', 'err');
    return true;
  }
  return false;
}

// One way of reading a response: without checking res.ok, a 500 returns an HTML
// error page that res.json() chokes on - the user then saw
// "SyntaxError: Unexpected token '<'" instead of something they could act on.

// Builds the canvas_json. It holds:
//   fabric         - the full Fabric state, for an exact reload
//   objects[]      - a flat list with imgSrc, so the backend can move images out
//                    to Nextcloud (_optimize_canvas_json expects this field)
//   previewDataUrl - the preview (stays in the main folder)
// An absolute address ties a design to the machine it was saved on. Fabric
// turns a relative image source into a full URL while loading, so a draft saved
// on the development server carried http://127.0.0.1:8000/... - and opened on
// Render as an empty artboard, because that host does not exist there. Nobody
// could see why. Addresses on our own server are therefore stored as paths.
export function alsPfadSpeichern(url) {
  if (typeof url !== 'string' || !url) return url;
  const eigen = window.location.origin;
  return url.startsWith(eigen + '/') ? url.slice(eigen.length) : url;
}

// The same in reverse, and more forgiving: a draft that already carries a
// foreign host is repaired on opening, whatever host that was, as long as what
// follows is a path of this app.
export function alsPfadLesen(url) {
  if (typeof url !== 'string' || !url) return url;
  const t = url.match(/^https?:\/\/[^/]+(\/(?:library|planner|media|static)\/.*)$/i);
  return t ? t[1] : url;
}

function pfadeEinebnen(zustand, fn) {
  (zustand.objects || []).forEach(o => {
    if (!o) return;
    ['src', 'srcUrl', 'originalUrl'].forEach(k => { if (o[k]) o[k] = fn(o[k]); });
    if (Array.isArray(o.objects)) pfadeEinebnen(o, fn);   // Gruppen
  });
  if (zustand.backgroundImage && zustand.backgroundImage.src) {
    zustand.backgroundImage.src = fn(zustand.backgroundImage.src);
  }
}

export function buildCanvasJson(editor, previewDataUrl) {
  const fabricState = editor.canvas.toJSON(FABRIC_PROPS);
  // _snap-Hilfslinien nicht mitspeichern
  fabricState.objects = (fabricState.objects || []).filter(o => !o._snap);
  pfadeEinebnen(fabricState, alsPfadSpeichern);

  const objects = editor.canvas.getObjects()
    .filter(o => o.type === 'image' && !o._snap)
    .map(o => ({ imgSrc: alsPfadSpeichern(o.srcUrl || o.getSrc?.() || ''),
                 originalUrl: alsPfadSpeichern(o.originalUrl || '') }));

  return JSON.stringify({
    version: 2,
    width: editor.width,
    height: editor.height,
    fabric: fabricState,
    objects,
    previewDataUrl: previewDataUrl || '',
  });
}

// Vollbild-PNG. Dank Proxy-geladener Bilder nie getaintet.
export function exportPng(editor) {
  // Rote Markierungs-Vorschau zurücknehmen – die gehört nie ins Ergebnis.
  beendeVorschauen(editor.canvas);
  // exportDataURL hides the alignment grid for the export.
  return editor.exportDataURL({ multiplier: 1 });
}

// Returns true when something really was saved, false otherwise. Only then may
// the caller show a success message. It used to write "Saved." unconditionally,
// even when this function had given up.
export async function saveImage(editor) {
  if (ladeGuard(editor)) return false;
  // The design could not be loaded in full when it was opened. Saving over that
  // same file now would destroy the original for good.
  if (editor._ladefehler && (CONFIG.libData?.item_id || CONFIG.libData?.nc_path)) {
    const weiter = window.confirm(
      'Warning: this draft was not fully loaded when opened ' +
      '(missing or corrupted images).\n\n' +
      'If you save now, the existing file will be overwritten with the incomplete ' +
      'state.\n\nSave anyway?');
    if (!weiter) { status('Save cancelled', 'red'); return false; }
  }
  if (_saving) { toast('Already saving…', 'err'); return false; }
  _saving = true;
  try {
    return await _saveImage(editor);
  } finally {
    _saving = false;
  }
}

async function _saveImage(editor) {
  // Turn any open brush or selection state into real images BEFORE the JSON is
  // built - a canvas as an image element does not survive serialisation.
  await vorschauenUebernehmen(editor.canvas);
  // Settle the unique name (asks on the first save, checks on a rename).
  // Without a name, nothing is saved.
  const title = await nameSicherstellen(editor);
  if (!title) return false;
  status('💾 Speichert…');

  let dataUrl, preview;
  try {
    dataUrl = exportPng(editor);          // nimmt Markierungs-Vorschauen zurück
    preview = editor.exportDataURL({ multiplier: 0.4 });
  } catch (e) {
    status('❌ Export failed (image tainted)', 'red');
    toast('An image is cross-origin – loading via the proxy', 'err');
    return false;
  }

  // Only carry on editing when an IMAGE is really open. With a GIF open and a
  // save as PNG, the GIF entry used to be repurposed as the image entry, and
  // the GIF file was no longer reachable through any entry.
  const istBildOffen = (CONFIG.libData?.kind || 'image') === 'image';
  const body = {
    dataUrl, title,
    post_id: POST_ID || '',
    lib_item_id: istBildOffen ? (CONFIG.libData?.item_id || null) : null,
    openNcPath: istBildOffen ? (CONFIG.libData?.nc_path || null) : null,
    templateId: editor._templateId || null,
    folderId: document.getElementById('save-folder')?.value || null,
    canvasJson: buildCanvasJson(editor, preview),
  };

  try {
    const res = await fetch(URLS.save, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify(body),
    });
    const d = await readJson(res);
    if (d.ok) {
      if (d.warning) {
        // The image is stored, but the editable design could not be saved with
        // it. The user has to know that before closing the page.
        status('⚠️ ' + d.warning, 'red');
        toast('Image saved – draft not (details above)', 'err');
        window.alert('Achtung:\n\n' + d.warning);
      } else {
        status('✅ Image saved!', 'green');
        toast('Gespeichert', 'ok');
      }
      // Remember WHAT was just saved. Without it, every further save after a
      // title change creates another duplicate.
      CONFIG.libData = { ...(CONFIG.libData || {}), item_id: d.lib_id ?? CONFIG.libData?.item_id ?? null,
                         title, nc_path: d.nc_path ?? CONFIG.libData?.nc_path ?? null, kind: 'image' };
      window.dispatchEvent(new CustomEvent('studio:output-changed', { detail: { tab: 'Images' } }));
      if (d.lib_id && !POST_ID) history.replaceState(null, '', '/library/studio/?lib_item=' + d.lib_id);
      // Erfolgreich gespeichert → der Editor gilt wieder als „sauber".
      editor._ladefehler = false;
      return true;
    }
    status('❌ ' + (d.error || 'Error'), 'red');
    toast(d.error || 'Save failed', 'err');
    return false;
  } catch (e) {
    status('❌ ' + (e.message || e), 'red');
    toast(e.message || 'Save failed', 'err');
    return false;
  }
}

// Saves an exported moving image (WebM/GIF) into "My outputs" - including the
// canvas_json, so it can be opened in the editor again later.
export async function saveAnimation(editor, blob, ext) {
  await vorschauenUebernehmen(editor.canvas);
  // Use the same name as the image: the image, GIF and video of one design are
  // called the same and belong together through that.
  const title = await nameSicherstellen(editor);
  if (!title) return { ok: false, error: 'cancelled' };
  let preview = '';
  try { preview = editor.exportDataURL({ multiplier: 0.4 }); } catch (e) { /* egal */ }
  const safe = title.replace(/[^a-zA-Z0-9_.-]/g, '_') + ext;
  const fd = new FormData();
  fd.append('video', blob, safe);
  fd.append('title', title);
  fd.append('canvas_json', buildCanvasJson(editor, preview));
  const folder = document.getElementById('save-folder')?.value;
  if (folder) fd.append('folder_id', folder);
  // Send lib_item_id ONLY when the open output has the same format. Otherwise
  // the image entry was repurposed as the GIF entry: the PNG file stayed where
  // it was, but was no longer reachable through any entry and opened without
  // its layers afterwards. Now every format gets its own entry - held together
  // by the shared, unique name.
  const offenesFormat = CONFIG.libData?.kind;
  const diesesFormat = ext === '.gif' ? 'gif' : 'video';
  if (CONFIG.libData?.item_id && offenesFormat === diesesFormat) {
    fd.append('lib_item_id', CONFIG.libData.item_id);
  }
  if (CONFIG.postId) fd.append('post_id', CONFIG.postId);   // GIF/Video an den Post hängen
  try {
    const res = await fetch(URLS.saveVideoFile, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
      body: fd,
    });
    const d = await readJson(res);
    if (d.ok) {
      status('✅ Gespeichert als „' + title + '"', 'green');
      toast('Saved to “My outputs”', 'ok');
      CONFIG.libData = { ...(CONFIG.libData || {}), item_id: d.lib_id ?? null, title,
                         nc_path: d.nc_path ?? null, kind: ext === '.gif' ? 'gif' : 'video' };
      window.dispatchEvent(new CustomEvent('studio:output-changed',
        { detail: { tab: ext === '.gif' ? 'GIFs' : 'Videos' } }));
    } else {
      toast(d.error || 'Saving to outputs failed', 'err');
    }
    return d;
  } catch (e) {
    status('❌ ' + (e.message || e), 'red');
    toast(e.message || 'Error saving to outputs', 'err');
    return { ok: false, error: String(e.message || e) };
  }
}

export function downloadImage(editor) {
  if (ladeGuard(editor)) return;
  try {
    const a = document.createElement('a');
    a.href = exportPng(editor);
    a.download = (document.getElementById('title-input')?.value.trim() || 'studio') + '.png';
    a.click();
  } catch (e) {
    status('❌ Herunterladen fehlgeschlagen', 'red');
    toast('An image is cross-origin – loading via the proxy', 'err');
  }
}

// ---- Loading --------------------------------------------------------------
// Restores a saved canvas. Image URLs are loaded through the proxy
// (crossOrigin), so cutting out and exporting still work afterwards.
// opts.frisch = true resets the history to the loaded state. That is right
// ONLY when opening the page. Applying a template in the middle of the work
// must keep the history, otherwise everything done before would no longer be
// reachable with Ctrl+Z.
export function restoreCanvas(editor, canvasJsonStr, opts = {}) {
  // A promise from now on: callers can wait for the load to FINISH. Before
  // this, "save template" straight after opening ran on a still empty canvas -
  // and so overwrote the template with an empty image.
  let state;
  try {
    state = JSON.parse(canvasJsonStr);
  } catch (e) {
    console.warn('canvas_json parse', e);
    // Do not carry on quietly: the user would take the empty editor for their
    // file, build it again, and overwrite an original that could be repaired.
    editor._ladefehler = true;
    status('❌ Saved data unreadable – please do not overwrite', 'red');
    toast('Draft could not be read', 'err');
    return Promise.resolve(false);
  }

  // A new load invalidates one still running (double-clicking two templates
  // used to mix both layouts onto the artboard).
  const token = ++editor._loadToken;

  editor._locked = true;   // VOR setSize: dessen snapshot() schrieb sonst den
                           // leeren Canvas als ältesten Undo-Schritt.
  if (state.width && state.height) editor.setSize(state.width, state.height);

  const fabricState = state.fabric || state;   // v2 hat .fabric, sonst direkt
  // Keep only objects that can be restored - a single unknown object used to
  // bring down the whole loadFromJSON (fromObject undefined).
  const before = (fabricState.objects || []).length;
  fabricState.objects = (fabricState.objects || []).filter(o => o && _klassOk(o.type));
  if (fabricState.objects.length < before) {
    console.warn(`restoreCanvas: ${before - fabricState.objects.length} unlesbare(s) Objekt(e) übersprungen`);
  }
  // Neutralise damaged text styles - otherwise Fabric crashes while
  // serialising (stylesToArray). Basic formatting is kept.
  fabricState.objects.forEach(o => {
    if (['text', 'textbox', 'i-text'].includes(o.type)) {
      if (!o.styles || typeof o.styles !== 'object' || Array.isArray(o.styles)) o.styles = {};
      if (typeof o.text !== 'string') o.text = String(o.text || '');
    }
  });
  // Rewrite image sources to the proxy and force crossOrigin.
  // IMPORTANT: cut-out (bgRemoved) AND pixel-edited images (edited, a recoloured
  // logo for instance) carry their finished state directly in src (data:/nc://)
  // - those must NOT be replaced by the original (srcUrl), or the transparency
  // and the recolouring are gone after opening.
  // Repair drafts that still carry the host they were saved on (see
  // alsPfadLesen): without this they keep pointing at a machine that is not
  // this one, and the artboard comes up empty.
  pfadeEinebnen(fabricState, alsPfadLesen);
  fabricState.objects.forEach(o => {
    if (o.type === 'image' && o.src) {
      o.src = (o.bgRemoved || o.edited) ? proxyUrl(o.src) : proxyUrl(o.srcUrl || o.src);
      o.crossOrigin = 'anonymous';
    }
  });
  if (fabricState.backgroundImage?.src) {
    fabricState.backgroundImage.src = proxyUrl(fabricState.backgroundImage.src);
    fabricState.backgroundImage.crossOrigin = 'anonymous';
  }

  return new Promise(resolve => {
    let done = false;
    let timer = null;
    const finish = (vollstaendig) => {
      if (done) return; done = true;
      clearTimeout(timer);
      // A load that has been overtaken: drop the result so the newer one wins.
      if (token !== editor._loadToken) { resolve(false); return; }
      editor._locked = false;
      editor._ladefehler = !vollstaendig;
      // The grid is not part of the saved state - rebuild it, or the grid button
      // says "on" while there is nothing to see.
      editor._grid = [];
      if (editor.gridOn) editor._buildGrid();
      editor.canvas.requestRenderAll();
      if (opts.frisch) {
        // On opening: set the history to the LOADED state. The empty canvas used
        // to sit in there as the oldest step - so an accidental Ctrl+Z wiped the
        // whole file.
        editor.resetHistory();
      } else {
        // In the middle of the work (applying a template, say): append, so the
        // step can be undone.
        editor.snapshot();
      }
      resolve(vollstaendig);
    };
    try {
      editor.canvas.loadFromJSON(fabricState, () => finish(true));
    } catch (e) {
      console.warn('restoreCanvas Fehler:', e);
      status('❌ Draft could not be fully loaded', 'red');
      finish(false);
    }
    // Safety net: should a missing image block the callback, release after 20s
    // anyway. More generous than it used to be (4s), because on a slow
    // connection it unlocked mid-load and wrote half a state down as the undo
    // baseline.
    timer = setTimeout(() => {
      console.warn('restoreCanvas: Zeitüberschreitung beim Laden');
      status('⚠️ Not all images could be loaded', 'red');
      finish(false);
    }, 20000);
  });
}
