// background.js – Hintergrundbild, Templates, Farbpalette.
import { loadImage, toast, status } from './util.js';
import { URLS, CONFIG } from './config.js';
import { restoreCanvas } from './io.js';

const PALETTE_KEY = 'studio_palette_v2';

// ---- Farbpalette (Brand-Farben aus CSS + eigene) --------------------------
function readBrandColors() {
  const s = getComputedStyle(document.documentElement);
  const get = (v, f) => (s.getPropertyValue(v).trim() || f);
  return [
    get('--brand-c1', '#ffffff'), get('--brand-c2', '#F56E28'),
    get('--brand-c3', '#008591'), get('--brand-c4', '#61CEBC'),
    get('--brand-c5', '#004f57'), get('--brand-c6', '#1a1a2e'),
  ];
}

export function getPalette() {
  const brand = readBrandColors();
  const extra = CONFIG.brandExtraColors || [];
  let custom = [];
  try { custom = JSON.parse(localStorage.getItem(PALETTE_KEY) || '[]'); } catch (e) {}
  return [...new Set([...brand, ...extra, ...custom])];
}

export function addCustomColor(hex) {
  let custom = [];
  try { custom = JSON.parse(localStorage.getItem(PALETTE_KEY) || '[]'); } catch (e) {}
  if (!custom.includes(hex)) { custom.push(hex); localStorage.setItem(PALETTE_KEY, JSON.stringify(custom)); }
}

// Rendert Swatches in ein Ziel-Element. onPick(hex) callback.
export function renderPalette(container, onPick) {
  if (!container) return;
  container.innerHTML = '';
  getPalette().forEach(col => {
    const sw = document.createElement('div');
    sw.className = 'swatch';
    sw.style.background = col;
    sw.title = col;
    sw.onclick = () => onPick(col);
    container.appendChild(sw);
  });
  const add = document.createElement('div');
  add.className = 'swatch add';
  add.textContent = '+';
  add.title = 'Farbe hinzufügen';
  add.onclick = () => {
    const picker = document.createElement('input');
    picker.type = 'color';
    picker.style.position = 'fixed'; picker.style.opacity = '0';
    document.body.appendChild(picker);
    // Aufräumen auch beim Abbrechen: 'change' feuert dann nicht, und der
    // unsichtbare Input blieb samt Closure für immer im Dokument hängen.
    const weg = () => { if (picker.parentNode) picker.parentNode.removeChild(picker); };
    picker.onchange = () => { addCustomColor(picker.value); renderPalette(container, onPick); onPick(picker.value); weg(); };
    setTimeout(weg, 120000);
    picker.click();
  };
  container.appendChild(add);

  // Hellere Teal-Töne speziell für Video/GIF (gleichen die Verdunklung beim
  // Export aus). Als eigene, markierte Gruppe „🎬 Video".
  const vlabel = document.createElement('span');
  vlabel.textContent = '🎬 Video-Teal:';
  vlabel.title = 'Hellere Teal-Töne für Video/GIF – gleichen die Verdunklung beim Export aus.';
  vlabel.style.cssText = 'flex-basis:100%;font-size:.66rem;color:#008591;margin:6px 0 2px';
  container.appendChild(vlabel);
  ['#0A97A3', '#12A7B4', '#1FB2C0'].forEach(col => {
    const sw = document.createElement('div');
    sw.className = 'swatch';
    sw.style.background = col;
    sw.style.outline = '2px dotted #12A7B4';
    sw.style.outlineOffset = '1px';
    sw.title = 'Video-Teal ' + col + ' – heller, für Video/GIF (gleicht die Verdunklung aus)';
    sw.onclick = () => onPick(col);
    container.appendChild(sw);
  });
}

// ---- Hintergrund setzen ---------------------------------------------------
// mode: 'cover'  = füllt den Canvas (schneidet ggf. über) – für beliebige Hintergründe
//       'stretch'= legt das Bild exakt auf die Canvas-Maße (1:1) – für Templates,
//                  damit Logo/Layout unbeschnitten und in richtiger Größe sitzen.
export async function setBackgroundImage(editor, url, mode = 'cover') {
  const imgEl = await loadImage(url);
  const fImg = new window.fabric.Image(imgEl, { crossOrigin: 'anonymous' });
  if (mode === 'stretch') {
    fImg.set({
      scaleX: editor.width / fImg.width,
      scaleY: editor.height / fImg.height,
      originX: 'left', originY: 'top', left: 0, top: 0,
    });
  } else {
    const scale = Math.max(editor.width / fImg.width, editor.height / fImg.height);
    fImg.set({
      scaleX: scale, scaleY: scale,
      originX: 'center', originY: 'center',
      left: editor.width / 2, top: editor.height / 2,
    });
  }
  editor.canvas.setBackgroundImage(fImg, editor.canvas.renderAll.bind(editor.canvas));
  editor.snapshot();
  updateBgInfo(editor);
}

