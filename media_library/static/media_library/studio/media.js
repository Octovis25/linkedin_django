// media.js – Animationen + Export als bewegtes Bild (WebM-Video) und GIF.
// Jedes Element kann eine Animation tragen: obj.anim = {type, dur, delay}.
// Beim Abspielen werden Opacity/Position/Skalierung/Winkel über die Zeit
// interpoliert und der Canvas Frame für Frame gerendert.
import { toast, status } from './util.js';
import { saveAnimation } from './io.js';

export const ANIM_TYPES = [
  'none', 'fadeIn', 'fadeOut',
  'slideLeft', 'slideRight', 'slideUp', 'slideDown',
  'zoomIn', 'zoomOut', 'bounce',
  'pulse', 'float', 'spin', 'flash', 'wobble', 'shake',
];
// Menschliche Beschriftung + Gruppierung (einmalig = spielt einmal, endlos = Schleife)
export const ANIM_LABELS = {
  none: 'Keine', fadeIn: 'Einblenden', fadeOut: 'Ausblenden',
  slideLeft: 'Rein von rechts', slideRight: 'Rein von links',
  slideUp: 'Rein von unten', slideDown: 'Rein von oben',
  zoomIn: 'Reinzoomen', zoomOut: 'Rauszoomen', bounce: 'Hüpfen (einmal)',
  pulse: 'Pulsieren (Schleife)', float: 'Schweben (Schleife)',
  spin: 'Drehen (Schleife)', flash: 'Blinken (Schleife)',
  wobble: 'Wackeln (Schleife)', shake: 'Zittern (Schleife)',
};

// Setzt eine Animation auf das aktuell gewählte Element.
export function setAnim(editor, type, dur = 1200, delay = 0) {
  const o = editor.active();
  if (!o) { toast('Erst ein Element wählen', 'err'); return; }
  o.anim = (type && type !== 'none') ? { type, dur, delay } : null;
  editor.snapshot();
}

export function hasAnimations(editor) {
  return editor.canvas.getObjects().some(o =>
    (o.anim && o.anim.type && o.anim.type !== 'none') || (o.fx && o.fx !== 'none'));
}

// ===== Deko-Effekte (Partikel: Funkeln, Konfetti, Kreise, Strahlen …) ======
export const EFFECTS = ['none', 'orbit', 'network', 'scan', 'neon', 'rays', 'glow', 'bubbles', 'confetti', 'hearts'];
export const EFFECT_LABELS = {
  none: 'Kein Effekt', orbit: '💫 Orbit', network: '🕸 Netzwerk', scan: '📡 Scan',
  neon: '💠 Neon-Puls', rays: '☀️ Strahlen', glow: '💡 Glow', bubbles: '⭕ Kreise',
  confetti: '🎊 Konfetti', hearts: '💕 Herzen',
};
const FX_COLORS = ['#F56E28', '#008591', '#61CEBC', '#ffd700', '#ff4d6d', '#4d94ff'];
let _fxOn = false, _fxTime = 0;
// deterministischer Pseudo-Zufall (frame-stabil für GIF-Export)
function _h(n) { const x = Math.sin(n * 12.9898) * 43758.5453; return x - Math.floor(x); }

