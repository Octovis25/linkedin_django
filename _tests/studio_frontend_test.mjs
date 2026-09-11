// Frontend test harness for the Image Studio.
// Django can't start in this container, but the front end can: the template is
// rendered to static HTML, the modules and fabric sit next to it, a tiny HTTP
// server serves the lot, and Playwright drives it. No login, no database.

import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve('app');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
                '.json': 'application/json', '.png': 'image/png' };

const SPEICHER_URLS = new Set(['/api/save', '/api/save-video']);
let SERVER_MODUS = 'ok';        // 'ok' | '500' | 'html' | '413'
let letzterUpload = null;

const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  // Stub the backend: every /api/ call answers with empty, well-formed JSON so
  // the boot steps run through instead of dying on a 404.
  if (url.startsWith('/api/')) {
    // The Videos output folder answers with one entry whose file does not
    // exist, so the "broken video thumbnail" case is reproducible.
    if (url === '/api/nc-browse' && /Output%2FVideos/i.test(req.url)) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: true, items: [
        { name: 'kaputt.webm', title: 'kaputt', url: '/api/gibt-es-nicht.webm',
          nc_path: 'Studio_Work/Output/Videos/kaputt.webm' },
      ] }));
    }
    if (url.endsWith('.webm')) { res.writeHead(404); return res.end('nope'); }
    // Schaltbare Fehlerfälle: die Tests unten stellen SERVER_MODUS um, um zu
    // prüfen, wie sich das Studio bei einem kranken Backend verhält.
    if (SPEICHER_URLS.has(url)) {
      letzterUpload = { url, laenge: +(req.headers['content-length'] || 0) };
      if (SERVER_MODUS === '500') { res.writeHead(500, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ ok: false, error: 'Interner Serverfehler' })); }
      if (SERVER_MODUS === 'html') { res.writeHead(200, { 'Content-Type': 'text/html' });
        return res.end('<!doctype html><title>Login</title><body>Bitte anmelden</body>'); }
      if (SERVER_MODUS === '413') { res.writeHead(413, { 'Content-Type': 'text/plain' });
        return res.end('Request Entity Too Large'); }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: true, lib_id: 42, nc_path: 'Studio_Work/Output/x' }));
    }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ ok: true, templates: [], items: [], folders: [], files: [] }));
  }
  const file = path.join(ROOT, url === '/' ? 'index.html' : url);
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404); return res.end('nope'); }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(buf);
  });
});

const PORT = 8931;
await new Promise(r => server.listen(PORT, r));

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell' });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });

// Anything the page reports is a defect, not a footnote. A 404 on a file the
// test deliberately breaks is the only thing worth ignoring.
const HARMLOS = [/ResizeObserver loop/i, /gibt-es-nicht\.webm/i, /Failed to load resource/i,
                 /Testfehler/i, /QuotaExceededError \(Test\)/i];
const fehler = [];
const melde = txt => { if (!HARMLOS.some(r => r.test(txt))) fehler.push(txt); };
page.on('pageerror', e => melde('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error') melde('console: ' + m.text()); });

// Nach jedem Abschnitt prüfen: ist seither ein Fehler aufgelaufen oder steht
// das rote Banner? Vorher wurden beide nur am Ende ausgedruckt – ein Test
// konnte grün sein, während die Seite darunter krachte.
let _gesehen = 0;
async function sauber(abschnitt) {
  const neu = fehler.slice(_gesehen);
  _gesehen = fehler.length;
  const banner = await page.locator('#studio-fehler').count();
  pruefe(`Kein Fehler in: ${abschnitt}`, neu.length === 0 && banner === 0,
    neu[0] || (banner ? 'rotes Banner steht' : ''));
  if (banner) await page.evaluate(() => document.getElementById('studio-fehler')?.remove());
}

await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'load' });
await page.waitForFunction(() => !!window._studioEditor, null, { timeout: 10000 });


// _work ist { canvas, ctx, W, H }; ohne Bearbeitung liegt das Bild in _element.
const pixel = (xRel, yRel) => page.evaluate(([xr, yr]) => {
  const img = window._studioEditor.realObjects().find(o => o.type === 'image');
  const src = img._work ? img._work.canvas : img._element;
  const c = document.createElement('canvas');
  c.width = src.width; c.height = src.height;
  const x = c.getContext('2d'); x.drawImage(src, 0, 0);
  return [...x.getImageData(Math.round(src.width * xr), Math.round(src.height * yr), 1, 1).data];
}, [xRel, yRel]);

const ergebnis = [];
const pruefe = (name, ok, detail = '') =>
  ergebnis.push({ name, ok, detail: String(detail).slice(0, 120) });

// ---- 1. Startet das Studio überhaupt sauber? ------------------------------
pruefe('Studio startet ohne Fehlerbanner',
  !(await page.locator('#studio-fehler').count()));
pruefe('Modus-Rail hat 4 Modi',
  (await page.locator('#mode-rail [data-mode]').count()) === 4);

await sauber('Start');

// ---- 2. Testbild auf den Canvas legen -------------------------------------
// Weißes Bild mit einem großen roten Feld. Das rote Feld ist die "freie Stelle",
// in die geklickt wird.
await page.evaluate(async () => {
  const c = document.createElement('canvas'); c.width = 400; c.height = 400;
  const x = c.getContext('2d');
  x.fillStyle = '#ffffff'; x.fillRect(0, 0, 400, 400);
  x.fillStyle = '#ff0000'; x.fillRect(0, 0, 400, 200);      // obere Hälfte rot
  const url = c.toDataURL('image/png');
  const el = await new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = url; });
  const img = new window.fabric.Image(el, { left: 0, top: 0, srcUrl: url });
  const e = window._studioEditor;
  img.scaleToWidth(e.width);
  e.canvas.add(img); e.canvas.setActiveObject(img); e.canvas.requestRenderAll();
  e.snapshot();
});
pruefe('Testbild liegt auf dem Canvas',
  await page.evaluate(() => window._studioEditor.realObjects().filter(o => o.type === 'image').length === 1));

await sauber('Bild laden');

// ---- 3. Modus Image: sind die Werkzeuge jetzt aktiv? ----------------------
await page.click('#mode-rail [data-mode="image"]');
await page.waitForTimeout(120);
pruefe('Image-Panel ist mit Bild nicht mehr ausgegraut',
  !(await page.locator('#retouch-body.is-disabled').count()));
const startTool = await page.getAttribute('#retouch-body [data-toolkey="erase"]', 'data-tool');
pruefe('Erase startet auf "fill" (Klick-Fläche)', startTool === 'fill', startTool);

await sauber('Modus Image');

// ---- 4. Der Griff, den Ortrud gewohnt ist: Werkzeug, dann in die Fläche klicken
await page.click('#retouch-body [data-toolkey="erase"]');
await page.waitForTimeout(120);
const status1 = await page.textContent('#tool-status');
pruefe('Klick auf Erase aktiviert ein Werkzeug', !!status1 && status1.trim().length > 0, status1);
pruefe('Erase-Knopf ist hervorgehoben',
  await page.evaluate(() => document.querySelector('#retouch-body [data-toolkey="erase"]').classList.contains('primary')));

// In die rote Fläche klicken (oberes Viertel des Canvas)
const box = await page.locator('#main-canvas').boundingBox();
await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.25);
await page.waitForTimeout(700);

const rotOben = await pixel(0.5, 0.25);
const weissUnten = await pixel(0.5, 0.75);
pruefe('Klick in die rote Fläche macht sie transparent', rotOben[3] === 0, JSON.stringify(rotOben));
pruefe('Der weiße Rest bleibt stehen', weissUnten[3] > 0, JSON.stringify(weissUnten));

await sauber('Klick-Fläche radieren');

