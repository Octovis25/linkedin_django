/* Tutorials: how-to films from screenshots, a moving cursor, a frame and a voice.

   Everything visual happens on one 1920 x 1080 canvas. The same drawing
   function serves three purposes: the editor (a step's end state), the live
   preview (real time, with the voice) and the export (frame by frame through
   WebCodecs, voice through AudioEncoder, packed by the Studio's webm-muxer).
   The server only stores files. */

const W = 1920, H = 1080;
const FPS = 30;
const VIDEO_CODEC = 'vp09.00.10.08';
const AUDIO_RATE = 48000;
const MUXER_URL = '/static/media_library/studio/vendor/webm-muxer.esm.js';

// Timing inside one step (ms)
const VOICE_AT = 400;        // the voice starts
const VOICE_TAIL = 700;      // silence after the voice
const MOVE_FROM = 200;       // the cursor starts to move
const CLICK_AT = 1100;       // ... arrives and clicks
const RIPPLE_MS = 600;
const FRAME_FADE = 300;
const IMAGE_FADE = 300;
const MIN_WITH_CLICK = 2400;

const COLORS = {
  bg: '#E9EEF0', orange: '#EB6E08', caption: 'rgba(11,61,68,0.92)', hint: '#6B7876',
};

const root = document.getElementById('tu-root');
const filmId = Number(root?.dataset.film || 0);

const state = {
  film: null, steps: [], sel: 0, mode: 'click',
  images: new Map(),      // url -> HTMLImageElement (loaded)
  voices: new Map(),      // url -> AudioBuffer (for preview / waveform)
  playing: null,          // running preview
  busy: false,
};

const $ = id => document.getElementById(id);
const stage = $('tu-stage');
const ctx = stage ? stage.getContext('2d') : null;

// ── Server ──────────────────────────────────────────────────────────────────
function csrf() {
  const m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}
async function postJson(url, data) {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
    body: JSON.stringify(data),
  });
  let j = null;
  try { j = await r.json(); } catch (_) { j = { ok: false, error: 'HTTP ' + r.status }; }
  if (!j.ok) throw new Error(j.error || 'HTTP ' + r.status);
  return j;
}
async function postForm(url, form) {
  const r = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: form });
  let j = null;
  try { j = await r.json(); } catch (_) { j = { ok: false, error: 'HTTP ' + r.status }; }
  if (!j.ok) throw new Error(j.error || 'HTTP ' + r.status);
  return j;
}
async function upload(kind, blob, name) {
  const f = new FormData();
  f.append('film_id', filmId);
  f.append('kind', kind);
  f.append('file', blob, name);
  return postForm('/tutorials/api/upload/', f);
}
function say(text, bad = false) {
  const el = $('tu-status');
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('bad', !!bad);
}