function _drawEffects(ctx, editor) {
  const z = editor.canvas.getZoom();
  const t = _fxTime;
  editor.canvas.getObjects().forEach(o => {
    if (o._snap || !o.fx || o.fx === 'none') return;
    const b = o.getBoundingRect(true);
    const L = b.left * z, T = b.top * z, W = b.width * z, H = b.height * z;
    const cx = L + W / 2, cy = T + H / 2, R = Math.max(W, H) / 2;
    ctx.save();
    if (o.fx === 'orbit') {
      ctx.translate(cx, cy);
      ctx.globalAlpha = 0.15; ctx.strokeStyle = '#61CEBC'; ctx.lineWidth = 1 * z;
      ctx.beginPath(); ctx.ellipse(0, 0, R * 1.15, R * 0.55, 0, 0, Math.PI * 2); ctx.stroke();
      const n = 5;
      for (let i = 0; i < n; i++) {
        const a = t / 700 + i * (2 * Math.PI / n), rx = R * 1.15, ry = R * 0.55;
        ctx.globalAlpha = 0.25; ctx.fillStyle = '#61CEBC';
        ctx.beginPath(); ctx.arc(Math.cos(a - 0.3) * rx, Math.sin(a - 0.3) * ry, 2.5 * z, 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = 0.95; ctx.fillStyle = i % 2 ? '#22d3ee' : '#61CEBC';
        ctx.beginPath(); ctx.arc(Math.cos(a) * rx, Math.sin(a) * ry, 4 * z, 0, Math.PI * 2); ctx.fill();
      }
    } else if (o.fx === 'network') {
      const N = 7, pts = [];
      for (let i = 0; i < N; i++) {
        pts.push([L + _h(i + 1) * W + Math.sin(t / 900 + i) * 6 * z,
                  T + _h(i * 5 + 2) * H + Math.cos(t / 1100 + i) * 6 * z]);
      }
      const maxd = Math.max(W, H) * 0.45;
      ctx.lineWidth = 1 * z; ctx.strokeStyle = '#22d3ee';
      for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
        const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]);
        if (d < maxd) { ctx.globalAlpha = 0.35 * (1 - d / maxd); ctx.beginPath(); ctx.moveTo(pts[i][0], pts[i][1]); ctx.lineTo(pts[j][0], pts[j][1]); ctx.stroke(); }
      }
      ctx.globalAlpha = 0.95; ctx.fillStyle = '#22d3ee';
      pts.forEach(p => { ctx.beginPath(); ctx.arc(p[0], p[1], 3 * z, 0, Math.PI * 2); ctx.fill(); });
    } else if (o.fx === 'scan') {
      ctx.globalAlpha = 0.12; ctx.strokeStyle = '#22d3ee'; ctx.lineWidth = 1;
      for (let gy = T; gy < T + H; gy += 14 * z) { ctx.beginPath(); ctx.moveTo(L, gy); ctx.lineTo(L + W, gy); ctx.stroke(); }
      const y = T + ((t / 1400) % 1) * H;
      const g = ctx.createLinearGradient(0, y - 12 * z, 0, y + 12 * z);
      g.addColorStop(0, 'rgba(34,211,238,0)'); g.addColorStop(0.5, 'rgba(34,211,238,0.45)'); g.addColorStop(1, 'rgba(34,211,238,0)');
      ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.fillRect(L, y - 12 * z, W, 24 * z);
      ctx.strokeStyle = 'rgba(34,211,238,0.9)'; ctx.lineWidth = 1.5 * z;
      ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + W, y); ctx.stroke();
    } else if (o.fx === 'neon') {
      const pulse = Math.sin(t / 350) * 0.5 + 0.5, pad = 6 * z;
      ctx.globalAlpha = 1; ctx.strokeStyle = `rgba(34,211,238,${0.5 + 0.5 * pulse})`;
      ctx.lineWidth = (2 + 2 * pulse) * z; ctx.shadowColor = '#22d3ee'; ctx.shadowBlur = (8 + 12 * pulse) * z;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(L - pad, T - pad, W + 2 * pad, H + 2 * pad, 10 * z);
      else ctx.rect(L - pad, T - pad, W + 2 * pad, H + 2 * pad);
      ctx.stroke();
    } else if (o.fx === 'rays') {
      ctx.translate(cx, cy); ctx.rotate(t / 1400);
      const pulse = Math.sin(t / 400) * 0.15 + 0.85;
      for (let k = 0; k < 12; k++) {
        ctx.rotate(Math.PI / 6);
        ctx.globalAlpha = 0.25 * pulse; ctx.fillStyle = '#ffd54a';
        ctx.beginPath(); ctx.moveTo(0, -R * 0.7); ctx.lineTo(R * 0.09, -R * 1.35 * pulse); ctx.lineTo(-R * 0.09, -R * 1.35 * pulse); ctx.closePath(); ctx.fill();
      }
    } else if (o.fx === 'bubbles') {
      for (let i = 0; i < 12; i++) {
        const ph = ((t / 1600) + i / 12) % 1;
        const x = L + _h(i + 5) * W, y = (T + H) - ph * H * 1.25, rad = (3 + _h(i * 5) * 7) * z;
        ctx.globalAlpha = (1 - ph) * 0.8; ctx.strokeStyle = '#61CEBC'; ctx.lineWidth = 1.5 * z;
        ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.stroke();
      }
    } else if (o.fx === 'confetti') {
      for (let i = 0; i < 18; i++) {
        const ph = ((t / 1300) + i / 18) % 1;
        const x = L + _h(i + 2) * W, y = T - H * 0.1 + ph * H * 1.3, sz = (4 + _h(i * 9) * 4) * z;
        ctx.save(); ctx.globalAlpha = 0.9 * (1 - ph * 0.3);
        ctx.translate(x, y); ctx.rotate(t / 200 + i);
        ctx.fillStyle = FX_COLORS[i % FX_COLORS.length];
        ctx.fillRect(-sz / 2, -sz / 4, sz, sz / 2); ctx.restore();
      }
    } else if (o.fx === 'glow') {
      const pulse = Math.sin(t / 500) * 0.5 + 0.5;
      const g = ctx.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * 1.3);
      g.addColorStop(0, `rgba(255,225,120,${0.25 * pulse})`); g.addColorStop(1, 'rgba(255,225,120,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R * 1.3, 0, Math.PI * 2); ctx.fill();
    } else if (o.fx === 'hearts') {
      for (let i = 0; i < 10; i++) {
        const ph = ((t / 1800) + i / 10) % 1;
        const x = L + _h(i + 4) * W, y = (T + H) - ph * H * 1.2, s = (5 + _h(i * 2) * 5) * z;
        ctx.globalAlpha = (1 - ph) * 0.9; ctx.fillStyle = '#ff4d6d';
        ctx.beginPath();
        ctx.moveTo(x, y + s * 0.3);
        ctx.bezierCurveTo(x, y, x - s, y, x - s, y + s * 0.3);
        ctx.bezierCurveTo(x - s, y + s * 0.7, x, y + s, x, y + s * 1.1);
        ctx.bezierCurveTo(x, y + s, x + s, y + s * 0.7, x + s, y + s * 0.3);
        ctx.bezierCurveTo(x + s, y, x, y, x, y + s * 0.3);
        ctx.fill();
      }
    }
    ctx.restore();
  });
}

