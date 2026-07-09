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
  return editor.canvas.getObjects().some(o => o.anim && o.anim.type && o.anim.type !== 'none');
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
  const tt = t / 1000;   // Sekunden (für Schleifen)
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
  return new Promise(resolve => {
    const start = performance.now();
    function tick(now) {
      const t = now - start;
      editor.canvas.getObjects().forEach(o => applyAt(o, t));
      editor.canvas.requestRenderAll();
      if (onFrame) onFrame(t);
      if (t < total) requestAnimationFrame(tick);
      else { resetAnim(editor); resolve(); }
    }
    requestAnimationFrame(tick);
  });
}

export function previewAnimation(editor) {
  if (!hasAnimations(editor)) { toast('Keine Animationen gesetzt', 'err'); return; }
  play(editor, animDuration(editor));
}

// Für Export: Canvas auf volle Auflösung (Zoom 1) setzen, danach zurück.
function toFullRes(editor) {
  editor.canvas.setZoom(1);
  editor.canvas.setDimensions({ width: editor.width, height: editor.height });
}
function restoreFit(editor) {
  if (editor._lastFit) editor.fitTo(editor._lastFit.w, editor._lastFit.h);
  else editor.canvas.requestRenderAll();
}

function animDuration(editor) {
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
    toFullRes(editor);
    for (let t = 0; t <= total; t += frameMs) {
      editor.canvas.getObjects().forEach(o => applyAt(o, t));
      editor.canvas.renderAll();
      gif.addFrame(editor.canvas.lowerCanvasEl, { copy: true, delay: frameMs });
    }
    resetAnim(editor);
    restoreFit(editor);

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