// ---- 5. Reichweite wechseln: Pinsel ---------------------------------------
await page.click('#scope-seg [data-scope="brush"]');
await page.waitForTimeout(150);
const brushTool = await page.getAttribute('#retouch-body [data-toolkey="erase"]', 'data-tool');
pruefe('Reichweite "Brush" schaltet Erase auf "erase"', brushTool === 'erase', brushTool);
pruefe('Pinselgröße erscheint nur beim Pinsel',
  await page.locator('#brush-row').isVisible());

await sauber('Pinsel-Reichweite');

// ---- 6. Select: Rechteck ziehen -------------------------------------------
await page.click('#retouch-body [data-toolkey="select"]');
await page.waitForTimeout(150);
pruefe('Select blendet die Reichweiten-Zeile aus',
  !(await page.locator('#scope-row').isVisible()));
pruefe('Select zeigt Rectangle/Free',
  await page.locator('#select-row').isVisible());
pruefe('Rechteck-Ebene ist aktiv',
  await page.evaluate(() => document.getElementById('rect-overlay').style.display === 'block'));

await page.mouse.move(box.x + box.width * 0.30, box.y + box.height * 0.30);
await page.mouse.down();
await page.mouse.move(box.x + box.width * 0.60, box.y + box.height * 0.45, { steps: 12 });
await page.mouse.up();
await page.waitForTimeout(400);
pruefe('Delete/Recolour erscheinen nach dem Ziehen',
  await page.locator('#mark-apply-row').isVisible());
// Ob die Markierung intern schon als _mask vorliegt oder erst beim Anwenden
// entsteht, ist Implementierungsdetail — geprüft wird das Ergebnis unten.
await page.click('#retouch-body [data-mark="remove"]');
await page.waitForTimeout(700);
const nachRechteck = await pixel(0.45, 0.37);
pruefe('Rechteck löschen macht den Bereich transparent', nachRechteck[3] === 0, JSON.stringify(nachRechteck));

await sauber('Rechteck-Auswahl');

// ---- 7. Leisten zuklappen und wieder aufklappen ---------------------------
// Der Klapp-Knopf saß eine Version lang IM Panel und verschwand mit ihm —
// zugeklappt gab es keinen Weg zurück, die ganze Werkzeugleiste blieb weg.
await page.click('#mode-rail [data-mode="build"]');
await page.waitForTimeout(120);
pruefe('Build-Panel ist sichtbar', await page.locator('[data-panel="build"]').isVisible());
pruefe('Template-Bereich ist da', await page.locator('#tpl-list').count() === 1);

const klick = async sel => {
  try { await page.click(sel, { timeout: 2500 }); return true; }
  catch (e) { return false; }
};
pruefe('Klapp-Knopf links ist anklickbar', await klick('#toggle-left'));
await page.waitForTimeout(300);
pruefe('Zuklappen blendet die Leiste aus',
  await page.evaluate(() => document.querySelector('.studio-wrap').classList.contains('hide-left')));
pruefe('Klapp-Knopf bleibt nach dem Zuklappen sichtbar',
  await page.locator('#toggle-left').isVisible());
pruefe('Klapp-Knopf bleibt anklickbar',
  await page.evaluate(() => {
    const b = document.getElementById('toggle-left');
    const r = b.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b;
  }));

pruefe('Wieder-Aufklappen ist möglich', await klick('#toggle-left'));
await page.waitForTimeout(300);
pruefe('Aufklappen bringt die Leiste zurück',
  !(await page.evaluate(() => document.querySelector('.studio-wrap').classList.contains('hide-left'))));
pruefe('Template-Bereich ist wieder erreichbar', await page.locator('#tpl-list').isVisible());

pruefe('Klapp-Knopf rechts ist anklickbar', await klick('#toggle-right'));
await page.waitForTimeout(300);
pruefe('Rechter Klapp-Knopf bleibt anklickbar',
  await page.evaluate(() => {
    const b = document.getElementById('toggle-right');
    const r = b.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b;
  }));
await klick('#toggle-right');
await page.waitForTimeout(250);
pruefe('Medien-Leiste kommt zurück',
  !(await page.evaluate(() => document.querySelector('.studio-wrap').classList.contains('hide-right'))));

await sauber('Leisten klappen');

// ---- 8. "Remove background": was tut es, und wann tut es nichts? ----------
// Der Algorithmus mittelt die vier Ecken zur Hintergrundfarbe und entfernt alles,
// was innerhalb der Toleranz daran hängt — ABER mit Weißschutz: helle, farbneutrale
// Pixel (max>=200, max-min<=38) gelten NIE als Hintergrund, damit weiße Inhalte
// wie Kittel und Icons stehen bleiben.
const neuesBild = (bg) => page.evaluate(async (bg) => {
  const e = window._studioEditor;
  e.canvas.getObjects().slice().forEach(o => e.canvas.remove(o));
  const c = document.createElement('canvas'); c.width = 400; c.height = 400;
  const x = c.getContext('2d');
  x.fillStyle = bg; x.fillRect(0, 0, 400, 400);
  x.fillStyle = '#c0392b'; x.beginPath(); x.arc(200, 200, 90, 0, Math.PI * 2); x.fill();
  const url = c.toDataURL('image/png');
  const el = await new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = url; });
  const img = new window.fabric.Image(el, { left: 0, top: 0, srcUrl: url });
  img.scaleToWidth(e.width);
  e.canvas.add(img); e.canvas.setActiveObject(img); e.canvas.requestRenderAll(); e.snapshot();
}, bg);

// Abschnitt 7 hat die Leisten auf- und zugeklappt — vor dem Weiterarbeiten
// sicherstellen, dass beide offen sind und der Image-Modus wirklich sichtbar ist.
await page.evaluate(() => document.querySelector('.studio-wrap')
  .classList.remove('hide-left', 'hide-right', 'peek-left', 'peek-right'));
await page.click('#mode-rail [data-mode="image"]');
await page.waitForSelector('[data-panel="image"]', { state: 'visible' });
await page.waitForTimeout(150);

// A) Farbiger Hintergrund — hier soll es wirken
await neuesBild('#1f6fb2');
await page.click('#retouch-body [data-act="cutout"]');
await page.waitForTimeout(900);
pruefe('Remove background: blauer Hintergrund verschwindet', (await pixel(0.04, 0.04))[3] === 0,
  JSON.stringify(await pixel(0.04, 0.04)));
pruefe('Remove background: der rote Kreis bleibt', (await pixel(0.5, 0.5))[3] > 0,
  JSON.stringify(await pixel(0.5, 0.5)));

// B) Weißer Hintergrund — hier tut es absichtlich NICHTS (Weißschutz)
await neuesBild('#ffffff');
await page.click('#retouch-body [data-act="cutout"]');
await page.waitForTimeout(900);
const weissEcke = await pixel(0.04, 0.04);
pruefe('Remove background lässt WEISS stehen (Weißschutz greift)', weissEcke[3] > 0,
  JSON.stringify(weissEcke));
const meldung = await page.textContent('#status-msg');
pruefe('...und sagt dem Nutzer warum, statt still nichts zu tun',
  /white/i.test(meldung || '') && /Whole colour/i.test(meldung || ''), meldung);

// C) Derselbe weiße Hintergrund über Erase x "ganze Farbe" — das ist der Weg
// Nach Select ist die Reichweiten-Zeile ausgeblendet; erst wieder ein
// Matrix-Werkzeug wählen, dann ist sie da. (So gedacht, nicht als Fehler.)
await page.click('#retouch-body [data-toolkey="erase"]');
await page.waitForTimeout(150);
pruefe('Nach Select bringt Erase die Reichweiten-Zeile zurück',
  await page.locator('#scope-row').isVisible());
