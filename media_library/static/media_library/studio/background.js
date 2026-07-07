// background.js – Hintergrundbild, Templates, Farbpalette.
import { loadImage, toast, status } from './util.js';
import { URLS, CONFIG } from './config.js';

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
    picker.onchange = () => { addCustomColor(picker.value); renderPalette(container, onPick); onPick(picker.value); document.body.removeChild(picker); };
    picker.click();
  };
  container.appendChild(add);
}

// ---- Hintergrund setzen ---------------------------------------------------
export async function setBackgroundImage(editor, url) {
  const imgEl = await loadImage(url);
  const fImg = new window.fabric.Image(imgEl, { crossOrigin: 'anonymous' });
  // Auf Canvas-Größe skalieren (cover).
  const scale = Math.max(editor.width / fImg.width, editor.height / fImg.height);
  fImg.set({
    scaleX: scale, scaleY: scale,
    originX: 'center', originY: 'center',
    left: editor.width / 2, top: editor.height / 2,
  });
  editor.canvas.setBackgroundImage(fImg, editor.canvas.renderAll.bind(editor.canvas));
  editor.snapshot();
  updateBgInfo(editor);
}

export function clearBackground(editor) {
  editor.canvas.setBackgroundImage(null, editor.canvas.renderAll.bind(editor.canvas));
  editor.canvas.setBackgroundColor('#1a1a2e', editor.canvas.renderAll.bind(editor.canvas));
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
  try {
    const res = await fetch(URLS.apiTemplates);
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
  status('Template wird geladen…');
  try {
    const tw = tpl.width || tpl.w, th = tpl.height || tpl.h;
    if (tw && th && (tw !== editor.width || th !== editor.height)) {
      editor.setSize(tw, th);
    }
    await setBackgroundImage(editor, tpl.url);
    editor._templateId = tpl.id || null;
    status('✅ Template geladen', 'green');
  } catch (e) {
    status('❌ Template-Fehler', 'red');
    toast('Template konnte nicht geladen werden', 'err');
  }
}