// ── Loading ─────────────────────────────────────────────────────────────────
function loadImage(url) {
  if (!url) return Promise.resolve(null);
  if (state.images.has(url)) return Promise.resolve(state.images.get(url));
  return new Promise(resolve => {
    const img = new Image();
    img.onload = () => { state.images.set(url, img); resolve(img); };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}
async function loadAllImages() {
  await Promise.all(state.steps.map(s => loadImage(s.image_url)));
}
let _audioCtx = null;
function audioCtx() {
  if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return _audioCtx;
}
async function loadVoice(url) {
  if (!url) return null;
  if (state.voices.has(url)) return state.voices.get(url);
  const buf = await fetch(url).then(r => r.arrayBuffer());
  const audio = await audioCtx().decodeAudioData(buf);
  state.voices.set(url, audio);
  return audio;
}

// ── Timeline ────────────────────────────────────────────────────────────────
function hasClick(s) { return s.click_x != null && s.click_y != null; }
function stepLength(s) {
  let ms = Math.max(1000, s.min_ms || 3000);
  if (s.audio_ms) ms = Math.max(ms, VOICE_AT + s.audio_ms + VOICE_TAIL);
  if (hasClick(s)) ms = Math.max(ms, MIN_WITH_CLICK);
  return ms;
}
function timeline(steps = state.steps) {
  let t = 0;
  const parts = steps.map(s => { const p = { start: t, dur: stepLength(s) }; t += p.dur; return p; });
  return { parts, total: t };
}
function fmt(ms) {
  const s = Math.round(ms / 1000);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

// ── Drawing ─────────────────────────────────────────────────────────────────
// Where a screenshot sits on the canvas: whole, centred, never cropped.
function fit(img) {
  if (!img) return { x: 0, y: 0, w: W, h: H };
  const k = Math.min(W / img.naturalWidth, H / img.naturalHeight);
  const w = img.naturalWidth * k, h = img.naturalHeight * k;
  return { x: (W - w) / 2, y: (H - h) / 2, w, h };
}
function imgOf(s) { return s && s.image_url ? state.images.get(s.image_url) || null : null; }
function pointOf(s) {
  if (!s || !hasClick(s)) return null;
  const r = fit(imgOf(s));
  return { x: r.x + s.click_x * r.w, y: r.y + s.click_y * r.h };
}
function frameOf(s) {
  if (!s || s.highlight !== 'frame' || s.frame_w == null || s.frame_h == null) return null;
  const r = fit(imgOf(s));
  return { x: r.x + s.frame_x * r.w, y: r.y + s.frame_y * r.h, w: s.frame_w * r.w, h: s.frame_h * r.h };
}
// Where the cursor comes from: the last click before this step.
function cursorBefore(i) {
  for (let k = i - 1; k >= 0; k--) {
    const p = pointOf(state.steps[k]);
    if (p) return p;
  }
  return null;
}
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function roundRect(c, x, y, w, h, r) {
  c.beginPath();
  c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r);
  c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r);
  c.arcTo(x, y, x + w, y, r);
  c.closePath();
}
function drawCursor(c, x, y) {
  c.save();
  c.translate(x, y);
  c.scale(2.4, 2.4);
  c.shadowColor = 'rgba(0,0,0,0.35)'; c.shadowBlur = 3; c.shadowOffsetY = 1;
  c.beginPath();
  c.moveTo(0, 0); c.lineTo(0, 17); c.lineTo(4.2, 13); c.lineTo(7, 19.5);
  c.lineTo(9.6, 18.4); c.lineTo(6.9, 12.2); c.lineTo(12.3, 12.2); c.closePath();
  c.fillStyle = '#fff'; c.fill();
  c.shadowColor = 'transparent';
  c.lineWidth = 1.3; c.strokeStyle = '#161616'; c.lineJoin = 'round'; c.stroke();
  c.restore();
}
function drawCaption(c, text, alpha) {
  if (!text) return;
  c.save();
  c.globalAlpha = alpha;
  c.font = '500 40px Roboto, "Segoe UI", Arial, sans-serif';
  const maxW = W - 240;
  let line = text;
  while (c.measureText(line).width > maxW && line.length > 4) line = line.slice(0, -2);
  if (line !== text) line = line.trimEnd() + '…';
  const tw = c.measureText(line).width;
  const bw = tw + 72, bh = 76;
  const x = (W - bw) / 2, y = H - bh - 54;
  roundRect(c, x, y, bw, bh, 14);
  c.fillStyle = COLORS.caption; c.fill();
  c.fillStyle = '#fff'; c.textBaseline = 'middle'; c.textAlign = 'center';
  c.fillText(line, W / 2, y + bh / 2 + 1);
  c.restore();
}
function drawImage(c, img, alpha = 1) {
  if (!img) return;
  const r = fit(img);
  c.save(); c.globalAlpha = alpha;
  c.drawImage(img, r.x, r.y, r.w, r.h);
  c.restore();
}

// One moment of the film. local = ms inside step i.
function drawStep(c, i, local, { editor = false, caption = true } = {}) {
  const s = state.steps[i];
  c.fillStyle = COLORS.bg; c.fillRect(0, 0, W, H);
  if (!s) return;
  const img = imgOf(s);
  const prev = i > 0 ? state.steps[i - 1] : null;
  const prevImg = imgOf(prev);
  if (prevImg && prevImg !== img && local < IMAGE_FADE && !editor) {
    drawImage(c, prevImg);
    drawImage(c, img, local / IMAGE_FADE);
  } else {
    drawImage(c, img);
  }
  if (!img && editor) {
    c.fillStyle = COLORS.hint; c.font = '36px Roboto, Arial, sans-serif'; c.textAlign = 'center';
    c.fillText('No screenshot yet – paste one (Ctrl+V) or upload it on the right', W / 2, H / 2);
  }

  // Frame around what matters
  const fr = frameOf(s);
  if (fr) {
    const a = editor ? 1 : clamp((local - CLICK_AT) / FRAME_FADE);
    if (a > 0) {
      c.save(); c.globalAlpha = a;
      roundRect(c, fr.x - 6, fr.y - 6, fr.w + 12, fr.h + 12, 12);
      c.lineWidth = 6; c.strokeStyle = COLORS.orange;
      c.shadowColor = 'rgba(235,110,8,0.45)'; c.shadowBlur = 18;
      c.stroke(); c.restore();
    }
  }

  // Cursor and click
  const to = pointOf(s);
  const from = cursorBefore(i) || (to ? { x: W * 0.5, y: H * 0.62 } : null);
  if (to) {
    const k = editor ? 1 : ease(clamp((local - MOVE_FROM) / (CLICK_AT - MOVE_FROM)));
    const x = from.x + (to.x - from.x) * k, y = from.y + (to.y - from.y) * k;
    const rp = (local - CLICK_AT) / RIPPLE_MS;
    if (!editor && rp >= 0 && rp <= 1) {
      c.save();
      c.globalAlpha = 1 - rp;
      c.beginPath(); c.arc(to.x, to.y, 14 + 56 * rp, 0, Math.PI * 2);
      c.lineWidth = 6; c.strokeStyle = COLORS.orange; c.stroke();
      c.restore();
    }
    if (editor) {
      c.save();
      c.beginPath(); c.arc(to.x, to.y, 22, 0, Math.PI * 2);
      c.lineWidth = 4; c.strokeStyle = COLORS.orange; c.setLineDash([8, 6]); c.stroke();
      c.restore();
    }
    drawCursor(c, x, y);
  } else if (from && cursorBefore(i)) {
    drawCursor(c, from.x, from.y);
  }

  if (caption) drawCaption(c, s.caption, editor ? 1 : clamp(local / 250));
}

// The whole film at time t (ms).
function drawAt(c, t, tl) {
  const { parts } = tl;
  let i = parts.findIndex(p => t < p.start + p.dur);
  if (i < 0) i = parts.length - 1;
  drawStep(c, i, t - parts[i].start);
}

// ── Editor view ─────────────────────────────────────────────────────────────
let dragStart = null, dragNow = null;

function render() {
  if (!ctx) return;
  if (state.playing) return;
  drawStep(ctx, state.sel, 1e9, { editor: true });
  if (dragStart && dragNow) {
    const x = Math.min(dragStart.x, dragNow.x), y = Math.min(dragStart.y, dragNow.y);
    ctx.save();
    ctx.setLineDash([12, 8]); ctx.lineWidth = 4; ctx.strokeStyle = COLORS.orange;
    ctx.strokeRect(x, y, Math.abs(dragNow.x - dragStart.x), Math.abs(dragNow.y - dragStart.y));
    ctx.restore();
  }
}
function canvasPoint(e) {
  const r = stage.getBoundingClientRect();
  return { x: (e.clientX - r.left) / r.width * W, y: (e.clientY - r.top) / r.height * H };
}
function toImage(p, s) {
  const r = fit(imgOf(s));
  return { x: clamp((p.x - r.x) / r.w), y: clamp((p.y - r.y) / r.h) };
}

function renderSteps() {
  const box = $('tu-steps');
  if (!box) return;
  const tl = timeline();
  box.innerHTML = '';
  state.steps.forEach((s, i) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'tu-step' + (i === state.sel ? ' on' : '');
    const th = document.createElement('canvas');
    th.width = 192; th.height = 108;
    const c = th.getContext('2d');
    c.scale(0.1, 0.1);
    drawStep(c, i, 1e9, { editor: true, caption: false });
    el.appendChild(th);
    const lab = document.createElement('span');
    lab.className = 'tu-step-lab';
    lab.textContent = (i + 1) + ' · ' + (s.caption || 'Step');
    const d = document.createElement('span');
    d.className = 'tu-step-dur';
    d.textContent = fmt(tl.parts[i].dur) + (s.audio_url ? ' 🎙' : '');
    el.append(lab, d);
    el.onclick = () => select(i);
    box.appendChild(el);
  });
  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'tu-step add';
  add.innerHTML = '＋ Step<small>upload or paste (Ctrl+V)</small>';
  add.onclick = () => $('tu-add-file').click();
  box.appendChild(add);
  $('tu-total').textContent = state.steps.length ? fmt(tl.total) : '0:00';
}

