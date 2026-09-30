// animbar.js - the bars that list what is on the artboard: the layer list
// (mode Layers) and the animation bar under the canvas, together with the
// hint layer that makes the invisible effect frames visible.
//
// Moved out of studio.js (review 27.09.2026). What the rows need from the
// Studio - the question web and spotlight actions - comes in through
// initAnimBar(); everything else they reach through the editor and media.js.
import * as media from './media.js';
import * as bg from './background.js';
import { modal, hexNorm } from './util.js';
import { fabric } from './editor.js';

let editor = null;
let S = {};     // netzVon, netzAktualisieren, netzEinstellen, frageDazu, frageZeichenFuer,
                // spotStarten, spotEinstellen, spotAlle

export function initAnimBar(ed, studio) {
  editor = ed;
  S = studio;
  editor.canvas.on('after:render', zeichneRahmenHinweise);
  // From the start, not only once a preview ran: the magnifier is always drawn.
  media.ensureFxHook(editor);
}

// Adding a magnifier, a question web or a spotlight opens the Effects group,
// so the new row is in sight.
export function oeffneEffekte() { _animOffen.effects = true; }

// Batched rebuilds of the layer list and the animation bar (see planeUiAufbau).
let _uiTimer = null, _uiZaehler = 0, _uiGeplant = 0, _ebenenGebaut = 0, _leisteGebaut = 0;
// About twenty actions still call renderLayers()/renderAnimBar() straight
// after their snapshot, which has already planned the same rebuild: each bar
// was built twice. A counter tells the planned rebuild whether a bar has been
// built since it was planned - then it is skipped.
export function planeUiAufbau() {
  _uiGeplant = ++_uiZaehler;
  if (_uiTimer) return;
  _uiTimer = requestAnimationFrame(() => {
    _uiTimer = null;
    try {
      if (_ebenenGebaut < _uiGeplant) renderLayers();
      if (_leisteGebaut < _uiGeplant) renderAnimBar();
    }
    catch (e) { console.error('[studio] UI-Aufbau:', e); }
  });
}

// ---- Ebenen-Liste ---------------------------------------------------------
export function layerLabel(o, i) {
  if (media.istSpot(o)) {
    const k = media.spotGruppeVon(editor, o);
    return '🔦 Spotlight' + (k.length > 1 ? ' ' + (k.indexOf(o) + 1) : '');
  }
  if (media.istEffektRahmen(o)) return (o.fx === 'magnifier' ? '🔍 Magnifier' : '✨ Effect frame');
  if (o.shapeKind === 'marker') return '📍 Marker';
  if (media.istFrageKnoten(o)) return '❓ ' + ((o.qwebText || 'Question').slice(0, 14));
  if (o.shapeKind === 'stamp')  return '🖈 Stamp';
  if (o.type === 'image')   return '🖼 Image ' + i;
  if (o.shapeKind === 'textblock') return '📝 ' + (o.tbHead || o.tbBody || 'Text block').slice(0, 14);
  if (o.type === 'textbox') return '✏️ ' + (o.text || 'Text').slice(0, 14);
  if (o.hexDeko)            return '⬡ Hexagon';
  if (o.svgPart)            return '📐 SVG part ' + o.svgPart;
  if (o.shapeKind)          return '🔷 Shape ' + i;
  return 'Element ' + i;
}
export function renderLayers() {
  _ebenenGebaut = ++_uiZaehler;
  const list = document.getElementById('layers-list');
  if (!list) return;
  const objs = editor.realObjects();
  if (!objs.length) { list.innerHTML = '<span class="no-templates">No elements yet.</span>'; return; }
  const active = editor.active();
  list.innerHTML = '';
  // Oben = vorderste Ebene → Reihenfolge umkehren.
  objs.slice().reverse().forEach((o, ri) => {
    const row = el('div', 'layer-row' + (o === active ? ' active' : ''));
    const name = el('span', 'layer-name', layerLabel(o, objs.length - ri));
    name.onclick = () => { editor.selectObj(o); };
    const schieben = (zeichen, titel, wohin) => {
      const b = knopf('layer-btn', zeichen, titel, e => { e.stopPropagation(); editor.moveObj(o, wohin); renderLayers(); });
      b.removeAttribute('type');
      return b;
    };
    row.append(name, schieben('⬆', 'Bring forward', 'up'), schieben('⬇', 'Send backward', 'down'));
    list.appendChild(row);
  });
}

/* ---- The bar under the canvas --------------------------------------------
   Two groups that fold away on their own: Motion, one row per element, and
   Effects, one row per effect frame. Mixed into one list, a frame looked like
   an element with half its controls missing.

   The effect frames themselves are invisible - that is the point of them, they
   must not end up in the picture. So the bar is also where one SEES them: the
   switch outlines every frame, pointing at a row lights up its frame, and
   Select puts the handles on it. All of that is drawn on a separate layer
   (zeichneRahmenHinweise), never on the canvas that gets exported. */
const _animOffen = { motion: true, effects: true };
let _rahmenZeigen = true;
// What the pointer rests on in the bar: one effect frame, or every member
// of a question web or spotlight. The hint layer lights these up.
let _hover = [];
function hoverZeile(row, liste) {
  row.onmouseenter = () => { _hover = liste; editor.canvas.requestRenderAll(); };
  row.onmouseleave = () => { if (_hover === liste) _hover = []; editor.canvas.requestRenderAll(); };
}

function animGruppe(schluessel, titel, zusatz, anzahl) {
  const d = document.createElement('details');
  d.className = 'anim-group';
  d.dataset.group = schluessel;
  d.open = _animOffen[schluessel] !== false;
  d.ontoggle = () => { _animOffen[schluessel] = d.open; };
  const s = document.createElement('summary');
  s.innerHTML = '<b>' + titel + '</b><small>' + zusatz + '</small>'
              + '<span class="anim-count">' + anzahl + '</span>';
  d.appendChild(s);
  return d;
}

/* Speed sliders run the same way everywhere: left slow, right fast. What is
   stored stays as it was (a duration, or a factor that stretches time), so
   saved drawings keep their pace - only the slider is turned round. */
function schnecke(wrap, inp) {
  const a = document.createElement('span'); a.className = 'speed-ico'; a.textContent = '🐢';
  const b = document.createElement('span'); b.className = 'speed-ico'; b.textContent = '🐇';
  wrap.appendChild(a); wrap.appendChild(inp); wrap.appendChild(b);
}

