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

// Entfernt den Hintergrund per RAND-FLOOD-FILL: startet an allen Randpixeln und
// entfernt nur die vom Rand her ZUSAMMENHÄNGENDE Hintergrundfarbe. Eingeschlossene
// Bereiche (weißer Kittel, Icons – auch wenn gleiche Farbe wie Rand) bleiben erhalten.
// Gibt Promise<HTMLImageElement>.
export function removeBackground(imgEl, { tol = 50, islandMaxPct = 0.6 } = {}) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);

  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) {
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
  const tol2 = tol * tol;
  // Weißschutz: helle, farbneutrale Pixel (Weiß/hellgrau) gelten NIE als
  // Hintergrund – so bleiben weiße Inhalte (Kittel, Icons) erhalten.
  const isProtectedWhite = (p) => {
    const max = Math.max(d[p], d[p + 1], d[p + 2]);
    const min = Math.min(d[p], d[p + 1], d[p + 2]);
    return max >= 200 && (max - min) <= 38;   // Weiß / Off-White / Hellgrau schützen
  };
  const near = (p) => {
    if (d[p + 3] === 0) return false;
    if (isProtectedWhite(p)) return false;
    const dr = d[p] - r, dg = d[p + 1] - g, db = d[p + 2] - b;
    return dr * dr + dg * dg + db * db <= tol2;
  };

  const total = W * H;
  const done = new Uint8Array(total);   // schon bearbeitet (egal ob entfernt)
  const clear = (idx) => { d[idx * 4 + 3] = 0; };

  // Ein zusammenhängendes Gebiet ab startIdx sammeln (nur near-Pixel).
  function collect(startIdx) {
    const region = [];
    const stack = [startIdx];
    while (stack.length) {
      const idx = stack.pop();
      if (done[idx]) continue;
      if (!near(idx * 4)) { continue; }
      done[idx] = 1;
      region.push(idx);
      const x = idx % W, y = (idx / W) | 0;
      if (x > 0)     stack.push(idx - 1);
      if (x < W - 1) stack.push(idx + 1);
      if (y > 0)     stack.push(idx - W);
      if (y < H - 1) stack.push(idx + W);
    }
    return region;
  }

  // 1) Äußeren Hintergrund vom Rand her entfernen.
  const edges = [];
  for (let x = 0; x < W; x++) { edges.push(x); edges.push((H - 1) * W + x); }
  for (let y = 0; y < H; y++) { edges.push(y * W); edges.push(y * W + W - 1); }
  for (const e of edges) {
    if (done[e] || !near(e * 4)) continue;
    collect(e).forEach(clear);
  }

  // 2) Eingeschlossene Inseln: alle übrigen near-Gebiete sammeln; NUR kleine
  //    (bis islandMaxPct % der Bildfläche) entfernen – große Flächen (Bluse) bleiben.
  const maxIsland = total * (islandMaxPct / 100);
  for (let idx = 0; idx < total; idx++) {
    if (done[idx] || !near(idx * 4)) continue;
    const region = collect(idx);
    if (region.length <= maxIsland) region.forEach(clear);
  }

  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}

// Entfernt ein helles, graustufiges "Transparenz-Schachbrett" (typisch für
// KI-generierte "transparente" Bilder): alle hellen, farbarmen (grauen/weißen)
// Pixel werden global transparent – egal ob zusammenhängend. Bunte/dunkle
// Bildinhalte bleiben erhalten. Gibt Promise<HTMLImageElement>.
export function removeGrayBackground(imgEl, { minBright = 175, maxSat = 32 } = {}) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);
  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) { return Promise.reject(new Error('Bild getaintet – über den Proxy laden.')); }
  const d = imgData.data;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] === 0) continue;
    const r = d[i], g = d[i + 1], b = d[i + 2];
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    const bright = max;          // Helligkeit
    const sat = max - min;       // grob: Farbigkeit (0 = grau)
    if (bright >= minBright && sat <= maxSat) d[i + 3] = 0;  // hell + grau → weg
  }
  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}


