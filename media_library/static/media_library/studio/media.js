// media.js – Animationen + Export als bewegtes Bild (WebM-Video) und GIF.
// Jedes Element kann eine Animation tragen: obj.anim = {type, dur, delay}.
// Beim Abspielen werden Opacity/Position/Skalierung/Winkel über die Zeit
// interpoliert und der Canvas Frame für Frame gerendert.
import { toast, status } from './util.js';

export const ANIM_TYPES = ['none', 'fadeIn', 'slideLeft', 'slideUp', 'pulse', 'spin', 'zoomIn'];

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
  switch (type) {
    case 'fadeIn':    o.set({ opacity: b.opacity * ease }); break;
    case 'slideLeft': o.set({ left: b.left - 200 * (1 - ease), opacity: b.opacity * ease }); break;
    case 'slideUp':   o.set({ top: b.top + 200 * (1 - ease), opacity: b.opacity * ease }); break;
    case 'zoomIn':    o.set({ scaleX: b.scaleX * (0.3 + 0.7 * ease), scaleY: b.scaleY * (0.3 + 0.7 * ease), opacity: b.opacity * ease }); break;
    case 'pulse':   { const s = 1 + 0.08 * Math.sin(t / 200); o.set({ scaleX: b.scaleX * s, scaleY: b.scaleY * s }); break; }
    case 'spin':      o.set({ angle: b.angle + (t / dur) * 360 }); break;
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

  const blob = new Blob(chunks, { type: 'video/webm' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = (document.getElementById('title-input')?.value.trim() || 'studio') + '.webm';
  a.click();
  status('✅ Video exportiert', 'green');
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
    for (let t = 0; t <= total; t += frameMs) {
      editor.canvas.getObjects().forEach(o => applyAt(o, t));
      editor.canvas.renderAll();
      gif.addFrame(editor.canvas.lowerCanvasEl, { copy: true, delay: frameMs });
    }
    resetAnim(editor);

    gif.on('finished', blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (document.getElementById('title-input')?.value.trim() || 'studio') + '.gif';
      a.click();
      status('✅ GIF exportiert', 'green');
    });
    gif.render();
  } catch (e) {
    status('❌ GIF-Fehler', 'red');
    toast('GIF-Bibliothek konnte nicht geladen werden', 'err');
  }
}