// A slider: every change of it is one undo step.
function schieber(cls, min, max, step, wert, titel) {
  const i = el('input', 'tl-slider' + (cls ? ' ' + cls : ''));
  i.type = 'range'; i.min = min; i.max = max; i.step = step; i.value = wert;
  if (titel) i.title = titel;
  i.onchange = () => editor.snapshot();
  return i;
}
// A labelled slot in a time row ("Speed", "Start", "Lens" ...).
function feld(titel) {
  const l = el('label', 'anim-time-item');
  l.innerHTML = '<span>' + titel + '</span>';
  return l;
}

const START_MAX = 10000;
const sekunden = ms => (Math.round(+ms / 100) / 10).toFixed(1) + ' s';
function startRegler(o) {
  const delWrap = feld('Start');
  // Up to 10 s: a video of 8-10 s has elements that start after 3 s (the old
  // end of this slider), and touching the slider pulled them back to 3 s.
  const del = schieber('', 0, Math.max(START_MAX, media.startOf(o)), 100, media.startOf(o), 'Start delay: when it begins');
  const wert = el('span', 'anim-start-wert', sekunden(media.startOf(o)));
  // One slider, both systems. It used to write only into o.anim.delay, so
  // with Motion = none it silently did nothing at all.
  del.oninput = () => { media.setStart(o, del.value); wert.textContent = sekunden(del.value); };
  delWrap.append(del, wert);
  return delWrap;
}

function zeitRegler(o, rahmen) {
  const timeRow = el('div', 'anim-ctl anim-time');
  const durWrap = feld('Speed');
  // fxTempo stretches the effect's time: 1 = as drawn, 6 = six times as slow.
  // anim.dur is how long the motion takes: more is slower.
  const dur = rahmen
    ? schieber('', 1, 6, 0.25, 7 - (o.fxTempo > 0 ? o.fxTempo : 1), 'Speed of this effect - left slow, right fast')
    : schieber('', 300, 4000, 100, 4300 - (o.anim?.dur || 1200), 'Speed - left slow, right fast');
  dur.oninput = () => {
    if (rahmen) { o.fxTempo = 7 - +dur.value; editor.canvas.requestRenderAll(); return; }
    if (o.anim) o.anim.dur = 4300 - +dur.value;
  };
  schnecke(durWrap, dur);
  timeRow.append(durWrap, startRegler(o));
  return timeRow;
}

/* The magnifier's own controls. Its frame is the WINDOW it travels in - that
   is dragged and sized on the picture. Here: which way it goes, how big the
   glass is, how much it enlarges, how fast it reads a line and how long it
   rests at the end of one so the enlarged words can be read. */
const lupenSekAus = v => 20 - (v - 1) * 2;            // slider 1..10 -> 20..2 s
const lupenReglerAus = sek => 1 + (20 - sek) / 2;
const LUPEN_EINHEIT = { lines: ' s/line', lr: ' s/sweep', pingpong: ' s/sweep', wander: ' s/round', still: '' };

function lupenRegler(o) {
  const teile = document.createDocumentFragment();
  const zeichnen = () => editor.canvas.requestRenderAll();
  const reihe = () => el('div', 'anim-ctl anim-time');
  const regler = schieber;

  const wegZeile = document.createElement('label'); wegZeile.className = 'anim-ctl';
  wegZeile.innerHTML = '<span>Path</span>';
  const weg = document.createElement('select'); weg.className = 'field fx-path';
  media.LUPEN_WEGE.forEach(k => {
    const op = document.createElement('option'); op.value = k; op.textContent = media.LUPEN_WEG_LABELS[k];
    if ((o.fxPath || 'still') === k) op.selected = true;
    weg.appendChild(op);
  });
  wegZeile.appendChild(weg);
  teile.appendChild(wegZeile);

  const r1 = reihe();
  const glasFeld = feld('Lens');
  const glas = regler('fx-lens', 30, Math.round(Math.min(editor.width, editor.height) * 0.6), 5,
                      Math.round(media.lupenRadius(o) * 2), 'Size of the glass - the frame is the window it travels in');
  glasFeld.appendChild(glas);
  const zoomFeld = feld('Zoom');
  const zoom = regler('fx-zoom', 1.2, 3, 0.1, o.fxZoom > 0 ? o.fxZoom : 1.9, 'How much the magnifier enlarges');
  zoomFeld.appendChild(zoom);
  r1.appendChild(glasFeld); r1.appendChild(zoomFeld);
  teile.appendChild(r1);

  const r2 = reihe();
  const tempoFeld = feld('Speed');
  const tempo = regler('fx-speed', 1, 10, 0.5, lupenReglerAus(media.lupenSekunden(o)),
                       'How fast it reads - left slow, right fast');
  schnecke(tempoFeld, tempo);
  const tempoAus = document.createElement('span'); tempoAus.className = 'fx-speed-out';
  tempoFeld.appendChild(tempoAus);
  const pauseFeld = feld('Pause');
  const pause = regler('fx-pause', 0, 4, 0.5, o.fxPause != null ? o.fxPause : 1.5,
                       'How long it rests at the end of a line, so the words can be read');
  const pauseAus = document.createElement('span'); pauseAus.className = 'fx-speed-out';
  pauseFeld.appendChild(pause); pauseFeld.appendChild(pauseAus);
  r2.appendChild(tempoFeld); r2.appendChild(pauseFeld);
  teile.appendChild(r2);

  const r3 = reihe();
  const runde = document.createElement('span'); runde.className = 'anim-time-item fx-round';
  r3.appendChild(startRegler(o)); r3.appendChild(runde);
  teile.appendChild(r3);

  const zeigen = () => {
    const w = o.fxPath || 'still', still = w === 'still';
    tempoAus.textContent = still ? '–' : media.lupenSekunden(o) + LUPEN_EINHEIT[w];
    pauseAus.textContent = (o.fxPause != null ? +o.fxPause : 1.5) + ' s';
    runde.textContent = still ? 'stays where it is' : 'one round: ' + Math.round(media.lupenWege(o).total) + ' s';
    tempo.disabled = pause.disabled = still;
  };
  weg.onchange = () => { o.fxPath = weg.value; zeigen(); zeichnen(); editor.snapshot(); };
  glas.oninput = () => {
    const d = +glas.value;
    o.fxLens = d;
    // The window is never smaller than its glass: it grows around its centre.
    const b = o.getBoundingRect(true);
    if (b.width < d || b.height < d) {
      const mitte = o.getCenterPoint();
      o.set({ width: Math.max(o.width, d / (o.scaleX || 1)), height: Math.max(o.height, d / (o.scaleY || 1)) });
      o.setPositionByOrigin(mitte, 'center', 'center');
      o.setCoords();
    }
    zeigen(); zeichnen();
  };
  zoom.oninput = () => { o.fxZoom = +zoom.value; zeichnen(); };
  tempo.oninput = () => { o.fxLineSec = lupenSekAus(+tempo.value); zeigen(); zeichnen(); };
  pause.oninput = () => { o.fxPause = +pause.value; zeigen(); zeichnen(); };
  zeigen();
  return teile;
}