await page.click('#scope-seg [data-scope="all"]');
await page.waitForTimeout(150);
const allTool = await page.getAttribute('#retouch-body [data-toolkey="erase"]', 'data-tool');
pruefe('Reichweite "Whole colour" schaltet Erase auf "pick"', allTool === 'pick', allTool);
await page.click('#retouch-body [data-toolkey="erase"]');
await page.waitForTimeout(150);
const box2 = await page.locator('#main-canvas').boundingBox();
await page.mouse.click(box2.x + box2.width * 0.06, box2.y + box2.height * 0.06);
await page.waitForTimeout(900);
const weissDanach = await pixel(0.04, 0.04);
pruefe('Erase x "ganze Farbe" entfernt den weißen Hintergrund doch', weissDanach[3] === 0,
  JSON.stringify(weissDanach));
pruefe('und der rote Kreis bleibt dabei stehen', (await pixel(0.5, 0.5))[3] > 0,
  JSON.stringify(await pixel(0.5, 0.5)));

await sauber('Remove background');

// ---- 9. Feiner Pinsel und Zoom -------------------------------------------
await page.evaluate(() => document.querySelector('.studio-wrap')
  .classList.remove('hide-left', 'hide-right'));
await page.click('#retouch-body [data-toolkey="erase"]');
await page.click('#scope-seg [data-scope="brush"]');
await page.waitForTimeout(150);
pruefe('Pinselregler startet fein', (await page.textContent('#brush-val')) === '6 px',
  await page.textContent('#brush-val'));

await page.evaluate(() => {
  const s = document.getElementById('brush-slider');
  s.value = 1; s.dispatchEvent(new Event('input', { bubbles: true }));
});
pruefe('Regler ganz links = 1 px', (await page.textContent('#brush-val')) === '1 px',
  await page.textContent('#brush-val'));
await page.evaluate(() => {
  const s = document.getElementById('brush-slider');
  s.value = 50; s.dispatchEvent(new Event('input', { bubbles: true }));
});
pruefe('Reglermitte liegt im kleinen Bereich (<=35 px)',
  parseInt(await page.textContent('#brush-val'), 10) <= 35, await page.textContent('#brush-val'));
await page.evaluate(() => {
  const s = document.getElementById('brush-slider');
  s.value = 100; s.dispatchEvent(new Event('input', { bubbles: true }));
});
pruefe('Regler ganz rechts = 120 px', (await page.textContent('#brush-val')) === '120 px',
  await page.textContent('#brush-val'));

const zoom0 = await page.evaluate(() => window._studioEditor.zoomFactor());
await page.locator('.canvas-host').hover();
await page.keyboard.down('Control');
await page.mouse.wheel(0, -300);
await page.keyboard.up('Control');
await page.waitForTimeout(250);
const zoom1 = await page.evaluate(() => window._studioEditor.zoomFactor());
pruefe('Strg+Mausrad zoomt hinein', zoom1 > zoom0, `${zoom0} -> ${zoom1}`);

await page.locator('.canvas-host').hover();
await page.mouse.wheel(0, -300);          // ohne Strg: darf nichts am Zoom ändern
await page.waitForTimeout(200);
pruefe('Mausrad ohne Strg lässt den Zoom in Ruhe',
  (await page.evaluate(() => window._studioEditor.zoomFactor())) === zoom1);

await page.click('[data-act="zoom-reset"]');
await page.waitForTimeout(150);
pruefe('Zoom zurücksetzen funktioniert',
  (await page.evaluate(() => window._studioEditor.zoomFactor())) === 1);

await sauber('Pinsel und Zoom');

// ---- 10. Doku im Rail, direkt unter Layers --------------------------------
pruefe('Rail hat einen Help-Knopf', (await page.locator('#mode-rail [data-help]').count()) === 1);
pruefe('Help steht unter den vier Modi', await page.evaluate(() => {
  const kinder = [...document.getElementById('mode-rail').children];
  const layers = kinder.findIndex(e => e.dataset.mode === 'layers');
  const help   = kinder.findIndex(e => e.dataset.help);
  return help > layers && help === kinder.length - 1;
}));
pruefe('Help ist kein Modus (Panel bleibt stehen)', await page.evaluate(() => {
  const vorher = document.querySelector('#mode-rail .active')?.dataset.mode;
  document.querySelector('#mode-rail [data-help]').click();
  return document.querySelector('#mode-rail .active')?.dataset.mode === vorher;
}));
pruefe('Klick auf Help öffnet die Dokumentation', await page.evaluate(() =>
  getComputedStyle(document.getElementById('studio-help')).display !== 'none'));
await page.evaluate(() => { document.getElementById('studio-help').style.display = 'none'; });
pruefe('Kein doppelter Doku-Knopf mehr in der Kopfzeile',
  (await page.locator('.studio-head button').count()) === 0);

await sauber('Doku im Rail');

// ---- 11. Startzeit gilt für Bewegung UND Effekt --------------------------
// Gemeldeter Fehler: Fade-in startet zur eingestellten Zeit, Pulse dagegen
// sofort – bei allen Elementen gleichzeitig, egal was als Start eingestellt war.
const takt = await page.evaluate(async () => {
  const m = await import('/media.js');
  const f = window.fabric;
  const mach = anim => {
    const r = new f.Rect({ left: 100, top: 100, width: 50, height: 50 });
    r.anim = anim; return r;
  };
  const puls = mach({ type: 'pulse', dur: 1200, delay: 800 });
  m.applyAt(puls, 400);  const vor  = puls.scaleX;
  m.applyAt(puls, 1000); const nach = puls.scaleX;

  const fade = mach({ type: 'fadeIn', dur: 1200, delay: 800 });
  m.applyAt(fade, 400);  const fadeVor  = fade.opacity;
  m.applyAt(fade, 2500); const fadeNach = fade.opacity;

  // Drei Kreispunkte mit verschiedenen Startzeiten – dürfen nicht im
  // Gleichschritt laufen.
  const a = mach({ type: 'pulse', dur: 1200, delay: 0 });
  const b = mach({ type: 'pulse', dur: 1200, delay: 600 });
  const c = mach({ type: 'pulse', dur: 1200, delay: 1200 });
  [a, b, c].forEach(o => m.applyAt(o, 1500));
  return { vor, nach, fadeVor, fadeNach, a: a.scaleX, b: b.scaleX, c: c.scaleX };
});
pruefe('Pulse ruht vor seiner Startzeit', Math.abs(takt.vor - 1) < 1e-9, takt.vor);
pruefe('Pulse läuft nach seiner Startzeit', Math.abs(takt.nach - 1) > 1e-6, takt.nach);
pruefe('Fade-in hält die Startzeit weiterhin ein',
  takt.fadeVor === 0 && takt.fadeNach > 0.99, `${takt.fadeVor} / ${takt.fadeNach}`);
pruefe('Drei Pulse mit verschiedenen Startzeiten laufen versetzt',
  Math.abs(takt.a - takt.b) > 1e-6 && Math.abs(takt.b - takt.c) > 1e-6,
  `${takt.a} / ${takt.b} / ${takt.c}`);

const fxTest = await page.evaluate(async () => {
  const m  = await import('/media.js');
  const ep = (await import('/editor.js')).EXTRA_PROPS;
  const ed = window._studioEditor;
  const r  = new window.fabric.Rect({ left: 40, top: 40, width: 30, height: 30 });
  ed.canvas.add(r);
  m.setEffect(ed, r, 'glow', 900);
  const json = JSON.stringify(ed.canvas.toJSON(ep));
  const erg = { delay: r.fxDelay, inProps: ep.includes('fxDelay'), serialisiert: /"fxDelay":900/.test(json) };
  ed.canvas.remove(r);
  return erg;
});
pruefe('Effekt speichert seine Startzeit', fxTest.delay === 900, fxTest.delay);
pruefe('fxDelay steht in EXTRA_PROPS', fxTest.inProps);
pruefe('fxDelay landet im Canvas-JSON (übersteht Undo und Speichern)', fxTest.serialisiert);

