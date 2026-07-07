// editor.js – Fabric-Canvas: Objekte, Multi-Select, Snapping, Ausrichten,
// Undo/Redo, Tastatursteuerung. Der stabile Kern des neuen Studios.
import { loadImage, toast } from './util.js';
import { proxyUrl } from './config.js';

export const fabric = window.fabric;
if (!fabric) console.error('Fabric.js nicht geladen!');

// Eigenschaften, die in den Snapshot/das Canvas-JSON serialisiert werden.
const EXTRA_PROPS = ['srcUrl', 'originalUrl', 'bgRemoved', 'anim', 'shapeKind'];

export class Editor {
  constructor(canvasEl) {
    this.canvas = new fabric.Canvas(canvasEl, {
      backgroundColor: '#1a1a2e',
      preserveObjectStacking: true,
      selection: true,          // Rubber-band Multi-Select
      controlsAboveOverlay: true,
    });
    this.width = canvasEl.width;
    this.height = canvasEl.height;

    // Undo/Redo-Historie
    this._history = [];
    this._redo = [];
    this._locked = false;       // verhindert History-Aufzeichnung beim Restore
    this._maxHistory = 60;

    this._snapLines = [];       // aktive Snapping-Hilfslinien
    this.snapTol = 8;           // Pixel-Toleranz fürs Einrasten

    this._bindEvents();
    this._enableSnapping();
    this._enableKeyboard();

    // Schöneres Auswahl-Styling (Octotrial-Orange)
    fabric.Object.prototype.set({
      borderColor: '#F56E28',
      cornerColor: '#F56E28',
      cornerStyle: 'circle',
      cornerSize: 10,
      transparentCorners: false,
      borderScaleFactor: 1.5,
      padding: 2,
    });

    this.snapshot();            // Ausgangszustand
  }

  // ---- Auf festen Rahmen einpassen (echtes Fabric-Zoom, kein Overflow) -----
  // Skaliert die Anzeige so, dass das GANZE Bild in maxW×maxH passt. Der Canvas
  // bleibt intern full-res (z.B. 1080²), nur die dargestellte Größe schrumpft –
  // inkl. Fabric-Container, daher keine Scrollbalken mehr.
  fitTo(maxW, maxH) {
    const scale = Math.min(maxW / this.width, maxH / this.height, 1);
    this.canvas.setZoom(scale);
    this.canvas.setDimensions({
      width:  Math.round(this.width  * scale),
      height: Math.round(this.height * scale),
    });
    this.canvas.requestRenderAll();
  }

  setSize(w, h) {
    this.width = w; this.height = h;
    // interne Auflösung zurücksetzen, Zoom neutralisieren …
    this.canvas.setZoom(1);
    this.canvas.setDimensions({ width: w, height: h });
    this.snapshot();
    // … dann wieder in den zuletzt bekannten Rahmen einpassen
    if (this._lastFit) this.fitTo(this._lastFit.w, this._lastFit.h);
    this.canvas.requestRenderAll();
  }

  // ---- Objekte hinzufügen --------------------------------------------------
  async addImageUrl(url, opts = {}) {
    const imgEl = await loadImage(url);
    const img = new fabric.Image(imgEl, {
      srcUrl: url, originalUrl: opts.originalUrl || url,
      crossOrigin: 'anonymous',
    });
    // Auf sinnvolle Größe skalieren
    const maxSize = Math.min(this.width, this.height) * 0.5;
    if (img.width > maxSize) img.scaleToWidth(maxSize);
    img.set({
      left: opts.x != null ? opts.x : this.width / 2,
      top:  opts.y != null ? opts.y : this.height / 2,
      originX: 'center', originY: 'center',
    });
    this.canvas.add(img);
    this.canvas.setActiveObject(img);
    this.canvas.requestRenderAll();
    this.snapshot();
    return img;
  }

  addText(text, opts = {}) {
    const t = new fabric.Textbox(text || 'Text', {
      left: this.width / 2, top: this.height / 2,
      originX: 'center', originY: 'center',
      width: this.width * 0.6,
      fontSize: opts.fontSize || 32,
      fontWeight: opts.fontWeight || 'bold',
      fontFamily: 'Roboto, Arial, sans-serif',
      fill: opts.color || '#ffffff',
      textAlign: 'center',
      shadow: 'rgba(0,0,0,0.6) 0 0 4px',
      editable: true,
    });
    this.canvas.add(t);
    this.canvas.setActiveObject(t);
    this.canvas.requestRenderAll();
    this.snapshot();
    return t;
  }

