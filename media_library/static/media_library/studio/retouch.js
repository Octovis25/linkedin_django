// retouch.js - manual brush corrections on cut-out images:
//   erase   = make transparent with the brush
//   restore = bring original pixels back with the brush
// Works on an offscreen working copy at image resolution.
import { loadImage, toast } from './util.js';
import { proxyUrl } from './config.js';

// Returns (and sets up if needed) the working canvas of a fabric image.
export function getWork(obj) {
  if (obj._work) return obj._work;
  const el = obj._element;
  const W = el.naturalWidth || el.width;
  const H = el.naturalHeight || el.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(el, 0, 0, W, H);
  obj._work = { canvas: c, ctx, W, H };
  return obj._work;
}

// Loads the original image (for restore) - cached on the object.
// The PROMISE is cached, not just the result: otherwise every mouse-move tick
// started another download of the same file (40 and more in parallel).
export function getOriginal(obj) {
  if (obj._origImg) return Promise.resolve(obj._origImg);
  if (obj._origPromise) return obj._origPromise;
  const url = obj.originalUrl || obj.srcUrl;
  if (!url) return Promise.reject(new Error('No original image stored'));
  obj._origPromise = loadImage(proxyUrl(url))
    .then(img => { obj._origImg = img; return img; })
    .catch(e => { obj._origPromise = null; throw e; });   // erneuter Versuch möglich
  return obj._origPromise;
}

// Shows the working canvas directly in the fabric image, without PNG encoding.
// For the live view while painting. The expensive commitWork() only runs when
// the mouse button is released.
export function showWork(obj) {
  if (!obj._work) return;
  obj.setElement(obj._work.canvas);
  obj.objectCaching = false;
  obj.dirty = true;
  obj.edited = true;
  if (obj.canvas) obj.canvas.requestRenderAll();
}

// Brush action at image coordinate (px,py).
// mode: 'erase' (transparent) | 'restore' (original back) | 'paint' (paint colour)
// origImg is needed for 'restore', color (#rrggbb) for 'paint'.
export function brushAt(obj, px, py, radius, mode, origImg, color) {
  const { ctx, W, H } = getWork(obj);
  ctx.save();
  ctx.beginPath();
  ctx.arc(px, py, radius, 0, Math.PI * 2);
  ctx.closePath();
  if (mode === 'erase') {
    ctx.clip();
    ctx.clearRect(px - radius, py - radius, radius * 2, radius * 2);
  } else if (mode === 'restore' && origImg) {
    ctx.clip();
    ctx.drawImage(origImg, 0, 0, W, H);
  } else if (mode === 'paint') {
    // Paint only where there is already coverage (transparent stays transparent),
    // so the cut-out edge is not filled back in.
    ctx.clip();
    ctx.globalCompositeOperation = 'source-atop';
    ctx.fillStyle = color || '#ffffff';
    ctx.fillRect(px - radius, py - radius, radius * 2, radius * 2);
  }
  ctx.restore();
}

// Swaps a fabric object's image cleanly: setElement plus invalidating the cache
// (dirty), otherwise Fabric mixes the old and new image - they "blend".
export function replaceElement(obj, imgEl) {
  obj._maskPreview = false;
  obj.setElement(imgEl);
  obj.objectCaching = false;   // kein Cache → kein Verschwimmen von Alt/Neu
  obj.dirty = true;
  // Pixels have been changed (recolour, brush, eraser). The finished state now
  // sits in src - do NOT replace it with the original when saving or loading.
  obj.edited = true;
  if (obj.canvas) obj.canvas.requestRenderAll();
}

// Transfers the working canvas back into the fabric image (a real image, so the
// state can be exported and saved).
// Generation counter: when two calls come back interleaved, the older must not
// overwrite the newer - otherwise brush strokes "jump" back.
export function commitWork(obj) {
  if (!obj._work) return Promise.resolve();
  const gen = (obj._commitGen = (obj._commitGen || 0) + 1);
  // Failing here must not reach the global handler as a red banner: a tainted
  // canvas or an oversized image makes toDataURL throw or return "data:,", and
  // loadImage then rejects. The edit is lost either way — the user gets a toast
  // and keeps working, instead of a crash message over the whole page.
  return loadImage(obj._work.canvas.toDataURL('image/png')).then(img => {
    if (gen !== obj._commitGen) return;   // ein neuerer Stand ist bereits da
    replaceElement(obj, img);
  }).catch(e => {
    console.error('[retouch] commitWork:', e);
    toast('The edit could not be applied to the image.', 'err');
  });
}