function renderPanel() {
  const s = state.steps[state.sel];
  const panel = $('tu-panel');
  if (!panel) return;
  panel.classList.toggle('empty', !s);
  if (!s) return;
  $('tu-step-no').textContent = 'Step ' + (state.sel + 1);
  $('tu-caption').value = s.caption || '';
  $('tu-script').value = s.script || '';
  $('tu-highlight').value = s.highlight || 'frame';
  $('tu-min').value = Math.round((s.min_ms || 3000) / 100) / 10;
  $('tu-click-info').textContent = hasClick(s) ? 'set – click elsewhere to move it' : 'not set – click on the screenshot';
  $('tu-frame-info').textContent = frameOf(s) || (s.frame_w != null) ? 'drawn' : 'not drawn yet';
  document.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('on', b.dataset.mode === state.mode));
  $('tu-voice-len').textContent = s.audio_ms ? fmt(s.audio_ms) + ' recorded' : 'no recording yet';
  $('tu-voice-play').disabled = !s.audio_url;
  $('tu-up').disabled = state.sel === 0;
  $('tu-down').disabled = state.sel >= state.steps.length - 1;
  drawWave(s);
}

async function drawWave(s) {
  const cv = $('tu-wave');
  if (!cv) return;
  const c = cv.getContext('2d');
  c.clearRect(0, 0, cv.width, cv.height);
  if (!s.audio_url) return;
  let buf = null;
  try { buf = await loadVoice(s.audio_url); } catch (_) { return; }
  if (state.steps[state.sel] !== s || !buf) return;
  const data = buf.getChannelData(0);
  const n = cv.width, step = Math.max(1, Math.floor(data.length / n));
  c.fillStyle = '#20B8B0';
  for (let x = 0; x < n; x++) {
    let peak = 0;
    for (let k = x * step; k < (x + 1) * step && k < data.length; k++) peak = Math.max(peak, Math.abs(data[k]));
    const h = Math.max(1, peak * cv.height);
    c.fillRect(x, (cv.height - h) / 2, 1, h);
  }
}