  addShape(kind, color = '#F56E28') {
    const cx = this.width / 2, cy = this.height / 2;
    const common = { left: cx, top: cy, originX: 'center', originY: 'center', shapeKind: kind };
    let obj;
    switch (kind) {
      case 'rect':
        obj = new fabric.Rect({ ...common, width: 200, height: 120, fill: '', stroke: color, strokeWidth: 3 }); break;
      case 'filledRect':
        obj = new fabric.Rect({ ...common, width: 200, height: 120, fill: color }); break;
      case 'circle':
        obj = new fabric.Circle({ ...common, radius: 70, fill: '', stroke: color, strokeWidth: 3 }); break;
      case 'filledCircle':
        obj = new fabric.Circle({ ...common, radius: 70, fill: color }); break;
      case 'line':
        obj = new fabric.Line([cx - 100, cy, cx + 100, cy], { ...common, stroke: color, strokeWidth: 3 }); break;
      case 'dottedLine':
        obj = new fabric.Line([cx - 100, cy, cx + 100, cy], { ...common, stroke: color, strokeWidth: 3, strokeDashArray: [8, 6] }); break;
      case 'arrow': {
        const line = new fabric.Line([cx - 100, cy, cx + 80, cy], { stroke: color, strokeWidth: 3 });
        const head = new fabric.Triangle({ left: cx + 90, top: cy, originX: 'center', originY: 'center', angle: 90, width: 22, height: 24, fill: color });
        obj = new fabric.Group([line, head], { ...common, shapeKind: 'arrow' }); break;
      }
      default:
        obj = new fabric.Rect({ ...common, width: 160, height: 100, fill: color });
    }
    this.canvas.add(obj);
    this.canvas.setActiveObject(obj);
    this.canvas.requestRenderAll();
    this.snapshot();
    return obj;
  }

  // ---- Aktionen auf Auswahl -----------------------------------------------
  active() { return this.canvas.getActiveObject(); }
  activeAll() { const a = this.active(); if (!a) return []; return a.type === 'activeSelection' ? a.getObjects() : [a]; }

  deleteSelected() {
    this.activeAll().forEach(o => this.canvas.remove(o));
    this.canvas.discardActiveObject();
    this.canvas.requestRenderAll();
    this.snapshot();
  }

  duplicateSelected() {
    const a = this.active();
    if (!a) return;
    a.clone(clone => {
      clone.set({ left: a.left + 25, top: a.top + 25 });
      this.canvas.add(clone);
      this.canvas.setActiveObject(clone);
      this.canvas.requestRenderAll();
      this.snapshot();
    }, EXTRA_PROPS);
  }

  flip(axis) {
    this.activeAll().forEach(o => o.set(axis === 'h' ? 'flipX' : 'flipY', !o[axis === 'h' ? 'flipX' : 'flipY']));
    this.canvas.requestRenderAll(); this.snapshot();
  }

  bringForward() { this.activeAll().forEach(o => this.canvas.bringForward(o)); this.canvas.requestRenderAll(); this.snapshot(); }
  sendBackward() { this.activeAll().forEach(o => this.canvas.sendBackwards(o)); this.canvas.requestRenderAll(); this.snapshot(); }

  // Ausrichten relativ zum Canvas (oder zur Gruppe bei Multi-Select).
  align(where) {
    const objs = this.activeAll();
    if (!objs.length) return;
    objs.forEach(o => {
      const b = o.getBoundingRect(true);
      switch (where) {
        case 'left':   o.set({ left: o.left - b.left }); break;
        case 'right':  o.set({ left: o.left + (this.width - (b.left + b.width)) }); break;
        case 'centerH':o.set({ left: o.left + (this.width / 2 - (b.left + b.width / 2)) }); break;
        case 'top':    o.set({ top: o.top - b.top }); break;
        case 'bottom': o.set({ top: o.top + (this.height - (b.top + b.height)) }); break;
        case 'centerV':o.set({ top: o.top + (this.height / 2 - (b.top + b.height / 2)) }); break;
      }
      o.setCoords();
    });
    this.canvas.requestRenderAll(); this.snapshot();
  }

  // ---- Snapping (Kanten/Mitte am Canvas + an anderen Objekten) -------------
  _enableSnapping() {
    this.canvas.on('object:moving', e => this._doSnap(e.target));
    this.canvas.on('object:modified', () => this._clearSnapLines());
    this.canvas.on('mouse:up', () => this._clearSnapLines());
  }