// ===== Rechteck-Bereich direkt bearbeiten (zuverlässig, ohne Maske) ========
function _rectBounds(obj, x0, y0, x1, y1) {
  const { W, H } = getWork(obj);
  const x = Math.max(0, Math.floor(Math.min(x0, x1)));
  const y = Math.max(0, Math.floor(Math.min(y0, y1)));
  const w = Math.min(W, Math.ceil(Math.max(x0, x1))) - x;
  const h = Math.min(H, Math.ceil(Math.max(y0, y1))) - y;
  return { x, y, w, h };
}

// Rechteck-Bereich umfärben – Schattierung bleibt (Helligkeit behalten).
export function recolorRect(obj, x0, y0, x1, y1, color) {
  const { ctx } = getWork(obj);
  const { x, y, w, h } = _rectBounds(obj, x0, y0, x1, y1);
  if (w <= 0 || h <= 0) return commitWork(obj);
  const nr = parseInt(color.slice(1, 3), 16), ng = parseInt(color.slice(3, 5), 16), nb = parseInt(color.slice(5, 7), 16);
  const img = ctx.getImageData(x, y, w, h);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] === 0) continue;
    const L = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) / 255;
    const f = 0.4 + 0.9 * L;
    d[i] = Math.min(255, nr * f); d[i + 1] = Math.min(255, ng * f); d[i + 2] = Math.min(255, nb * f);
  }
  ctx.putImageData(img, x, y);
  return commitWork(obj);
}

// Rechteck-Bereich transparent machen.
export function removeRect(obj, x0, y0, x1, y1) {
  const { ctx } = getWork(obj);
  const { x, y, w, h } = _rectBounds(obj, x0, y0, x1, y1);
  if (w > 0 && h > 0) ctx.clearRect(x, y, w, h);
  return commitWork(obj);
}

// ===== Markieren (Maske) + am Stück umfärben/entfernen =====================
export function getMask(obj) {
  if (obj._mask) return obj._mask;
  const { W, H } = getWork(obj);
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  obj._mask = { canvas: c, ctx: c.getContext('2d'), W, H };
  return obj._mask;
}

// Markierung an Bildpunkt hinzufügen (weiß in die Maske malen).
export function markAt(obj, px, py, radius) {
  const { ctx } = getMask(obj);
  ctx.fillStyle = '#ffffff';
  ctx.beginPath(); ctx.arc(px, py, radius, 0, Math.PI * 2); ctx.fill();
  obj._maskDirty = true;
}

export function clearMask(obj) {
  if (obj._mask) obj._mask.ctx.clearRect(0, 0, obj._mask.W, obj._mask.H);
  obj._maskDirty = false;
}

// Rechteck-Markierung: setzt die Maske auf ein Rechteck (ersetzt vorherige).
export function markRect(obj, x0, y0, x1, y1) {
  const { ctx, W, H } = getMask(obj);
  ctx.clearRect(0, 0, W, H);
  const x = Math.min(x0, x1), y = Math.min(y0, y1);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(x, y, Math.abs(x1 - x0), Math.abs(y1 - y0));
  obj._maskDirty = (Math.abs(x1 - x0) > 0 && Math.abs(y1 - y0) > 0);
}
// This used to scan the entire mask on EVERY tool change (about 300 ms of
// stutter per click on a 24-megapixel image). A flag does the job now.
export function hasMask(obj) {
  return !!(obj._mask && obj._maskDirty);
}