function select(i) {
  state.sel = clamp(i, 0, Math.max(0, state.steps.length - 1));
  render(); renderSteps(); renderPanel();
}
function refreshAll() { render(); renderSteps(); renderPanel(); }

// ── Saving steps ────────────────────────────────────────────────────────────
const pending = new Map();
function saveStep(s, fields, wait = 0) {
  Object.assign(s, fields);
  const key = s.id;
  const old = pending.get(key);
  if (old) { clearTimeout(old.timer); Object.assign(fields, old.fields, fields); }
  const run = async () => {
    pending.delete(key);
    try {
      await postJson('/tutorials/api/step/', { action: 'update', id: s.id, ...fields });
      say('Saved.');
    } catch (e) { say('Not saved: ' + e.message, true); }
  };
  if (wait) pending.set(key, { fields, timer: setTimeout(run, wait) });
  else run();
}

async function addSteps(files) {
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue;
    say('Uploading screenshot…');
    try {
      const up = await upload('image', f, f.name || 'screenshot.png');
      const j = await postJson('/tutorials/api/step/', { action: 'create', film_id: filmId, image_nc_path: up.nc_path });
      state.steps = j.steps;
      await loadAllImages();
      state.sel = state.steps.findIndex(s => s.id === j.id);
      say('Step added. Now click on the screenshot where the click goes.');
    } catch (e) { say('Upload failed: ' + e.message, true); }
  }
  refreshAll();
}

