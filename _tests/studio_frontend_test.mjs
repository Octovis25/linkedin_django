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

const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  // Stub the backend: every /api/ call answers with empty, well-formed JSON so
  // the boot steps run through instead of dying on a 404.
  if (url.startsWith('/api/')) {
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

const fehler = [];
page.on('pageerror', e => fehler.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error') fehler.push('console: ' + m.text()); });

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

// ---- 3. Modus Image: sind die Werkzeuge jetzt aktiv? ----------------------
await page.click('#mode-rail [data-mode="image"]');
await page.waitForTimeout(120);
pruefe('Image-Panel ist mit Bild nicht mehr ausgegraut',
  !(await page.locator('#retouch-body.is-disabled').count()));
const startTool = await page.getAttribute('#retouch-body [data-toolkey="erase"]', 'data-tool');
pruefe('Erase startet auf "fill" (Klick-Fläche)', startTool === 'fill', startTool);

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

// ---- 5. Reichweite wechseln: Pinsel ---------------------------------------
await page.click('#scope-seg [data-scope="brush"]');
await page.waitForTimeout(150);
const brushTool = await page.getAttribute('#retouch-body [data-toolkey="erase"]', 'data-tool');
pruefe('Reichweite "Brush" schaltet Erase auf "erase"', brushTool === 'erase', brushTool);
pruefe('Pinselgröße erscheint nur beim Pinsel',
  await page.locator('#brush-row').isVisible());

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

// ---- Ausgabe --------------------------------------------------------------
console.log('\n===== ERGEBNIS =====');
for (const r of ergebnis) console.log((r.ok ? '  OK   ' : '  FEHL ') + r.name + (r.detail ? '   [' + r.detail + ']' : ''));
const fehlgeschlagen = ergebnis.filter(r => !r.ok);
console.log(`\n${ergebnis.length - fehlgeschlagen.length}/${ergebnis.length} bestanden`);
if (fehler.length) { console.log('\n--- JS-Fehler auf der Seite ---'); fehler.slice(0, 8).forEach(f => console.log('  ' + f)); }

await browser.close();
server.close();
process.exit(fehlgeschlagen.length ? 1 : 0);
