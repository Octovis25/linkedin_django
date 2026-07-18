// io.js – Speichern & Laden. Erzeugt PNG + canvas_json, spricht das bestehende
// Django-Backend an (studio_save). Reload rekonstruiert exakt den Fabric-State.
import { URLS, POST_ID, CONFIG, getCookie, proxyUrl } from './config.js';
import { toast, status } from './util.js';
import { fabric } from './editor.js';

// Fabric-Objekttypen, die sich sicher wiederherstellen lassen.
function _klassOk(type) {
  if (!type || typeof type !== 'string') return false;
  const name = type.split('-').map(s => s.charAt(0).toUpperCase() + s.slice(1)).join('');
  return !!(fabric && fabric[name] && typeof fabric[name].fromObject === 'function');
}

const FABRIC_PROPS = ['srcUrl', 'originalUrl', 'bgRemoved', 'anim', 'shapeKind', 'fx', 'svgPart',
                      'tbHead', 'tbBody', 'tbWidth', 'tbSize', 'tbAlign'];

// Baut das canvas_json. Enthält:
//   fabric        – vollständiger Fabric-State für exakten Reload
//   objects[]     – flache Liste mit imgSrc, damit das Backend Bilder nach NC
//                   auslagern kann (_optimize_canvas_json erwartet dieses Feld)
//   previewDataUrl– Vorschau (bleibt im Hauptordner)
export function buildCanvasJson(editor, previewDataUrl) {
  const fabricState = editor.canvas.toJSON(FABRIC_PROPS);
  // _snap-Hilfslinien nicht mitspeichern
  fabricState.objects = (fabricState.objects || []).filter(o => !o._snap);

  const objects = editor.canvas.getObjects()
    .filter(o => o.type === 'image' && !o._snap)
    .map(o => ({ imgSrc: o.srcUrl || o.getSrc?.() || '', originalUrl: o.originalUrl || '' }));

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
  // exportDataURL blendet das Ausricht-Raster für den Export aus.
  return editor.exportDataURL({ multiplier: 1 });
}

export async function saveImage(editor) {
  const titleEl = document.getElementById('title-input');
  const title = titleEl.value.trim();
  if (!title) {
    titleEl.style.border = '2px solid #dc3545';
    titleEl.focus();
    status('⚠️ Bitte zuerst einen Titel eingeben!', '#dc3545');
    setTimeout(() => { titleEl.style.border = ''; }, 2500);
    return;
  }
  titleEl.style.border = '';
  status('💾 Speichert…');

  let dataUrl, preview;
  try {
    dataUrl = exportPng(editor);
    preview = editor.exportDataURL({ multiplier: 0.4 });
  } catch (e) {
    status('❌ Export fehlgeschlagen (Bild getaintet)', 'red');
    toast('Ein Bild ist cross-origin – über den Proxy laden', 'err');
    return;
  }

  const body = {
    dataUrl, title,
    post_id: POST_ID || '',
    lib_item_id: CONFIG.libData?.item_id || null,   // beim Weiterbearbeiten → gleiches Bild aktualisieren
    openNcPath: CONFIG.libData?.nc_path || null,    // geöffnete Datei → genau diese überschreiben
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
    const d = await res.json();
    if (d.ok) {
      status('✅ Bild gespeichert!', 'green');
      toast('Gespeichert', 'ok');
      window.dispatchEvent(new CustomEvent('studio:output-changed', { detail: { tab: 'Images' } }));
      if (d.lib_id && !POST_ID) history.replaceState(null, '', '/library/studio/?lib_item=' + d.lib_id);
    } else {
      status('❌ ' + (d.error || 'Fehler'), 'red');
    }
  } catch (e) {
    status('❌ ' + e, 'red');
  }
}

