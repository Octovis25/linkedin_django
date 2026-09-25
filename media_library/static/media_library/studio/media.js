// media.js - animations plus export as moving image (WebM video) and GIF.
// Every element can carry an animation: obj.anim = {type, dur} and/or a
// decorative effect obj.fx. When it starts is written ONCE in obj.startAt -
// see startOf()/elapsedAt() further down.
// On playback, opacity, position, scale and angle are interpolated over time
// and the canvas is rendered frame by frame.
import { toast, status } from './util.js';
import { fabric } from './editor.js';
import { saveAnimation } from './io.js';

export const ANIM_TYPES = [
  'none', 'fadeIn', 'fadeOut',
  'slideLeft', 'slideRight', 'slideUp', 'slideDown',
  'zoomIn', 'zoomOut', 'bounce',
  'pulse', 'float', 'spin', 'flash', 'wobble', 'shake',
];
// Menschliche Beschriftung + Gruppierung (einmalig = spielt einmal, endlos = Schleife)
export const ANIM_LABELS = {
  none: 'None', fadeIn: 'Fade in', fadeOut: 'Fade out',
  slideLeft: 'In from right', slideRight: 'In from left',
  slideUp: 'In from bottom', slideDown: 'In from top',
  zoomIn: 'Zoom in', zoomOut: 'Zoom out', bounce: 'Bounce (once)',
  pulse: 'Pulse (loop)', float: 'Float (loop)',
  spin: 'Spin (loop)', flash: 'Flash (loop)',
  wobble: 'Wobble (loop)', shake: 'Shake (loop)',
};
// Motions that never end. They are driven by the wall clock instead of by a
// progress ratio, which is why they need their own Start handling in applyAt().
export const LOOP_TYPES = new Set(['pulse', 'float', 'spin', 'flash', 'wobble', 'shake']);

/* ---------------------------------------------------------------------------
   ONE clock for everything that moves.

   Motion and Effect used to be two systems: each kept its own start value and
   read its own clock. That is what let them drift apart — one honoured the Start
   slider, the other never even looked at it. Both now go through the three
   helpers below, so a change to the timing is a change for both by construction.

   `startAt` is the single stored start. The fallbacks read drafts saved before
   this change: those carry the value inside `anim.delay` or `fxDelay`, and they
   must keep working untouched.
   --------------------------------------------------------------------------- */

/* Tempo - one factor for the whole piece ------------------------------------
   Stretches every Speed and every Start at once. Choreograph with the
   relative timings, then slow the whole thing down without touching a single
   element. 1 = as set, 3 = three times as slow.

   It is read from the toolbar, the way the video length is, because it belongs
   to the piece and not to an element - but only ONCE per playback. A DOM lookup
   sixty times a second for every element is what turns a smooth preview into a
   slideshow.

   It is not stored with the drawing: reopening starts at 1x again.
--------------------------------------------------------------------------- */
let _tempo = 1;
export function tempo() { return _tempo; }
// True while a preview or a GIF/video recording is playing the effects.
export function effectsRunning() { return _fxOn; }
// The time (ms) the effects were last drawn at - for the frame-by-frame checks.
export function effectsClock() { return _fxTime; }
// The slider is a SPEED: left slow, right fast. Its value is a step on a
// doubling scale - 0 as set, -2 twice as slow, +2 twice as fast - and _tempo
// stays what the painters need: the factor every time is stretched by.
export function readTempo() {
  const el = document.getElementById('anim-tempo');
  const v = el ? parseFloat(el.value) : 0;
  _tempo = Number.isFinite(v) ? Math.min(8, Math.max(0.25, Math.pow(2, -v / 2))) : 1;
  return _tempo;
}

export function startOf(o) {
  return (o?.startAt ?? o?.anim?.delay ?? o?.fxDelay ?? 0) || 0;
}
export function hasStarted(o, t) { return t >= startOf(o) * _tempo; }
export function elapsedAt(o, t) { return Math.max(0, t - startOf(o) * _tempo); }
// Writes the start in the one place that counts. The two legacy fields are kept
// in step so a draft saved now still opens on an older deployment.
export function setStart(o, ms) {
  const v = Math.max(0, +ms || 0);
  o.startAt = v;
  if (o.anim) o.anim.delay = v;
  if (o.fx) o.fxDelay = v;
  return v;
}

// Puts an animation on the currently selected element.
export function setAnim(editor, type, dur = 1200, delay = 0) {
  const o = editor.active();
  if (!o) { toast('Select an element first', 'err'); return; }
  o.anim = (type && type !== 'none') ? { type, dur } : null;
  setStart(o, delay);
  editor.snapshot();
}

export function hasAnimations(editor) {
  return editor.canvas.getObjects().some(o =>
    (o.anim && o.anim.type && o.anim.type !== 'none') || (o.fx && o.fx !== 'none'));
}

// ===== Deko-Effekte (Partikel: Funkeln, Konfetti, Kreise, Strahlen …) ======
export const EFFECTS = [
  'none',
  'network', 'networkFlat', 'question', 'pins', 'signals', 'edgeNet',
  'orbit', 'veil', 'scan', 'magnifier',
  'neon', 'rays', 'glow', 'bubbles', 'confetti', 'hearts',
];
export const EFFECT_LABELS = {
  none: 'No effect',
  network: '🕸 Network', networkFlat: '🕸 Network, flat', question: '❓ Question',
  pins: '📍 Pins', signals: '✨ Signals', edgeNet: '⭕ Net around the edge',
  orbit: '💫 Orbit', veil: '🌫 Veil', scan: '📡 Scan', magnifier: '🔍 Magnifier',
  neon: '💠 Neon pulse', rays: '☀️ Rays', glow: '💡 Glow', bubbles: '⭕ Circles',
  confetti: '🎊 Confetti', hearts: '💕 Hearts',
};

/* ---------------------------------------------------------------------------
   The effect frame.

   An effect used to sit on an element and was drawn into that element's
   bounding box - so it could only ever be as big as the thing it hung on. The
   frame is an element of its own that shows nothing: it is there to give an
   effect a box. Drag it, pull its corners, and the effect follows. Several of
   them on one picture are simply several frames.

   It carries no fill and no stroke, so it is invisible in the export. On the
   artboard it is found through its handles and through the Layers list.
--------------------------------------------------------------------------- */
export const FX_RAHMEN = 'fxframe';
export function istEffektRahmen(o) { return !!o && o.shapeKind === FX_RAHMEN; }