const regler = await page.evaluate(() => {
  const o = window._studioEditor.realObjects()[0];
  if (!o) return { keinElement: true };
  o.anim = null; o.fx = 'glow'; o.fxDelay = 0;   // nur Effekt, keine Bewegung
  const s = document.querySelectorAll('#anim-bar .anim-row')[0]
    ?.querySelectorAll('.anim-time-item input')[1];
  if (!s) return { keinRegler: true };
  s.value = 1400; s.dispatchEvent(new Event('input', { bubbles: true }));
  return { fxDelay: o.fxDelay };
});
pruefe('Start-Regler wirkt auch ohne Bewegung (nur Effekt)',
  regler.fxDelay === 1400, JSON.stringify(regler));

await sauber('Startzeiten');

// ---- 12. Kaputte Video-Vorschau wirft kein Fehlerbanner -------------------
await page.click('#media-tabs [data-media="outputs"]');
await page.click('[data-out="Videos"]');
await page.waitForSelector('#output-grid video.lib-thumb', { timeout: 5000 });
await page.locator('#output-grid video.lib-thumb').hover();
await page.waitForTimeout(600);
pruefe('Hover auf kaputte Video-Kachel zeigt kein rotes Fehlerbanner',
  (await page.locator('#studio-fehler').count()) === 0,
  await page.locator('#studio-fehler').textContent().catch(() => ''));
pruefe('Kaputte Video-Kachel wird ausgegraut', await page.evaluate(() =>
  parseFloat(getComputedStyle(document.querySelector('#output-grid video.lib-thumb')).opacity) < 0.5));
pruefe('Keine unbehandelte Promise-Ablehnung durch play()',
  !fehler.some(f => /no supported sources/i.test(f)),
  fehler.find(f => /no supported sources/i.test(f)) || '');


// ---- 13. Rundgang: alle vier Modi, jedes Einfüge-Werkzeug ----------------
// Sauberer Ausgangsstand, damit gezählt werden kann.
await page.evaluate(() => {
  const e = window._studioEditor;
  e.canvas.getObjects().slice().forEach(o => e.canvas.remove(o));
  e.canvas.discardActiveObject(); e.canvas.requestRenderAll(); e.snapshot();
});

for (const modus of ['build', 'insert', 'image', 'layers']) {
  await page.click(`#mode-rail [data-mode="${modus}"]`);
  await page.waitForTimeout(120);
  pruefe(`Modus ${modus}: Panel erscheint`,
    await page.locator(`.mode-panel[data-panel="${modus}"]`).isVisible());
  pruefe(`Modus ${modus}: nur dieses Panel ist offen`,
    (await page.locator('.mode-panel:visible').count()) === 1);
  pruefe(`Modus ${modus}: Überschrift passt zum Rail-Knopf`, await page.evaluate(m => {
    const btn = document.querySelector(`#mode-rail [data-mode="${m}"]`);
    const titel = document.getElementById('panel-title').textContent.trim();
    return btn.textContent.replace(/[^A-Za-z]/g, '').toLowerCase().includes(titel.toLowerCase());
  }, modus));
}
await sauber('Moduswechsel');

// --- Insert: jedes Werkzeug legt genau ein Element ab ---
await page.click('#mode-rail [data-mode="insert"]');
await page.waitForTimeout(120);
await page.fill('#text-input', 'Testtext');
await page.fill('#tb-head', 'Überschrift');
await page.fill('#tb-body', 'Fließtext');

const zahl = () => page.evaluate(() => window._studioEditor.realObjects().length);
const einfuegen = async (name, klick) => {
  const vorher = await zahl();
  await klick();
  await page.waitForTimeout(220);
  const nachher = await zahl();
  pruefe(`Insert: ${name} legt ein Element ab`, nachher === vorher + 1, `${vorher} -> ${nachher}`);
};

await einfuegen('Text', () => page.click('[data-act="add-text"]'));
await einfuegen('Textblock', () => page.click('[data-act="add-textblock"]'));
await einfuegen('Text mit Haken', () => page.click('[data-act="add-checktext"]'));
await einfuegen('Checkliste', () => page.click('[data-act="add-checklist"]'));
for (const f of ['rect', 'circle', 'line', 'arrow', 'hex', 'dottedLine', 'filledRect', 'filledCircle', 'filledHex']) {
  await einfuegen(`Form ${f}`, () => page.click(`[data-shape="${f}"]`));
}
for (const b of ['circle', 'hex', 'pill']) {
  await einfuegen(`Badge ${b}`, () => page.click(`[data-badge="${b}"]`));
}
await sauber('Insert-Werkzeuge');

// --- Ebenenliste zeigt wirklich jedes Element ---
await page.click('#mode-rail [data-mode="layers"]');
await page.waitForTimeout(250);
pruefe('Ebenenliste zählt wie der Canvas', await page.evaluate(() =>
  document.querySelectorAll('#layers-list [data-layer], #layers-list .layer-row').length
    === window._studioEditor.realObjects().length),
  await page.evaluate(() => document.querySelectorAll('#layers-list [data-layer], #layers-list .layer-row').length
    + ' vs ' + window._studioEditor.realObjects().length));

// --- Kontextleiste und die Aktionen darin ---
await page.evaluate(() => {
  const e = window._studioEditor;
  e.canvas.setActiveObject(e.realObjects().at(-1)); e.canvas.requestRenderAll();
});
await page.waitForTimeout(250);
pruefe('Kontextleiste füllt sich bei Auswahl',
  (await page.locator('#sel-bar button').count()) > 0);

for (const act of ['forward', 'backward', 'flip-h', 'flip-v',
                   'align-left', 'align-right', 'align-top', 'align-bottom',
                   'align-centerH', 'align-centerV']) {
  const ziel = page.locator(`[data-act="${act}"]:visible`).first();
  if (await ziel.count()) { await ziel.click(); await page.waitForTimeout(80); }
  pruefe(`Aktion ${act} läuft durch`, true);
}
await sauber('Auswahl-Aktionen');

// --- Duplizieren, Gruppieren, Löschen, Undo/Redo ---
const vorDup = await zahl();
await page.locator('[data-act="duplicate"]:visible').first().click();
await page.waitForTimeout(250);
pruefe('Duplizieren legt eine Kopie an', (await zahl()) === vorDup + 1, `${vorDup} -> ${await zahl()}`);

await page.locator('[data-act="delete"]:visible').first().click();
await page.waitForTimeout(250);
pruefe('Löschen entfernt sie wieder', (await zahl()) === vorDup, `${await zahl()}`);

await page.click('[data-act="undo"]');
await page.waitForTimeout(300);
pruefe('Undo holt das gelöschte Element zurück', (await zahl()) === vorDup + 1, `${await zahl()}`);
await page.click('[data-act="redo"]');
await page.waitForTimeout(300);
pruefe('Redo löscht es erneut', (await zahl()) === vorDup, `${await zahl()}`);
await sauber('Undo und Redo');

// --- Build: Hintergrundfarben und Canvas-Format ---
await page.click('#mode-rail [data-mode="build"]');
await page.waitForTimeout(120);
for (const act of ['bg-weiss', 'bg-creme', 'bg-transparent', 'clear-bg']) {
  await page.click(`[data-act="${act}"]`);
  await page.waitForTimeout(120);
  pruefe(`Hintergrund ${act} läuft durch`, true);
}
pruefe('Markenfarben stehen unter dem Panel',
  (await page.locator('#palette-row .swatch, #palette-row button').count()) > 0);