// Live-Vorschau: Arbeitsbild + rote Markierung → nur als Anzeige ins Element.
export function renderMaskPreview(obj) {
  const { canvas: work, W, H } = getWork(obj);
  const mask = getMask(obj);
  // Keep the two helper canvases on the object. Before, every mouse move made
  // two new full-size canvases (48 MB each at 12 MP) - the browser could not
  // clean up fast enough.
  if (!obj._prevCv || obj._prevCv.tmp.width !== W || obj._prevCv.tmp.height !== H) {
    const tmp = document.createElement('canvas'); tmp.width = W; tmp.height = H;
    const rc  = document.createElement('canvas'); rc.width  = W; rc.height  = H;
    obj._prevCv = { tmp, tctx: tmp.getContext('2d'), rc, rctx: rc.getContext('2d') };
  }
  const { tmp, tctx, rc, rctx } = obj._prevCv;
  tctx.clearRect(0, 0, W, H);
  tctx.globalAlpha = 1;
  tctx.drawImage(work, 0, 0);
  // red area only where the mask is set
  rctx.clearRect(0, 0, W, H);
  rctx.globalCompositeOperation = 'source-over';
  rctx.fillStyle = '#ff3b30'; rctx.fillRect(0, 0, W, H);
  rctx.globalCompositeOperation = 'destination-in';
  rctx.drawImage(mask.canvas, 0, 0);
  tctx.globalAlpha = 0.5;
  tctx.drawImage(rc, 0, 0);
  obj.setElement(tmp);
  obj._maskPreview = true;   // markiert: das ist NUR Anzeige, kein echter Stand
  obj.dirty = true;
}

// Takes back every red marking preview. MUST run before any export - otherwise
// the red 50% area ended up in the saved PNG and in the design.
// A synchronous emergency variant: resets the display only (canvas as element).
// That is enough for the export, because toDataURL rasterises the display.
export function beendeVorschauen(fabricCanvas) {
  if (!fabricCanvas) return;
  fabricCanvas.getObjects().forEach(o => {
    if (o._maskPreview) {
      o._maskPreview = false;
      if (o._work) { o.setElement(o._work.canvas); o.dirty = true; }
    }
  });
  fabricCanvas.requestRenderAll();
}

// Call before SAVING: turns every working canvas back into a real image.
// A <canvas> as the element of a fabric.Image cannot be serialised reliably -
// depending on the Fabric version, the canvas_json ended up with a huge base64
// image or with no src at all (image lost on opening).
export async function vorschauenUebernehmen(fabricCanvas) {
  if (!fabricCanvas) return;
  const offen = fabricCanvas.getObjects().filter(
    o => o.type === 'image' && o._work &&
         (o._maskPreview || (o._element && o._element.tagName === 'CANVAS')));
  for (const o of offen) {
    o._maskPreview = false;
    try { await commitWork(o); }
    catch (e) { console.warn('Arbeitsstand konnte nicht übernommen werden:', e); }
  }
  fabricCanvas.requestRenderAll();
}

// Markierung anwenden. mode: 'recolor' (Farbe) | 'remove' (transparent).
export function applyMask(obj, mode, color) {
  const { ctx, canvas: work, W, H } = getWork(obj);
  const mask = getMask(obj);
  if (mode === 'remove') {
    ctx.globalCompositeOperation = 'destination-out';
    ctx.drawImage(mask.canvas, 0, 0);         // wegradieren wo Maske
    ctx.globalCompositeOperation = 'source-over';
    clearMask(obj);
    return commitWork(obj);
  }
  // recolour: inside the mask only, keeping the SHADING (brightness stays, hue
  // moves to the target colour) - so the folds and shadows of a blouse stay visible.
  const nr = parseInt((color || '#ffffff').slice(1, 3), 16);
  const ng = parseInt((color || '#ffffff').slice(3, 5), 16);
  const nb = parseInt((color || '#ffffff').slice(5, 7), 16);
  const img = ctx.getImageData(0, 0, W, H);
  const d = img.data;
  const m = mask.ctx.getImageData(0, 0, W, H).data;
  for (let i = 0; i < d.length; i += 4) {
    if (m[i + 3] === 0 || d[i + 3] === 0) continue;        // nur maskiert + sichtbar
    const L = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) / 255; // Helligkeit 0..1
    // Modulate the target colour with the original brightness (multiply-like, plus a lift)
    const f = 0.4 + 0.9 * L;
    d[i]     = Math.min(255, nr * f);
    d[i + 1] = Math.min(255, ng * f);
    d[i + 2] = Math.min(255, nb * f);
  }
  ctx.putImageData(img, 0, 0);
  clearMask(obj);
  return commitWork(obj);
}