export function addEffektRahmen(editor, fx = 'network') {
  // A magnifier's frame is the WINDOW it travels in: wide and low, in the
  // middle, with a glass of its own size. Every other effect starts over the
  // whole picture.
  const lupe = fx === 'magnifier';
  const W = editor.width, H = editor.height;
  const glas = lupenGlasStandard(editor);
  const fw = Math.round(W * 0.7), fh = Math.max(glas, Math.round(H * 0.3));
  const o = new fabric.Rect({
    left: lupe ? Math.round((W - fw) / 2) : 0,
    top: lupe ? Math.round((H - fh) / 2) : 0,
    width: lupe ? fw : W,
    height: lupe ? fh : H,
    fill: 'rgba(0,0,0,0)', stroke: '', strokeWidth: 0,
    shapeKind: FX_RAHMEN, fx: fx, fxTempo: 2.5, startAt: 0,
    ...(lupe ? { fxLens: glas, ...LUPEN_STANDARD } : {}),
    objectCaching: false, lockRotation: true, hasRotatingPoint: false,
    cornerColor: '#008591', cornerStrokeColor: '#ffffff', cornerSize: 10,
    transparentCorners: false, borderColor: '#008591', borderDashArray: [5, 4],
  });
  o.setControlsVisibility({ mtr: false });
  editor.canvas.add(o);
  editor.canvas.setActiveObject(o);
  editor.canvas.requestRenderAll();
  editor.snapshot();
  return o;
}

/* Drawings from before the frame existed: every element that carried an effect
   gets a frame of its own, exactly around that element. It therefore looks the
   way it was saved - and from now on it can be moved. */
/* ---- The magnifier's way through its window ------------------------------
   The frame is the window, the glass has a size of its own (fxLens, picture
   pixels). A round is a list of legs: move from A to B in d seconds, or rest.
   fxLineSec is the time for ONE line or ONE sweep, so a taller window does not
   make the lens hurry - the round just takes longer. A magnifier saved before
   there were ways has no fxPath and simply stays where it is. */
export const LUPEN_WEGE = ['lines', 'lr', 'pingpong', 'wander', 'still'];
export const LUPEN_WEG_LABELS = {
  lines: 'Line by line – reads along the text', lr: 'Left → right, then again',
  pingpong: 'Back and forth', wander: 'Wander freely', still: 'Stay put',
};
export const LUPEN_STANDARD = { fxPath: 'lines', fxLineSec: 7, fxPause: 1.5 };
export function lupenGlasStandard(editor) {
  return Math.round(Math.min(editor.width, editor.height) * 0.22);
}
export function lupenRadius(o) {
  const b = o.getBoundingRect(true);
  const halb = Math.min(b.width, b.height) / 2;
  return o.fxLens > 0 ? Math.min(o.fxLens / 2, halb) : halb;
}
export function lupenSekunden(o) { return o.fxLineSec > 0 ? +o.fxLineSec : 7; }
export function lupenWege(o) {
  const b = o.getBoundingRect(true), r = lupenRadius(o);
  const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
  const L = Math.min(cx, b.left + r), R = Math.max(cx, b.left + b.width - r);
  const O = Math.min(cy, b.top + r), U = Math.max(cy, b.top + b.height - r);
  const v = lupenSekunden(o);
  const p = o.fxPause != null && +o.fxPause >= 0 ? +o.fxPause : 1.5;
  const zurueck = Math.min(1.2, v * 0.25);
  const legs = [];
  const geh = (a, z, d) => legs.push({ a, b: z, d });
  const halt = (a, d) => { if (d > 0) legs.push({ a, b: a, d }); };
  switch (o.fxPath || 'still') {
    case 'lr':
      geh([L, cy], [R, cy], v); halt([R, cy], p); geh([R, cy], [L, cy], zurueck); halt([L, cy], p / 2); break;
    case 'pingpong':
      geh([L, cy], [R, cy], v); halt([R, cy], p); geh([R, cy], [L, cy], v); halt([L, cy], p); break;
    case 'wander':
      legs.push({ wander: true, box: [L, O, R, U], a: [L + (R - L) * (0.5 + 0.5 * Math.sin(0.3)), O + (U - O) * 0.5], d: v * 3 });
      break;
    case 'lines': {
      const zeilen = Math.max(1, Math.round(b.height / (2 * r * 0.85)));
      const ys = Array.from({ length: zeilen }, (_, i) => zeilen === 1 ? cy : O + (U - O) * i / (zeilen - 1));
      ys.forEach((y, i) => {
        halt([L, y], i === 0 ? p / 2 : 0);
        geh([L, y], [R, y], v);
        halt([R, y], p);
        geh([R, y], [L, ys[(i + 1) % zeilen]], zurueck);
      });
      break;
    }
    default:
      halt([cx, cy], 1);
  }
  if (!legs.length) halt([cx, cy], 1);
  return { legs, total: legs.reduce((s, l) => s + l.d, 0) };
}
const _sanft = k => k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
// Where the glass's centre is, sek seconds into its round (picture pixels).
export function lupenStelle(o, sek, wege) {
  const { legs, total } = wege || lupenWege(o);
  let rest = total > 0 ? ((sek % total) + total) % total : 0;
  for (const l of legs) {
    if (rest <= l.d) {
      const k = l.d ? rest / l.d : 0;
      if (l.wander) {
        const [L, O, R, U] = l.box, a = k * Math.PI * 2;
        return [L + (R - L) * (0.5 + 0.5 * Math.sin(a * 2 + 0.3)), O + (U - O) * (0.5 + 0.5 * Math.sin(a * 3))];
      }
      const e = _sanft(k);
      return [l.a[0] + (l.b[0] - l.a[0]) * e, l.a[1] + (l.b[1] - l.a[1]) * e];
    }
    rest -= l.d;
  }
  return legs[0].a;
}