function motionZeile(o, idx) {
  const row = document.createElement('div'); row.className = 'anim-row';
  row.dataset.objIdx = String(idx);

  const th = document.createElement('img'); th.className = 'anim-thumb';
  th.title = layerLabel(o, idx + 1) + ' – select';
  th.onclick = () => editor.selectObj(o);
  // Preview image from the cache. Without it, every element was rasterised to
  // a PNG again on EVERY click and every move - with 25 elements that meant
  // seconds of hang per mouse click.
  try {
    if (!o.__thumb) {
      const dim = Math.max(o.getScaledWidth?.() || o.width || 1, o.getScaledHeight?.() || o.height || 1);
      o.__thumb = o.toDataURL({ format: 'png', multiplier: Math.min(1, 64 / Math.max(dim, 1)) });
    }
    th.src = o.__thumb;
  } catch (e) { th.style.background = '#dfe3e6'; }

  const col = document.createElement('div'); col.className = 'anim-col';
  const selRow = document.createElement('label'); selRow.className = 'anim-ctl';
  selRow.innerHTML = '<span>Motion</span>';
  const sel = document.createElement('select'); sel.className = 'field';
  bewegungsListe(sel, o.anim?.type || 'none', media.canDraw(o));
  // From (Grow) and Then (every "come in" motion) - only where they apply.
  const extra = el('span', 'anim-extra');
  const extrasZeigen = () => {
    extra.innerHTML = '';
    const t = o.anim?.type;
    if (t === 'grow') {
      extra.append(extraWahl('From', 'anim-from', [['left', 'left'], ['right', 'right'], ['top', 'top'], ['bottom', 'bottom']],
                             o.anim.from || 'left', v => { o.anim.from = v; }));
    }
    if (t && media.ARRIVE_TYPES.has(t)) {
      extra.append(extraWahl('Then', 'anim-then', [['', '—'], ...media.THEN_TYPES.map(k => [k, k])],
                             o.anim.then || '', v => { if (v) o.anim.then = v; else delete o.anim.then; }));
    }
  };
  sel.onchange = () => {
    const t = sel.value;
    // From and Then are kept when the motion changes, so trying out another
    // motion does not lose them.
    const alt = o.anim || {};
    o.anim = (t && t !== 'none') ? { type: t, dur: alt.dur || 1200 } : null;
    if (o.anim && alt.from) o.anim.from = alt.from;
    if (o.anim && alt.then) o.anim.then = alt.then;
    media.setStart(o, media.startOf(o));   // eine Quelle fuer beide Systeme
    extrasZeigen();
    editor.snapshot();
  };
  selRow.appendChild(sel);
  selRow.appendChild(extra);
  extrasZeigen();
  const name = document.createElement('span');
  name.className = 'anim-name'; name.textContent = layerLabel(o, idx + 1);
  selRow.appendChild(name);

  col.appendChild(selRow);
  col.appendChild(zeitRegler(o, false));
  row.appendChild(th); row.appendChild(col);
  return row;
}

// All hexagons of the pattern share ONE row: a pattern of twelve would
// otherwise fill the Motion group with twelve identical rows. Motion, speed
// and start apply to all of them; "In turn" staggers their starts.
function musterZeile(hexe) {
  const e = hexe[0];
  const row = el('div', 'anim-row hex-row');
  const th = el('div', 'anim-thumb fx-thumb', '⬡');
  th.title = 'Select all hexagons';
  th.onclick = () => {
    editor.canvas.setActiveObject(new fabric.ActiveSelection(hexe, { canvas: editor.canvas }));
    editor.canvas.requestRenderAll();
  };
  const col = el('div', 'anim-col');
  const selRow = el('label', 'anim-ctl');
  selRow.innerHTML = '<span>Motion</span>';
  const sel = el('select', 'field hex-motion');
  bewegungsListe(sel, e.anim?.type || 'none', media.canDraw(e));
  const starts = () => {
    const basis = media.startOf(e), folge = e.hexFolge === 'reihe';
    hexe.forEach((o, i) => media.setStart(o, basis + (folge ? i * 250 : 0)));
  };
  sel.onchange = () => {
    const t = sel.value;
    hexe.forEach(o => { o.anim = (t && t !== 'none') ? { type: t, dur: e.anim?.dur || 1200 } : null; });
    starts();
    editor.snapshot();
  };
  selRow.append(sel, el('span', 'anim-name', '⬡ Hexagon pattern (' + hexe.length + ')'));
  col.appendChild(selRow);
  segmente(col, 'Together', 'hexFolge', 'qweb-seg hex-folge',
           [['zusammen', 'All at once'], ['reihe', 'In turn']],
           wert => (e.hexFolge || 'zusammen') === wert,
           wert => { hexe.forEach(o => { o.hexFolge = wert; }); starts(); editor.snapshot(); renderAnimBar(); });
  const zeit = el('div', 'anim-ctl anim-time');
  const durWrap = feld('Speed');
  const dur = schieber('', 300, 4000, 100, 4300 - (e.anim?.dur || 1200), 'Speed - left slow, right fast');
  dur.oninput = () => hexe.forEach(o => { if (o.anim) o.anim.dur = 4300 - +dur.value; });
  schnecke(durWrap, dur);
  const startWrap = feld('Start');
  const start = schieber('', 0, 3000, 100, media.startOf(e), 'When the pattern begins');
  start.oninput = () => { media.setStart(e, start.value); starts(); };
  startWrap.appendChild(start);
  zeit.append(durWrap, startWrap);
  col.appendChild(zeit);
  row.append(th, col);
  return row;
}

