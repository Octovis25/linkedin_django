// io.js – Speichern & Laden. Erzeugt PNG + canvas_json, spricht das bestehende
// Django-Backend an (studio_save). Reload rekonstruiert exakt den Fabric-State.
import { URLS, POST_ID, CONFIG, getCookie, proxyUrl } from './config.js';
import { toast, status } from './util.js';
import { fabric, EXTRA_PROPS } from './editor.js';
import { beendeVorschauen, vorschauenUebernehmen } from './retouch.js';
import { vorschlagAusInhalt, vergebeneNamen, eindeutig, entschaerfe, frageNachNamen } from './namen.js';

// Stellt sicher, dass ein eindeutiger Name feststeht, BEVOR gespeichert wird.
// Der Name ist die Identität des Entwurfs – Bild, GIF und Video desselben
// Designs teilen ihn sich. Deshalb wird er einmal abgefragt und bleibt dann.
//
// Rückgabe: der Name, oder null wenn der Nutzer abgebrochen hat.
// Merkt sich den Namen für diese Sitzung, auch wenn CONFIG.libData ihn nicht
// führt. Nötig beim Arbeiten an einem Planner-Post: dort liefert der Server
// keine libData, sodass jedes Speichern sonst wie ein Erstspeichern aussah –
// und der Name bei jedem Mal ein _2, _3, _4 … bekam.
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

  // Titelfeld leer, aber es gibt schon einen Namen? Dann diesen behalten,
  // statt den Entwurf unter einem neuen Namen ein zweites Mal anzulegen.
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

  status('⏳ Namen prüfen…');
  const belegt = await vergebeneNamen();

  // Umbenennen einer bestehenden Ausgabe: nur prüfen, nicht neu fragen.
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
      hinweis: `„${sauber}" gehört bereits zu einer anderen Ausgabe. Bitte einen anderen Namen wählen.`,
    });
    if (!gewaehlt) { status('Umbenennen abgebrochen – nichts gespeichert', 'red'); return null; }
    if (feld) feld.value = gewaehlt;
    _festerName = gewaehlt;
    return gewaehlt;
  }

  // Erstes Speichern: nach dem Namen fragen, mit Vorschlag aus dem Inhalt.
  let vorschlag = entschaerfe(eingetippt) || vorschlagAusInhalt(editor)
                  || entschaerfe(CONFIG.postData?.title || '');
  if (!vorschlag) {
    // Kein Text im Entwurf und kein Post-Titel → durchnummerieren.
    let n = 1;
    while (belegt.has(('Entwurf_' + n).toLowerCase())) n++;
    vorschlag = 'Entwurf_' + n;
  }
  vorschlag = eindeutig(vorschlag, belegt, null);

  const gewaehlt = await frageNachNamen({ vorschlag, belegt, eigener: null });
  if (!gewaehlt) { status('Speichern abgebrochen', 'red'); return null; }
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

// Gleiche Liste wie Undo/Redo – früher standen hier zwei Listen, die
// auseinandergelaufen sind (siehe editor.js).
const FABRIC_PROPS = EXTRA_PROPS;

// Läuft gerade ein Speichervorgang? Verhindert, dass ein zweiter Klick auf
// „Speichern" ein zweites Bibliotheks-Element und eine zweite Datei anlegt.
let _saving = false;
export function istAmSpeichern() { return _saving; }

// Prüft, ob der Editor gerade eine Datei lädt. Speichern/Exportieren in diesem
// Moment würde einen halb gefüllten Canvas über das Original schreiben.
function ladeGuard(editor) {
  if (editor._locked) {
    status('⏳ Wird noch geladen – bitte einen Moment warten', 'red');
    toast('Der Entwurf lädt noch', 'err');
    return true;
  }
  return false;
}

