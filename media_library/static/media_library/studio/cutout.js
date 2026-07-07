// cutout.js – Hintergrund freistellen. SAUBER: arbeitet nur auf same-origin
// (proxy-geladenen) Bildern, daher wird der Canvas nie getaintet und
// toDataURL() funktioniert zuverlässig. Das war die Kernursache dafür, dass
// freigestellte Bilder vorher verschwanden bzw. nicht auf dem Hintergrund lagen.
import { loadImage } from './util.js';

// Prüft, ob ein fabric.Image bereits Transparenz hat (schon freigestellt).
// Wichtig: bei Fehler geben wir FALSE zurück (Bild als NICHT freigestellt
// behandeln) – die alte Logik nahm fälschlich TRUE an und übersprang das
// Freistellen, wodurch Bilder mit Kasten auf dem Hintergrund landeten.
export function hasTransparency(imgEl) {
  try {
    const w = Math.min(imgEl.naturalWidth || imgEl.width, 200);
    const h = Math.min(imgEl.naturalHeight || imgEl.height, 200);
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.drawImage(imgEl, 0, 0, w, h);
    const d = ctx.getImageData(0, 0, w, h).data;
    let transp = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] < 250) transp++;
    return transp > w * h * 0.03;   // >3 % transparent → schon freigestellt
  } catch (e) {
    console.warn('Transparenz-Check fehlgeschlagen:', e);
    return false;                    // sicher: als NICHT freigestellt behandeln
  }
}

// Entfernt eine einfarbige Hintergrundfläche (aus den 4 Ecken abgetastet).
// Gibt eine Promise<HTMLImageElement> mit dem freigestellten Bild zurück.
export function removeBackground(imgEl, { strictTol = 30, softTol = 55 } = {}) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);

  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) {
    // Sollte mit Proxy-Bildern nie passieren – aber sauber melden statt still scheitern.
    return Promise.reject(new Error('Bild ist cross-origin getaintet – über den Proxy laden.'));
  }
  const d = imgData.data;

  // Hintergrundfarbe aus 4 Ecken (8×8) mitteln.
  let r = 0, g = 0, b = 0, n = 0;
  const sample = (sx, sy) => {
    for (let y = sy; y < sy + 8 && y < H; y++)
      for (let x = sx; x < sx + 8 && x < W; x++) {
        const i = (y * W + x) * 4; r += d[i]; g += d[i + 1]; b += d[i + 2]; n++;
      }
  };
  sample(0, 0); sample(W - 8, 0); sample(0, H - 8); sample(W - 8, H - 8);
  r = Math.round(r / n); g = Math.round(g / n); b = Math.round(b / n);

  for (let i = 0; i < W * H; i++) {
    const p = i * 4;
    if (d[p + 3] === 0) continue;
    const dist = Math.sqrt((d[p] - r) ** 2 + (d[p + 1] - g) ** 2 + (d[p + 2] - b) ** 2);
    if (dist <= strictTol) d[p + 3] = 0;
    else if (dist <= softTol) d[p + 3] = Math.min(d[p + 3], Math.round(255 * (dist - strictTol) / (softTol - strictTol)));
  }
  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}