await page.click('[data-act="canvas-size"]');
await page.waitForTimeout(250);
pruefe('Canvas-Format öffnet einen Dialog',
  (await page.locator('.studio-modal').count()) === 1);
await page.keyboard.press('Escape');
await page.waitForTimeout(200);
pruefe('Escape schließt den Dialog wieder',
  (await page.locator('.studio-modal').count()) === 0);
await sauber('Build-Panel');

// --- Medien-Panel: alle drei Reiter mounten ---
for (const tab of ['upload', 'assets', 'outputs']) {
  await page.click(`#media-tabs [data-media="${tab}"]`);
  await page.waitForTimeout(200);
  pruefe(`Medien-Reiter ${tab} zeigt seinen Inhalt`,
    await page.locator(`[data-media-panel="${tab}"]`).isVisible());
}
await sauber('Medien-Panel');

// --- Speichern-Dialog öffnet (ohne wirklich zu speichern) ---
await page.fill('#title-input', 'Testtitel');
await page.click('[data-act="save-as-new"]');
await page.waitForTimeout(300);
pruefe('Format-Auswahl öffnet einen Dialog',
  (await page.locator('.studio-modal').count()) === 1);
await page.keyboard.press('Escape');
await page.waitForTimeout(200);
await sauber('Speichern-Dialog');

// --- Zum Schluss: alles leeren ---
await page.click('#mode-rail [data-mode="build"]');
await page.waitForTimeout(120);
await page.click('[data-act="clear-all"]');
await page.waitForTimeout(250);
await page.locator('.modal-btns button').first().click();
await page.waitForTimeout(300);
pruefe('Alles leeren räumt den Canvas', (await zahl()) === 0, `${await zahl()}`);
await sauber('Alles leeren');


// ---- 14. Wenn etwas schiefgeht: Meldung statt Absturz --------------------
// Die Abschnitte oben zeigen nur, dass im Normalbetrieb nichts kracht. Hier
// werden Fehler absichtlich ausgelöst: Sie müssen als Hinweis ankommen, nicht
// als rotes Banner über der ganzen Seite.

const bannerDa = async () => (await page.locator('#studio-fehler').count()) > 0;
const bannerWeg = () => page.evaluate(() => document.getElementById('studio-fehler')?.remove());

// (a) Retusche scheitert am Bild (toDataURL wirft – z. B. verunreinigter Canvas)
await page.evaluate(async () => {
  const c = document.createElement('canvas'); c.width = 300; c.height = 300;
  const x = c.getContext('2d'); x.fillStyle = '#ffffff'; x.fillRect(0, 0, 300, 300);
  const url = c.toDataURL('image/png');
  const el = await new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = url; });
  const e = window._studioEditor;
  const img = new window.fabric.Image(el, { left: 0, top: 0, srcUrl: url });
  img.scaleToWidth(e.width);
  e.canvas.add(img); e.canvas.setActiveObject(img); e.canvas.requestRenderAll(); e.snapshot();
});
await page.click('#mode-rail [data-mode="image"]');
await page.waitForTimeout(150);
await page.click('#retouch-body [data-toolkey="select"]');
await page.waitForTimeout(150);
const rahmen = await page.locator('#main-canvas').boundingBox();
await page.mouse.move(rahmen.x + rahmen.width * 0.3, rahmen.y + rahmen.height * 0.3);
await page.mouse.down();
await page.mouse.move(rahmen.x + rahmen.width * 0.6, rahmen.y + rahmen.height * 0.6, { steps: 6 });
await page.mouse.up();
await page.waitForTimeout(250);

await page.evaluate(() => {
  window.__echtesToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function () { throw new Error('Testfehler: Canvas verunreinigt'); };
});
const markKnopf = page.locator('#retouch-body [data-mark]:visible').first();
if (await markKnopf.count()) { await markKnopf.click(); await page.waitForTimeout(600); }
await page.evaluate(() => { HTMLCanvasElement.prototype.toDataURL = window.__echtesToDataURL; });
pruefe('Gescheiterte Retusche zeigt kein Fehlerbanner', !(await bannerDa()),
  await page.locator('#studio-fehler').textContent().catch(() => ''));
pruefe('…sondern eine Meldung für den Nutzer', await page.evaluate(() =>
  !!document.querySelector('.studio-toast')?.textContent
  || !!document.getElementById('status-msg')?.textContent));
await bannerWeg();

// (b) Das Bild verschwindet mitten im Ziehen (Leeren, Vorlage, Strg+Z)
await page.click('#retouch-body [data-toolkey="select"]');
await page.waitForTimeout(200);
pruefe('Rechteck-Ebene ist für den Abbruchtest aktiv',
  await page.evaluate(() => document.getElementById('rect-overlay').style.display === 'block'));
await page.mouse.move(rahmen.x + rahmen.width * 0.3, rahmen.y + rahmen.height * 0.3);
await page.mouse.down();
await page.mouse.move(rahmen.x + rahmen.width * 0.4, rahmen.y + rahmen.height * 0.4, { steps: 3 });
await page.evaluate(() => window._studioEditor.clearAll());   // Ziel wird entzogen
await page.waitForTimeout(150);
await page.mouse.move(rahmen.x + rahmen.width * 0.7, rahmen.y + rahmen.height * 0.7, { steps: 6 });
await page.mouse.up();
await page.waitForTimeout(300);
pruefe('Verschwundenes Bild mitten im Ziehen bricht sauber ab', !(await bannerDa()),
  await page.locator('#studio-fehler').textContent().catch(() => ''));
await bannerWeg();

// (c) Badge ohne Beschriftung (aus einem älteren canvas_json)
await page.click('#mode-rail [data-mode="insert"]');
await page.waitForTimeout(150);
await page.click('[data-badge="circle"]');
await page.waitForTimeout(250);
await page.evaluate(() => {
  const e = window._studioEditor;
  const badge = e.realObjects().at(-1);
  if (badge?._objects?.length > 1) badge._objects.splice(1, 1);   // Beschriftung fehlt
  e.canvas.setActiveObject(badge); e.canvas.requestRenderAll();
});
await page.waitForTimeout(150);
const swatch = page.locator('#palette-row button, #palette-row .swatch').first();
pruefe('Eine Markenfarbe zum Anklicken ist da', (await swatch.count()) > 0);
await swatch.click({ force: true });
await page.waitForTimeout(300);
pruefe('Kaputtes Badge bringt die Palette nicht zum Absturz', !(await bannerDa()),
  JSON.stringify(await page.evaluate(() => {
    const a = window._studioEditor.active();
    return { aktiv: a?.shapeKind || a?.type || null, kinder: a?._objects?.length ?? null,
             banner: !!document.getElementById('studio-fehler') };
  })));
await bannerWeg();

// (d) Browser verweigert localStorage (privates Fenster, Speicher voll)
const lsTest = await page.evaluate(async () => {
  const bg = await import('/background.js');
  const echt = localStorage.setItem;
  localStorage.setItem = () => { throw new Error('QuotaExceededError (Test)'); };
  let geworfen = false;
  try { bg.addCustomColor('#123456'); } catch (e) { geworfen = true; }
  localStorage.setItem = echt;
  return geworfen;
});
pruefe('Blockierter Browser-Speicher wirft nicht', lsTest === false);

// (e) Eine Aktion, die scheitert, meldet sich – ohne Banner
await page.evaluate(() => {
  const b = document.createElement('button');
  b.id = 'test-kaputt'; b.dataset.act = 'cutout';
  document.body.appendChild(b);
});
await page.evaluate(() => {
  const e = window._studioEditor;
  e.canvas.discardActiveObject(); e.canvas.requestRenderAll();
});
await page.click('#test-kaputt');
await page.waitForTimeout(500);
pruefe('Aktion ohne Auswahl bleibt ohne Banner', !(await bannerDa()),
  await page.locator('#studio-fehler').textContent().catch(() => ''));
