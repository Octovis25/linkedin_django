// retouch.js – manuelle Pinsel-Korrektur für freigestellte Bilder:
//   Radieren      = mit Pinsel transparent machen
//   Wiederherstellen = Originalpixel per Pinsel zurückholen
// Arbeitet auf einer Offscreen-Arbeitskopie in Bild-Auflösung.
import { loadImage } from './util.js';
import { proxyUrl } from './config.js';

// Liefert (und initialisiert bei Bedarf) die Arbeits-Canvas eines fabric-Bildes.
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

// Lädt das Originalbild (für Wiederherstellen) – gecacht am Objekt.
export async function getOriginal(obj) {
  if (obj._origImg) return obj._origImg;
  const url = obj.originalUrl || obj.srcUrl;
  obj._origImg = await loadImage(proxyUrl(url));
  return obj._origImg;
}

// Pinsel-Aktion an Bildkoordinate (px,py).
// mode: 'erase' (transparent) | 'restore' (Original zurück) | 'paint' (Farbe malen)
// origImg wird bei 'restore' gebraucht, color (#rrggbb) bei 'paint'.
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
    // Nur dort malen, wo schon Deckung ist (Transparenz bleibt transparent),
    // damit man den freigestellten Rand nicht wieder auffüllt.
    ctx.clip();
    ctx.globalCompositeOperation = 'source-atop';
    ctx.fillStyle = color || '#ffffff';
    ctx.fillRect(px - radius, py - radius, radius * 2, radius * 2);
  }
  ctx.restore();
}

// Tauscht das Bild eines fabric-Objekts sauber aus: setElement + Cache
// invalidieren (dirty), sonst mischt Fabric altes und neues Bild ("verschmilzt").
export function replaceElement(obj, imgEl) {
  obj.setElement(imgEl);
  obj.objectCaching = false;   // kein Cache → kein Verschwimmen von Alt/Neu
  obj.dirty = true;
  if (obj.canvas) obj.canvas.requestRenderAll();
}

// Überträgt die Arbeits-Canvas zurück ins fabric-Bild.
export function commitWork(obj) {
  if (!obj._work) return Promise.resolve();
  return loadImage(obj._work.canvas.toDataURL('image/png')).then(img => {
    replaceElement(obj, img);
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
}

export function clearMask(obj) {
  if (obj._mask) obj._mask.ctx.clearRect(0, 0, obj._mask.W, obj._mask.H);
}

// Rechteck-Markierung: setzt die Maske auf ein Rechteck (ersetzt vorherige).
export function markRect(obj, x0, y0, x1, y1) {
  const { ctx, W, H } = getMask(obj);
  ctx.clearRect(0, 0, W, H);
  const x = Math.min(x0, x1), y = Math.min(y0, y1);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(x, y, Math.abs(x1 - x0), Math.abs(y1 - y0));
}
export function hasMask(obj) {
  if (!obj._mask) return false;
  const d = obj._mask.ctx.getImageData(0, 0, obj._mask.W, obj._mask.H).data;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true;
  return false;
}

// Live-Vorschau: Arbeitsbild + rote Markierung → nur als Anzeige ins Element.
export function renderMaskPreview(obj) {
  const { canvas: work, W, H } = getWork(obj);
  const mask = getMask(obj);
  const tmp = document.createElement('canvas'); tmp.width = W; tmp.height = H;
  const tctx = tmp.getContext('2d');
  tctx.drawImage(work, 0, 0);
  // rote Fläche nur wo Maske gesetzt ist
  const rc = document.createElement('canvas'); rc.width = W; rc.height = H;
  const rctx = rc.getContext('2d');
  rctx.fillStyle = '#ff3b30'; rctx.fillRect(0, 0, W, H);
  rctx.globalCompositeOperation = 'destination-in';
  rctx.drawImage(mask.canvas, 0, 0);
  tctx.globalAlpha = 0.5;
  tctx.drawImage(rc, 0, 0);
  obj.setElement(tmp);
  obj.dirty = true;
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
  // recolor: nur innerhalb der Maske, SCHATTIERUNG erhalten (Helligkeit behalten,
  // Farbton auf Zielfarbe setzen) – so bleiben Falten/Schatten der Bluse sichtbar.
  const nr = parseInt((color || '#ffffff').slice(1, 3), 16);
  const ng = parseInt((color || '#ffffff').slice(3, 5), 16);
  const nb = parseInt((color || '#ffffff').slice(5, 7), 16);
  const img = ctx.getImageData(0, 0, W, H);
  const d = img.data;
  const m = mask.ctx.getImageData(0, 0, W, H).data;
  for (let i = 0; i < d.length; i += 4) {
    if (m[i + 3] === 0 || d[i + 3] === 0) continue;        // nur maskiert + sichtbar
    const L = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) / 255; // Helligkeit 0..1
    // Zielfarbe mit der Original-Helligkeit modulieren (Multiply-artig, plus Aufhellung)
    const f = 0.4 + 0.9 * L;
    d[i]     = Math.min(255, nr * f);
    d[i + 1] = Math.min(255, ng * f);
    d[i + 2] = Math.min(255, nb * f);
  }
  ctx.putImageData(img, 0, 0);
  clearMask(obj);
  return commitWork(obj);
}