// The Motion list, grouped (Come in / Go out / Keep moving). "Draw on" is
// greyed out for an element without a line - unless it already has it.
function bewegungsListe(sel, aktuell, zeichenbar) {
  media.ANIM_GROUPS.forEach(([titel, typen]) => {
    const ziel = titel ? el('optgroup') : sel;
    if (titel) ziel.label = titel;
    typen.forEach(t => {
      const op = el('option', null, media.ANIM_LABELS[t] || t); op.value = t;
      if (t === 'drawOn' && !zeichenbar && aktuell !== 'drawOn') {
        op.disabled = true; op.title = 'Only for lines, arrows and outlines';
      }
      if (aktuell === t) op.selected = true;
      ziel.appendChild(op);
    });
    if (titel) sel.appendChild(ziel);
  });
}
// A small labelled drop-down next to the motion ("From", "Then").
function extraWahl(titel, cls, optionen, wert, setzen) {
  const l = el('label', 'anim-extra-item');
  l.append(el('span', null, titel));
  const s = el('select', 'field ' + cls);
  optionen.forEach(([v, text]) => { const op = el('option', null, text); op.value = v; if (v === wert) op.selected = true; s.appendChild(op); });
  s.onchange = () => { setzen(s.value); editor.snapshot(); };
  l.append(s);
  return l;
}

// ---- Building blocks shared by the effect rows ------------------------------
// The frame, question web and spotlight rows used to build the same parts by
// hand, each a little differently. These make the same markup in one place.
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function knopf(cls, text, titel, klick) {
  const b = el('button', cls, text);
  b.type = 'button';
  if (titel) b.title = titel;
  if (klick) b.onclick = klick;
  return b;
}
// Both bars again, straight away (the snapshot has planned them too; the
// counters in planeUiAufbau skip that second build).
function neuAufbauen() { renderAnimBar(); renderLayers(); }

// Row with its symbol on the left and the column for the controls. Pointing at
// the row lights up `leuchten` on the picture.
function effektRumpf(klasse, symbol, symbolTitel, waehlen, leuchten, an) {
  const row = el('div', 'anim-row fx-row' + (klasse ? ' ' + klasse : '') + (an ? ' on' : ''));
  hoverZeile(row, leuchten);
  const th = el('div', 'anim-thumb fx-thumb', symbol);
  th.title = symbolTitel;
  th.onclick = waehlen;
  const col = el('div', 'anim-col');
  row.append(th, col);
  return { row, col };
}
// ⌖ Select and ✕ Remove on the right of a row.
function werkzeuge(row, waehlenTitel, waehlen, entfernenTitel, entfernen) {
  const tools = el('div', 'fx-tools');
  tools.append(knopf('fx-select', '⌖ Select', waehlenTitel, waehlen),
               knopf('fx-remove', '✕ Remove', entfernenTitel, () => {
                 entfernen();
                 editor.canvas.requestRenderAll();
                 editor.snapshot();
                 neuAufbauen();
               }));
  row.appendChild(tools);
}
function titelZeile(col, name) {
  const kopf = el('div', 'anim-ctl');
  kopf.innerHTML = '<span>Effect</span><b class="qweb-titel">' + name + '</b>';
  col.appendChild(kopf);
}
// A choice of a few, as a row of buttons. optionen: [wert, text, an?]
function segmente(col, titel, schluessel, klasse, optionen, istAn, klick) {
  const z = el('div', 'anim-ctl');
  z.innerHTML = '<span>' + titel + '</span>';
  const seg = el('span', klasse);
  seg.dataset.key = schluessel;
  optionen.forEach(([wert, text, an]) => {
    const b = knopf('', text, null, () => klick(wert));
    b.dataset.v = String(wert);
    if (an != null ? an : istAn(wert)) b.classList.add('on');
    seg.appendChild(b);
  });
  z.appendChild(seg);
  col.appendChild(z);
  return z;
}
// A slider with its read-out; each change is one undo step.
function reglerZeile(col, klasse, titel, min, max, schritt, wert, text, setzen) {
  const z = el('label', 'anim-ctl spot-regler');
  z.innerHTML = '<span>' + titel + '</span>';
  const inp = el('input', 'tl-slider');
  inp.type = 'range'; inp.min = min; inp.max = max; inp.step = schritt; inp.value = wert;
  const aus = el('span', 'fx-speed-out', text(+inp.value));
  inp.oninput = () => { setzen(+inp.value); aus.textContent = text(+inp.value); editor.canvas.requestRenderAll(); };
  inp.onchange = () => editor.snapshot();
  if (klasse) inp.classList.add(klasse);
  z.append(inp, aus);
  col.appendChild(z);
  return inp;
}

function effektZeile(o, idx) {
  const lupe = o.fx === 'magnifier';
  const { row, col } = effektRumpf('', lupe ? '🔍' : '✨', 'Select this frame', () => editor.selectObj(o),
                                   [o], o === editor.active());
  row.dataset.objIdx = String(idx);

  const fxRow = el('label', 'anim-ctl');
  fxRow.innerHTML = '<span>Effect</span>';
  const fxsel = el('select', 'field');
  media.EFFECTS.filter(t => t !== 'none').forEach(t => {
    const op = el('option', null, media.EFFECT_LABELS[t] || t); op.value = t;
    if (o.fx === t) op.selected = true;
    fxsel.appendChild(op);
  });
  fxsel.onchange = () => {
    o.fx = fxsel.value;
    // Turned into a magnifier: it needs a glass and a way.
    if (o.fx === 'magnifier' && !o.fxPath) {
      Object.assign(o, media.LUPEN_STANDARD);
      if (!(o.fxLens > 0)) o.fxLens = media.lupenGlasStandard(editor);
    }
    media.setStart(o, media.startOf(o));
    editor.canvas.requestRenderAll();
    editor.snapshot();
    neuAufbauen();
  };
  fxRow.appendChild(fxsel);
  if (!lupe) {
    // Its colour, as a dot. The palette itself sits once, above the list.
    const punkt = el('span', 'fx-dot');
    punkt.style.background = o.fxColor || '#61CEBC';
    punkt.title = o.fxColor ? 'Colour ' + o.fxColor : 'Colour: as drawn';
    fxRow.appendChild(punkt);
  }
  col.appendChild(fxRow);
  // No Area buttons: the frame is dragged and sized on the picture itself.
  col.appendChild(lupe ? lupenRegler(o) : zeitRegler(o, true));
  werkzeuge(row, 'Put the handles on this frame, so it can be dragged', () => editor.selectObj(o),
            null, () => { _hover = _hover.filter(x => x !== o); editor.canvas.remove(o); });
  return row;
}