export function rahmenAusAltenEffekten(editor) {
  const alte = editor.canvas.getObjects()
    .filter(o => !o._snap && !o._grid && !istEffektRahmen(o) && o.fx && o.fx !== 'none');
  alte.forEach(o => {
    const b = o.getBoundingRect(true);
    const rahmen = new fabric.Rect({
      left: b.left, top: b.top, width: b.width, height: b.height,
      fill: 'rgba(0,0,0,0)', stroke: '', strokeWidth: 0,
      shapeKind: FX_RAHMEN, fx: o.fx, fxTempo: o.fxTempo || 1, startAt: startOf(o),
      objectCaching: false, lockRotation: true, hasRotatingPoint: false,
      cornerColor: '#008591', cornerStrokeColor: '#ffffff', cornerSize: 10,
      transparentCorners: false, borderColor: '#008591', borderDashArray: [5, 4],
    });
    rahmen.setControlsVisibility({ mtr: false });
    editor.canvas.add(rahmen);
    // Right above the element it came from, so the order stays as it was.
    editor.canvas.moveTo(rahmen, editor.canvas.getObjects().indexOf(o) + 1);
    o.fx = null; o.fxDelay = 0;
  });
  if (alte.length) editor.canvas.requestRenderAll();
  return alte.length;
}
const FX_COLORS = ['#F56E28', '#008591', '#61CEBC', '#ffd700', '#ff4d6d', '#4d94ff'];
let _fxOn = false, _fxTime = 0;
// deterministischer Pseudo-Zufall (frame-stabil für GIF-Export)
function _h(n) { const x = Math.sin(n * 12.9898) * 43758.5453; return x - Math.floor(x); }

/* Where an effect is drawn, and in which order.

   It used to be: render everything, then paint every effect on top. That put
   the network lines across the headline as well - the one thing that has to
   stay readable. The objects are now walked in their own order: a frame paints
   its effect where it sits in the stack, and whatever lies above it is drawn
   once more on top of it.

   An element that is not fully opaque is left alone in that second pass. It was
   already drawn once, and drawing it again would darken it - the effect stays
   over it, exactly as before. */