// Entfernt NUR das eingebackene Schachbrett-/Rautenmuster: helle, farbneutrale
// Pixel, die Teil eines abwechselnden Musters sind (hoher lokaler Kontrast zu
// hellen Nachbarn). Gleichmäßig weiße Flächen (Bluse) haben KEIN Muster und
// bleiben erhalten. Gibt Promise<HTMLImageElement>.
export function removeCheckerboard(imgEl) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);
  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) { return Promise.reject(new Error('Bild getaintet – über den Proxy laden.')); }
  const d = imgData.data;
  const N = W * H;
  const neutral = (i) => (Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2])) <= 22;
  const bright = (i) => Math.max(d[i], d[i + 1], d[i + 2]);

  // 1) Histogramm der neutralen Helligkeiten 150..234 → schärfste Spitze = Karo-Grau.
  const hist = new Float64Array(256);
  for (let idx = 0; idx < N; idx++) {
    const i = idx * 4;
    if (d[i + 3] === 0 || !neutral(i)) continue;
    const b = bright(i);
    if (b >= 150 && b <= 234) hist[b]++;
  }
  let peak = -1, peakVal = 0;
  for (let b = 150; b <= 234; b++) if (hist[b] > peakVal) { peakVal = hist[b]; peak = b; }
  if (peak < 0 || peakVal < N * 0.01) {   // kein deutliches Karo-Grau → nichts tun
    return loadImage(c.toDataURL('image/png'));
  }

  const isGray  = (i) => neutral(i) && Math.abs(bright(i) - peak) <= 10;   // exakter Karo-Grauton
  const isWhite = (i) => neutral(i) && bright(i) >= 235;

  // 2) Karo-Grau immer entfernen; Weiß nur, wenn nahe an Karo-Grau (= weißes Karo).
  const remove = new Uint8Array(N);
  const R = 8;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const idx = y * W + x, i = idx * 4;
      if (d[i + 3] === 0) continue;
      if (isGray(i)) { remove[idx] = 1; continue; }
      if (isWhite(i)) {
        let nearGray = false;
        for (let dy = -R; dy <= R && !nearGray; dy += 2) {
          const yy = y + dy; if (yy < 0 || yy >= H) continue;
          for (let dx = -R; dx <= R; dx += 2) {
            const xx = x + dx; if (xx < 0 || xx >= W) continue;
            if (isGray((yy * W + xx) * 4)) { nearGray = true; break; }
          }
        }
        if (nearGray) remove[idx] = 1;
      }
    }
  }
  for (let idx = 0; idx < N; idx++) if (remove[idx]) d[idx * 4 + 3] = 0;
  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}

// Erkennt, ob das Bild ein eingebackenes „Transparenz-Rautenmuster" als
// Hintergrund hat (typisch für KI-Bilder): Randpixel sind hell und bestehen
// aus zwei Graustufen (Schachbrett). Gibt true/false.
export function hasCheckerboardBorder(imgEl) {
  try {
    const W = imgEl.naturalWidth || imgEl.width;
    const H = imgEl.naturalHeight || imgEl.height;
    const c = document.createElement('canvas');
    c.width = W; c.height = H;
    const ctx = c.getContext('2d');
    ctx.drawImage(imgEl, 0, 0, W, H);
    const d = ctx.getImageData(0, 0, W, H).data;
    let light = 0, tot = 0;
    const shades = {};
    const check = (x, y) => {
      const p = (y * W + x) * 4;
      if (d[p + 3] < 250) return;                 // schon transparent
      const max = Math.max(d[p], d[p + 1], d[p + 2]);
      const min = Math.min(d[p], d[p + 1], d[p + 2]);
      tot++;
      if (max >= 180 && (max - min) <= 25) {       // hell + grau
        light++;
        shades[Math.round(max / 10) * 10] = (shades[Math.round(max / 10) * 10] || 0) + 1;
      }
    };
    const step = Math.max(1, Math.floor(W / 100));
    for (let x = 0; x < W; x += step) { check(x, 0); check(x, H - 1); }
    for (let y = 0; y < H; y += step) { check(0, y); check(W - 1, y); }
    if (tot === 0) return false;
    const lightFrac = light / tot;
    const distinctShades = Object.values(shades).filter(v => v > tot * 0.05).length;
    // Viel Hell am Rand UND mindestens zwei Graustufen → Schachbrett
    return lightFrac > 0.7 && distinctShades >= 2;
  } catch (e) { return false; }
}