// One palette for all frames: it paints the selected one - or the first, if
// none is selected. Six swatches in every row would be six palettes doing one job.
function frageZeile(knoten) {
  const e = knoten[0];
  const { row, col } = effektRumpf('qweb-row', '❓', 'Select the first question mark', () => editor.selectObj(e),
                                   knoten, knoten.includes(editor.active()));
  row.dataset.qweb = e.qwebId || 'q';
  titelZeile(col, 'Question web');

  knoten.forEach((o, i) => {
    const z = el('div', 'anim-ctl qweb-text');
    const punkt = el('span', 'qweb-dot', S.frageZeichenFuer(o, i));
    punkt.style.background = o.qwebColor || '#F56E28';
    punkt.title = 'Select this question mark'; punkt.onclick = () => editor.selectObj(o);
    const inp = el('input', 'field'); inp.type = 'text';
    inp.value = o.qwebText || ''; inp.placeholder = 'Text (optional)';
    inp.oninput = () => { o.qwebText = inp.value; editor.canvas.requestRenderAll(); };
    inp.onchange = () => { editor.snapshot(); renderLayers(); };
    const weg = knopf('qweb-weg', '✕', 'Remove this question', () => {
      editor.canvas.remove(o);
      S.netzAktualisieren(knoten.filter(k => k !== o));
      editor.snapshot(); neuAufbauen();
    });
    weg.disabled = knoten.length < 2;
    z.append(punkt, inp, weg);
    col.appendChild(z);
  });
  col.appendChild(knopf('qweb-dazu', '+ Question', null, () => S.frageDazu(knoten)));

  const wahl = (titel, schluessel, optionen) => segmente(col, titel, schluessel, 'qweb-seg', optionen,
    wert => (e[schluessel] || media.FRAGE_STANDARD[schluessel]) === wert,
    wert => S.netzEinstellen(knoten, schluessel, wert));
  wahl('Threads', 'qwebThreads', [['web', 'Web'], ['chain', 'Chain'], ['none', 'None']]);
  wahl('Blink', 'qwebBlink', [['turn', 'One after another'], ['all', 'All together']]);
  wahl('Text', 'qwebLabel', [['blink', 'When it blinks'], ['always', 'Always'], ['off', 'Off']]);
  wahl('Sign', 'qwebSign', [['?', '?'], ['!', '!'], ['#', '1 2 3']]);

  const zeit = el('div', 'anim-ctl anim-time');
  const tempoFeld = feld('Speed');
  const tempo = schieber('qweb-speed', 1, 10, 0.5, e.qwebSpeed > 0 ? e.qwebSpeed : media.FRAGE_STANDARD.qwebSpeed,
                         'How fast the questions take turns - left slow, right fast');
  tempo.oninput = () => { knoten.forEach(o => { o.qwebSpeed = +tempo.value; }); editor.canvas.requestRenderAll(); };
  schnecke(tempoFeld, tempo);
  zeit.append(tempoFeld, startRegler(e));
  col.appendChild(zeit);

  werkzeuge(row, 'Put the handles on the first question mark', () => editor.selectObj(e),
            'Remove the whole question web', () => knoten.forEach(o => editor.canvas.remove(o)));
  return row;
}

function effektPalette(rahmenListe, netzListe = [], spotListe = []) {
  const row = document.createElement('div'); row.className = 'anim-row fx-palette';
  const th = document.createElement('div'); th.className = 'anim-thumb fx-thumb'; th.textContent = '🎨';
  const col = document.createElement('div'); col.className = 'anim-col';
  const zeile = document.createElement('div'); zeile.className = 'anim-ctl';
  zeile.innerHTML = '<span>Colour</span>';
  const aktiv = editor.active();
  // A spotlight takes the colour for its frame - all of its frames at once.
  let spotZiel = media.istSpot(aktiv) ? media.spotGruppeVon(editor, aktiv) : null;
  let netzZiel = !spotZiel && media.istFrageKnoten(aktiv) ? S.netzVon(aktiv) : null;
  // The magnifier shows what lies under it and has no colour of its own.
  const farbRahmen = r => media.istEffektRahmen(r) && r.fx !== 'magnifier';
  let ziel = (netzZiel || spotZiel) ? null : (farbRahmen(aktiv) ? aktiv : rahmenListe.find(farbRahmen));
  if (!ziel && !netzZiel && !spotZiel && netzListe.length) netzZiel = netzListe[0];
  if (!ziel && !netzZiel && !spotZiel && spotListe.length) spotZiel = spotListe[0];
  const farbeSetzen = f => {
    if (spotZiel) { S.spotEinstellen(spotZiel, 'fxColor', f || null); return; }
    if (netzZiel) { S.netzEinstellen(netzZiel, 'qwebColor', f || media.FRAGE_STANDARD.qwebColor); return; }
    if (!ziel) return;
    ziel.fxColor = f; editor.canvas.requestRenderAll(); editor.snapshot(); renderAnimBar();
  };
  const sw = document.createElement('span'); sw.className = 'fx-swatches';
  const standard = document.createElement('button');
  standard.type = 'button'; standard.className = 'fx-swatch fx-swatch-auto'; standard.textContent = 'auto';
  standard.title = 'As the effect is drawn';
  if ((ziel && !ziel.fxColor) || (spotZiel && !spotZiel[0].fxColor) || (netzZiel && hexNorm(netzZiel[0].qwebColor || '') === hexNorm(media.FRAGE_STANDARD.qwebColor))) standard.classList.add('on');
  standard.onclick = () => farbeSetzen(null);
  sw.appendChild(standard);
  bg.getPalette().forEach(f => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'fx-swatch'; b.style.background = f; b.title = f;
    const jetzt = spotZiel ? spotZiel[0].fxColor : netzZiel ? netzZiel[0].qwebColor : (ziel && ziel.fxColor);
    if (jetzt && hexNorm(jetzt) === hexNorm(f)) b.classList.add('on');
    b.onclick = () => farbeSetzen(f);
    sw.appendChild(b);
  });
  zeile.appendChild(sw);
  const hinweis = document.createElement('span'); hinweis.className = 'anim-name';
  hinweis.textContent = spotZiel ? (media.istSpot(aktiv) ? 'paints the selected spotlight' : 'paints the spotlight')
    : netzZiel ? (media.istFrageKnoten(aktiv) ? 'paints the selected question web' : 'paints the question web')
    : !ziel ? 'no frame with a colour'
    : (ziel === aktiv ? 'paints the selected frame' : 'paints the first frame - select another to change it');
  zeile.appendChild(hinweis);
  col.appendChild(zeile);
  row.appendChild(th); row.appendChild(col);
  return row;
}