// Ganze Fläche mit einer Farbe füllen. Ein (reines) Hintergrundbild wird
// entfernt, damit die Farbe sichtbar wird. Logo/Text/Formen liegen darüber
// und bleiben erhalten.
export function setBackgroundColor(editor, hex) {
  editor.canvas.setBackgroundImage(null, editor.canvas.renderAll.bind(editor.canvas));
  editor.canvas.setBackgroundColor(hex, editor.canvas.renderAll.bind(editor.canvas));
  editor.snapshot();
}

export function clearBackground(editor) {
  editor.canvas.setBackgroundImage(null, editor.canvas.renderAll.bind(editor.canvas));
  // '' = transparent (Schachbrett). Vorher wurde hier dunkelblau gesetzt – die
  // Fläche sah nach „🚫 BG weg" kaputt aus und das Blau landete im Export.
  editor.canvas.setBackgroundColor('', editor.canvas.renderAll.bind(editor.canvas));
  editor.snapshot();
  updateBgInfo(editor);
}

export function updateBgInfo(editor) {
  const el = document.getElementById('bg-info');
  if (!el) return;
  const parts = [];
  if (editor.canvas.backgroundImage) parts.push('BG: Bild');
  parts.push(`${editor.width}×${editor.height}`);
  parts.push(`${editor.canvas.getObjects().filter(o => !o._snap).length} Elemente`);
  el.textContent = parts.join(' · ');
}

// ---- Templates ------------------------------------------------------------
export async function loadTemplateList(editor) {
  const listEl = document.getElementById('tpl-list');
  if (!listEl) return;   // fehlte der Guard, warf auch der catch-Zweig erneut
  try {
    const res = await fetch(URLS.apiTemplates);
    if (!res.ok) throw new Error('Server-Fehler ' + res.status);
    const data = await res.json();
    listEl.innerHTML = '';
    (data.templates || []).forEach(t => {
      const img = document.createElement('img');
      img.className = 'tpl-thumb';
      img.src = t.thumb || t.url;
      img.title = t.title || '';
      img.onclick = () => applyTemplate(editor, t);
      listEl.appendChild(img);
    });
    if (!(data.templates || []).length) listEl.innerHTML = '<span class="no-templates">Keine Templates.</span>';
  } catch (e) {
    listEl.innerHTML = '<span class="no-templates">Fehler beim Laden.</span>';
  }
}

export async function applyTemplate(editor, tpl) {
  // Ungespeicherte Arbeit nicht kommentarlos wegwerfen.
  if (typeof window.studioDarfVerlassen === 'function' && !window.studioDarfVerlassen()) return;
  if (editor._locked) { status('⏳ Es lädt noch etwas – kurz warten', 'red'); return; }
  status('⏳ Vorlage wird geladen…');
  // Neue Vorlagen tragen ein Layout (Hintergrund + Logo + Textfelder). Dann das
  // ganze Layout laden, damit man nur noch die Texte ersetzen muss.
  if (tpl.has_canvas) {
    try {
      const res = await fetch(`/library/studio/template/canvas/${tpl.id}/`, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('Server-Fehler ' + res.status);
      const d = await res.json();
      if (d.ok && d.canvas_json) {
        // await: ohne das lief der Rest hier auf einem noch LEEREN Canvas –
        // die Erfolgsmeldung und die Elementzahl waren schlicht falsch, und der
        // snapshot() verpuffte, weil der Editor noch gesperrt war.
        const vollstaendig = await restoreCanvas(editor, d.canvas_json);
        editor._templateId = tpl.id || null;
        updateBgInfo(editor);
        status(vollstaendig ? '✅ Vorlage geladen – Texte anpassen'
                            : '⚠️ Vorlage nur teilweise geladen', vollstaendig ? 'green' : 'red');
        return;
      }
    } catch (e) { console.warn('Template-Layout-Fehler, nutze Hintergrundbild:', e); }
  }
  try {
    // Canvas-Größe wird NICHT geändert – die bleibt fix und wird nur über
    // "📐 Größe" explizit umgestellt. Das Template füllt die aktuelle Größe.
    const imgEl = await loadImage(tpl.url);
    const fImg = new window.fabric.Image(imgEl, { crossOrigin: 'anonymous' });
    fImg.set({ scaleX: editor.width / fImg.width, scaleY: editor.height / fImg.height,
               originX: 'left', originY: 'top', left: 0, top: 0 });
    editor.canvas.setBackgroundImage(fImg, editor.canvas.renderAll.bind(editor.canvas));
    editor._templateId = tpl.id || null;
    editor.snapshot();
    updateBgInfo(editor);
    status('✅ Template geladen', 'green');
  } catch (e) {
    console.error('Template-Fehler:', e);
    status('❌ Template-Fehler', 'red');
    toast('Template konnte nicht geladen werden', 'err');
  }
}
