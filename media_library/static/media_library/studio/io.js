// io.js – Speichern & Laden. Erzeugt PNG + canvas_json, spricht das bestehende
// Django-Backend an (studio_save). Reload rekonstruiert exakt den Fabric-State.
import { URLS, POST_ID, CONFIG, getCookie, proxyUrl } from './config.js';
import { toast, status } from './util.js';

const FABRIC_PROPS = ['srcUrl', 'originalUrl', 'bgRemoved', 'anim', 'shapeKind'];

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
  editor.canvas.discardActiveObject();
  editor.canvas.requestRenderAll();
  return editor.canvas.toDataURL({ format: 'png', multiplier: 1 });
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
    preview = editor.canvas.toDataURL({ format: 'png', multiplier: 0.4 });
  } catch (e) {
    status('❌ Export fehlgeschlagen (Bild getaintet)', 'red');
    toast('Ein Bild ist cross-origin – über den Proxy laden', 'err');
    return;
  }

  const body = {
    dataUrl, title,
    post_id: POST_ID || '',
    lib_item_id: CONFIG.libData?.item_id || null,   // beim Weiterbearbeiten → gleiches Bild aktualisieren
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
      if (d.lib_id && !POST_ID) history.replaceState(null, '', '/library/studio/?lib_item=' + d.lib_id);
    } else {
      status('❌ ' + (d.error || 'Fehler'), 'red');
    }
  } catch (e) {
    status('❌ ' + e, 'red');
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
  // Bildquellen auf Proxy umschreiben + crossOrigin erzwingen
  (fabricState.objects || []).forEach(o => {
    if (o.type === 'image' && o.src) { o.src = proxyUrl(o.srcUrl || o.src); o.crossOrigin = 'anonymous'; }
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