// Einheitliche Antwortauswertung: ohne res.ok-Prüfung liefert ein 500er eine
// HTML-Fehlerseite, an der res.json() scheitert – der Nutzer sah dann
// „SyntaxError: Unexpected token '<'" statt einer verständlichen Meldung.
async function leseAntwort(res) {
  if (!res.ok) {
    if (res.status === 413) throw new Error('Datei zu groß für den Server (413)');
    if (res.status === 403) throw new Error('Nicht angemeldet oder Sitzung abgelaufen (403)');
    throw new Error(`Server-Fehler ${res.status}`);
  }
  const txt = await res.text();
  try { return JSON.parse(txt); }
  catch { throw new Error('Unerwartete Server-Antwort'); }
}

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
  // Rote Markierungs-Vorschau zurücknehmen – die gehört nie ins Ergebnis.
  beendeVorschauen(editor.canvas);
  // exportDataURL blendet das Ausricht-Raster für den Export aus.
  return editor.exportDataURL({ multiplier: 1 });
}

// Gibt true zurück, wenn wirklich gespeichert wurde – sonst false. Der Aufrufer
// darf nur dann eine Erfolgsmeldung anzeigen. Vorher schrieb er unbedingt
// „Gespeichert.", auch wenn hier abgebrochen wurde.
export async function saveImage(editor) {
  if (ladeGuard(editor)) return false;
  // Der Entwurf konnte beim Öffnen nicht vollständig geladen werden. Jetzt über
  // dieselbe Datei zu speichern würde das Original endgültig zerstören.
  if (editor._ladefehler && (CONFIG.libData?.item_id || CONFIG.libData?.nc_path)) {
    const weiter = window.confirm(
      'Achtung: Dieser Entwurf wurde beim Öffnen nicht vollständig geladen ' +
      '(fehlende oder beschädigte Bilder).\n\n' +
      'Wenn du jetzt speicherst, wird die vorhandene Datei mit dem unvollständigen ' +
      'Stand überschrieben.\n\nTrotzdem speichern?');
    if (!weiter) { status('Speichern abgebrochen', 'red'); return false; }
  }
  if (_saving) { toast('Speichert bereits…', 'err'); return false; }
  _saving = true;
  try {
    return await _saveImage(editor);
  } finally {
    _saving = false;
  }
}

async function _saveImage(editor) {
  // Offene Pinsel-/Markierungsstände in echte Bilder umwandeln, BEVOR das JSON
  // gebaut wird – ein Canvas als Bild-Element überlebt die Serialisierung nicht.
  await vorschauenUebernehmen(editor.canvas);
  // Eindeutigen Namen festlegen (fragt beim ersten Mal nach, prüft beim
  // Umbenennen). Ohne Namen wird nicht gespeichert.
  const title = await nameSicherstellen(editor);
  if (!title) return false;
  status('💾 Speichert…');

  let dataUrl, preview;
  try {
    dataUrl = exportPng(editor);          // nimmt Markierungs-Vorschauen zurück
    preview = editor.exportDataURL({ multiplier: 0.4 });
  } catch (e) {
    status('❌ Export fehlgeschlagen (Bild getaintet)', 'red');
    toast('Ein Bild ist cross-origin – über den Proxy laden', 'err');
    return false;
  }

  // Nur weiterbearbeiten, wenn wirklich ein BILD geöffnet ist. Hatte man ein GIF
  // offen und speichert als PNG, wurde sonst der GIF-Eintrag zum Bild-Eintrag
  // umgewidmet und die GIF-Datei war über keinen Eintrag mehr erreichbar.
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
    const d = await leseAntwort(res);
    if (d.ok) {
      if (d.warning) {
        // Das Bild liegt, aber der bearbeitbare Entwurf konnte nicht mitgespeichert
        // werden. Das muss der Nutzer wissen, bevor er die Seite schließt.
        status('⚠️ ' + d.warning, 'red');
        toast('Bild gespeichert – Entwurf nicht (Details oben)', 'err');
        window.alert('Achtung:\n\n' + d.warning);
      } else {
        status('✅ Bild gespeichert!', 'green');
        toast('Gespeichert', 'ok');
      }
      // Merken, WAS gerade gespeichert wurde. Ohne das legt jedes weitere
      // Speichern nach einer Titeländerung ein zusätzliches Duplikat an.
      CONFIG.libData = { ...(CONFIG.libData || {}), item_id: d.lib_id ?? CONFIG.libData?.item_id ?? null,
                         title, nc_path: d.nc_path ?? CONFIG.libData?.nc_path ?? null, kind: 'image' };
      window.dispatchEvent(new CustomEvent('studio:output-changed', { detail: { tab: 'Images' } }));
      if (d.lib_id && !POST_ID) history.replaceState(null, '', '/library/studio/?lib_item=' + d.lib_id);
      // Erfolgreich gespeichert → der Editor gilt wieder als „sauber".
      editor._ladefehler = false;
      return true;
    }
    status('❌ ' + (d.error || 'Fehler'), 'red');
    toast(d.error || 'Speichern fehlgeschlagen', 'err');
    return false;
  } catch (e) {
    status('❌ ' + (e.message || e), 'red');
    toast(e.message || 'Speichern fehlgeschlagen', 'err');
    return false;
  }
}