export function renderAnimBar() {
  _leisteGebaut = ++_uiZaehler;
  const bar = document.getElementById('anim-bar');
  if (!bar) return;
  const objs = editor.realObjects();
  if (!objs.length) { bar.innerHTML = '<span class="hint">Add elements to animate them.</span>'; return; }
  bar.innerHTML = '';
  const head = document.createElement('div'); head.className = 'anim-bar-head';
  const title = document.createElement('span');
  title.className = 'anim-bar-title'; title.textContent = '🎬 Animation';

  // Tempo - stretches every Speed and every Start at once, so a piece can be
  // slowed down without dragging every element's slider again.
  const tempoWrap = document.createElement('label');
  tempoWrap.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:.75rem;color:#555;margin-left:auto';
  tempoWrap.appendChild(document.createTextNode('Tempo'));
  const tempoInp = document.createElement('input');
  tempoInp.type = 'range'; tempoInp.id = 'anim-tempo';
  // A speed on a doubling scale: 0 = as set, -2 twice as slow, +2 twice as fast.
  tempoInp.min = -5; tempoInp.max = 2; tempoInp.step = 0.5;
  tempoInp.value = window._animTempo != null ? window._animTempo : 0;
  tempoInp.style.cssText = 'width:104px';
  tempoInp.title = 'Speeds up or slows down everything together - left slow, right fast.';
  const tempoOut = document.createElement('span');
  tempoOut.style.cssText = 'min-width:32px;text-align:right;font-variant-numeric:tabular-nums';
  const showTempo = () => {
    tempoOut.textContent = (Math.round(Math.pow(2, +tempoInp.value / 2) * 10) / 10) + '×';
  };
  showTempo();
  tempoInp.oninput = () => { window._animTempo = tempoInp.value; showTempo(); };
  schnecke(tempoWrap, tempoInp); tempoWrap.appendChild(tempoOut);

  // Video length - applies to the whole GIF/video, not per element.
  const lenWrap = document.createElement('label');
  lenWrap.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:.75rem;color:#555;margin-left:14px';
  lenWrap.appendChild(document.createTextNode('🎬 Video length'));
  const lenInp = document.createElement('input');
  lenInp.type = 'number'; lenInp.id = 'video-length'; lenInp.min = 0; lenInp.max = 15; lenInp.step = 0.5;
  lenInp.placeholder = 'auto';
  lenInp.style.cssText = 'width:58px;padding:3px;border:1px solid #ccc;border-radius:4px';
  lenInp.title = 'Total length of GIF/video in seconds. Empty = automatic.';
  if (window._videoLen != null) lenInp.value = window._videoLen;
  lenInp.oninput = () => { window._videoLen = lenInp.value; };
  lenWrap.appendChild(lenInp);
  lenWrap.appendChild(document.createTextNode('s'));

  const prevTop = document.createElement('button');
  prevTop.className = 'tbtn primary'; prevTop.textContent = '▶ Preview';
  prevTop.style.marginLeft = '10px';
  prevTop.onclick = () => media.previewAnimation(editor);
  head.appendChild(title); head.appendChild(tempoWrap); head.appendChild(lenWrap);
  head.appendChild(prevTop);
  bar.appendChild(head);

  const elemente = [], rahmen = [], hexe = [];
  objs.forEach((o, idx) => {
    if (media.istFrageKnoten(o)) return;          // a question web has a row of its own
    if (media.istSpot(o)) return;                 // so has a spotlight
    if (o.hexDeko) { hexe.push(o); return; }      // and the hexagon pattern one for all
    (media.istEffektRahmen(o) ? rahmen : elemente).push([o, idx]);
  });
  const netze = [...media.fragenNetze(editor).values()];
  const spots = [...media.spotGruppen(editor).values()];

  const gm = animGruppe('motion', 'Motion', 'what each element does',
                        elemente.length + (elemente.length === 1 ? ' element' : ' elements')
                        + (hexe.length ? ' · hexagon pattern' : ''));
  if (hexe.length) gm.appendChild(musterZeile(hexe));
  if (!elemente.length && !hexe.length) {
    const h = document.createElement('span'); h.className = 'hint'; h.textContent = 'No elements yet.';
    gm.appendChild(h);
  }
  elemente.forEach(([o, idx]) => gm.appendChild(motionZeile(o, idx)));
  const ge = animGruppe('effects', 'Effects', 'each one lives in a frame',
                        [rahmen.length || (!netze.length && !spots.length) ? rahmen.length + (rahmen.length === 1 ? ' frame' : ' frames') : '',
                         netze.length ? netze.length + (netze.length === 1 ? ' question web' : ' question webs') : '',
                         spots.length ? spots.length + (spots.length === 1 ? ' spotlight' : ' spotlights') : '']
                          .filter(Boolean).join(' · '));
  // The switch sits in the group's head, but must not fold the group when clicked.
  const schalter = document.createElement('label'); schalter.className = 'fx-show';
  schalter.innerHTML = '<input type="checkbox" id="fx-show-frames"> Show frames on the picture';
  const kasten = schalter.querySelector('input');
  kasten.checked = _rahmenZeigen;
  schalter.onclick = e => e.stopPropagation();
  kasten.onchange = () => { _rahmenZeigen = kasten.checked; editor.canvas.requestRenderAll(); };
  ge.querySelector('summary').appendChild(schalter);
  if (!rahmen.length && !netze.length && !spots.length) {
    const h = document.createElement('span'); h.className = 'hint';
    h.textContent = 'No effect yet - add one in the ✨ Effects tab.';
    ge.appendChild(h);
  } else {
    ge.appendChild(effektPalette(rahmen.map(([o]) => o), netze, spots));
    rahmen.forEach(([o, idx]) => ge.appendChild(effektZeile(o, idx)));
    netze.forEach(k => ge.appendChild(frageZeile(k)));
    spots.forEach(k => ge.appendChild(spotZeile(k)));
  }
  // Effects first: that is what the picture is built from; Motion comes after.
  bar.appendChild(ge);
  bar.appendChild(gm);
}