// Speichert ein exportiertes bewegtes Bild (WebM/GIF) in „Meine Ausgaben"
// – inkl. canvas_json, damit es später wieder im Editor geöffnet werden kann.
export async function saveAnimation(editor, blob, ext) {
  const titleEl = document.getElementById('title-input');
  const title = titleEl?.value.trim();
  if (!title) {
    if (titleEl) { titleEl.style.border = '2px solid #dc3545'; titleEl.focus(); }
    status('⚠️ Bitte zuerst einen Titel eingeben!', '#dc3545');
    setTimeout(() => { if (titleEl) titleEl.style.border = ''; }, 2500);
    return;
  }
  let preview = '';
  try { preview = editor.exportDataURL({ multiplier: 0.4 }); } catch (e) { /* egal */ }
  const safe = title.replace(/[^a-zA-Z0-9_.-]/g, '_') + ext;
  const fd = new FormData();
  fd.append('video', blob, safe);
  fd.append('title', title);
  fd.append('canvas_json', buildCanvasJson(editor, preview));
  const folder = document.getElementById('save-folder')?.value;
  if (folder) fd.append('folder_id', folder);
  if (CONFIG.libData?.item_id) fd.append('lib_item_id', CONFIG.libData.item_id);   // vorhandene Ausgabe überschreiben
  try {
    const res = await fetch(URLS.saveVideoFile, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
      body: fd,
    });
    const d = await res.json();
    if (d.ok) {
      toast('In „Meine Ausgaben" gespeichert', 'ok');
      window.dispatchEvent(new CustomEvent('studio:output-changed',
        { detail: { tab: ext === '.gif' ? 'GIFs' : 'Videos' } }));
    } else {
      toast('Speichern in Ausgaben fehlgeschlagen', 'err');
    }
    return d;
  } catch (e) {
    toast('Fehler beim Speichern in Ausgaben', 'err');
  }
}

export function downloadImage(editor) {
  const a = document.createElement('a');
  a.href = exportPng(editor);
  a.download = (document.getElementById('title-input')?.value.trim() || 'studio') + '.png';
  a.click();
}

// ---- Laden ---------------------------------------------------------------
// Stellt einen gespeicherten Canvas wieder her. Bild-URLs werden über den
// Proxy geladen (crossOrigin), damit späteres Freistellen/Export klappt.
export function restoreCanvas(editor, canvasJsonStr) {
  let state;
  try { state = JSON.parse(canvasJsonStr); } catch (e) { console.warn('canvas_json parse', e); return; }

  if (state.width && state.height) editor.setSize(state.width, state.height);

  const fabricState = state.fabric || state;   // v2 hat .fabric, sonst direkt
  // Nur wiederherstellbare Objekte behalten – ein einziges unbekanntes Objekt
  // ließ sonst das ganze loadFromJSON abstürzen (fromObject undefined).
  const before = (fabricState.objects || []).length;
  fabricState.objects = (fabricState.objects || []).filter(o => o && _klassOk(o.type));
  if (fabricState.objects.length < before) {
    console.warn(`restoreCanvas: ${before - fabricState.objects.length} unlesbare(s) Objekt(e) übersprungen`);
  }
  // Beschädigte Text-Styles neutralisieren – sonst stürzt Fabric beim
  // Serialisieren (stylesToArray) ab. Basisformatierung bleibt erhalten.
  fabricState.objects.forEach(o => {
    if (['text', 'textbox', 'i-text'].includes(o.type)) {
      if (!o.styles || typeof o.styles !== 'object' || Array.isArray(o.styles)) o.styles = {};
      if (typeof o.text !== 'string') o.text = String(o.text || '');
    }
  });
  // Bildquellen auf Proxy umschreiben + crossOrigin erzwingen.
  // WICHTIG: Freigestellte/bearbeitete Bilder tragen ihren transparenten Stand
  // direkt in src (data:/nc://) – die dürfen NICHT durch das Original (srcUrl)
  // ersetzt werden, sonst ist die Transparenz nach dem Öffnen weg.
  fabricState.objects.forEach(o => {
    if (o.type === 'image' && o.src) {
      o.src = o.bgRemoved ? proxyUrl(o.src) : proxyUrl(o.srcUrl || o.src);
      o.crossOrigin = 'anonymous';
    }
  });
  if (fabricState.backgroundImage?.src) {
    fabricState.backgroundImage.src = proxyUrl(fabricState.backgroundImage.src);
    fabricState.backgroundImage.crossOrigin = 'anonymous';
  }

  editor._locked = true;
  let done = false;
  const finish = () => {
    if (done) return; done = true;
    editor._locked = false;
    editor.canvas.requestRenderAll();
    editor.snapshot();
  };
  try {
    editor.canvas.loadFromJSON(fabricState, finish);
  } catch (e) {
    console.warn('restoreCanvas Fehler:', e);
    finish();
  }
  // Sicherheitsnetz: falls ein fehlendes Bild den Callback blockiert,
  // nach 4s trotzdem freigeben, damit der Editor nie „hängt".
  setTimeout(finish, 4000);
}
