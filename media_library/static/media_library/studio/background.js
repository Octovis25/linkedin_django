// background.js – Hintergrundbild, Templates, Farbpalette.
import { loadImage, toast, status, modal } from './util.js';
import { URLS, CONFIG, proxyUrl } from './config.js';
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
  // Writing can throw on a full quota or with site data blocked. The colour is
  // then simply not remembered for next time — no reason to take the page down.
  if (!custom.includes(hex)) {
    custom.push(hex);
    try { localStorage.setItem(PALETTE_KEY, JSON.stringify(custom)); } catch (e) {}
  }
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
  add.title = 'Add colour';
  add.onclick = () => {
    const picker = document.createElement('input');
    picker.type = 'color';
    picker.style.position = 'fixed'; picker.style.opacity = '0';
    document.body.appendChild(picker);
    // Clean up on cancel too: 'change' does not fire then, and the invisible
    // input stayed in the document forever, closure and all.
    const weg = () => { if (picker.parentNode) picker.parentNode.removeChild(picker); };
    picker.onchange = () => { addCustomColor(picker.value); renderPalette(container, onPick); onPick(picker.value); weg(); };
    setTimeout(weg, 120000);
    picker.click();
  };
  container.appendChild(add);

  // Lighter teal shades made for video and GIF - they make up for the
  // darkening on export. Kept as their own labelled group "🎬 Video".
  const vlabel = document.createElement('span');
  vlabel.textContent = '🎬 Video-Teal:';
  vlabel.title = 'Lighter teal tones for video/GIF – compensate for the darkening on export.';
  vlabel.style.cssText = 'flex-basis:100%;font-size:.66rem;color:#008591;margin:6px 0 2px';
  container.appendChild(vlabel);
  ['#0A97A3', '#12A7B4', '#1FB2C0'].forEach(col => {
    const sw = document.createElement('div');
    sw.className = 'swatch';
    sw.style.background = col;
    sw.style.outline = '2px dotted #12A7B4';
    sw.style.outlineOffset = '1px';
    sw.title = 'Video teal ' + col + ' – lighter, for video/GIF (compensates for the darkening)';
    sw.onclick = () => onPick(col);
    container.appendChild(sw);
  });
}

// ---- Setting the background ----------------------------------------------
// mode: 'cover'   = fills the canvas (may crop) - for any background
//       'stretch' = lays the image exactly on the canvas size (1:1) - for
//                   templates, so logo and layout sit uncropped and true to size.
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

// Fill the whole area with one colour. A plain background image is removed so
// the colour becomes visible. Logo, text and shapes sit on top and are kept.
// und bleiben erhalten.
export function setBackgroundColor(editor, hex) {
  editor.canvas.setBackgroundImage(null, editor.canvas.renderAll.bind(editor.canvas));
  editor.canvas.setBackgroundColor(hex, editor.canvas.renderAll.bind(editor.canvas));
  editor.snapshot();
}

export function clearBackground(editor) {
  editor.canvas.setBackgroundImage(null, editor.canvas.renderAll.bind(editor.canvas));
  // '' = transparent (chequerboard). This used to set dark blue - the area
  // looked broken after "🚫 BG off", and the blue ended up in the export.
  editor.canvas.setBackgroundColor('', editor.canvas.renderAll.bind(editor.canvas));
  editor.snapshot();
  updateBgInfo(editor);
}

export function updateBgInfo(editor) {
  const el = document.getElementById('bg-info');
  if (!el) return;
  const parts = [];
  if (editor.canvas.backgroundImage) parts.push('BG: image');
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
    if (!(data.templates || []).length) listEl.innerHTML = '<span class="no-templates">No templates.</span>';
  } catch (e) {
    listEl.innerHTML = '<span class="no-templates">Fehler beim Laden.</span>';
  }
}