// Speichert ein exportiertes bewegtes Bild (WebM/GIF) in „Meine Ausgaben"
// – inkl. canvas_json, damit es später wieder im Editor geöffnet werden kann.
export async function saveAnimation(editor, blob, ext) {
  await vorschauenUebernehmen(editor.canvas);
  // Denselben Namen wie das Bild verwenden: Bild, GIF und Video eines Entwurfs
  // heißen gleich und gehören dadurch zusammen.
  const title = await nameSicherstellen(editor);
  if (!title) return { ok: false, error: 'abgebrochen' };
  let preview = '';
  try { preview = editor.exportDataURL({ multiplier: 0.4 }); } catch (e) { /* egal */ }
  const safe = title.replace(/[^a-zA-Z0-9_.-]/g, '_') + ext;
  const fd = new FormData();
  fd.append('video', blob, safe);
  fd.append('title', title);
  fd.append('canvas_json', buildCanvasJson(editor, preview));
  const folder = document.getElementById('save-folder')?.value;
  if (folder) fd.append('folder_id', folder);
  // lib_item_id NUR mitschicken, wenn die geöffnete Ausgabe dasselbe Format hat.
  // Sonst wurde der Bild-Eintrag zum GIF-Eintrag umgewidmet: die PNG-Datei blieb
  // liegen, war aber über keinen Eintrag mehr erreichbar und öffnete danach ohne
  // Ebenen. Jetzt bekommt jedes Format seinen Eintrag – zusammengehalten über
  // den gemeinsamen (eindeutigen) Namen.
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
    const d = await leseAntwort(res);
    if (d.ok) {
      status('✅ Gespeichert als „' + title + '"', 'green');
      toast('In „Meine Ausgaben" gespeichert', 'ok');
      CONFIG.libData = { ...(CONFIG.libData || {}), item_id: d.lib_id ?? null, title,
                         nc_path: d.nc_path ?? null, kind: ext === '.gif' ? 'gif' : 'video' };
      window.dispatchEvent(new CustomEvent('studio:output-changed',
        { detail: { tab: ext === '.gif' ? 'GIFs' : 'Videos' } }));
    } else {
      toast(d.error || 'Speichern in Ausgaben fehlgeschlagen', 'err');
    }
    return d;
  } catch (e) {
    status('❌ ' + (e.message || e), 'red');
    toast(e.message || 'Fehler beim Speichern in Ausgaben', 'err');
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
    toast('Ein Bild ist cross-origin – über den Proxy laden', 'err');
  }
}