// ── Voice ───────────────────────────────────────────────────────────────────
let recorder = null, recTimer = null;
async function toggleRecord() {
  const s = state.steps[state.sel];
  const btn = $('tu-rec');
  if (recorder) { recorder.stop(); return; }
  if (!s) return;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { say('No microphone: ' + e.message, true); return; }
  const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
    .find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || '';
  recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks = [];
  const t0 = Date.now();
  recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = async () => {
    clearInterval(recTimer);
    stream.getTracks().forEach(t => t.stop());
    recorder = null;
    btn.textContent = '🎙 Record'; btn.classList.remove('rec');
    const blob = new Blob(chunks, { type: (type || 'audio/webm').split(';')[0] });
    say('Saving the recording…');
    try {
      let ms = Date.now() - t0;
      try {
        const buf = await audioCtx().decodeAudioData(await blob.arrayBuffer());
        ms = Math.round(buf.duration * 1000);
      } catch (_) { /* keep the measured time */ }
      const up = await upload('audio', blob, 'step' + s.id + '.webm');
      state.voices.delete(up.url);
      saveStep(s, { audio_nc_path: up.nc_path, audio_ms: ms });
      s.audio_url = up.url;
      refreshAll();
    } catch (e) { say('Recording not saved: ' + e.message, true); }
  };
  recorder.start();
  btn.textContent = '■ Stop'; btn.classList.add('rec');
  recTimer = setInterval(() => { $('tu-voice-len').textContent = '● ' + fmt(Date.now() - t0); }, 250);
  say('Recording… speak the text, then press Stop.');
}
async function playVoice() {
  const s = state.steps[state.sel];
  if (!s || !s.audio_url) return;
  const buf = await loadVoice(s.audio_url);
  const ac = audioCtx(); await ac.resume();
  const src = ac.createBufferSource(); src.buffer = buf; src.connect(ac.destination); src.start();
}

// ── Preview ─────────────────────────────────────────────────────────────────
async function preview() {
  if (state.playing) { stopPreview(); return; }
  if (!state.steps.length) return;
  say('Loading…');
  await loadAllImages();
  const tl = timeline();
  const ac = audioCtx(); await ac.resume();
  const sources = [];
  const t0 = ac.currentTime + 0.15;
  for (let i = 0; i < state.steps.length; i++) {
    const s = state.steps[i];
    if (!s.audio_url) continue;
    try {
      const buf = await loadVoice(s.audio_url);
      const src = ac.createBufferSource(); src.buffer = buf; src.connect(ac.destination);
      src.start(t0 + (tl.parts[i].start + VOICE_AT) / 1000);
      sources.push(src);
    } catch (_) { /* a missing recording only means silence */ }
  }
  const run = { sources, raf: 0 };
  state.playing = run;
  $('tu-preview').textContent = '■ Stop';
  say('Preview…');
  const frame = () => {
    if (state.playing !== run) return;
    const t = (ac.currentTime - t0) * 1000;
    if (t >= tl.total) { stopPreview(); return; }
    drawAt(ctx, Math.max(0, t), tl);
    run.raf = requestAnimationFrame(frame);
  };
  frame();
}
function stopPreview() {
  const run = state.playing;
  if (!run) return;
  cancelAnimationFrame(run.raf);
  run.sources.forEach(s => { try { s.stop(); } catch (_) {} });
  state.playing = null;
  $('tu-preview').textContent = '▶ Preview';
  say('');
  render();
}