  _doSnap(obj) {
    if (!obj) return;
    this._clearSnapLines();
    const b = obj.getBoundingRect(true);
    const tol = this.snapTol;
    // Kandidaten-Linien: Canvas-Kanten + Mitte
    const vTargets = [0, this.width / 2, this.width];
    const hTargets = [0, this.height / 2, this.height];
    // + andere Objektkanten
    this.canvas.getObjects().forEach(o => {
      if (o === obj) return;
      const ob = o.getBoundingRect(true);
      vTargets.push(ob.left, ob.left + ob.width / 2, ob.left + ob.width);
      hTargets.push(ob.top, ob.top + ob.height / 2, ob.top + ob.height);
    });
    const objEdgesX = [b.left, b.left + b.width / 2, b.left + b.width];
    const objEdgesY = [b.top, b.top + b.height / 2, b.top + b.height];

    for (const t of vTargets) for (let i = 0; i < objEdgesX.length; i++) {
      if (Math.abs(objEdgesX[i] - t) < tol) {
        obj.left += t - objEdgesX[i];
        this._drawSnapLine(t, true);
        break;
      }
    }
    for (const t of hTargets) for (let i = 0; i < objEdgesY.length; i++) {
      if (Math.abs(objEdgesY[i] - t) < tol) {
        obj.top += t - objEdgesY[i];
        this._drawSnapLine(t, false);
        break;
      }
    }
    obj.setCoords();
  }

  _drawSnapLine(pos, vertical) {
    const line = new fabric.Line(
      vertical ? [pos, 0, pos, this.height] : [0, pos, this.width, pos],
      { stroke: '#61CEBC', strokeWidth: 1, selectable: false, evented: false, excludeFromExport: true, _snap: true }
    );
    this._snapLines.push(line);
    this.canvas.add(line);
    this.canvas.bringToFront(line);
  }
  _clearSnapLines() {
    if (!this._snapLines.length) return;
    this._snapLines.forEach(l => this.canvas.remove(l));
    this._snapLines = [];
  }

  // ---- Undo / Redo ---------------------------------------------------------
  _bindEvents() {
    const record = () => { if (!this._locked) this.snapshot(); };
    this.canvas.on('object:modified', record);
    // add/remove werden explizit in den add*-Methoden per snapshot() erfasst
  }

  snapshot() {
    if (this._locked) return;
    const json = JSON.stringify(this.canvas.toJSON(EXTRA_PROPS));
    // Duplikate vermeiden
    if (this._history.length && this._history[this._history.length - 1] === json) return;
    this._history.push(json);
    if (this._history.length > this._maxHistory) this._history.shift();
    this._redo = [];
    this._emitChange();
  }

  undo() {
    if (this._history.length < 2) return;
    this._redo.push(this._history.pop());
    this._restore(this._history[this._history.length - 1]);
  }
  redo() {
    if (!this._redo.length) return;
    const json = this._redo.pop();
    this._history.push(json);
    this._restore(json);
  }

  _restore(json) {
    this._locked = true;
    this.canvas.loadFromJSON(json, () => {
      this.canvas.requestRenderAll();
      this._locked = false;
      this._emitChange();
    });
  }

  _emitChange() {
    if (this._onChange) this._onChange();
  }
  onChange(fn) { this._onChange = fn; }
  canUndo() { return this._history.length > 1; }
  canRedo() { return this._redo.length > 0; }

  // ---- Tastatursteuerung ---------------------------------------------------
  _enableKeyboard() {
    document.addEventListener('keydown', e => {
      const tag = (e.target.tagName || '').toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;
      // Undo/Redo auch beim Tippen erlauben? Nein – nur außerhalb von Feldern.
      if (typing) return;
      const a = this.active();

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); this.redo(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); this.duplicateSelected(); return; }

      if (!a) return;
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); this.deleteSelected(); return; }

      const step = e.shiftKey ? 10 : 1;
      let moved = false;
      if (e.key === 'ArrowLeft')  { a.left -= step; moved = true; }
      if (e.key === 'ArrowRight') { a.left += step; moved = true; }
      if (e.key === 'ArrowUp')    { a.top  -= step; moved = true; }
      if (e.key === 'ArrowDown')  { a.top  += step; moved = true; }
      if (moved) { e.preventDefault(); a.setCoords(); this.canvas.requestRenderAll(); this._nudgeSnapshot(); }
    });
  }

  // Nudges bündeln, damit nicht jeder Pfeiltasten-Tick eine History-Stufe wird.
  _nudgeSnapshot() {
    clearTimeout(this._nudgeTimer);
    this._nudgeTimer = setTimeout(() => this.snapshot(), 400);
  }
}