/* ---- Seeing the invisible frames -----------------------------------------
   A layer of its own, laid over the artboard: pointer-events off, and not part
   of Fabric at all. That is what keeps the outlines out of every export - PNG,
   GIF and video all read Fabric's canvas, and this is not it. */
let _rahmenEbene = null;
function rahmenEbene() {
  const wrap = editor.canvas.wrapperEl;
  if (_rahmenEbene && _rahmenEbene.parentNode === wrap) return _rahmenEbene;
  _rahmenEbene = document.createElement('canvas');
  _rahmenEbene.id = 'fx-frame-layer';
  _rahmenEbene.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;z-index:4';
  wrap.appendChild(_rahmenEbene);
  return _rahmenEbene;
}

// The little teal name tag at the corner of a lit-up frame.
function namensSchild(ctx, name, x, y, zoom) {
  ctx.font = `700 ${12 / zoom}px Roboto, Arial, sans-serif`;
  ctx.textBaseline = 'top'; ctx.textAlign = 'left';
  const w = ctx.measureText(name).width + 12 / zoom;
  ctx.fillStyle = '#008591'; ctx.fillRect(x, y, w, 18 / zoom);
  ctx.fillStyle = '#ffffff'; ctx.fillText(name, x + 6 / zoom, y + 3 / zoom);
}