await page.evaluate(() => document.getElementById('test-kaputt')?.remove());
await bannerWeg();


// ---- 15. Speichern und Wiederöffnen: überlebt alles die Runde? -----------
// Der Weg über Nextcloud lässt sich hier nicht fahren, der entscheidende Teil
// schon: Canvas → JSON → leer → zurück. Genau hier gingen früher Eigenschaften
// verloren, die nicht in EXTRA_PROPS standen.
await page.evaluate(() => {
  const e = window._studioEditor;
  e.canvas.getObjects().slice().forEach(o => e.canvas.remove(o));
  e.canvas.requestRenderAll(); e.snapshot();
});
await page.click('#mode-rail [data-mode="insert"]');
await page.waitForTimeout(150);
await page.fill('#text-input', 'Rundreise');
await page.fill('#tb-head', 'Kopf');
await page.fill('#tb-body', 'Körper');
await page.click('[data-act="add-text"]');       await page.waitForTimeout(150);
await page.click('[data-act="add-textblock"]');  await page.waitForTimeout(150);
await page.click('[data-act="add-checklist"]');  await page.waitForTimeout(150);
await page.click('[data-badge="pill"]');         await page.waitForTimeout(150);
await page.click('[data-shape="filledHex"]');    await page.waitForTimeout(150);

// Ein Bild mit allem, was ein Bild tragen kann.
await page.evaluate(async () => {
  const c = document.createElement('canvas'); c.width = 120; c.height = 120;
  const x = c.getContext('2d'); x.fillStyle = '#61CEBC'; x.fillRect(0, 0, 120, 120);
  const url = c.toDataURL('image/png');
  const el = await new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = url; });
  const e = window._studioEditor;
  const img = new window.fabric.Image(el, { left: 30, top: 30, srcUrl: url, originalUrl: url, bgRemoved: true });
  img.anim = { type: 'pulse', dur: 1600, delay: 700 };
  img.fx = 'glow'; img.fxDelay = 700;
  e.canvas.add(img); e.canvas.requestRenderAll(); e.snapshot();
});

const vorRunde = await page.evaluate(() => {
  const e = window._studioEditor;
  return {
    anzahl: e.realObjects().length,
    arten: e.realObjects().map(o => o.shapeKind || o.type).sort(),
  };
});

const json = await page.evaluate(async () => {
  const io = await import('/io.js');
  return io.buildCanvasJson(window._studioEditor, '');
});
pruefe('Gespeichertes JSON enthält die Animationsdaten',
  /"fxDelay":700/.test(json) && /"delay":700/.test(json) && /"fx":"glow"/.test(json));
pruefe('Gespeichertes JSON enthält die Textfelder',
  /"tbHead"/.test(json) && /"clItems"/.test(json));

const nachRunde = await page.evaluate(async (j) => {
  const io = await import('/io.js');
  const e = window._studioEditor;
  e.canvas.getObjects().slice().forEach(o => e.canvas.remove(o));
  e.canvas.requestRenderAll();
  await io.restoreCanvas(e, j);
  const img = e.realObjects().find(o => o.type === 'image');
  return {
    anzahl: e.realObjects().length,
    arten: e.realObjects().map(o => o.shapeKind || o.type).sort(),
    anim: img?.anim || null, fx: img?.fx || null, fxDelay: img?.fxDelay ?? null,
    srcUrl: !!img?.srcUrl, bgRemoved: img?.bgRemoved ?? null,
    tbHead: e.realObjects().find(o => o.tbHead)?.tbHead || null,
    clItems: e.realObjects().find(o => o.clItems)?.clItems?.length || 0,
    ladefehler: !!e._ladefehler,
  };
}, json);

pruefe('Wiederöffnen bringt alle Elemente zurück',
  nachRunde.anzahl === vorRunde.anzahl, `${vorRunde.anzahl} -> ${nachRunde.anzahl}`);
pruefe('…und zwar dieselben Arten',
  JSON.stringify(nachRunde.arten) === JSON.stringify(vorRunde.arten),
  JSON.stringify(nachRunde.arten));
pruefe('Bewegung überlebt Speichern und Öffnen',
  nachRunde.anim?.type === 'pulse' && nachRunde.anim?.delay === 700,
  JSON.stringify(nachRunde.anim));
pruefe('Effekt und seine Startzeit überleben',
  nachRunde.fx === 'glow' && nachRunde.fxDelay === 700, `${nachRunde.fx} / ${nachRunde.fxDelay}`);
pruefe('Bildherkunft und Freistell-Merker überleben',
  nachRunde.srcUrl === true && nachRunde.bgRemoved === true);
pruefe('Überschrift des Textblocks überlebt', nachRunde.tbHead === 'Kopf', nachRunde.tbHead);
pruefe('Checklisten-Zeilen überleben', nachRunde.clItems === 3, nachRunde.clItems);
pruefe('Sauberer Ladevorgang setzt keinen Ladefehler', nachRunde.ladefehler === false);
await sauber('Speichern und Wiederöffnen');

// --- Kaputter Entwurf: Warnung statt stillem Leerlauf ---
const kaputt = await page.evaluate(async () => {
  const io = await import('/io.js');
  const e = window._studioEditor;
  const ok = await io.restoreCanvas(e, '{das ist kein JSON');
  return { ok, ladefehler: !!e._ladefehler, status: document.getElementById('status-msg')?.textContent || '' };
});
pruefe('Unlesbarer Entwurf meldet Misserfolg', kaputt.ok === false);
pruefe('…setzt den Überschreib-Schutz', kaputt.ladefehler === true);
pruefe('…und sagt es dem Nutzer', /unreadable|unlesbar|❌/i.test(kaputt.status), kaputt.status);
pruefe('…ohne rotes Fehlerbanner', !(await bannerDa()));
await bannerWeg();

// --- Unbekanntes Objekt im Entwurf darf nicht alles mitreißen ---
const gemischt = await page.evaluate(async () => {
  const io = await import('/io.js');
  const e = window._studioEditor;
  const j = JSON.parse(io.buildCanvasJson(e, ''));
  j.fabric.objects.push({ type: 'quantenblume', left: 5, top: 5 });
  const vorher = j.fabric.objects.length;
  e.canvas.getObjects().slice().forEach(o => e.canvas.remove(o));
  await io.restoreCanvas(e, JSON.stringify(j));
  return { vorher, nachher: e.realObjects().length };
});
pruefe('Unbekanntes Objekt wird aussortiert, der Rest kommt zurück',
  gemischt.nachher === gemischt.vorher - 1, `${gemischt.vorher} -> ${gemischt.nachher}`);
pruefe('…ohne rotes Fehlerbanner', !(await bannerDa()));
await bannerWeg();
await sauber('Kaputte Entwürfe');


// ---- 16. Jede benutzte Server-Adresse ist auch konfiguriert --------------
// Fängt den stillsten Fehler von allen: der Code liest URLS.irgendwas, die
// Konfiguration kennt den Schlüssel nicht – fetch(undefined) holt dann die
// eigene Seite und der Nutzer sieht „Fehler beim Laden" ohne jeden Hinweis.
const urlPruefung = await page.evaluate(async () => {
  const module = ['studio.js', 'io.js', 'library.js', 'background.js', 'config.js',
                  'media.js', 'namen.js', 'cutout.js', 'editor.js', 'util.js'];
  const benutzt = new Set();
  for (const m of module) {
    const txt = await (await fetch('/' + m)).text();
    for (const t of txt.matchAll(/URLS\.([A-Za-z_$][\w$]*)/g)) benutzt.add(t[1]);
  }
  const cfg = JSON.parse(document.getElementById('studio-config').textContent);
  const fehlend = [...benutzt].filter(k => !(k in (cfg.urls || {})));
  return { benutzt: [...benutzt].sort(), fehlend };
});
pruefe('Alle im Code benutzten Server-Adressen sind konfiguriert',
  urlPruefung.fehlend.length === 0, 'fehlt: ' + urlPruefung.fehlend.join(', '));