// 'after:render'-Haken einmalig registrieren (zeichnet Effekte übers Bild).
function ensureFxHook(editor) {
  if (editor._fxHook) return;
  editor._fxHook = true;
  editor.canvas.on('after:render', () => {
    if (!_fxOn) return;
    const ctx = editor.canvas.getContext();
    _drawEffects(ctx, editor);
  });
}

export function setEffect(editor, obj, fx) {
  if (!obj) return;
  obj.fx = (fx && fx !== 'none') ? fx : null;
  editor.snapshot();
}

// Wendet den Animationszustand zum Zeitpunkt t (ms) auf ein Objekt an.
// Speichert/wiederherstellt Originalwerte über _base.
function applyAt(o, t) {
  if (!o.anim) return;
  if (!o._base) o._base = { opacity: o.opacity, left: o.left, top: o.top, scaleX: o.scaleX, scaleY: o.scaleY, angle: o.angle };
  const b = o._base;
  const { type, dur, delay } = o.anim;
  let p = (t - delay) / dur;               // Fortschritt 0..1
  p = Math.max(0, Math.min(1, p));
  const ease = 1 - Math.pow(1 - p, 3);     // easeOutCubic

  o.set({ opacity: b.opacity, left: b.left, top: b.top, scaleX: b.scaleX, scaleY: b.scaleY, angle: b.angle });
  // Schleifen-Tempo an den Dauer-Regler koppeln: größere Dauer = langsamer.
  // dur=1200 ⇒ sp=1 (unverändert); dur=2400 ⇒ halbe Geschwindigkeit.
  const tt = (t / 1000) * (1200 / Math.max(200, dur));
  switch (type) {
    // — einmalige Effekte (über die Dauer) —
    case 'fadeIn':     o.set({ opacity: b.opacity * ease }); break;
    case 'fadeOut':    o.set({ opacity: b.opacity * (1 - ease) }); break;
    case 'slideLeft':  o.set({ left: b.left + 220 * (1 - ease), opacity: b.opacity * ease }); break;
    case 'slideRight': o.set({ left: b.left - 220 * (1 - ease), opacity: b.opacity * ease }); break;
    case 'slideUp':    o.set({ top: b.top + 220 * (1 - ease), opacity: b.opacity * ease }); break;
    case 'slideDown':  o.set({ top: b.top - 220 * (1 - ease), opacity: b.opacity * ease }); break;
    case 'zoomIn':     o.set({ scaleX: b.scaleX * (0.3 + 0.7 * ease), scaleY: b.scaleY * (0.3 + 0.7 * ease), opacity: b.opacity * ease }); break;
    case 'zoomOut':    o.set({ scaleX: b.scaleX * (1.7 - 0.7 * ease), scaleY: b.scaleY * (1.7 - 0.7 * ease), opacity: b.opacity * ease }); break;
    case 'bounce': {   // hüpft einmal rein
      const bo = Math.abs(Math.sin(p * Math.PI * 2)) * (1 - p);
      o.set({ top: b.top - 60 * bo, opacity: b.opacity * Math.min(1, p * 2) }); break;
    }
    // — Schleifen-Effekte (dauerhaft) —
    case 'pulse':  { const s = 1 + 0.08 * Math.sin(tt * 4); o.set({ scaleX: b.scaleX * s, scaleY: b.scaleY * s }); break; }
    case 'float':  o.set({ top: b.top + 12 * Math.sin(tt * 2) }); break;
    case 'spin':   o.set({ angle: b.angle + tt * 90 }); break;
    case 'flash':  o.set({ opacity: b.opacity * (0.5 + 0.5 * Math.abs(Math.sin(tt * 3))) }); break;
    case 'wobble': o.set({ angle: b.angle + 6 * Math.sin(tt * 4) }); break;
    case 'shake':  o.set({ left: b.left + 5 * Math.sin(tt * 25) }); break;
  }
  o.setCoords();
}