function zeichneRahmenHinweise() {
  if (!editor.canvas.wrapperEl) return;
  const unten = editor.canvas.lowerCanvasEl;
  const ebene = rahmenEbene();
  if (ebene.width !== unten.width) ebene.width = unten.width;
  if (ebene.height !== unten.height) ebene.height = unten.height;
  ebene.style.width = unten.style.width; ebene.style.height = unten.style.height;
  const ctx = ebene.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, ebene.width, ebene.height);
  // A preview shows the picture as it will be posted - no helper lines in it.
  if (media.effectsRunning()) return;
  // Removed from the bar while the pointer rested on its row: forget it.
  if (_hover.some(o => !o.canvas)) _hover = [];
  const rahmen = editor.canvas.getObjects().filter(media.istEffektRahmen);
  if (!rahmen.length && !_hover.length) return;
  const retina = editor.canvas.getRetinaScaling ? editor.canvas.getRetinaScaling() : 1;
  const vp = editor.canvas.viewportTransform;
  const zoom = editor.canvas.getZoom() || 1;
  ctx.setTransform(vp[0] * retina, vp[1] * retina, vp[2] * retina, vp[3] * retina,
                   vp[4] * retina, vp[5] * retina);
  const aktiv = editor.active();
  rahmen.forEach(o => {
    const hell = _hover.includes(o);
    if (!hell && !_rahmenZeigen) return;
    if (o === aktiv && !hell) return;          // the handles already show it
    const b = o.getBoundingRect(true);
    ctx.save();
    if (hell) { ctx.fillStyle = 'rgba(0,133,145,0.12)'; ctx.fillRect(b.left, b.top, b.width, b.height); }
    ctx.setLineDash([7 / zoom, 5 / zoom]);
    ctx.strokeStyle = hell ? '#008591' : 'rgba(0,133,145,0.55)';
    ctx.lineWidth = (hell ? 2 : 1.5) / zoom;
    ctx.strokeRect(b.left, b.top, b.width, b.height);
    ctx.setLineDash([]);
    if (hell) namensSchild(ctx, media.EFFECT_LABELS[o.fx] || o.fx, b.left, Math.max(0, b.top), zoom);
    ctx.restore();
  });
  // The question marks of a web light up like a frame does.
  _hover.filter(media.istFrageKnoten).forEach((o, i) => {
    const b = o.getBoundingRect(true);
    ctx.save();
    ctx.fillStyle = 'rgba(0,133,145,0.12)'; ctx.fillRect(b.left, b.top, b.width, b.height);
    ctx.setLineDash([7 / zoom, 5 / zoom]); ctx.strokeStyle = '#008591'; ctx.lineWidth = 2 / zoom;
    ctx.strokeRect(b.left, b.top, b.width, b.height);
    ctx.setLineDash([]);
    if (!i) namensSchild(ctx, '❓ Question web', b.left, Math.max(0, b.top - 20 / zoom), zoom);
    ctx.restore();
  });
  // A spotlight's heading band: above the line nothing steps back.
  if (media.istSpot(aktiv)) {
    const e = media.spotGruppeVon(editor, aktiv)[0];
    if (media.spotWert(e, 'spotKopf') !== false) {
      const y = media.spotKopfHoehe(editor, e);
      ctx.save();
      ctx.setLineDash([4 / zoom, 6 / zoom]); ctx.strokeStyle = 'rgba(0,133,145,0.75)'; ctx.lineWidth = 1.2 / zoom;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(editor.width, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = `600 ${11 / zoom}px Roboto, Arial, sans-serif`; ctx.textBaseline = 'bottom'; ctx.textAlign = 'left';
      ctx.fillStyle = 'rgba(0,133,145,0.9)'; ctx.fillText('heading stays clear', 8 / zoom, y - 3 / zoom);
      ctx.restore();
    }
  }
  // The magnifier's way, dotted orange: where the glass will travel.
  rahmen.forEach(o => {
    if (o.fx !== 'magnifier' || (o.fxPath || 'still') === 'still') return;
    if (!_rahmenZeigen && o !== aktiv && !_hover.includes(o)) return;
    const wege = media.lupenWege(o);
    ctx.save();
    ctx.setLineDash([2 / zoom, 5 / zoom]);
    ctx.strokeStyle = 'rgba(245,110,40,0.85)'; ctx.lineWidth = 2 / zoom;
    ctx.beginPath();
    for (let i = 0; i <= 240; i++) {
      const [x, y] = media.lupenStelle(o, wege.total * i / 240, wege);
      if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
  });
}

function spotZeile(k) {
  const e = k[0], film = k.length > 1;
  const aktiv = editor.active();
  const { row, col } = effektRumpf('spot-row', '🔦', 'Select the spotlight frame', () => editor.selectObj(e),
                                   k, k.includes(aktiv));
  row.dataset.spot = e.spotId || 's';
  titelZeile(col, 'Spotlight');

  const wahl = (titel, schluessel, optionen, bei) => {
    const jetzt = schluessel ? media.spotWert(e, schluessel) : null;
    return segmente(col, titel, schluessel, 'qweb-seg spot-seg', optionen, wert => jetzt === wert,
                    wert => (bei ? bei(wert) : S.spotEinstellen(k, schluessel, wert)));
  };
  const regler = (klasse, titel, min, max, schritt, wert, text, setzen) =>
    reglerZeile(col, klasse, titel, min, max, schritt, wert, text, setzen);

  wahl('Spots', null, [['eins', 'Just one', !film], ['reihe', 'One after another', film]], async wert => {
    if (wert === 'reihe') { if (!film) S.spotStarten(k); return; }
    if (!film) return;
    const bleibt = k.includes(aktiv) ? aktiv : e;
    const ja = await modal('Just one spot?', 'Keep only one spot and remove the other ' + (k.length - 1) + '?', [
      { label: 'Keep one', value: true },
      { label: 'Cancel', value: false },
    ]);
    if (!ja) return;
    k.forEach(o => { if (o !== bleibt) editor.canvas.remove(o); });
    bleibt.spotNr = 0;
    editor.canvas.setActiveObject(bleibt);
    editor.canvas.requestRenderAll(); editor.snapshot(); neuAufbauen();
  });
  // Always in view: with one spot, choosing an order takes every element of
  // the picture into the film.
  wahl('Order', 'spotReihe', [['klick', 'As clicked'], ['links', 'Around ↺'], ['rechts', 'Around ↻'], ['zeilen', 'Top to bottom']], wert => {
    if (!film && wert !== 'klick') { k.forEach(o => { o.spotReihe = wert; }); S.spotAlle(k); return; }
    S.spotEinstellen(k, 'spotReihe', wert);
  });

  if (film) {
    k.forEach((o, i) => {
      const z = el('div', 'anim-ctl qweb-text spot-eintrag');
      const punkt = el('span', 'qweb-dot', String(i + 1));
      punkt.style.background = e.fxColor || '#008591';
      punkt.title = 'Select this spot'; punkt.onclick = () => editor.selectObj(o);
      const name = el('span', 'spot-name', 'Spot ' + (i + 1));
      const sek = el('select', 'field spot-sek');
      for (let v = 1; v <= 8; v += 0.5) {
        const op = el('option', null, v.toFixed(1) + ' s'); op.value = v;
        if (Math.abs(v - media.spotSekunden(o)) < 0.01) op.selected = true;
        sek.appendChild(op);
      }
      sek.title = 'How long this one stays forward';
      sek.onchange = () => { o.spotSek = +sek.value; editor.snapshot(); renderAnimBar(); };
      const schieben = (d, zeichen, titel) => {
        const b = knopf('qweb-weg', zeichen, titel, () => {
          const neu = k.slice(); [neu[i], neu[i + d]] = [neu[i + d], neu[i]];
          neu.forEach((x, j) => { x.spotNr = j; x.spotReihe = 'klick'; });
          editor.canvas.requestRenderAll(); editor.snapshot(); renderAnimBar();
        });
        b.disabled = (i + d < 0 || i + d >= k.length);
        return b;
      };
      const weg = knopf('qweb-weg', '✕', 'Remove this spot', () => {
        editor.canvas.remove(o);
        k.filter(x => x !== o).forEach((x, j) => { x.spotNr = j; });
        editor.canvas.requestRenderAll(); editor.snapshot(); neuAufbauen();
      });
      z.append(punkt, name, sek, schieben(-1, '↑', 'Earlier'), schieben(1, '↓', 'Later'), weg);
      col.appendChild(z);
    });
  }
  const knoepfe = el('div', 'spot-knoepfe');
  knoepfe.append(knopf('qweb-dazu spot-dazu', '+ Spot', 'Click the next element in the picture', () => S.spotStarten(k)),
                 knopf('qweb-dazu spot-alle', '✚ All elements', 'Every element the Studio finds in the picture, one after another',
                       () => S.spotAlle(k)));
  col.appendChild(knoepfe);

  if (!film) wahl('Motion', 'spotBewegung', [['fest', 'Still'], ['bewegt', 'Moving']]);
  wahl('Style', 'spotStil', [['karte', 'Pop out'], ['ring', 'Ring only']]);
  wahl('Frame', 'spotRahmen', [[true, 'With frame'], [false, 'Without']]);
  wahl('Where', 'spotWo', [['platz', 'Where it is'], ['mitte', 'To the middle']]);
  wahl('The rest', 'spotRest', [['weich', 'Softer'], ['dunkel', 'Darker'], ['blur', 'Blurred'], ['aus', 'Unchanged']]);
  regler('spot-staerke', 'How much', 10, 70, 5, Math.round(media.spotWert(e, 'spotStaerke') * 100), v => v + ' %',
         v => k.forEach(o => { o.spotStaerke = v / 100; }));
  wahl('Heading', 'spotKopf', [[true, 'Stays clear'], [false, 'Steps back too']]);
  if (media.spotWert(e, 'spotKopf') !== false) {
    regler('spot-kopf', 'Top band', 5, 50, 1, Math.round(media.spotKopfHoehe(editor, e) / editor.height * 100), v => v + ' %',
           v => k.forEach(o => { o.spotKopfH = Math.round(editor.height * v / 100); }));
  }
  regler('spot-zoom', 'Zoom', 1.2, 2.5, 0.1, +media.spotWert(e, 'spotZoom'), v => v.toFixed(1) + '×',
         v => k.forEach(o => { o.spotZoom = v; }));
  if (film) {
    regler('spot-pause', 'Pause', 0, 2, 0.1, +media.spotWert(e, 'spotPause'), v => v.toFixed(1) + ' s',
           v => k.forEach(o => { o.spotPause = v; }));
    wahl('At the end', 'spotEnde', [['alle', 'Whole picture'], ['loop', 'Start again']]);
    const runde = media.spotRundeMs(k) / 1000;
    const info = el('div', 'anim-ctl');
    info.innerHTML = '<span></span><span class="fx-round spot-runde">One round: ' + runde.toFixed(1) + ' s'
      + (runde > 15 ? ' - GIF and video stop at 15 s: shorten the times' : '') + '</span>';
    col.appendChild(info);
  }
  if (!media.spotStill(k)) {
    const zeit = el('div', 'anim-ctl anim-time');
    zeit.appendChild(startRegler(e));
    col.appendChild(zeit);
  }

  werkzeuge(row, 'Put the handles on the (first) spotlight frame', () => editor.selectObj(k.includes(aktiv) ? aktiv : e),
            'Remove the whole spotlight', () => k.forEach(o => editor.canvas.remove(o)));
  return row;
}