// ── Export ──────────────────────────────────────────────────────────────────
async function voiceTrack(tl) {
  const withVoice = state.steps.map((s, i) => [s, i]).filter(([s]) => s.audio_url);
  if (!withVoice.length) return null;
  const length = Math.ceil(tl.total / 1000 * AUDIO_RATE);
  const off = new OfflineAudioContext(1, length, AUDIO_RATE);
  for (const [s, i] of withVoice) {
    const raw = await fetch(s.audio_url).then(r => r.arrayBuffer());
    const buf = await off.decodeAudioData(raw);
    const src = off.createBufferSource();
    src.buffer = buf; src.connect(off.destination);
    src.start((tl.parts[i].start + VOICE_AT) / 1000);
  }
  return off.startRendering();
}

async function encodeVoice(buffer) {
  const chunks = [];
  let fehler = null;
  const enc = new AudioEncoder({
    output: (chunk, meta) => chunks.push({ chunk, meta }),
    error: e => { fehler = e; },
  });
  enc.configure({ codec: 'opus', sampleRate: AUDIO_RATE, numberOfChannels: 1, bitrate: 96000 });
  const data = buffer.getChannelData(0);
  const block = 4800;
  for (let off = 0; off < data.length; off += block) {
    const n = Math.min(block, data.length - off);
    const ad = new AudioData({
      format: 'f32-planar', sampleRate: AUDIO_RATE, numberOfFrames: n, numberOfChannels: 1,
      timestamp: Math.round(off / AUDIO_RATE * 1e6), data: data.slice(off, off + n),
    });
    enc.encode(ad);
    ad.close();
  }
  await enc.flush();
  enc.close();
  if (fehler) throw fehler;
  return chunks;
}

async function exportVideo() {
  if (state.busy || !state.steps.length) return;
  if (typeof VideoEncoder === 'undefined') { say('This browser cannot create videos. Please use Chrome or Edge.', true); return; }
  stopPreview();
  state.busy = true;
  const btn = $('tu-save');
  btn.disabled = true;
  try {
    say('Preparing…');
    await loadAllImages();
    const tl = timeline();
    const ok = await VideoEncoder.isConfigSupported({ codec: VIDEO_CODEC, width: W, height: H, bitrate: 2_500_000, framerate: FPS });
    if (!ok.supported) throw new Error('VP9 video is not supported in this browser');

    say('Preparing the voice…');
    const voice = await voiceTrack(tl);
    if (voice && typeof AudioEncoder === 'undefined') throw new Error('This browser cannot encode the voice');
    const audioChunks = voice ? await encodeVoice(voice) : [];

    const { Muxer, ArrayBufferTarget } = await import(MUXER_URL);
    const muxer = new Muxer({
      target: new ArrayBufferTarget(),
      video: { codec: 'V_VP9', width: W, height: H, frameRate: FPS },
      ...(audioChunks.length ? { audio: { codec: 'A_OPUS', numberOfChannels: 1, sampleRate: AUDIO_RATE } } : {}),
    });
    // Voice and picture go into the file in time order.
    let a = 0;
    const audioUpTo = ts => {
      while (a < audioChunks.length && audioChunks[a].chunk.timestamp <= ts) {
        muxer.addAudioChunk(audioChunks[a].chunk, audioChunks[a].meta); a++;
      }
    };
    let fehler = null;
    const enc = new VideoEncoder({
      output: (chunk, meta) => { audioUpTo(chunk.timestamp); muxer.addVideoChunk(chunk, meta); },
      error: e => { fehler = e; },
    });
    enc.configure({ codec: VIDEO_CODEC, width: W, height: H, bitrate: 2_500_000, framerate: FPS });

    const bild = document.createElement('canvas'); bild.width = W; bild.height = H;
    const bctx = bild.getContext('2d');
    const frameMs = 1000 / FPS, frameUs = 1e6 / FPS;
    const count = Math.ceil(tl.total / frameMs);
    for (let n = 0; n < count; n++) {
      if (fehler) throw fehler;
      drawAt(bctx, n * frameMs, tl);
      const f = new VideoFrame(bild, { timestamp: Math.round(n * frameUs), duration: Math.round(frameUs) });
      enc.encode(f, { keyFrame: n % (FPS * 2) === 0 });
      f.close();
      if (enc.encodeQueueSize > 6 || n % 15 === 14) {
        say(`🎬 Creating video… ${Math.round((n + 1) / count * 100)} %`);
        await new Promise(r => setTimeout(r, 0));
        while (enc.encodeQueueSize > 6) await new Promise(r => setTimeout(r, 5));
      }
    }
    await enc.flush();
    enc.close();
    if (fehler) throw fehler;
    audioUpTo(Infinity);
    muxer.finalize();
    const blob = new Blob([muxer.target.buffer], { type: 'video/webm' });

    say(`Uploading the video (${(blob.size / 1048576).toFixed(1)} MB)…`);
    const f = new FormData();
    f.append('film_id', filmId);
    f.append('seconds', (tl.total / 1000).toFixed(1));
    f.append('video', blob, 'tutorial.webm');
    const j = await postForm('/tutorials/api/video/', f);
    state.film = j.film;
    renderFilm();
    say('Video saved (' + fmt(tl.total) + ').');
  } catch (e) {
    console.error(e);
    say('Video not created: ' + e.message, true);
  } finally {
    state.busy = false;
    btn.disabled = false;
  }
}