function _malEffekt(ctx, art, L, T, W, H, t, z, farbe) {
  const cx = L + W / 2, cy = T + H / 2, R = Math.max(W, H) / 2;
  // The frame's own colour, if one was picked. Most effects are drawn in two
  // shades of teal; a picked colour replaces both, so the effect stays one
  // colour instead of half teal, half orange. The small orange accents of
  // Pins, Signals and the edge net stay: they are the Octovis orange, not
  // the effect's colour.
  const F1 = farbe || '#61CEBC';
  const F2 = farbe || '#22d3ee';
  ctx.save();
  if (art === 'orbit') {
    ctx.translate(cx, cy);
    ctx.globalAlpha = 0.15; ctx.strokeStyle = F1; ctx.lineWidth = 1 * z;
    ctx.beginPath(); ctx.ellipse(0, 0, R * 1.15, R * 0.55, 0, 0, Math.PI * 2); ctx.stroke();
    const n = 5;
    for (let i = 0; i < n; i++) {
      const a = t / 700 + i * (2 * Math.PI / n), rx = R * 1.15, ry = R * 0.55;
      ctx.globalAlpha = 0.25; ctx.fillStyle = F1;
      ctx.beginPath(); ctx.arc(Math.cos(a - 0.3) * rx, Math.sin(a - 0.3) * ry, 2.5 * z, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 0.95; ctx.fillStyle = i % 2 ? F2 : F1;
      ctx.beginPath(); ctx.arc(Math.cos(a) * rx, Math.sin(a) * ry, 4 * z, 0, Math.PI * 2); ctx.fill();
    }
  } else if (art === 'network') {
    const N = 14, pts = [];
    for (let i = 0; i < N; i++) {
      pts.push([L + _h(i + 1) * W + Math.sin(t / 900 + i) * 9 * z,
                T + _h(i * 5 + 2) * H + Math.cos(t / 1100 + i) * 9 * z]);
    }
    const maxd = Math.max(W, H) * 0.55;
    ctx.lineWidth = 3 * z; ctx.strokeStyle = F2;
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]);
      if (d < maxd) { ctx.globalAlpha = Math.min(1, 0.9 * (1 - d / maxd) + 0.15); ctx.beginPath(); ctx.moveTo(pts[i][0], pts[i][1]); ctx.lineTo(pts[j][0], pts[j][1]); ctx.stroke(); }
    }
    ctx.globalAlpha = 1; ctx.fillStyle = F2;
    ctx.shadowColor = F2; ctx.shadowBlur = 14 * z;
    pts.forEach(p => { ctx.beginPath(); ctx.arc(p[0], p[1], 6 * z, 0, Math.PI * 2); ctx.fill(); });
    ctx.shadowBlur = 0;
  } else if (art === 'scan') {
    ctx.globalAlpha = 0.12; ctx.strokeStyle = F2; ctx.lineWidth = 1;
    for (let gy = T; gy < T + H; gy += 14 * z) { ctx.beginPath(); ctx.moveTo(L, gy); ctx.lineTo(L + W, gy); ctx.stroke(); }
    const y = T + ((t / 1400) % 1) * H;
    const g = ctx.createLinearGradient(0, y - 12 * z, 0, y + 12 * z);
    g.addColorStop(0, _mitAlpha(F2, 0)); g.addColorStop(0.5, _mitAlpha(F2, 0.45)); g.addColorStop(1, _mitAlpha(F2, 0));
    ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.fillRect(L, y - 12 * z, W, 24 * z);
    ctx.strokeStyle = _mitAlpha(F2, 0.9); ctx.lineWidth = 1.5 * z;
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + W, y); ctx.stroke();
  } else if (art === 'neon') {
    const pulse = Math.sin(t / 350) * 0.5 + 0.5, pad = 6 * z;
    ctx.globalAlpha = 1; ctx.strokeStyle = _mitAlpha(F2, 0.5 + 0.5 * pulse);
    ctx.lineWidth = (2 + 2 * pulse) * z; ctx.shadowColor = F2; ctx.shadowBlur = (8 + 12 * pulse) * z;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(L - pad, T - pad, W + 2 * pad, H + 2 * pad, 10 * z);
    else ctx.rect(L - pad, T - pad, W + 2 * pad, H + 2 * pad);
    ctx.stroke();
  } else if (art === 'rays') {
    ctx.translate(cx, cy); ctx.rotate(t / 1400);
    const pulse = Math.sin(t / 400) * 0.15 + 0.85;
    for (let k = 0; k < 12; k++) {
      ctx.rotate(Math.PI / 6);
      ctx.globalAlpha = 0.25 * pulse; ctx.fillStyle = farbe || '#ffd54a';
      ctx.beginPath(); ctx.moveTo(0, -R * 0.7); ctx.lineTo(R * 0.09, -R * 1.35 * pulse); ctx.lineTo(-R * 0.09, -R * 1.35 * pulse); ctx.closePath(); ctx.fill();
    }
  } else if (art === 'bubbles') {
    for (let i = 0; i < 12; i++) {
      const ph = ((t / 1600) + i / 12) % 1;
      const x = L + _h(i + 5) * W, y = (T + H) - ph * H * 1.25, rad = (3 + _h(i * 5) * 7) * z;
      ctx.globalAlpha = (1 - ph) * 0.8; ctx.strokeStyle = F1; ctx.lineWidth = 1.5 * z;
      ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.stroke();
    }
  } else if (art === 'confetti') {
    for (let i = 0; i < 18; i++) {
      const ph = ((t / 1300) + i / 18) % 1;
      const x = L + _h(i + 2) * W, y = T - H * 0.1 + ph * H * 1.3, sz = (4 + _h(i * 9) * 4) * z;
      ctx.save(); ctx.globalAlpha = 0.9 * (1 - ph * 0.3);
      ctx.translate(x, y); ctx.rotate(t / 200 + i);
      ctx.fillStyle = FX_COLORS[i % FX_COLORS.length];
      ctx.fillRect(-sz / 2, -sz / 4, sz, sz / 2); ctx.restore();
    }
  } else if (art === 'glow') {
    const pulse = Math.sin(t / 500) * 0.5 + 0.5;
    const g = ctx.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * 1.3);
    g.addColorStop(0, _mitAlpha(farbe || '#ffe178', 0.25 * pulse)); g.addColorStop(1, _mitAlpha(farbe || '#ffe178', 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R * 1.3, 0, Math.PI * 2); ctx.fill();
  } else if (art === 'hearts') {
    for (let i = 0; i < 10; i++) {
      const ph = ((t / 1800) + i / 10) % 1;
      const x = L + _h(i + 4) * W, y = (T + H) - ph * H * 1.2, s = (5 + _h(i * 2) * 5) * z;
      ctx.globalAlpha = (1 - ph) * 0.9; ctx.fillStyle = farbe || '#ff4d6d';
      ctx.beginPath();
      ctx.moveTo(x, y + s * 0.3);
      ctx.bezierCurveTo(x, y, x - s, y, x - s, y + s * 0.3);
      ctx.bezierCurveTo(x - s, y + s * 0.7, x, y + s, x, y + s * 1.1);
      ctx.bezierCurveTo(x, y + s, x + s, y + s * 0.7, x + s, y + s * 0.3);
      ctx.bezierCurveTo(x + s, y, x, y, x, y + s * 0.3);
      ctx.fill();
    }
  } else if (art === 'networkFlat') {
    // The same web, but quiet: fewer knots, thin lines, no glow. It lies over
    // the picture instead of standing in front of it.
    const pts = _netzPunkte(L, T, W, H, 9, t, 6 * z);
    _netzLinien(ctx, pts, Math.max(W, H) * 0.5, F1, 1.4 * z, 0.55);
    ctx.fillStyle = F1;
    pts.forEach(p => { ctx.beginPath(); ctx.arc(p[0], p[1], 3.4 * z, 0, Math.PI * 2); ctx.fill(); });
  } else if (art === 'question') {
    const pts = _netzPunkte(L, T, W, H, 10, t, 7 * z);
    ctx.lineWidth = 1.4 * z; ctx.strokeStyle = F1;
    pts.forEach((p, i) => {
      ctx.globalAlpha = 0.25 + 0.3 * (Math.sin(t / 900 + i) * 0.5 + 0.5);
      ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(cx, cy); ctx.stroke();
    });
    ctx.globalAlpha = 1; ctx.fillStyle = F1;
    pts.forEach(p => { ctx.beginPath(); ctx.arc(p[0], p[1], 3.4 * z, 0, Math.PI * 2); ctx.fill(); });
    const puls = Math.sin(t / 1000) * 0.5 + 0.5;
    const gr = Math.min(W, H) * 0.34;
    ctx.globalAlpha = 0.16 + 0.12 * puls; ctx.fillStyle = '#0A4D52';
    ctx.beginPath(); ctx.arc(cx, cy, gr * 0.78, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 0.9; ctx.fillStyle = '#ffffff';
    ctx.font = '700 ' + gr + 'px Roboto, Arial';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('?', cx, cy + gr * 0.04);
  } else if (art === 'pins') {
    // Heads with a short stem, the way they sit in the Octovis illustrations.
    const pts = _netzPunkte(L, T, W, H, 7, t, 5 * z);
    ctx.lineWidth = 2 * z; ctx.lineCap = 'round';
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], c = pts[i + 1];
      const mx = (a[0] + c[0]) / 2, my = (a[1] + c[1]) / 2 - Math.max(18 * z, H * 0.09);
      ctx.strokeStyle = i % 2 ? '#F56E28' : (farbe || '#008591');
      ctx.globalAlpha = 0.75;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(mx, my, c[0], c[1]); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    pts.forEach((p, i) => {
      const r = Math.max(5 * z, W * 0.013), kopf = i % 2 ? '#F56E28' : (farbe || '#008591');
      ctx.save(); ctx.translate(p[0], p[1]); ctx.rotate(Math.sin(t / 1600 + i) * 0.25);
      ctx.globalAlpha = 0.35; ctx.strokeStyle = '#0A4D52'; ctx.lineWidth = Math.max(1, r * 0.35);
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, r * 2.1); ctx.stroke();
      ctx.globalAlpha = 1; ctx.fillStyle = kopf;
      ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 0.45; ctx.fillStyle = '#ffffff';
      ctx.beginPath(); ctx.arc(-r * 0.3, -r * 0.35, r * 0.3, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    });
  } else if (art === 'signals') {
    const pts = _netzPunkte(L, T, W, H, 9, t, 3 * z);
    const maxd = Math.max(W, H) * 0.5;
    const paare = [];
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      if (Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) < maxd) paare.push([i, j]);
    }
    ctx.globalAlpha = 0.4; ctx.strokeStyle = F1; ctx.lineWidth = 1.2 * z;
    paare.forEach(pr => {
      ctx.beginPath(); ctx.moveTo(pts[pr[0]][0], pts[pr[0]][1]);
      ctx.lineTo(pts[pr[1]][0], pts[pr[1]][1]); ctx.stroke();
    });
    ctx.globalAlpha = 1; ctx.fillStyle = F1;
    pts.forEach(p => { ctx.beginPath(); ctx.arc(p[0], p[1], 3 * z, 0, Math.PI * 2); ctx.fill(); });
    paare.forEach((pr, k) => {
      const ph = ((t / 2600) + _h(k + 3)) % 1;
      const x = pts[pr[0]][0] + (pts[pr[1]][0] - pts[pr[0]][0]) * ph;
      const y = pts[pr[0]][1] + (pts[pr[1]][1] - pts[pr[0]][1]) * ph;
      ctx.fillStyle = k % 3 === 0 ? '#F56E28' : F2;
      ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 8 * z;
      ctx.beginPath(); ctx.arc(x, y, 3.6 * z, 0, Math.PI * 2); ctx.fill();
    });
    ctx.shadowBlur = 0;
  } else if (art === 'edgeNet') {
    // Knots only around the outside: whatever stands in the middle - text,
    // documents - is left untouched.
    const n = 12, pts = [];
    for (let i = 0; i < n; i++) {
      const w = (i / n) * Math.PI * 2 + Math.sin(t / 2400) * 0.15;
      const rx = W * 0.46 * (0.92 + 0.08 * Math.sin(t / 1300 + i));
      const ry = H * 0.46 * (0.92 + 0.08 * Math.cos(t / 1500 + i));
      pts.push([cx + Math.cos(w) * rx, cy + Math.sin(w) * ry]);
    }
    ctx.strokeStyle = F1; ctx.lineWidth = 1.4 * z; ctx.globalAlpha = 0.6;
    ctx.beginPath();
    pts.forEach((p, i) => { i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); });
    ctx.closePath(); ctx.stroke();
    for (let k = 0; k < n; k += 2) {
      ctx.globalAlpha = 0.25;
      ctx.beginPath(); ctx.moveTo(pts[k][0], pts[k][1]);
      ctx.lineTo(pts[(k + 5) % n][0], pts[(k + 5) % n][1]); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    pts.forEach((p, i) => {
      ctx.fillStyle = i % 4 === 0 ? '#F56E28' : F1;
      ctx.beginPath(); ctx.arc(p[0], p[1], (i % 4 === 0 ? 4.5 : 3.2) * z, 0, Math.PI * 2); ctx.fill();
    });
  } else if (art === 'veil') {
    // No dots at all: soft bands drifting through the picture, plus haze.
    _nebel(ctx, L, T, W, H, t, [F1, F2, farbe || '#0A4D52']);
    for (let i = 0; i < 3; i++) {
      const phase = t / (4200 + i * 900) + i * 1.3;
      ctx.beginPath();
      for (let x = 0; x <= W; x += 12 * z) {
        const y = T + H * (0.30 + 0.16 * i) + Math.sin(x / (W * 0.35) + phase) * H * 0.10;
        x ? ctx.lineTo(L + x, y) : ctx.moveTo(L + x, y);
      }
      const band = i % 2 ? F2 : F1;
      const g = ctx.createLinearGradient(L, 0, L + W, 0);
      g.addColorStop(0, _mitAlpha(band, 0));
      g.addColorStop(0.5, _mitAlpha(band, 0.45));
      g.addColorStop(1, _mitAlpha(band, 0));
      ctx.strokeStyle = g; ctx.lineWidth = (16 + i * 6) * z; ctx.globalAlpha = 0.5;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
  ctx.restore();
}

/* Helpers the web-like effects share, so what differs between them is only how
   they are drawn - never where the knots sit. */
function _netzPunkte(L, T, W, H, n, t, weite) {
  const raus = [];
  for (let i = 0; i < n; i++) {
    raus.push([L + _h(i + 1) * W + Math.sin(t / 900 + i) * weite,
               T + _h(i * 5 + 2) * H + Math.cos(t / 1100 + i) * weite]);
  }
  return raus;
}

function _netzLinien(ctx, pts, maxd, farbe, breite, alpha) {
  ctx.lineWidth = breite; ctx.strokeStyle = farbe;
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
    const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]);
    if (d < maxd) {
      ctx.globalAlpha = Math.min(1, alpha * (1 - d / maxd) + 0.1);
      ctx.beginPath(); ctx.moveTo(pts[i][0], pts[i][1]); ctx.lineTo(pts[j][0], pts[j][1]); ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;
}