// Umfärben mit Erkennung: erkennt ab dem Klickpunkt automatisch den
// zusammenhängenden, farbähnlichen Bereich (Magic Wand) und färbt ihn in
// hex (#rrggbb) um. Transparenz bleibt erhalten.
export function recolorRegion(imgEl, px, py, hex, tol = 40) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);
  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) { return Promise.reject(new Error('Bild getaintet – über den Proxy laden.')); }
  const d = imgData.data;
  px = Math.round(px); py = Math.round(py);
  if (px < 0 || py < 0 || px >= W || py >= H) return loadImage(c.toDataURL('image/png'));

  const nr = parseInt(hex.slice(1, 3), 16), ng = parseInt(hex.slice(3, 5), 16), nb = parseInt(hex.slice(5, 7), 16);
  // Originalfarben (Kopie), damit Vergleich nicht durch die neue Farbe verfälscht wird.
  const orig = new Uint8ClampedArray(d);
  const seed = (py * W + px) * 4;
  const seR = orig[seed], seG = orig[seed + 1], seB = orig[seed + 2];
  const tol2 = tol * tol;        // Schritt-Toleranz zum NACHBARN (breitet sich über Verläufe aus)
  const seedTol2 = (tol * 2) ** 2; // Sicherheitsgrenze zum Startpunkt (nicht ins ganze Bild laufen)

  const visited = new Uint8Array(W * H);
  const start = py * W + px;
  visited[start] = 1;
  const stack = [start];
  const near = (a, b) => {
    const dr = orig[a] - orig[b], dg = orig[a + 1] - orig[b + 1], db = orig[a + 2] - orig[b + 2];
    return dr * dr + dg * dg + db * db <= tol2;
  };
  const nearSeed = (p) => {
    const dr = orig[p] - seR, dg = orig[p + 1] - seG, db = orig[p + 2] - seB;
    return dr * dr + dg * dg + db * db <= seedTol2;
  };
  while (stack.length) {
    const idx = stack.pop();
    const p = idx * 4;
    if (orig[p + 3] === 0) continue;
    d[p] = nr; d[p + 1] = ng; d[p + 2] = nb;   // umfärben, Alpha bleibt
    const x = idx % W, y = (idx / W) | 0;
    const tryN = (nidx) => {
      if (visited[nidx]) return;
      const np = nidx * 4;
      if (orig[np + 3] === 0) return;
      // Nachbar ähnlich UND noch im erlaubten Abstand zum Start
      if (near(np, p) && nearSeed(np)) { visited[nidx] = 1; stack.push(nidx); }
    };
    if (x > 0)     tryN(idx - 1);
    if (x < W - 1) tryN(idx + 1);
    if (y > 0)     tryN(idx - W);
    if (y < H - 1) tryN(idx + W);
  }
  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}

// Pipette / Farb-Key: nimmt die Farbe am Klickpunkt und macht ALLE ähnlichen
// Pixel im ganzen Bild transparent (idealer Hintergrund-Entferner bei
// einfarbigem Hintergrund). Transparenz bleibt.
export function removeColorGlobal(imgEl, px, py, tol = 40) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);
  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) { return Promise.reject(new Error('Bild getaintet – über den Proxy laden.')); }
  const d = imgData.data;
  px = Math.round(px); py = Math.round(py);
  if (px < 0 || py < 0 || px >= W || py >= H) return loadImage(c.toDataURL('image/png'));
  // Größeres Feld um den Klick abtasten → Referenzfarben sammeln
  // (Schachbrett = zwei Töne; einfarbig = einer). Deckt auch größere Kästchen ab.
  const refs = [];
  const R = 14;
  const neutralPx = (r, g, b) => (Math.max(r, g, b) - Math.min(r, g, b)) <= 24;
  let allNeutral = true, minB = 255, maxB = 0, neutralCount = 0, sampleCount = 0;
  for (let dy = -R; dy <= R; dy++) {
    const yy = py + dy; if (yy < 0 || yy >= H) continue;
    for (let dx = -R; dx <= R; dx++) {
      const xx = px + dx; if (xx < 0 || xx >= W) continue;
      const j = (yy * W + xx) * 4;
      if (d[j + 3] === 0) continue;
      const r = d[j], g = d[j + 1], b = d[j + 2];
      sampleCount++;
      const bri = Math.max(r, g, b);
      if (neutralPx(r, g, b)) { neutralCount++; if (bri < minB) minB = bri; if (bri > maxB) maxB = bri; }
      else allNeutral = false;
      let found = false;
      for (const rf of refs) {
        const dr = rf[0] - r, dg = rf[1] - g, db = rf[2] - b;
        if (dr * dr + dg * dg + db * db <= 400) { found = true; break; }
      }
      if (!found && refs.length < 6) refs.push([r, g, b]);
    }
  }
  if (!refs.length) return loadImage(c.toDataURL('image/png'));

  // Muster-Erkennung: fast alles im Feld ist farbneutral mit Helligkeits-Spanne
  // → wie ein graues Schachbrett. Dann per Helligkeitsbereich entfernen.
  const looksPattern = allNeutral && neutralCount > sampleCount * 0.9 && (maxB - minB) >= 12;
  const tol2 = tol * tol, soft2 = (tol * 1.6) ** 2;
  const bandLo = minB - tol, bandHi = maxB + tol;

  const nearestDist2 = (i) => {
    let best = Infinity;
    for (const rf of refs) {
      const dr = d[i] - rf[0], dg = d[i + 1] - rf[1], db = d[i + 2] - rf[2];
      const dd = dr * dr + dg * dg + db * db;
      if (dd < best) best = dd;
    }
    return best;
  };
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] === 0) continue;
    if (looksPattern) {
      const bri = Math.max(d[i], d[i + 1], d[i + 2]);
      if (neutralPx(d[i], d[i + 1], d[i + 2]) && bri >= bandLo && bri <= bandHi) { d[i + 3] = 0; continue; }
    }
    const dist2 = nearestDist2(i);
    if (dist2 <= tol2) d[i + 3] = 0;
    else if (dist2 <= soft2) {
      const f = (dist2 - tol2) / (soft2 - tol2);
      d[i + 3] = Math.min(d[i + 3], Math.round(255 * f));
    }
  }
  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}