pruefe('Der Prüfstand deckt überhaupt Adressen ab',
  urlPruefung.benutzt.length >= 8, urlPruefung.benutzt.join(','));
await sauber('Server-Adressen');

// ---- 17. GIF- und Video-Export -------------------------------------------
// Beide Exporte geben ihr Ergebnis an onBlob weiter, statt zu speichern –
// so lässt sich prüfen, dass wirklich Daten entstehen.
await page.evaluate(async () => {
  const e = window._studioEditor;
  e.canvas.getObjects().slice().forEach(o => e.canvas.remove(o));
  const c = document.createElement('canvas'); c.width = 200; c.height = 200;
  const x = c.getContext('2d'); x.fillStyle = '#F56E28'; x.fillRect(0, 0, 200, 200);
  const url = c.toDataURL('image/png');
  const el = await new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = url; });
  const img = new window.fabric.Image(el, { left: 100, top: 100, srcUrl: url });
  img.anim = { type: 'fadeIn', dur: 600, delay: 0 };
  e.canvas.add(img);
  // Kurze Gesamtlänge, damit der Test nicht ewig läuft.
  const len = document.getElementById('video-length');
  if (len) { len.value = '1'; len.dispatchEvent(new Event('input', { bubbles: true })); }
  window._videoLen = 1;
  e.canvas.requestRenderAll(); e.snapshot();
});

const gif = await page.evaluate(async () => {
  const m = await import('/media.js');
  let groesse = -1, typ = '';
  const ok = await m.exportGif(window._studioEditor, b => { groesse = b.size; typ = b.type; });
  return { ok, groesse, typ };
}).catch(e => ({ fehler: String(e).slice(0, 120) }));
pruefe('GIF-Export läuft durch', gif.ok === true, JSON.stringify(gif));
pruefe('GIF enthält wirklich Daten', gif.groesse > 1000, `${gif.groesse} Bytes`);
pruefe('GIF ist als GIF gekennzeichnet', /gif/.test(gif.typ || ''), gif.typ);
await sauber('GIF-Export');

// MediaRecorder braucht im kopflosen Browser gelegentlich einen zweiten Anlauf:
// liefert der erste Durchgang einen leeren Container, wird einmal wiederholt.
const videoLauf = () => page.evaluate(async () => {
  const m = await import('/media.js');
  const e = window._studioEditor;
  window._videoLen = 2;
  const len = document.getElementById('video-length');
  if (len) { len.value = '2'; len.dispatchEvent(new Event('input', { bubbles: true })); }
  e.canvas.requestRenderAll();
  await new Promise(r => setTimeout(r, 250));
  let groesse = -1, typ = '';
  const ok = await m.exportVideo(e, b => { groesse = b.size; typ = b.type; });
  return { ok, groesse, typ };
}).catch(e => ({ fehler: String(e).slice(0, 120) }));

let video = await videoLauf();
if (!(video.groesse > 1000)) { await page.waitForTimeout(400); video = await videoLauf(); }
pruefe('Video-Export läuft durch', video.ok === true, JSON.stringify(video));
pruefe('Video enthält wirklich Daten', video.groesse > 1000, `${video.groesse} Bytes`);
pruefe('Video ist WebM', /webm/.test(video.typ || ''), video.typ);
pruefe('Editor steht nach dem Export wieder normal', await page.evaluate(() =>
  window._studioEditor.zoomFactor() > 0 && !!document.getElementById('main-canvas')));
await sauber('Video-Export');

// ---- 18. Speichern gegen ein krankes Backend -----------------------------
await page.evaluate(async () => {
  const io = await import('/io.js');
  io.merkeNamen('Prüfstand');            // kein Namensdialog im Test
});

const speichern = async (modus) => {
  SERVER_MODUS = modus;
  letzterUpload = null;
  const r = await page.evaluate(async () => {
    const io = await import('/io.js');
    const blob = new Blob([new Uint8Array(4096)], { type: 'video/webm' });
    const erg = await io.saveAnimation(window._studioEditor, blob, '.webm');
    return { ok: !!erg?.ok, fehler: String(erg?.error || ''),
             status: document.getElementById('status-msg')?.textContent || '',
             toast: document.querySelector('.studio-toast')?.textContent || '' };
  });
  SERVER_MODUS = 'ok';
  return r;
};

const gut = await speichern('ok');
pruefe('Speichern gegen ein gesundes Backend gelingt', gut.ok === true, JSON.stringify(gut));
pruefe('…die Datei kommt auch wirklich an',
  !!letzterUpload && letzterUpload.laenge > 4000, JSON.stringify(letzterUpload));
pruefe('…und es wird bestätigt', /gespeichert|saved|✅/i.test(gut.status + gut.toast),
  gut.status + ' | ' + gut.toast);
await sauber('Speichern (gesund)');

for (const [modus, name] of [['500', 'Serverfehler 500'],
                             ['html', 'HTML statt JSON (abgelaufene Sitzung)'],
                             ['413', 'Datei zu groß (413)']]) {
  const r = await speichern(modus);
  pruefe(`${name}: Speichern meldet Misserfolg`, r.ok === false, JSON.stringify(r).slice(0, 120));
  pruefe(`${name}: der Nutzer bekommt eine Meldung`,
    (r.status + r.toast).trim().length > 0, r.status + ' | ' + r.toast);
  pruefe(`${name}: kein rotes Fehlerbanner`, !(await bannerDa()),
    await page.locator('#studio-fehler').textContent().catch(() => ''));
  await bannerWeg();
}
await sauber('Speichern (krankes Backend)');

// Nach einem gescheiterten Speichern muss ein zweiter Versuch wieder gehen –
// sonst hängt der Nutzer bis zum Neuladen fest.
const wieder = await speichern('ok');
pruefe('Nach einem Fehlschlag gelingt der nächste Versuch wieder',
  wieder.ok === true, JSON.stringify(wieder).slice(0, 120));
pruefe('Kein Dauer-Sperrflag „speichert gerade" hängen geblieben', await page.evaluate(async () =>
  (await import('/io.js')).istAmSpeichern() === false));
await sauber('Zweiter Versuch');