function renderFilm() {
  const f = state.film;
  if (!f) return;
  const box = $('tu-video');
  if (!box) return;
  $('tu-status-sel').value = f.status;
  if (f.video_url) {
    box.innerHTML = '';
    const v = document.createElement('video');
    v.src = f.video_url; v.controls = true; v.preload = 'metadata';
    const dl = document.createElement('a');
    dl.href = f.video_url; dl.download = (f.title || 'tutorial').replace(/[^A-Za-z0-9]+/g, '_') + '.webm';
    dl.className = 'tu-btn full'; dl.textContent = '⬇ Download for the portal';
    const info = document.createElement('div');
    info.className = 'tu-hint';
    info.textContent = 'Saved ' + (f.updated_at || '') + (f.video_seconds ? ' · ' + fmt(f.video_seconds * 1000) : '');
    box.append(v, dl, info);
  } else {
    box.innerHTML = '<div class="tu-hint">No video yet – “Save video” creates it.</div>';
  }
}

// ── Wiring ──────────────────────────────────────────────────────────────────
async function start() {
  if (!filmId || !stage) return;
  try {
    const r = await fetch(`/tutorials/api/film/${filmId}/`).then(r => r.json());
    state.film = r.film;
    state.steps = r.steps;
  } catch (e) { say('Film could not be loaded: ' + e.message, true); return; }
  await loadAllImages();
  renderFilm();
  refreshAll();

  // Film fields
  const filmField = (id, key, wait) => {
    const el = $(id);
    if (!el) return;
    let timer = null;
    const go = async () => {
      try { const j = await postJson('/tutorials/api/film/', { action: 'update', id: filmId, [key]: el.value }); state.film = j.film; say('Saved.'); }
      catch (e) { say('Not saved: ' + e.message, true); }
    };
    el.addEventListener(wait ? 'input' : 'change', () => { clearTimeout(timer); timer = setTimeout(go, wait || 0); });
  };
  filmField('tu-title', 'title', 700);
  filmField('tu-page', 'page', 700);
  filmField('tu-lang', 'lang');
  filmField('tu-status-sel', 'status');

  // Step fields
  const cur = () => state.steps[state.sel];
  $('tu-caption').addEventListener('input', e => { saveStep(cur(), { caption: e.target.value }, 600); render(); renderStepsLater(); });
  $('tu-script').addEventListener('input', e => saveStep(cur(), { script: e.target.value }, 800));
  $('tu-highlight').addEventListener('change', e => { saveStep(cur(), { highlight: e.target.value }); refreshAll(); });
  $('tu-min').addEventListener('change', e => {
    const ms = Math.round(clamp(parseFloat(e.target.value) || 3, 1, 600) * 1000);
    saveStep(cur(), { min_ms: ms }); refreshAll();
  });
  $('tu-click-clear').onclick = () => { saveStep(cur(), { click_x: null, click_y: null }); refreshAll(); };
  $('tu-frame-clear').onclick = () => { saveStep(cur(), { frame_x: null, frame_y: null, frame_w: null, frame_h: null }); refreshAll(); };
  document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { state.mode = b.dataset.mode; renderPanel(); });

  // Moving and deleting
  const move = async dir => {
    const s = cur(); if (!s) return;
    const j = await postJson('/tutorials/api/step/', { action: 'move', id: s.id, dir });
    state.steps = j.steps; state.sel = state.steps.findIndex(x => x.id === s.id); refreshAll();
  };
  $('tu-up').onclick = () => move(-1);
  $('tu-down').onclick = () => move(1);
  $('tu-del').onclick = async () => {
    const s = cur(); if (!s) return;
    if (!confirm(`Remove step ${state.sel + 1} from the film? The screenshot and the recording stay in Nextcloud.`)) return;
    const j = await postJson('/tutorials/api/step/', { action: 'delete', id: s.id });
    state.steps = j.steps; select(state.sel);
  };

  // Screenshots
  $('tu-add-file').addEventListener('change', e => { addSteps([...e.target.files]); e.target.value = ''; });
  $('tu-replace-file').addEventListener('change', async e => {
    const file = e.target.files[0]; e.target.value = '';
    const s = cur(); if (!file || !s) return;
    try {
      say('Uploading screenshot…');
      const up = await upload('image', file, file.name || 'screenshot.png');
      saveStep(s, { image_nc_path: up.nc_path });
      s.image_url = up.url;
      await loadImage(up.url);
      refreshAll();
    } catch (err) { say('Upload failed: ' + err.message, true); }
  });
  $('tu-replace').onclick = () => $('tu-replace-file').click();
  document.addEventListener('paste', e => {
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
    const files = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
    if (files.length) { e.preventDefault(); addSteps(files); }
  });

  // Click point and frame on the stage
  stage.addEventListener('pointerdown', e => {
    const s = cur(); if (!s || state.playing || !imgOf(s)) return;
    const p = canvasPoint(e);
    if (state.mode === 'frame') { dragStart = p; dragNow = p; stage.setPointerCapture(e.pointerId); return; }
    const q = toImage(p, s);
    saveStep(s, { click_x: q.x, click_y: q.y });
    refreshAll();
  });
  stage.addEventListener('pointermove', e => { if (dragStart) { dragNow = canvasPoint(e); render(); } });
  stage.addEventListener('pointerup', () => {
    const s = cur();
    if (!dragStart || !s) { dragStart = null; return; }
    const a = toImage(dragStart, s), b = toImage(dragNow, s);
    dragStart = dragNow = null;
    const w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);
    if (w > 0.005 && h > 0.005) {
      saveStep(s, { frame_x: Math.min(a.x, b.x), frame_y: Math.min(a.y, b.y), frame_w: w, frame_h: h, highlight: 'frame' });
    }
    refreshAll();
  });

  $('tu-rec').onclick = toggleRecord;
  $('tu-voice-play').onclick = playVoice;
  $('tu-preview').onclick = preview;
  $('tu-save').onclick = exportVideo;
  document.addEventListener('keydown', e => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT')) return;
    if (e.key === 'ArrowRight') select(state.sel + 1);
    if (e.key === 'ArrowLeft') select(state.sel - 1);
  });
}
let _stepsTimer = null;
function renderStepsLater() { clearTimeout(_stepsTimer); _stepsTimer = setTimeout(renderSteps, 400); }

// New film (works without a selected film too)
const newBtn = document.getElementById('tu-new');
if (newBtn) newBtn.onclick = async () => {
  const input = document.getElementById('tu-new-title');
  const title = (input.value || '').trim();
  if (!title) { input.focus(); return; }
  try {
    const j = await postJson('/tutorials/api/film/', { action: 'create', portal: root.dataset.portal, title });
    location.href = `/tutorials/?portal=${encodeURIComponent(root.dataset.portal)}&film=${j.id}`;
  } catch (e) { alert('Not created: ' + e.message); }
};

// For checks from outside (tests, Claude in Chrome)
window._tutorials = { state, timeline, drawAt, exportVideo, select };

start();