function _mitAlpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return 'rgba(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + a + ')';
}

function _nebel(ctx, L, T, W, H, t, farben) {
  for (let i = 0; i < 5; i++) {
    const x = L + W * (0.2 + 0.6 * (0.5 + 0.5 * Math.sin(t / (3000 + i * 700) + i)));
    const y = T + H * (0.25 + 0.5 * (0.5 + 0.5 * Math.cos(t / (3600 + i * 500) + i * 2)));
    const r = Math.max(W, H) * (0.22 + 0.10 * _h(i + 3));
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    const f = farben[i % farben.length];
    g.addColorStop(0, _mitAlpha(f, 0.22));
    g.addColorStop(0.55, _mitAlpha(f, 0.09));
    g.addColorStop(1, _mitAlpha(f, 0));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }
}

/* The magnifier.

   It computes nothing: it takes the piece of the picture under its own frame
   and draws it again, larger. Everything BELOW it in the layers is rendered
   once into an offscreen canvas first - otherwise the lens would magnify the
   headline lying on top of it as well, and the very thing that has to stay
   readable would appear twice.

   Glass, then rim, then the handle: flat black, the way the Octovis drawings
   are drawn - no gradients, no gloss on the metal. */
let _lupenLeinwand = null;

function _malLupe(ctx, editor, rahmen, z, sek) {
  // The frame is the window; the glass sits where its way has brought it.
  const [px, py] = lupenStelle(rahmen, sek);
  const cx = px * z, cy = py * z;
  const r = lupenRadius(rahmen) * z;
  if (r < 6) return;
  const vergroesserung = rahmen.fxZoom > 0 ? rahmen.fxZoom : 1.9;

  const breit = ctx.canvas.width, hoch = ctx.canvas.height;
  if (!_lupenLeinwand) _lupenLeinwand = document.createElement('canvas');
  if (_lupenLeinwand.width !== breit || _lupenLeinwand.height !== hoch) {
    _lupenLeinwand.width = breit; _lupenLeinwand.height = hoch;
  }
  const u = _lupenLeinwand.getContext('2d');
  u.setTransform(1, 0, 0, 1, 0, 0);
  u.clearRect(0, 0, breit, hoch);
  const vp = editor.canvas.viewportTransform;
  u.save();
  u.transform(vp[0], vp[1], vp[2], vp[3], vp[4], vp[5]);
  const objekte = editor.canvas.getObjects();
  for (const o of objekte) {
    if (o === rahmen) break;               // alles UNTER der Lupe
    if (o._snap || o._grid) continue;
    o.render(u);
  }
  u.restore();

  // das Glas
  ctx.save();
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.clip();
  const q = (r * 2) / vergroesserung;
  ctx.drawImage(_lupenLeinwand, cx - q / 2, cy - q / 2, q, q, cx - r, cy - r, r * 2, r * 2);
  const g = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
  g.addColorStop(0, 'rgba(255,255,255,0.22)');
  g.addColorStop(0.45, 'rgba(255,255,255,0.04)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g; ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
  ctx.restore();

  const SCHWARZ = '#111318';
  const ringDick = Math.max(3, r * 0.135);
  const stielDick = Math.max(3, r * 0.17);
  const knauf = Math.max(5, r * 0.135);
  const wx = Math.SQRT1_2, wy = Math.SQRT1_2;      // 45 Grad, nach unten rechts
  // The handle starts OUTSIDE the glass - a stick showing through the lens is
  // the one thing that gives it away as drawn.
  const ax = cx + wx * (r + ringDick * 0.35), ay = cy + wy * (r + ringDick * 0.35);
  const bx = cx + wx * r * 1.95, by = cy + wy * r * 1.95;
  ctx.save();
  ctx.strokeStyle = SCHWARZ; ctx.lineCap = 'round'; ctx.lineWidth = stielDick * 1.25;
  ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
  ctx.fillStyle = SCHWARZ;
  ctx.beginPath(); ctx.arc(bx, by, knauf, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = SCHWARZ; ctx.lineWidth = ringDick;
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
  ctx.restore();
}

/* A small, live picture of one effect - for the tiles in the Effects tab. Same
   painter as on the artboard, so a tile never promises something the picture
   will not do. */
export function malEffektVorschau(ctx, art, W, H, t, farbe) {
  if (art === 'magnifier') {
    const r = Math.min(W, H) * 0.3, cx = W * 0.45, cy = H * 0.45;
    ctx.save();
    ctx.strokeStyle = '#111318'; ctx.lineWidth = Math.max(2, r * 0.14);
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    ctx.lineCap = 'round'; ctx.lineWidth = Math.max(2, r * 0.2);
    ctx.beginPath(); ctx.moveTo(cx + r * 0.78, cy + r * 0.78); ctx.lineTo(cx + r * 1.5, cy + r * 1.5); ctx.stroke();
    ctx.restore();
    return;
  }
  _malEffekt(ctx, art, 0, 0, W, H, t, Math.max(0.35, W / 520), farbe || null);
}

function _obenDrauf(ctx, editor, o) {
  if ((o.opacity ?? 1) < 0.99) return;
  const vp = editor.canvas.viewportTransform;
  ctx.save();
  ctx.transform(vp[0], vp[1], vp[2], vp[3], vp[4], vp[5]);
  o.render(ctx);
  ctx.restore();
}

// nurLupe: outside a preview only the magnifier is drawn. It is not motion -
// it is part of the picture, so it has to be seen (and sized) while editing
// and belongs in a still PNG as well. It then ignores its start time too.
function _drawEffects(ctx, editor, nurLupe = false) {
  const z = editor.canvas.getZoom();
  let gemalt = false;
  editor.canvas.getObjects().forEach(o => {
    if (o._snap || o._grid) return;
    const hatEffekt = o.fx && o.fx !== 'none';
    if (hatEffekt) {
      if (nurLupe && o.fx !== 'magnifier') return;
      // Effects honour the Start slider as well. They used to ignore it: every
      // effect was drawn from frame zero, so three elements with different start
      // times all began together.
      if (!nurLupe && !hasStarted(o, _fxTime)) return;
      // Divided by the tempo, so the effect does not merely start later but
      // actually runs slower. A frame has a speed of its own on top of that.
      const t = elapsedAt(o, _fxTime) / _tempo / (o.fxTempo > 0 ? o.fxTempo : 1);
      const b = o.getBoundingRect(true);
      // The magnifier needs to know what lies under it, so it gets the editor
      // and its own frame instead of just a box.
      // Its way runs in seconds of its own (fxLineSec per line), so only the
      // global tempo stretches it - not fxTempo. Outside a preview: the start.
      if (o.fx === 'magnifier') _malLupe(ctx, editor, o, z, nurLupe ? 0 : elapsedAt(o, _fxTime) / _tempo / 1000);
      else _malEffekt(ctx, o.fx, b.left * z, b.top * z, b.width * z, b.height * z, t, z, o.fxColor || null);
      gemalt = true;
      return;
    }
    if (gemalt) _obenDrauf(ctx, editor, o);
  });
}

// Registers the 'after:render' hook once (paints the effects over the picture).
// Fabric hands over the context it just drew into - for a PNG export that is
// the export canvas, not the screen. renderTop() fires without one; outside a
// preview that call is skipped, or the lens would be painted twice onto the
// screen canvas without it being cleared in between.
export function ensureFxHook(editor) {
  if (editor._fxHook) return;
  editor._fxHook = true;
  editor.canvas.on('after:render', e => {
    const ctx = e && e.ctx;
    if (_fxOn) { _drawEffects(ctx || editor.canvas.getContext(), editor); return; }
    if (ctx) _drawEffects(ctx, editor, true);
  });
}

export function setEffect(editor, obj, fx, delay = 0) {
  if (!obj) return;
  obj.fx = (fx && fx !== 'none') ? fx : null;
  setStart(obj, delay);
  editor.snapshot();
}

// Applies the animation state at time t (ms) to an object.
// Keeps and restores the original values through _base.
export function applyAt(o, t) {
  if (!o.anim) return;
  if (!o._base) o._base = { opacity: o.opacity, left: o.left, top: o.top, scaleX: o.scaleX, scaleY: o.scaleY, angle: o.angle };
  const b = o._base;
  const { type } = o.anim;
  const dur = (o.anim.dur || 1200) * _tempo;
  const delay = startOf(o) * _tempo;
  let p = (t - delay) / dur;               // Fortschritt 0..1
  p = Math.max(0, Math.min(1, p));
  const ease = 1 - Math.pow(1 - p, 3);     // easeOutCubic

  o.set({ opacity: b.opacity, left: b.left, top: b.top, scaleX: b.scaleX, scaleY: b.scaleY, angle: b.angle });
  // A loop that has not started yet rests in its base state — the line above
  // has just restored it. Without this an element ignored its Start entirely:
  // one-shot motions divide by `dur` and so subtract the delay, but the loop
  // clock below used to run off the raw `t`.
  if (LOOP_TYPES.has(type) && t < delay) { o.setCoords(); return; }
  // Schleifen-Tempo an den Dauer-Regler koppeln: größere Dauer = langsamer.
  // dur=1200 ⇒ sp=1 (unverändert); dur=2400 ⇒ halbe Geschwindigkeit.
  const tt = (elapsedAt(o, t) / 1000) * (1200 / Math.max(200, dur));
  switch (type) {
    // - one-shot effects (over the duration) -
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

// Plays the animation over `total` ms and calls onFrame() for each frame.
// Returns a promise that resolves when it is done.
function play(editor, total, onFrame) {
  ensureFxHook(editor);
  readTempo();
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
  if (!hasAnimations(editor)) { toast('No animations set', 'err'); return; }
  // The selection's dashed border and handles would run through the preview -
  // on a frame they are all you would see of it.
  editor.canvas.discardActiveObject();
  // Called from a click handler: keep a failed frame off the global handler.
  play(editor, animDuration(editor)).catch(e => console.error('[media] preview:', e));
}

// For export: set the canvas to full resolution and undo zoom and panning,
// otherwise the shifted cut-out is what gets recorded.
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
  // Capped at 15 s: 30 s x 12 fps = 360 frames at 2.5 MB per copy = around
  // 900 MB in memory before the GIF encoding even starts, and the tab dies.
  if (secs && secs > 0) return Math.min(secs, 15) * 1000;
  readTempo();
  let max = 1500, hasLoop = false, lupenWeg = 0;
  editor.canvas.getObjects().forEach(o => {
    // A travelling magnifier wants one whole round, or it never reaches the
    // second line - up to the same 15 s ceiling as everything else.
    if (o.fx === 'magnifier' && (o.fxPath || 'still') !== 'still') {
      lupenWeg = Math.max(lupenWeg, (startOf(o) + lupenWege(o).total * 1000) * _tempo + 300);
    }
    if (o.anim) {
      max = Math.max(max, (startOf(o) + (o.anim.dur || 1200)) * _tempo + 300);
      if (LOOP_TYPES.has(o.anim.type)) hasLoop = true;
    }
    // A late effect needs room after its Start, otherwise an effect set to
    // begin at 2.5 s never appears in a 4 s export.
    if (o.fx && o.fx !== 'none') { hasLoop = true; max = Math.max(max, startOf(o) * _tempo + 1500); }
  });
  // Looping motion and effects: at least 4 s, otherwise it is a brief hop.
  if (hasLoop) max = Math.max(max, 4000 * _tempo);
  // The ceiling grows with the tempo, otherwise a slowed piece is cut off -
  // but never past 15 s, which is where the GIF encoder runs out of memory.
  if (lupenWeg) return Math.min(Math.max(max, lupenWeg), 15000);
  return Math.min(max, Math.min(8000 * _tempo, 15000));
}

// ---- Export as a moving image (WebM) --------------------------------------
export async function exportVideo(editor, onBlob) {
  // Returns true/false: the caller may only report "saved" on true.
  if (!hasAnimations(editor)) { toast('No animations – nothing to export', 'err'); return false; }
  const canvasEl = editor.canvas.lowerCanvasEl;
  if (!canvasEl.captureStream) { toast('Browser does not support video capture', 'err'); return false; }

  status('🎬 Recording video…');
  editor.canvas.discardActiveObject();
  const chunks = [];
  try {
    editor.setGridVisible(false);   // Raster nicht mit aufnehmen
    toFullRes(editor);
    /* Frame by frame, like the GIF - not played in real time.
       The video used to be the preview, filmed: play() asks the browser for
       the next frame and takes the wall clock as the time. When the browser
       hands out frames rarely - the tab in the background, the window behind
       another one, a busy machine - the clock runs on between two frames and
       the magnifier "jumps once, and that's it". Here every frame is drawn at
       its own time (n x 1/30 s) and only then handed to the recorder, so
       nothing can be skipped. The recorder is paused while the tab is hidden,
       so a switch to another window leaves no frozen gap in the video, and
       while each frame is drawn, so a slow machine does not stretch it. */
    let stream = canvasEl.captureStream(0);
    let spur = stream.getVideoTracks()[0];
    // A browser without requestFrame would record nothing at all from a
    // stream at rate 0 - there the stream films at 30 fps by itself.
    if (!spur || typeof spur.requestFrame !== 'function') {
      stream = canvasEl.captureStream(30);
      spur = null;
    }
    const bildHolen = () => { if (spur) spur.requestFrame(); };
    const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9') ? 'video/webm;codecs=vp9' : 'video/webm';
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 6_000_000 });
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };

    const done = new Promise(res => { rec.onstop = res; });
    const gesamt = animDuration(editor);    // reads the tempo as well
    ensureFxHook(editor);
    const frameMs = 1000 / 30;
    const warteSichtbar = () => new Promise(res => {
      const weiter = () => { if (!document.hidden) { document.removeEventListener('visibilitychange', weiter); res(); } };
      document.addEventListener('visibilitychange', weiter);
      weiter();
    });
    rec.start();
    _fxOn = true;
    for (let n = 0; n * frameMs <= gesamt; n++) {
      if (document.hidden) {
        if (rec.state === 'recording') rec.pause();
        status('⏸ Video paused - bring this tab back to the front to go on.', '#854F0B');
        await warteSichtbar();
        if (rec.state === 'paused') rec.resume();
        status('🎬 Recording video…');
      }
      const t = n * frameMs;
      _fxTime = t;
      // The recorder stamps frames with the wall clock. Paused while a frame is
      // drawn, it only counts the 1/30 s the frame is shown - so a slow machine
      // gives the same video, it just takes longer to make.
      if (spur && rec.state === 'recording') rec.pause();
      editor.canvas.getObjects().forEach(o => applyAt(o, t));
      editor.canvas.renderAll();
      if (spur && rec.state === 'paused') rec.resume();
      bildHolen();
      await new Promise(r => setTimeout(r, frameMs));
    }
    // Hold the last frame for a moment, so the video does not end mid-move.
    for (let i = 0; i < 12; i++) { bildHolen(); await new Promise(r => setTimeout(r, frameMs)); }
    rec.stop();
    await done;
  } catch (e) {
    console.error('Video-Aufnahme:', e);
    status('❌ ' + (e.message || 'Video capture failed'), 'red');
    toast(e.message || 'Video capture failed', 'err');
    throw e;
  } finally {
    // Without the finally, an error left the canvas at full resolution and the
    // grid invisible - the editor was broken until the page was reloaded.
    _fxOn = false;
    resetAnim(editor);
    restoreFit(editor);
    if (editor.gridOn) editor.setGridVisible(true);
  }

  const blob = new Blob(chunks, { type: 'video/webm' });
  if (!blob.size) { status('❌ Video is empty', 'red'); toast('Video capture returned no data', 'err'); return false; }
  if (typeof onBlob === 'function') { onBlob(blob); status('Bereit.'); return true; }
  // No auto-download - save to "My outputs" only (with canvas_json, so it stays editable).
  status('💾 Saving video…');
  const erg = await saveAnimation(editor, blob, '.webm');
  if (!erg?.ok) return false;
  status('✅ Video saved!', 'green');
  return true;
}