// Applies only the template's background to the current canvas and leaves
// every element in place. This is what makes the order of work free: cut an
// image out first, decide on the template afterwards.
async function nurHintergrundAnwenden(editor, canvasJsonStr) {
  const state = JSON.parse(canvasJsonStr);
  const fab = state.fabric || state;
  editor.canvas.backgroundColor = fab.backgroundColor || '';
  const bgi = fab.backgroundImage;
  if (bgi && bgi.src) {
    const imgEl = await loadImage(proxyUrl(bgi.src));
    const fImg = new window.fabric.Image(imgEl, { crossOrigin: 'anonymous' });
    // Canvas size is deliberately NOT changed — the background fills the
    // current size, exactly like the plain-image template path below.
    fImg.set({ scaleX: editor.width / fImg.width, scaleY: editor.height / fImg.height,
               originX: 'left', originY: 'top', left: 0, top: 0 });
    editor.canvas.setBackgroundImage(fImg, editor.canvas.renderAll.bind(editor.canvas));
  } else {
    editor.canvas.setBackgroundImage(null, editor.canvas.renderAll.bind(editor.canvas));
  }
  editor.canvas.requestRenderAll();
  editor.snapshot();
}

export async function applyTemplate(editor, tpl) {
  // Ungespeicherte Arbeit nicht kommentarlos wegwerfen.
  if (typeof window.studioDarfVerlassen === 'function' && !window.studioDarfVerlassen()) return;
  if (editor._locked) { status('⏳ Something is still loading – please wait', 'red'); return; }

  // A template with a layout replaces the WHOLE canvas. That forced the order
  // of work: template first, everything else after — anyone who cut out an
  // image first and then picked a template lost the work. Now it asks.
  let nurHintergrund = false;
  const vorhanden = editor.realObjects().length;
  if (tpl.has_canvas && vorhanden) {
    const wahl = await modal('Load template',
      `There ${vorhanden === 1 ? 'is 1 element' : 'are ' + vorhanden + ' elements'} on the canvas.`,
      [ { label: '🖼 Keep my elements – take the background only', value: 'bg' },
        { label: '♻️ Replace everything with the template',        value: 'all' },
        { label: 'Cancel',                                          value: null } ]);
    if (!wahl) return;
    nurHintergrund = (wahl === 'bg');
  }
  status('⏳ Loading template…');
  // Newer templates carry a layout (background + logo + text fields). Load the
  // whole layout then, so only the text is left to replace.
  if (tpl.has_canvas) {
    try {
      const res = await fetch(`/library/studio/template/canvas/${tpl.id}/`, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('Server-Fehler ' + res.status);
      const d = await res.json();
      if (d.ok && d.canvas_json && nurHintergrund) {
        await nurHintergrundAnwenden(editor, d.canvas_json);
        // _templateId is deliberately NOT bound here: the canvas is now your
        // composition, not that template. "Save template" therefore offers to
        // create a new one instead of silently overwriting the original.
        updateBgInfo(editor);
        status('✅ Background taken from the template – your elements stayed', 'green');
        return;
      }
      if (d.ok && d.canvas_json) {
        // await: without it the rest of this ran on a still EMPTY canvas - the
        // success message and the element count were simply wrong, and the
        // snapshot() came to nothing because the editor was still locked.
        const vollstaendig = await restoreCanvas(editor, d.canvas_json);
        editor._templateId = tpl.id || null;
        updateBgInfo(editor);
        status(vollstaendig ? '✅ Template loaded – adjust the text'
                            : '⚠️ Template only partially loaded', vollstaendig ? 'green' : 'red');
        return;
      }
    } catch (e) { console.warn('Template-Layout-Fehler, nutze Hintergrundbild:', e); }
  }
  try {
    // The canvas size is NOT changed - it stays fixed and is only altered
    // through "📐 Size". The template fills whatever size is set.
    const imgEl = await loadImage(tpl.url);
    const fImg = new window.fabric.Image(imgEl, { crossOrigin: 'anonymous' });
    fImg.set({ scaleX: editor.width / fImg.width, scaleY: editor.height / fImg.height,
               originX: 'left', originY: 'top', left: 0, top: 0 });
    editor.canvas.setBackgroundImage(fImg, editor.canvas.renderAll.bind(editor.canvas));
    editor._templateId = tpl.id || null;
    editor.snapshot();
    updateBgInfo(editor);
    status('✅ Template loaded', 'green');
  } catch (e) {
    console.error('Template-Fehler:', e);
    status('❌ Template-Fehler', 'red');
    toast('Template could not be loaded', 'err');
  }
}