function resetAnim(editor) {
  editor.canvas.getObjects().forEach(o => { if (o._base) { o.set(o._base); o.setCoords(); delete o._base; } });
  editor.canvas.requestRenderAll();
}

// Spielt die Animation über `total` ms und ruft onFrame() pro Frame.
// Gibt Promise zurück, die nach Ablauf auflöst.
function play(editor, total, onFrame) {
  ensureFxHook(editor);
  return new Promise(resolve => {
    const start = performance.now();
    _fxOn = true;
    function tick(now) {
      const t = now - start;
      _fxTime = t;
      editor.canvas.getObjects().forEach(o => applyAt(o, t));
      editor.canvas.requestRenderAll();
      if (onFrame) onFrame(t);
      if (t < total) requestAnimationFrame(tick);
      else { resetAnim(editor); _fxOn = false; editor.canvas.requestRenderAll(); resolve(); }
    }
    requestAnimationFrame(tick);
  });
}

export function previewAnimation(editor) {
  if (!hasAnimations(editor)) { toast('Keine Animationen gesetzt', 'err'); return; }
  play(editor, animDuration(editor));
}

// Für Export: Canvas auf volle Auflösung setzen und Zoom + Verschiebung
// neutralisieren, sonst wird der verschobene Ausschnitt aufgenommen.
function toFullRes(editor) {
  editor.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  editor.canvas.setDimensions({ width: editor.width, height: editor.height });
}
function restoreFit(editor) {
  if (editor._lastFit) editor.fitTo(editor._lastFit.w, editor._lastFit.h);
  else editor.canvas.requestRenderAll();
}