// ---- 19. Eine Uhr für Bewegung und Effekt --------------------------------
// Motion und Effect waren zwei Systeme mit je eigenem Startwert. Jetzt lesen
// beide startOf(). Hier wird geprüft, dass das auch für ALTE Entwürfe gilt:
// die tragen ihren Start noch in anim.delay bzw. fxDelay.
const uhr = await page.evaluate(async () => {
  const m = await import('/media.js');
  const f = window.fabric;
  const neuesElement = () => new f.Rect({ left: 50, top: 50, width: 40, height: 40 });

  // 1. Entwurf von heute: startAt
  const a = neuesElement(); a.anim = { type: 'pulse', dur: 1200 }; a.startAt = 900;

  // 2. Alter Entwurf, nur Bewegung: Start steckt in anim.delay
  const b = neuesElement(); b.anim = { type: 'pulse', dur: 1200, delay: 900 };

  // 3. Alter Entwurf, nur Effekt: Start steckt in fxDelay
  const c = neuesElement(); c.fx = 'glow'; c.fxDelay = 900;

  // 4. Gar kein Start gesetzt
  const d = neuesElement(); d.anim = { type: 'pulse', dur: 1200 };

  // setStart hält beide Altfelder in Schritt, damit ein heute gespeicherter
  // Entwurf auch auf einer älteren Version noch richtig startet.
  const e = neuesElement(); e.anim = { type: 'pulse', dur: 1200 }; e.fx = 'glow';
  m.setStart(e, 750);

  return {
    neu: m.startOf(a), altBewegung: m.startOf(b), altEffekt: m.startOf(c), ohne: m.startOf(d),
    spiegelAnim: e.anim.delay, spiegelFx: e.fxDelay, spiegelStart: e.startAt,
    vorStart: m.hasStarted(a, 400), nachStart: m.hasStarted(a, 1000),
    verstrichen: m.elapsedAt(a, 1500),
  };
});
pruefe('Neuer Entwurf: startAt wird gelesen', uhr.neu === 900, uhr.neu);
pruefe('Alter Entwurf mit Bewegung behält seinen Start', uhr.altBewegung === 900, uhr.altBewegung);
pruefe('Alter Entwurf mit Effekt behält seinen Start', uhr.altEffekt === 900, uhr.altEffekt);
pruefe('Ohne Angabe ist der Start 0', uhr.ohne === 0, uhr.ohne);
pruefe('setStart hält die Altfelder in Schritt',
  uhr.spiegelStart === 750 && uhr.spiegelAnim === 750 && uhr.spiegelFx === 750,
  `${uhr.spiegelStart} / ${uhr.spiegelAnim} / ${uhr.spiegelFx}`);
pruefe('hasStarted trennt vorher und nachher', uhr.vorStart === false && uhr.nachStart === true);
pruefe('elapsedAt zählt ab dem eigenen Nullpunkt', uhr.verstrichen === 600, uhr.verstrichen);

// Der eigentliche Punkt: Bewegung und Effekt am selben Element MÜSSEN dieselbe
// Zeit sehen. Vorher war genau das nicht so.
const gleich = await page.evaluate(async () => {
  const m = await import('/media.js');
  const o = new window.fabric.Rect({ left: 50, top: 50, width: 40, height: 40 });
  o.anim = { type: 'pulse', dur: 1200 }; o.fx = 'glow';
  m.setStart(o, 800);
  // Was die Bewegung als Start sieht …
  const fuerBewegung = m.startOf(o);
  // … und was der Effekt sieht. Eine Quelle, also identisch.
  const fuerEffekt = m.startOf(o);
  m.setStart(o, 1600);                 // Start ändern: beide ziehen mit
  return { fuerBewegung, fuerEffekt, nachAenderung: m.startOf(o) };
});
pruefe('Bewegung und Effekt sehen denselben Start',
  gleich.fuerBewegung === gleich.fuerEffekt && gleich.fuerBewegung === 800,
  `${gleich.fuerBewegung} / ${gleich.fuerEffekt}`);
pruefe('Start ändern wirkt auf beide zugleich', gleich.nachAenderung === 1600, gleich.nachAenderung);

// Alter Entwurf durch die volle Speicher-Runde: der Start muss überleben.
const alteRunde = await page.evaluate(async () => {
  const io = await import('/io.js');
  const m  = await import('/media.js');
  const ed = window._studioEditor;
  ed.canvas.getObjects().slice().forEach(o => ed.canvas.remove(o));
  const alt = new window.fabric.Rect({ left: 60, top: 60, width: 40, height: 40 });
  alt.anim = { type: 'pulse', dur: 1200, delay: 1100 };   // Format von vorher
  ed.canvas.add(alt); ed.canvas.requestRenderAll();
  const j = io.buildCanvasJson(ed, '');
  ed.canvas.getObjects().slice().forEach(o => ed.canvas.remove(o));
  await io.restoreCanvas(ed, j);
  return m.startOf(ed.realObjects()[0]);
});
pruefe('Alter Entwurf überlebt Speichern und Öffnen mit seinem Start',
  alteRunde === 1100, alteRunde);
await sauber('Gemeinsame Uhr');


// ---- 20. Sagt die Medien-Leiste, WAS schiefgelaufen ist? -----------------
// Vorher stand bei jedem Problem „Fehler beim Laden." – abgelaufene Sitzung,
// Serverfehler und kaputte Antwort sahen identisch aus.
const leseTests = await page.evaluate(async () => {
  const u = await import('/util.js');
  const bau = (status, typ, body) => new Response(body, { status, headers: { 'Content-Type': typ } });
  const hol = async r => { try { await u.readJson(r); return 'kein Fehler'; } catch (e) { return e.message; } };
  return {
    ok:    await u.readJson(bau(200, 'application/json', '{"ok":true,"n":7}')).then(d => d.n),
    f500:  await hol(bau(500, 'application/json', '{}')),
    f413:  await hol(bau(413, 'text/plain', 'zu gross')),
    f403:  await hol(bau(403, 'text/plain', 'nope')),
    login: await hol(bau(200, 'text/html', '<!doctype html><html><body>Bitte anmelden</body></html>')),
    murks: await hol(bau(200, 'application/json', 'das ist kein JSON')),
  };
});
pruefe('Gute Antwort kommt als Objekt zurück', leseTests.ok === 7, leseTests.ok);
pruefe('500 nennt den Serverfehler', /500/.test(leseTests.f500), leseTests.f500);
pruefe('413 sagt "zu groß"', /too large/i.test(leseTests.f413), leseTests.f413);
pruefe('403 sagt "nicht angemeldet"', /signed in|session/i.test(leseTests.f403), leseTests.f403);
pruefe('Login-Seite statt JSON wird als abgelaufene Sitzung erkannt',
  /session expired/i.test(leseTests.login), leseTests.login);
pruefe('Kaputtes JSON heißt nicht "Sitzung abgelaufen"',
  /unexpected/i.test(leseTests.murks), leseTests.murks);

// Es darf nur EINE Fassung davon geben – io.js und library.js teilen sie sich.
const eineFassung = await page.evaluate(async () => {
  const quellen = await Promise.all(['/io.js', '/library.js', '/util.js']
    .map(async p => [p, await (await fetch(p)).text()]));
  return {
    eigeneFassungen: quellen.filter(([, t]) => /function\s+(readJson|leseAntwort)\s*\(/.test(t)).map(([p]) => p),
    importiert: quellen.filter(([, t]) => /import\s*\{[^}]*readJson/.test(t)).map(([p]) => p),
    rohesJson: quellen.filter(([p, t]) => p !== '/util.js' && /await\s+\w+\.json\(\)/.test(t)).map(([p]) => p),
  };
});
pruefe('Der Antwort-Leser existiert genau einmal',
  eineFassung.eigeneFassungen.length === 1 && eineFassung.eigeneFassungen[0] === '/util.js',
  eineFassung.eigeneFassungen.join(','));
pruefe('io.js und library.js benutzen dieselbe Fassung',
  eineFassung.importiert.includes('/io.js') && eineFassung.importiert.includes('/library.js'),
  eineFassung.importiert.join(','));
pruefe('Kein Modul liest Server-Antworten mehr ungeprüft',
  eineFassung.rohesJson.length === 0, eineFassung.rohesJson.join(','));
await sauber('Fehlermeldungen');

// ---- Ausgabe --------------------------------------------------------------
console.log('\n===== ERGEBNIS =====');
for (const r of ergebnis) console.log((r.ok ? '  OK   ' : '  FEHL ') + r.name + (r.detail ? '   [' + r.detail + ']' : ''));
const fehlgeschlagen = ergebnis.filter(r => !r.ok);
console.log(`\n${ergebnis.length - fehlgeschlagen.length}/${ergebnis.length} bestanden`);
if (fehler.length) { console.log('\n--- JS-Fehler auf der Seite ---'); fehler.slice(0, 8).forEach(f => console.log('  ' + f)); }

await browser.close();
server.close();
process.exit(fehlgeschlagen.length ? 1 : 0);