// Farbtausch: nimmt die Farbe am Klickpunkt und ersetzt ALLE ähnlichen Pixel
// im ganzen Bild durch hex (#rrggbb). Für flache Illustrationen ideal
// (z.B. alle orangenen Flächen auf einmal umfärben). Transparenz bleibt.
export function recolorSimilarAll(imgEl, px, py, hex, tol = 45) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);
  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) { return Promise.reject(new Error('Bild getaintet – über den Proxy laden.')); }
  const d = imgData.data;
  px = Math.round(px); py = Math.round(py);
  if (px < 0 || py < 0 || px >= W || py >= H) return loadImage(c.toDataURL('image/png'));
  const si = (py * W + px) * 4;
  if (d[si + 3] === 0) return loadImage(c.toDataURL('image/png'));   // transparent geklickt
  const sr = d[si], sg = d[si + 1], sb = d[si + 2];
  const nr = parseInt(hex.slice(1, 3), 16), ng = parseInt(hex.slice(3, 5), 16), nb = parseInt(hex.slice(5, 7), 16);
  const tol2 = tol * tol;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] === 0) continue;
    const dr = d[i] - sr, dg = d[i + 1] - sg, db = d[i + 2] - sb;
    if (dr * dr + dg * dg + db * db <= tol2) { d[i] = nr; d[i + 1] = ng; d[i + 2] = nb; }
  }
  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}

// zusammenhängenden, farbähnlichen Pixel transparent. Für weiße Reste, die
// das Auto-Freistellen übrig gelassen hat. Gibt Promise<HTMLImageElement>.
export function floodFillTransparent(imgEl, px, py, tol = 40) {
  const W = imgEl.naturalWidth || imgEl.width;
  const H = imgEl.naturalHeight || imgEl.height;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, W, H);

  let imgData;
  try { imgData = ctx.getImageData(0, 0, W, H); }
  catch (e) { return Promise.reject(new Error('Bild getaintet – über den Proxy laden.')); }
  const d = imgData.data;

  px = Math.round(px); py = Math.round(py);
  if (px < 0 || py < 0 || px >= W || py >= H) return loadImage(c.toDataURL('image/png'));

  const start = (py * W + px) * 4;
  const sr = d[start], sg = d[start + 1], sb = d[start + 2];
  if (d[start + 3] === 0) return loadImage(c.toDataURL('image/png')); // schon transparent

  const tol2 = tol * tol;
  const visited = new Uint8Array(W * H);
  const stack = [py * W + px];
  while (stack.length) {
    const idx = stack.pop();
    if (visited[idx]) continue;
    visited[idx] = 1;
    const p = idx * 4;
    if (d[p + 3] === 0) continue;
    const dr = d[p] - sr, dg = d[p + 1] - sg, db = d[p + 2] - sb;
    if (dr * dr + dg * dg + db * db > tol2) continue;
    d[p + 3] = 0;                       // transparent machen
    const x = idx % W, y = (idx / W) | 0;
    if (x > 0)     stack.push(idx - 1);
    if (x < W - 1) stack.push(idx + 1);
    if (y > 0)     stack.push(idx - W);
    if (y < H - 1) stack.push(idx + W);
  }
  ctx.putImageData(imgData, 0, 0);
  return loadImage(c.toDataURL('image/png'));
}