// ---- Laden ---------------------------------------------------------------
// Stellt einen gespeicherten Canvas wieder her. Bild-URLs werden über den
// Proxy geladen (crossOrigin), damit späteres Freistellen/Export klappt.
// opts.frisch = true: die Historie wird auf den geladenen Zustand zurückgesetzt.
// Das ist NUR beim Öffnen der Seite richtig. Beim Anwenden einer Vorlage mitten
// in der Arbeit muss die Historie erhalten bleiben, sonst wäre alles Vorherige
// per Strg+Z nicht mehr erreichbar.
export function restoreCanvas(editor, canvasJsonStr, opts = {}) {
  // Ab sofort ein Promise: Aufrufer können auf das FERTIGE Laden warten. Vorher
  // lief z.B. „Vorlage speichern" direkt nach dem Öffnen auf einem noch leeren
  // Canvas – und überschrieb damit die Vorlage mit einem leeren Bild.
  let state;
  try {
    state = JSON.parse(canvasJsonStr);
  } catch (e) {
    console.warn('canvas_json parse', e);
    // Nicht stillschweigend weitermachen: sonst hält der Nutzer den leeren
    // Editor für seine Datei, baut neu und überschreibt das reparable Original.
    editor._ladefehler = true;
    status('❌ Gespeicherte Daten unlesbar – bitte nicht überschreiben', 'red');
    toast('Entwurf konnte nicht gelesen werden', 'err');
    return Promise.resolve(false);
  }

  // Ein neuer Ladevorgang macht einen noch laufenden ungültig (Doppelklick auf
  // zwei Vorlagen mischte sonst beide Layouts auf der Fläche).
  const token = ++editor._loadToken;

  editor._locked = true;   // VOR setSize: dessen snapshot() schrieb sonst den
                           // leeren Canvas als ältesten Undo-Schritt.
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
  // WICHTIG: Freigestellte (bgRemoved) UND pixelbearbeitete (edited, z.B. Logo
  // umgefärbt) Bilder tragen ihren fertigen Stand direkt in src (data:/nc://) –
  // die dürfen NICHT durch das Original (srcUrl) ersetzt werden, sonst sind
  // Transparenz bzw. Umfärbung nach dem Öffnen weg.
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
      // Überholter Ladevorgang: Ergebnis verwerfen, damit der neuere gewinnt.
      if (token !== editor._loadToken) { resolve(false); return; }
      editor._locked = false;
      editor._ladefehler = !vollstaendig;
      // Raster ist nicht Teil des gespeicherten Zustands – neu aufbauen,
      // sonst zeigt der Raster-Knopf „an", während nichts zu sehen ist.
      editor._grid = [];
      if (editor.gridOn) editor._buildGrid();
      editor.canvas.requestRenderAll();
      if (opts.frisch) {
        // Beim Öffnen: Historie auf den GELADENEN Zustand setzen. Vorher stand
        // der leere Canvas als ältester Schritt darin – ein versehentliches
        // Strg+Z löschte damit die ganze Datei.
        editor.resetHistory();
      } else {
        // Mitten in der Arbeit (z.B. Vorlage anwenden): anhängen, damit man den
        // Schritt rückgängig machen kann.
        editor.snapshot();
      }
      resolve(vollstaendig);
    };
    try {
      editor.canvas.loadFromJSON(fabricState, () => finish(true));
    } catch (e) {
      console.warn('restoreCanvas Fehler:', e);
      status('❌ Entwurf konnte nicht vollständig geladen werden', 'red');
      finish(false);
    }
    // Sicherheitsnetz: falls ein fehlendes Bild den Callback blockiert, nach
    // 20s trotzdem freigeben. Großzügiger als früher (4s), weil bei langsamer
    // Verbindung sonst mitten im Laden entsperrt und ein halber Zustand als
    // Undo-Basis festgeschrieben wurde.
    timer = setTimeout(() => {
      console.warn('restoreCanvas: Zeitüberschreitung beim Laden');
      status('⚠️ Nicht alle Bilder konnten geladen werden', 'red');
      finish(false);
    }, 20000);
  });
}