function animDuration(editor) {
  // Manueller Längen-Regler hat Vorrang (Sekunden). Leer/0 = automatisch.
  const el = document.getElementById('video-length');
  const secs = el ? parseFloat(el.value) : 0;
  if (secs && secs > 0) return Math.min(secs, 30) * 1000;
  let max = 1500;
  editor.canvas.getObjects().forEach(o => { if (o.anim) max = Math.max(max, (o.anim.delay || 0) + (o.anim.dur || 1200) + 300); });
  return Math.min(max, 8000);
}

// ---- Export als bewegtes Bild (WebM) -------------------------------------
export async function exportVideo(editor) {
  if (!hasAnimations(editor)) { toast('Keine Animationen – nichts zu exportieren', 'err'); return; }
  const canvasEl = editor.canvas.lowerCanvasEl;
  if (!canvasEl.captureStream) { toast('Browser unterstützt keine Video-Aufnahme', 'err'); return; }

  status('🎬 Nehme Video auf…');
  editor.canvas.discardActiveObject();
  editor.setGridVisible(false);   // Raster nicht mit aufnehmen
  toFullRes(editor);
  const stream = canvasEl.captureStream(30);
  const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9') ? 'video/webm;codecs=vp9' : 'video/webm';
  const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 6_000_000 });
  const chunks = [];
  rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };

  const done = new Promise(res => { rec.onstop = res; });
  rec.start();
  await play(editor, animDuration(editor));
  await new Promise(r => setTimeout(r, 400));   // letzten Frame halten
  rec.stop();
  await done;
  restoreFit(editor);
  if (editor.gridOn) editor.setGridVisible(true);

  const blob = new Blob(chunks, { type: 'video/webm' });
  // Kein Auto-Download – nur in „Meine Ausgaben" speichern (mit canvas_json → editierbar).
  status('💾 Video wird gespeichert…');
  await saveAnimation(editor, blob, '.webm');
}

// ---- Export als GIF -------------------------------------------------------
// Nutzt gif.js (lokal ausgeliefert, lazy geladen). Rendert Frames aus der Animation.
const VENDOR = window.STUDIO_VENDOR || '/static/media_library/studio/vendor/';
let _gifLibPromise = null;
function loadGifLib() {
  if (_gifLibPromise) return _gifLibPromise;
  _gifLibPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = VENDOR + 'gif.js';
    s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
  return _gifLibPromise;
}

export async function exportGif(editor) {
  if (!hasAnimations(editor)) { toast('Keine Animationen – nichts zu exportieren', 'err'); return; }
  status('🎞 GIF wird erzeugt…');
  try {
    await loadGifLib();
    const total = animDuration(editor);
    const fps = 15, frameMs = 1000 / fps;
    const gif = new window.GIF({
      workers: 2, quality: 10,
      width: editor.width, height: editor.height,
      workerScript: VENDOR + 'gif.worker.js',
    });

    editor.canvas.discardActiveObject();
    editor.setGridVisible(false);   // Raster nicht mit aufnehmen
    ensureFxHook(editor);
    toFullRes(editor);
    _fxOn = true;
    for (let t = 0; t <= total; t += frameMs) {
      _fxTime = t;
      editor.canvas.getObjects().forEach(o => applyAt(o, t));
      editor.canvas.renderAll();
      gif.addFrame(editor.canvas.lowerCanvasEl, { copy: true, delay: frameMs });
    }
    _fxOn = false;
    resetAnim(editor);
    restoreFit(editor);
    if (editor.gridOn) editor.setGridVisible(true);

    gif.on('finished', async blob => {
      // Kein Auto-Download – nur in „Meine Ausgaben" speichern.
      status('💾 GIF wird gespeichert…');
      await saveAnimation(editor, blob, '.gif');
    });
    gif.render();
  } catch (e) {
    status('❌ GIF-Fehler', 'red');
    toast('GIF-Bibliothek konnte nicht geladen werden', 'err');
  }
}
