// editor.js – Fabric-Canvas: Objekte, Multi-Select, Snapping, Ausrichten,
// Undo/Redo, Tastatursteuerung. Der stabile Kern des neuen Studios.
import { loadImage, toast } from './util.js';
import { proxyUrl } from './config.js';

export const fabric = window.fabric;
if (!fabric) console.error('Fabric.js nicht geladen!');

// Objekt-Caching global aus: verhindert grundsätzlich jedes "Verschmelzen"
// von altem und neuem Bild beim Bearbeiten (immer direkt gerendert).
if (fabric) fabric.Object.prototype.objectCaching = false;

// Eigenschaften, die in den Snapshot/das Canvas-JSON serialisiert werden.
const EXTRA_PROPS = ['srcUrl', 'originalUrl', 'bgRemoved', 'anim', 'shapeKind', 'fx', 'svgPart',
                     'tbHead', 'tbBody', 'tbWidth', 'tbSize', 'tbAlign'];

export class Editor {
  constructor(canvasEl) {
    this.canvas = new fabric.Canvas(canvasEl, {
      backgroundColor: '',        // transparent → Schachbrett scheint durch
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

    this._grid = [];            // Raster-Linien (nur Hilfe, nie exportiert)
    this.gridOn = false;
    this.gridCols = 6;          // "große Kästen" – wenige Spalten = große Felder

    this._bindEvents();
    this._enableSnapping();
    this._enableKeyboard();

    // Dezentes Auswahl-Styling (Octotrial-Orange)
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
    this._baseScale = Math.min(maxW / this.width, maxH / this.height, 1);
    this._userZoom = this._userZoom || 1;
    this._applyZoom();
  }

  _applyZoom() {
    const scale = (this._baseScale || 1) * (this._userZoom || 1);
    this.canvas.setZoom(scale);
    this.canvas.setDimensions({
      width:  Math.round(this.width  * scale),
      height: Math.round(this.height * scale),
    });
    this.canvas.requestRenderAll();
  }

  // Zoom rein/raus/zurück (für präzises Arbeiten an kleinen Details).
  zoom(dir) {
    this._userZoom = this._userZoom || 1;
    if (dir === 'in')   this._userZoom = Math.min(this._userZoom * 1.25, 24);
    else if (dir === 'out') this._userZoom = Math.max(this._userZoom / 1.25, 1);
    else this._userZoom = 1;   // reset
    this._applyZoom();
    return this._userZoom;
  }

  // Aktueller Vergrößerungsfaktor gegenüber der Einpassung (für Anzeige).
  zoomFactor() { return this._userZoom || 1; }

  // Leert die gesamte Arbeitsfläche: alle Objekte + Hintergrund.
  clearAll() {
    this.canvas.getObjects().slice().forEach(o => this.canvas.remove(o));
    this.canvas.discardActiveObject();
    this.canvas.setBackgroundImage(null, () => {});
    this.canvas.setBackgroundColor('#1a1a2e', () => {});
    this._templateId = null;
    if (this.gridOn) this._buildGrid();   // Raster wieder anlegen
    this.canvas.requestRenderAll();
    this.snapshot();
  }

  setSize(w, h) {
    this.width = w; this.height = h;
    // interne Auflösung zurücksetzen, Zoom neutralisieren …
    this.canvas.setZoom(1);
    this.canvas.setDimensions({ width: w, height: h });
    if (this.gridOn) this._buildGrid();   // Raster an neue Größe anpassen
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
    if (opts.fill) {
      // Ganzen Canvas ausfüllen (z.B. beim Öffnen einer fertigen Ausgabe zum Bearbeiten)
      const s = Math.max(this.width / img.width, this.height / img.height);
      img.scale(s);
    } else {
      // Auf sinnvolle Größe skalieren
      const maxSize = Math.min(this.width, this.height) * 0.5;
      if (img.width > maxSize) img.scaleToWidth(maxSize);
    }
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
    const str = text || 'Text';
    const size = opts.fontSize || 32;
    const weight = opts.fontWeight || 'bold';
    const family = 'Roboto, Arial, sans-serif';

    // Breite an den Text anpassen statt starr 60 % der Canvas
    let w = opts.width;
    if (!w) {
      const probe = new fabric.Text(str, { fontSize: size, fontWeight: weight, fontFamily: family });
      w = Math.min(Math.ceil(probe.width) + Math.round(size * 0.8), this.width * 0.9);
      w = Math.max(w, Math.round(size * 3));
    }

    const t = new fabric.Textbox(str, {
      left: this.width / 2, top: this.height / 2,
      originX: 'center', originY: 'center',
      width: w,
      fontSize: size,
      fontWeight: weight,
      fontFamily: family,
      fill: opts.color || '#111111',
      textAlign: opts.align || 'center',
      // Schatten nur auf Wunsch – auf hellem Grund macht er den Text schmutzig
      shadow: opts.shadow ? 'rgba(0,0,0,0.55) 0 2px 5px' : null,
      editable: true,
    });
    this.canvas.add(t);
    this.canvas.setActiveObject(t);
    this.canvas.requestRenderAll();
    this.snapshot();
    return t;
  }

  // Wabe (Sechseck, Spitze oben) – Punkte relativ, Fabric setzt die Bounding-Box
  addShape(kind, color = '#F56E28') {
    const hexPoints = r => Array.from({ length: 6 }, (_, i) => {
      const a = (Math.PI / 3) * i - Math.PI / 2;
      return { x: r * Math.cos(a), y: r * Math.sin(a) };
    });
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
      case 'hex':
        obj = new fabric.Polygon(hexPoints(70), { ...common, fill: '', stroke: color, strokeWidth: 3 }); break;
      case 'filledHex':
        obj = new fabric.Polygon(hexPoints(70), { ...common, fill: color }); break;
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

  // Mehrere ausgewählte Objekte zu EINER Gruppe zusammenfassen (verkleben).
  group() {
    const a = this.active();
    if (!a || a.type !== 'activeSelection') return false;
    const g = a.toGroup();
    g.set({ shapeKind: 'group' });
    this.canvas.requestRenderAll();
    this.snapshot();
    return true;
  }
  // Gruppe wieder in Einzelteile auflösen.
  ungroup() {
    const a = this.active();
    if (!a || a.type !== 'group') return false;
    a.toActiveSelection();
    this.canvas.requestRenderAll();
    this.snapshot();
    return true;
  }
  isGroup() { const a = this.active(); return !!(a && a.type === 'group'); }

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

  // Einzelnes Objekt in der Ebenen-Reihenfolge bewegen.
  moveObj(o, dir) {
    if (!o) return;
    if (dir === 'up')       this.canvas.bringForward(o);
    else if (dir === 'down') this.canvas.sendBackwards(o);
    else if (dir === 'front') this.canvas.bringToFront(o);
    else if (dir === 'back')  this.canvas.sendToBack(o);
    this.canvas.requestRenderAll(); this.snapshot();
  }
  selectObj(o) { if (o) { this.canvas.setActiveObject(o); this.canvas.requestRenderAll(); } }
  // Nur echte Objekte (ohne Snapping-Hilfslinien).
  realObjects() { return this.canvas.getObjects().filter(o => !o._snap && !o._grid); }

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
    // + andere Objektkanten (Raster- und Hilfslinien nie als Ziel!)
    this.canvas.getObjects().forEach(o => {
      if (o === obj || o._snap || o._grid) return;
      const ob = o.getBoundingRect(true);
      vTargets.push(ob.left, ob.left + ob.width / 2, ob.left + ob.width);
      hTargets.push(ob.top, ob.top + ob.height / 2, ob.top + ob.height);
    });
    const objEdgesX = [b.left, b.left + b.width / 2, b.left + b.width];
    const objEdgesY = [b.top, b.top + b.height / 2, b.top + b.height];

    // Pro Achse nur EINEN – den am dichtesten liegenden – Treffer nehmen und
    // genau eine Linie zeichnen. Sonst erscheinen mehrere „Fadenkreuze".
    const best = (targets, edges) => {
      let d = tol, shift = null, at = null;
      for (const t of targets) for (const e of edges) {
        const diff = Math.abs(e - t);
        if (diff < d) { d = diff; shift = t - e; at = t; }
      }
      return at == null ? null : { shift, at };
    };
    const bx = best(vTargets, objEdgesX);
    if (bx) { obj.left += bx.shift; this._drawSnapLine(bx.at, true); }
    const by = best(hTargets, objEdgesY);
    if (by) { obj.top += by.shift; this._drawSnapLine(by.at, false); }
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

  // ---- Raster (Ausricht-Hilfe, wird nie mitgespeichert/exportiert) ---------
  toggleGrid(on) {
    this.gridOn = (on == null) ? !this.gridOn : !!on;
    this._buildGrid();
    return this.gridOn;
  }
  // PNG-Export: das Raster darf NICHT mit aufs Bild. toDataURL zeichnet die
  // echten Pixel (excludeFromExport hilft nur bei JSON/SVG), also blenden wir
  // die Rasterlinien für den Moment aus.
  exportDataURL(opts = {}) {
    const weg = this._grid.filter(l => l.visible !== false);
    weg.forEach(l => (l.visible = false));
    this.canvas.discardActiveObject();
    // Zoom/Verschiebung fürs Bild neutralisieren, sonst wird der sichtbare
    // (verschobene) Ausschnitt exportiert statt der ganzen Arbeitsfläche.
    const vpt = this.canvas.viewportTransform ? this.canvas.viewportTransform.slice() : null;
    this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    this.canvas.renderAll();
    const url = this.canvas.toDataURL({ format: 'png', multiplier: 1, ...opts });
    if (vpt) this.canvas.setViewportTransform(vpt);
    weg.forEach(l => (l.visible = true));
    this.canvas.requestRenderAll();
    return url;
  }
  _clearGrid() {
    this._grid.forEach(l => this.canvas.remove(l));
    this._grid = [];
  }
  // Für GIF/Video-Aufnahme: Raster kurz unsichtbar schalten.
  setGridVisible(v) {
    this._grid.forEach(l => (l.visible = !!v));
    this.canvas.renderAll();
  }
  _buildGrid() {
    this._clearGrid();
    if (!this.gridOn) { this.canvas.requestRenderAll(); return; }
    const step = Math.round(this.width / this.gridCols);
    const mk = (pts, stark) => new fabric.Line(pts, {
      stroke: stark ? '#F56E28' : '#8AA0AA',
      strokeWidth: stark ? 1.4 : 1,
      opacity: stark ? 0.55 : 0.32,
      selectable: false, evented: false, hoverCursor: 'default',
      excludeFromExport: true, _grid: true,
    });
    // Senkrechte + waagerechte Linien im gleichen Abstand = quadratische Felder.
    for (let x = step; x < this.width; x += step) this._grid.push(mk([x, 0, x, this.height]));
    for (let y = step; y < this.height; y += step) this._grid.push(mk([0, y, this.width, y]));
    // Mittelachsen etwas kräftiger, als Hauptorientierung.
    this._grid.push(mk([this.width / 2, 0, this.width / 2, this.height], true));
    this._grid.push(mk([0, this.height / 2, this.width, this.height / 2], true));
    this._grid.forEach(l => { this.canvas.add(l); this.canvas.sendToBack(l); });
    this.canvas.requestRenderAll();
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
      // Raster ist nicht Teil der Historie – nach dem Laden neu aufbauen.
      this._grid = [];
      if (this.gridOn) this._buildGrid();
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