// Make a video and download it straight to the computer (instead of "My outputs").
export async function downloadVideo(editor) {
  await exportVideo(editor, blob => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (document.getElementById('title-input')?.value.trim() || 'studio') + '.webm';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast('Video downloaded', 'ok');
  });
}

// ---- Export as GIF --------------------------------------------------------
// Uses gif.js (served locally, loaded lazily). Renders frames from the animation.
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

export async function exportGif(editor, onBlob) {
  if (!hasAnimations(editor)) { toast('No animations – nothing to export', 'err'); return false; }
  status('🎞 Creating GIF…');
  try {
    try {
      await loadGifLib();
    } catch (e) {
      // So a second attempt is possible once the problem is fixed - the failed
      // promise used to stay cached until the page was reloaded.
      _gifLibPromise = null;
      throw new Error('GIF library could not be loaded (vendor/gif.js)');
    }
    if (!window.GIF) { _gifLibPromise = null; throw new Error('GIF library incomplete'); }

    const total = animDuration(editor);
    const fps = 12, frameMs = 1000 / fps;
    // Keep GIFs small (Cloudinary/LinkedIn ~10 MB): 800 px longest edge and
    // somewhat stronger compression. Video (WebM) remains the better choice
    // for large or long clips.
    const scale = Math.min(1, 800 / Math.max(editor.width, editor.height));
    const gw = Math.round(editor.width * scale), gh = Math.round(editor.height * scale);
    const gif = new window.GIF({
      workers: 2, quality: 15,
      width: gw, height: gh,
      workerScript: VENDOR + 'gif.worker.js',
    });
    const _tmp = document.createElement('canvas'); _tmp.width = gw; _tmp.height = gh;
    const _tctx = _tmp.getContext('2d');

    editor.canvas.discardActiveObject();
    try {
      editor.setGridVisible(false);   // Raster nicht mit aufnehmen
      ensureFxHook(editor);
      toFullRes(editor);
      _fxOn = true;
      const gesamtFrames = Math.floor(total / frameMs) + 1;
      let n = 0;
      for (let t = 0; t <= total; t += frameMs) {
        _fxTime = t;
        editor.canvas.getObjects().forEach(o => applyAt(o, t));
        editor.canvas.renderAll();
        _tctx.clearRect(0, 0, gw, gh);
        _tctx.drawImage(editor.canvas.lowerCanvasEl, 0, 0, gw, gh);
        gif.addFrame(_tmp, { copy: true, delay: frameMs });
        n++;
        // Hand control back to the browser every 12 frames: otherwise the page
        // freezes completely for the whole frame loop - no repaint, no status
        // text - and to the user that looks like a crash.
        if (n % 12 === 0) {
          status(`🎞 Creating GIF… ${Math.round(n / gesamtFrames * 100)} %`);
          await new Promise(r => setTimeout(r, 0));
        }
      }
    } finally {
      // MUST run on failure too. Without it the canvas stayed at full
      // resolution, the elements in their half-animated positions and the
      // effect particles switched on for good - and a save afterwards wrote
      // exactly that broken state into the image.
      _fxOn = false;
      resetAnim(editor);
      restoreFit(editor);
      if (editor.gridOn) editor.setGridVisible(true);
    }

    // Wait for the FINISHED GIF. The Studio used to report "Saved." while the
    // encoding was still running - close the tab and everything was lost.
    status('🎞 Compressing GIF…');
    const blob = await new Promise((resolve, reject) => {
      const abbruch = setTimeout(() => reject(new Error('GIF generation is taking too long (worker file reachable?)')), 180000);
      gif.on('finished', b => { clearTimeout(abbruch); resolve(b); });
      gif.on('abort', () => { clearTimeout(abbruch); reject(new Error('GIF generation cancelled')); });
      gif.render();
    });

    if (typeof onBlob === 'function') { onBlob(blob); status('Bereit.'); return true; }
    // No auto-download - save to "My outputs" only.
    status('💾 Saving GIF…');
    const erg = await saveAnimation(editor, blob, '.gif');
    if (!erg?.ok) return false;
    status('✅ GIF saved!', 'green');
    return true;
  } catch (e) {
    console.error('GIF-Export:', e);
    status('❌ ' + (e.message || 'GIF error'), 'red');
    toast(e.message || 'GIF-Export fehlgeschlagen', 'err');
    throw e;   // der Aufrufer darf danach kein „Gespeichert." melden
  }
}

// Make a GIF and download it straight to the computer (instead of "My outputs").
export async function downloadGif(editor) {
  await exportGif(editor, blob => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (document.getElementById('title-input')?.value.trim() || 'studio') + '.gif';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast('GIF downloaded', 'ok');
  });
}
