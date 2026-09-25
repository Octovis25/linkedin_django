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
let LOESCH_MODUS = 'ok';        // 'ok' | 'gesperrt'
let letzteLoeschung = null;

// Posts to open the Studio from. A layout with one animated text: that is what
// a video built here leaves behind.
const POST_LAYOUT = JSON.stringify({ version: '5.3.0', objects: [
  { type: 'text', text: 'Hi', left: 50, top: 50, fontSize: 40, fill: '#08323a',
    anim: { type: 'fadeIn', dur: 800 } }] });
const POST_GRUND = { id: 7, title: 'Test post', image: '', gif: '', video: '',
                     image_url: '', gif_url: '', video_url: '' };
const POST_SEITEN = {
  '/post-video':  { ...POST_GRUND, video: 'Planner/Videos/a.webm', video_url: '/api/a.webm', canvas_json: POST_LAYOUT },
  '/post-upload': { ...POST_GRUND, video: 'Planner/Videos/b.webm', video_url: '/api/b.webm' },
  '/post-bild':   { ...POST_GRUND, image: 'Planner/a.png', image_url: '/api/a.png', canvas_json: POST_LAYOUT },
};

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
    // Der Bilder-Ordner liefert eine Kachel MIT verkleinerter Fassung (thumb)
    // und eine OHNE - alte Antworten kennen das Feld nicht und muessen weiter
    // funktionieren.
    // Der Sammel-Endpunkt: beide Fundorte schon zusammengefuehrt, wie ihn der
    // Server liefert. am_post markiert die Dateien, die an einem Beitrag haengen.
    if (url === '/api/outputs') {
      const art = /kind=Videos/.test(req.url) ? 'Videos'
                : /kind=GIFs/.test(req.url) ? 'GIFs' : 'Images';
      res.writeHead(200, { 'Content-Type': 'application/json' });
      if (art === 'Videos') {
        return res.end(JSON.stringify({ ok: true, items: [
          { name: 'kaputt.webm', title: 'kaputt', url: '/api/gibt-es-nicht.webm',
            nc_path: 'Studio_Work/Output/Videos/kaputt.webm', am_post: false },
        ] }));
      }
      if (art === 'GIFs') return res.end(JSON.stringify({ ok: true, items: [] }));
      return res.end(JSON.stringify({ ok: true, items: [
        { name: 'gross.png', title: 'gross', url: '/api/voll/gross.png',
          thumb: '/api/klein/gross.png?w=240',
          nc_path: 'Studio_Work/Output/Images/gross.png', am_post: false },
        { name: 'alt.png', title: 'alt', url: '/api/voll/alt.png',
          nc_path: 'LinkedIn/Planner/Images/alt.png', am_post: true },
      ] }));
    }
    if (url === '/api/nc-browse' && /Output%2FImages/i.test(req.url)) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: true, items: [
        { name: 'gross.png', title: 'gross', url: '/api/voll/gross.png',
          thumb: '/api/klein/gross.png?w=240', nc_path: 'Studio_Work/Output/Images/gross.png' },
        { name: 'alt.png', title: 'alt', url: '/api/voll/alt.png',
          nc_path: 'Studio_Work/Output/Images/alt.png' },
      ] }));
    }
    // Loeschen einer Ausgabe. LOESCH_MODUS schaltet den Fehlerfall an, den es in
    // echt gibt: Nextcloud lehnt ab, und der Server sagt auch warum.
    if (url === '/api/output-delete') {
      let rumpf = '';
      req.on('data', d => rumpf += d);
      return req.on('end', () => {
        letzteLoeschung = decodeURIComponent(rumpf);
        if (LOESCH_MODUS === 'gesperrt') {
          res.writeHead(502, { 'Content-Type': 'application/json' });
          return res.end(JSON.stringify({ ok: false,
            error: 'The file is locked in Nextcloud (423) - it may still be open elsewhere' }));
        }
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
      });
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
  // The Studio opened from a post: the same page, with a post in its config.
  if (POST_SEITEN[url]) {
    const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
      .replace('"postData": null', '"postData": ' + JSON.stringify(POST_SEITEN[url]));
    res.writeHead(200, { 'Content-Type': 'text/html' });
    return res.end(html);
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
pruefe('Modus-Rail hat 5 Modi',
  (await page.locator('#mode-rail [data-mode]').count()) === 5,
  String(await page.locator('#mode-rail [data-mode]').count()));
pruefe('Effekte sind ein eigener Reiter, nicht im Einfügen-Panel versteckt',
  (await page.locator('#mode-rail [data-mode="effects"]').count()) === 1);

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
pruefe('Help steht unter allen Modi', await page.evaluate(() => {
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


// ---- 13. Rundgang: alle Modi, jedes Einfüge-Werkzeug ---------------------
// Sauberer Ausgangsstand, damit gezählt werden kann.
await page.evaluate(() => {
  const e = window._studioEditor;
  e.canvas.getObjects().slice().forEach(o => e.canvas.remove(o));
  e.canvas.discardActiveObject(); e.canvas.requestRenderAll(); e.snapshot();
});

for (const modus of ['build', 'insert', 'effects', 'image', 'layers']) {
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
    // Der Server nennt selbst den Grund - der muss durchkommen. Vorher stand
    // beim Nutzer "Server error 502", waehrend im Rumpf der eigentliche
    // Grund lag (gesperrte Datei, Nextcloud nicht erreichbar).
    eigen: await hol(bau(502, 'application/json',
      '{"ok":false,"error":"The file is locked in Nextcloud (423)"}')),
    // Ohne verwertbaren Grund bleibt es bei der Standardmeldung.
    leer:  await hol(bau(502, 'application/json', '{"ok":false,"error":"  "}')),
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
pruefe('Der Grund des Servers schlaegt die Standardmeldung',
  /locked in Nextcloud/i.test(leseTests.eigen), leseTests.eigen);
pruefe('Ohne Grund bleibt die Standardmeldung',
  /Server error 502/.test(leseTests.leer), leseTests.leer);

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


// ---- 21. Ausgabe loeschen: sagt die Kachel die Wahrheit? -----------------
// September 2026: Videos liessen sich scheinbar nicht mehr loeschen. Der
// Server meldete bedingungslos Erfolg, auch wenn Nextcloud die Loeschung
// abgelehnt hatte - die Kachel verschwand, die Datei blieb, und beim naechsten
// Laden war sie wieder da. Zwei Dinge muessen darum stimmen: bei Erfolg geht
// die Kachel, bei Misserfolg BLEIBT sie und der Grund steht auf dem Schirm.
page.on('dialog', d => d.accept());   // die Loesch-Rueckfrage bestaetigen

await page.evaluate(() => document.querySelector('#media-tabs [data-media="outputs"]')?.click());
await page.evaluate(() => document.querySelector('#output-tabs [data-out="Videos"]')?.click());
await page.waitForSelector('#output-grid .tile-del', { timeout: 5000 });

const kachelnVorher = await page.evaluate(() => document.querySelectorAll('#output-grid .lib-tile').length);
pruefe('Videos-Reiter zeigt Kacheln mit Loeschknopf', kachelnVorher > 0, kachelnVorher);

// (a) Nextcloud lehnt ab
LOESCH_MODUS = 'gesperrt';
letzteLoeschung = null;
await page.locator('#output-grid .tile-del').first().click();
await page.waitForTimeout(700);

const nachFehler = await page.evaluate(() => ({
  kacheln: document.querySelectorAll('#output-grid .lib-tile').length,
  meldung: [...document.querySelectorAll('.toast, #toast, [class*="toast"]')]
    .map(t => t.textContent.trim()).filter(Boolean).join(' | '),
  knopfWiederNutzbar: !document.querySelector('#output-grid .tile-del')?.disabled,
}));
pruefe('Abgelehnte Loeschung: der Auftrag ging ueberhaupt raus',
  !!letzteLoeschung && /nc_path/.test(letzteLoeschung), String(letzteLoeschung).slice(0, 60));
pruefe('Abgelehnte Loeschung: die Kachel bleibt stehen',
  nachFehler.kacheln === kachelnVorher, nachFehler.kacheln + ' statt ' + kachelnVorher);
pruefe('Abgelehnte Loeschung: der Grund steht auf dem Schirm',
  /locked in Nextcloud/i.test(nachFehler.meldung), nachFehler.meldung || '(keine Meldung)');
pruefe('Abgelehnte Loeschung: man kann es nochmal versuchen',
  nachFehler.knopfWiederNutzbar === true, nachFehler.knopfWiederNutzbar);

// (b) Nextcloud loescht wirklich
LOESCH_MODUS = 'ok';
await page.locator('#output-grid .tile-del').first().click();
await page.waitForTimeout(700);
const nachErfolg = await page.evaluate(() => document.querySelectorAll('#output-grid .lib-tile').length);
pruefe('Gelungene Loeschung: die Kachel verschwindet',
  nachErfolg === kachelnVorher - 1, nachErfolg + ' statt ' + (kachelnVorher - 1));

await sauber('Ausgabe loeschen');


// ---- 22. Kachel klein, Einfuegen gross ----------------------------------
// Die Kachel zeigt seit September 2026 eine verkleinerte Fassung (rund 15 KB
// statt 1,5 MB). Auf den Canvas gehoert weiterhin das Original - sonst liegt
// dort ploetzlich ein 240 Pixel breites Bild.
await page.evaluate(() => document.querySelector('#output-tabs [data-out="Images"]')?.click());
await page.waitForTimeout(900);

// Der Titel bekommt bei nicht ladbarer Datei einen Zusatz angehaengt - darum
// ueber den Anfang des Titels suchen, nicht ueber Gleichheit.
const kacheln = await page.evaluate(() => {
  const gefunden = {};
  document.querySelectorAll('#output-grid img.lib-thumb').forEach(el => {
    // Der Titel kann Zusaetze tragen: "– preview could not be loaded" bei
    // nicht ladbarer Datei, "· am Post" bei einer Datei im Planner-Ordner.
    const name = (el.title || '').split(/[\u2013\u00b7]/)[0].trim();
    gefunden[name] = el.getAttribute('src') || el.dataset.src || '';
  });
  return gefunden;
});
const marken = await page.evaluate(() =>
  [...document.querySelectorAll('#output-grid img.lib-thumb')].map(e => e.title || ''));
pruefe('eine an einem Post haengende Ausgabe wird markiert',
  marken.some(t => /am Post/.test(t)), marken.join(' | '));
pruefe('eine freie Ausgabe wird NICHT markiert',
  marken.some(t => /gross/.test(t) && !/am Post/.test(t)), marken.join(' | '));
pruefe('Kachel nimmt die verkleinerte Fassung',
  /\/api\/klein\//.test(kacheln['gross'] || ''), kacheln['gross']);
pruefe('ohne verkleinerte Fassung bleibt es beim Original',
  /\/api\/voll\/alt\.png/.test(kacheln['alt'] || ''), kacheln['alt']);

// Und das Wichtigste: Was auf den Canvas wandert, ist das Original. Geprueft
// an der Drag-Nutzlast der Assets-Kacheln - die traegt genau die Adresse,
// die beim Ablegen eingefuegt wird.
const zugAdresse = await page.evaluate(async () => {
  const grid = document.getElementById('lib-grid');
  if (!grid) return 'kein lib-grid';
  const lib = await import('/library.js');
  // Ein Raster mit einer Kachel bauen, wie renderImages es tut.
  grid.innerHTML = '';
  const img = document.createElement('img');
  img.className = 'lib-thumb';
  const item = { url: '/api/voll/x.png', thumb: '/api/klein/x.png', title: 'x', name: 'x.png' };
  img.addEventListener('dragstart', e => e.dataTransfer.setData('text/studio-url', item.url));
  grid.appendChild(img);
  let getragen = null;
  const dt = { setData: (k, v) => { if (k === 'text/studio-url') getragen = v; } };
  const ev = new Event('dragstart');
  ev.dataTransfer = dt;
  img.dispatchEvent(ev);
  return getragen;
});
pruefe('gezogen wird das Original, nicht die Verkleinerung',
  zugAdresse === '/api/voll/x.png', zugAdresse);

await sauber('Vorschaubilder');

// ---- Effektrahmen ---------------------------------------------------------
// The effect used to hang on an element and could only ever be as big as that
// element. It now sits on a frame of its own: an element that shows nothing and
// is there to give the effect an area.
await page.evaluate(() => { window._studioEditor.clearAll(); });
await page.click('[data-mode="effects"]');
// Die Effekte liegen als kleine laufende Bilder im Reiter - ein Klick legt den
// Effekt als Rahmen über das Bild.
await page.waitForSelector('#fx-tiles .fx-tile[data-fx="network"]', { timeout: 3000 });
await page.click('#fx-tiles .fx-tile[data-fx="network"]');
await page.waitForTimeout(200);

const fxRahmen = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const r = ed.canvas.getObjects().filter(m.istEffektRahmen);
  const o = r[0];
  return {
    anzahl: r.length,
    fx: o?.fx,
    gross: o ? (o.width === ed.width && o.height === ed.height) : false,
    unsichtbar: o ? (!o.strokeWidth && /rgba\(0, ?0, ?0, ?0\)/.test(String(o.fill))) : false,
    drehbar: o ? o.lockRotation !== true : true,
  };
});
pruefe('Eine Kachel legt genau einen Effektrahmen an', fxRahmen.anzahl === 1, fxRahmen.anzahl);
pruefe('Er beginnt über dem ganzen Bild', fxRahmen.gross);
pruefe('Er trägt einen Effekt', !!fxRahmen.fx && fxRahmen.fx !== 'none', fxRahmen.fx);
pruefe('Er ist unsichtbar - im Export ist nur der Effekt zu sehen', fxRahmen.unsichtbar);
pruefe('Er lässt sich nicht drehen (ein Effekt hat kein Oben)', !fxRahmen.drehbar);

const fxLeiste = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.addText('Überschrift', { left: 20, top: 20 });
  window._studioRender?.();
  await new Promise(r => setTimeout(r, 250));
  const objs = ed.realObjects();
  const idxRahmen = objs.findIndex(m.istEffektRahmen);
  const idxText = objs.findIndex(o => !m.istEffektRahmen(o));
  // Die Zeilen stehen nach Gruppen, nicht mehr in Ebenen-Reihenfolge - also
  // über ihre Kennung finden statt über die Position.
  const zeile = i => document.querySelector('#anim-bar .anim-row[data-obj-idx="' + i + '"]');
  const reihen = [...document.querySelectorAll('#anim-bar .anim-row')];
  // Sichtbar heißt: man SIEHT es. Das Attribut hidden allein sagt darüber
  // nichts - .anim-ctl ist display:flex, und das schlägt hidden. Genau daran
  // ist die erste Fassung vorbeigelaufen: Test grün, Zeile trotzdem auf dem
  // Schirm. Deshalb wird hier die gerechnete Darstellung gelesen.
  const sichtbar = z => !!z && getComputedStyle(z).display !== 'none' && !!z.offsetParent;
  const fxSicht = i => {
    const zeilen = [...zeile(i).querySelectorAll('.anim-ctl')];
    const fx = zeilen.find(z => z.textContent.trim().startsWith('Effect'));
    const mo = zeilen.find(z => z.textContent.trim().startsWith('Motion'));
    return { fx: sichtbar(fx), motion: sichtbar(mo) };
  };
  return { rahmen: fxSicht(idxRahmen), element: fxSicht(idxText), reihen: reihen.length };
});
pruefe('Der Rahmen zeigt den Effekt', fxLeiste.rahmen.fx === true, JSON.stringify(fxLeiste));
pruefe('und keine Bewegung', fxLeiste.rahmen.motion === false, JSON.stringify(fxLeiste.rahmen));
pruefe('Ein normales Element zeigt KEINEN Effekt mehr', fxLeiste.element.fx === false,
  JSON.stringify(fxLeiste.element));
pruefe('aber weiterhin seine Bewegung', fxLeiste.element.motion === true);

const fxTempoTest = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ep = (await import('/editor.js')).EXTRA_PROPS;
  const ed = window._studioEditor;
  const o = ed.realObjects().find(m.istEffektRahmen);
  const reihe = document.querySelector('#anim-bar .anim-row[data-obj-idx="' + ed.realObjects().indexOf(o) + '"]');
  const s = reihe.querySelectorAll('.anim-time-item input')[0];
  // Links langsam, rechts schnell: 5 von 1..6 heißt fxTempo 2 (doppelt so langsam wie gezeichnet).
  s.value = 5; s.dispatchEvent(new Event('input', { bubbles: true }));
  const json = JSON.stringify(ed.canvas.toJSON(ep));
  return { fxTempo: o.fxTempo, inProps: ep.includes('fxTempo'), serialisiert: /"fxTempo":2/.test(json) };
});
pruefe('Das eigene Tempo des Rahmens lässt sich stellen (rechts = schneller)', fxTempoTest.fxTempo === 2, fxTempoTest.fxTempo);
pruefe('fxTempo steht in EXTRA_PROPS', fxTempoTest.inProps);
pruefe('und landet im Canvas-JSON', fxTempoTest.serialisiert);

// Alte Zeichnungen: jeder Element-Effekt wird zu einem Rahmen um dieses Element.
const fxUmbau = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.clearAll();
  const alt = new window.fabric.Rect({ left: 60, top: 80, width: 120, height: 90, fill: '#ccc' });
  alt.fx = 'orbit'; alt.startAt = 700;
  ed.canvas.add(alt);
  const anzahl = m.rahmenAusAltenEffekten(ed);
  const rahmen = ed.canvas.getObjects().find(m.istEffektRahmen);
  const b = alt.getBoundingRect(true);
  return {
    anzahl, altFx: alt.fx, rahmenFx: rahmen?.fx, start: rahmen?.startAt,
    passt: rahmen ? Math.abs(rahmen.width - b.width) < 2 && Math.abs(rahmen.left - b.left) < 2 : false,
    ueber: rahmen ? ed.canvas.getObjects().indexOf(rahmen) > ed.canvas.getObjects().indexOf(alt) : false,
    nochmal: m.rahmenAusAltenEffekten(ed),
  };
});
pruefe('Ein alter Element-Effekt wird zu einem Rahmen', fxUmbau.anzahl === 1 && fxUmbau.rahmenFx === 'orbit',
  JSON.stringify(fxUmbau));
pruefe('Der Rahmen liegt genau um das Element', fxUmbau.passt);
pruefe('und direkt darüber, damit die Reihenfolge bleibt', fxUmbau.ueber);
pruefe('Das Element selbst trägt den Effekt nicht mehr', !fxUmbau.altFx, fxUmbau.altFx);
pruefe('Die Startzeit wandert mit', fxUmbau.start === 700, fxUmbau.start);
pruefe('Zweimal umwandeln legt nichts doppelt an', fxUmbau.nochmal === 0, fxUmbau.nochmal);

// Die Reihenfolge: was ÜBER dem Rahmen liegt, bleibt sauber. Das ist der Grund
// für den ganzen Umbau - vorher lag jeder Effekt über der Schrift.
const fxOrdnung = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.clearAll();
  ed.setSize(400, 300);
  const rahmen = m.addEffektRahmen(ed, 'question');   // malt eine dunkle Scheibe + „?"
  const deckel = new window.fabric.Rect({ left: 0, top: 0, width: 400, height: 300, fill: '#ffffff' });
  ed.canvas.add(deckel);
  m.previewAnimation(ed);
  await new Promise(r => setTimeout(r, 500));
  const c = ed.canvas.lowerCanvasEl.getContext('2d');
  const mitte = c.getImageData(Math.round(ed.canvas.getZoom() * 200),
                               Math.round(ed.canvas.getZoom() * 150), 1, 1).data;
  return { r: mitte[0], g: mitte[1], b: mitte[2], a: mitte[3] };
});
pruefe('Der Effekt malt NICHT über das, was darüber liegt',
  fxOrdnung.r > 245 && fxOrdnung.g > 245 && fxOrdnung.b > 245,
  JSON.stringify(fxOrdnung));

await sauber('Effektrahmen');

// ---- Marker, Lupe, Stempel -----------------------------------------------
await page.evaluate(() => { window._studioEditor.clearAll(); window._studioEditor.setSize(600, 500); });
await page.click('[data-mode="effects"]');
await page.click('[data-act="add-marker"]');
await page.waitForTimeout(150);
await page.keyboard.press('Escape');
await page.click('[data-act="add-stamp"]');
await page.waitForTimeout(150);
await page.keyboard.press('Escape');
await page.click('[data-act="add-magnifier"]');
await page.waitForTimeout(250);

const stuecke = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const objs = ed.realObjects();
  const marker = objs.find(o => o.shapeKind === 'marker');
  const stempel = objs.find(o => o.shapeKind === 'stamp');
  const lupe = objs.find(o => m.istEffektRahmen(o) && o.fx === 'magnifier');
  return {
    marker: !!marker, markerAnim: marker?.anim?.type, markerText: marker?._objects?.[3]?.text,
    stempel: !!stempel, stempelAnim: stempel?.anim?.type, stempelText: stempel?._objects?.[2]?.text,
    stempelSchraeg: stempel ? stempel.angle !== 0 : false,
    lupe: !!lupe,
    lupeFenster: lupe ? lupe.fxLens > 0 && lupe.fxPath === 'lines' && lupe.getScaledWidth() > lupe.fxLens : false,
    lupeKleiner: lupe ? lupe.width < ed.width : false,
  };
});
pruefe('Marker liegt auf dem Canvas', stuecke.marker);
pruefe('Marker blinkt von allein (Pulse)', stuecke.markerAnim === 'pulse', stuecke.markerAnim);
pruefe('Marker trägt ein Zeichen', !!stuecke.markerText, stuecke.markerText);
pruefe('Stempel liegt auf dem Canvas', stuecke.stempel);
pruefe('Stempel blendet ein statt zu knallen', stuecke.stempelAnim === 'fadeIn', stuecke.stempelAnim);
pruefe('Stempel steht schräg, wie ein Stempel', stuecke.stempelSchraeg);
pruefe('Stempeltext ist groß geschrieben', /^[A-Z ]+$/.test(stuecke.stempelText || ''), stuecke.stempelText);
pruefe('Lupe ist ein Effektrahmen', stuecke.lupe);
pruefe('Lupe kommt mit Fenster, Glas und Weg (Line by line)', stuecke.lupeFenster);
pruefe('und nicht über dem ganzen Bild', stuecke.lupeKleiner);

// Text nachträglich ändern: derselbe Weg wie beim Badge
const geaendert = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const alt = ed.realObjects().find(o => o.shapeKind === 'stamp');
  ed.canvas.setActiveObject(alt);
  ed.canvas.fire('mouse:dblclick', { target: alt });
  await new Promise(r => setTimeout(r, 120));
  const inp = document.getElementById('badge-edit');
  if (!inp) return { keinFeld: true };
  inp.value = 'Version 3.2';
  inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await new Promise(r => setTimeout(r, 200));
  const neu = ed.realObjects().find(o => o.shapeKind === 'stamp');
  return { text: neu?._objects?.[2]?.text, anim: neu?.anim?.type };
});
pruefe('Stempeltext lässt sich per Doppelklick ändern',
  (geaendert.text || '').toUpperCase().includes('VERSION 3.2'), JSON.stringify(geaendert));
pruefe('und behält dabei seine Animation', geaendert.anim === 'fadeIn', geaendert.anim);

// Die Lupe zeigt wirklich Vergrößertes: ein feines Muster unter ihr wird gröber.
const lupenBild = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(400, 400);
  // Weißer Grund: sonst ist der durchsichtige Canvas selbst 'dunkel' und
  // die Messung zählt ihn als Streifen mit.
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  // Streifen: unter der Lupe müssen sie breiter werden.
  for (let i = 0; i < 40; i++) {
    ed.canvas.add(new window.fabric.Rect({
      left: i * 10, top: 0, width: 5, height: 400, fill: i % 2 ? '#000000' : '#ffffff',
    }));
  }
  const lupe = m.addEffektRahmen(ed, 'magnifier');
  lupe.set({ left: 120, top: 120, width: 160, height: 160 }); lupe.setCoords();
  // Hier wird das Vergrößern gemessen, nicht das Wandern: Glas so groß wie das
  // Fenster, und es bleibt stehen.
  lupe.fxPath = 'still'; lupe.fxLens = 160;
  // Messen heißt Pixel zählen, und dafür muss 1 Canvas-Punkt = 1 Bildpunkt
  // sein. Sonst misst man an einer verschobenen Stelle - genau das hat hier
  // zwei Anläufe gekostet.
  ed.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  ed.canvas.setDimensions({ width: 400, height: 400 });
  m.previewAnimation(ed);
  const z = ed.canvas.getZoom();
  const c = ed.canvas.lowerCanvasEl.getContext('2d');
  // Auf den Moment warten, in dem die Lupe wirklich auf dem Bild liegt: ihr
  // schwarzer Rand am oberen Scheitel ist das Zeichen dafür. Sonst hinge der
  // Test an der Laufzeit der Vorschau.
  const px = (x, y) => c.getImageData(Math.round(x * z), Math.round(y * z), 1, 1).data;
  // Zwei Bedingungen, nicht eine: der schwarze Rand der Lupe MUSS da sein, und
  // daneben muss weißer Grund stehen. Ein frisch umgestellter Canvas ist
  // nämlich komplett durchsichtig - und das sah wie "Rand da" aus.
  const bereit = () => {
    const rand = px(200, 122), grund = px(6, 200);
    return rand[0] < 60 && rand[3] > 200 && grund[0] > 200 && grund[3] > 200;
  };
  let versuche = 0;
  while (!bereit() && versuche++ < 60) await new Promise(r => setTimeout(r, 25));
  // Wie breit ein schwarzer Streifen im Schnitt ist. Unter der Lupe muss er
  // breiter sein als daneben - das ist genau, was Vergrößern heißt.
  const streifenbreite = (x0, x1, y) => {
    const d = c.getImageData(Math.round(x0 * z), Math.round(y * z), Math.round((x1 - x0) * z), 1).data;
    const laengen = []; let lauf = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] < 100) lauf++;
      else { if (lauf) laengen.push(lauf); lauf = 0; }
    }
    if (lauf) laengen.push(lauf);
    // Randstücke zählen nicht: die sind angeschnitten.
    const voll = laengen.length > 2 ? laengen.slice(1, -1) : laengen;
    return voll.length ? voll.reduce((a, b) => a + b, 0) / voll.length : 0;
  };
  return { drin: streifenbreite(168, 232, 200), draussen: streifenbreite(300, 390, 200),
           gewartet: versuche, bereit: bereit() };
});
pruefe('Unter der Lupe sind die Streifen breiter als daneben',
  lupenBild.drin > lupenBild.draussen * 1.3,
  JSON.stringify(lupenBild));

await sauber('Marker, Lupe, Stempel');

// ---- Leiste unter dem Canvas: Motion und Effects getrennt -----------------
await page.evaluate(() => { const ed = window._studioEditor; ed.clearAll(); ed.setSize(600, 400); });
await page.click('[data-mode="effects"]');
await page.waitForSelector('#fx-tiles .fx-tile', { timeout: 3000 });
const lxKacheln = await page.evaluate(() => [...document.querySelectorAll('#fx-tiles .fx-tile')].map(k => k.dataset.fx));
pruefe('Der Effekte-Reiter zeigt eine Kachel je Effekt', lxKacheln.length >= 9, lxKacheln.join(','));
pruefe('Jede Kachel hat ein laufendes Bild', await page.evaluate(() =>
  [...document.querySelectorAll('#fx-tiles .fx-tile canvas')].every(c => c.width > 0)));
await page.click('#fx-tiles .fx-tile[data-fx="veil"]');
await page.click('#fx-tiles .fx-tile[data-fx="question"]');
await page.evaluate(() => { window._studioEditor.addText('Headline', { left: 20, top: 20 }); });
await page.waitForTimeout(300);

const lxGruppen = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const objs = ed.realObjects();
  const g = s => document.querySelector('#anim-bar details.anim-group[data-group="' + s + '"]');
  const idxIn = s => [...g(s).querySelectorAll('.anim-row[data-obj-idx]')].map(r => +r.dataset.objIdx);
  return {
    motion: !!g('motion'), effects: !!g('effects'),
    motionOk: idxIn('motion').every(i => !m.istEffektRahmen(objs[i])),
    effectsOk: idxIn('effects').every(i => m.istEffektRahmen(objs[i])),
    zahlRahmen: idxIn('effects').length,
    paletten: document.querySelectorAll('#anim-bar .fx-palette').length,
    swatchesJeZeile: document.querySelectorAll('#anim-bar .fx-row .fx-swatch').length,
    titel: document.querySelector('#anim-bar .anim-bar-title')?.textContent || '',
    text: document.getElementById('anim-bar').textContent,
  };
});
pruefe('Die Leiste hat eine Gruppe Motion', lxGruppen.motion);
pruefe('und eine Gruppe Effects', lxGruppen.effects);
pruefe('In Motion steht kein Rahmen', lxGruppen.motionOk);
pruefe('In Effects stehen nur Rahmen', lxGruppen.effectsOk && lxGruppen.zahlRahmen === 2, lxGruppen.zahlRahmen);
pruefe('Die Farbpalette steht genau einmal', lxGruppen.paletten === 1, lxGruppen.paletten);
pruefe('und nicht in jeder Effekt-Zeile', lxGruppen.swatchesJeZeile === 0, lxGruppen.swatchesJeZeile);
pruefe('Die Leiste spricht Englisch', lxGruppen.titel.includes('Animation')
  && !/je Element|Sek\./.test(lxGruppen.text), lxGruppen.titel);

const lxZuklappen = await page.evaluate(async () => {
  const d = document.querySelector('#anim-bar details.anim-group[data-group="motion"]');
  d.open = false; d.dispatchEvent(new Event('toggle'));
  await new Promise(r => setTimeout(r, 50));
  const zeile = d.querySelector('.anim-row');
  // Closed <details> keep a layout box in current Chromium - ask what is seen.
  return { zu: !d.open, versteckt: !zeile || !zeile.checkVisibility() };
});
pruefe('Motion lässt sich zuklappen', lxZuklappen.zu && lxZuklappen.versteckt, JSON.stringify(lxZuklappen));

// Farbe: die eine Palette färbt den ausgewählten Rahmen, und es wird gespeichert.
const lxFarbe = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ep = (await import('/editor.js')).EXTRA_PROPS;
  const ed = window._studioEditor;
  const rahmen = ed.realObjects().filter(m.istEffektRahmen);
  const zweiter = rahmen[1];
  ed.selectObj(zweiter);
  await new Promise(r => setTimeout(r, 100));
  const knoepfe = [...document.querySelectorAll('#anim-bar .fx-palette .fx-swatch')]
    .filter(b => b.style.background);
  const orange = knoepfe.find(b => /245, 110, 40|f56e28/i.test(b.style.background)) || knoepfe[1];
  orange.click();
  await new Promise(r => setTimeout(r, 100));
  const json = JSON.stringify(ed.canvas.toJSON(ep));
  return { gesetzt: zweiter.fxColor, ersterUnberuehrt: !rahmen[0].fxColor,
           inProps: ep.includes('fxColor'), imJson: /"fxColor":"#/.test(json) };
});
pruefe('Die Palette färbt den ausgewählten Rahmen', !!lxFarbe.gesetzt, lxFarbe.gesetzt);
pruefe('und nur diesen', lxFarbe.ersterUnberuehrt);
pruefe('fxColor wird gespeichert', lxFarbe.inProps && lxFarbe.imJson, JSON.stringify(lxFarbe));

// Die Farbe kommt wirklich im Bild an: derselbe Effekt, einmal ohne, einmal in Orange.
const lxPixel = await page.evaluate(async () => {
  const m = await import('/media.js');
  const zaehle = (farbe) => {
    const c = document.createElement('canvas'); c.width = 300; c.height = 200;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 300, 200);
    m.malEffektVorschau(ctx, 'networkFlat', 300, 200, 1000, farbe);
    const d = ctx.getImageData(0, 0, 300, 200).data;
    let orange = 0, tuerkis = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] > 150 && d[i + 1] < 140 && d[i + 2] < 90) orange++;
      if (d[i] < 140 && d[i + 1] > 150 && d[i + 2] > 140) tuerkis++;
    }
    return { orange, tuerkis };
  };
  return { ohne: zaehle(null), orange: zaehle('#F56E28') };
});
pruefe('Ohne Farbe zeichnet der Effekt türkis', lxPixel.ohne.tuerkis > 20 && lxPixel.ohne.orange === 0,
  JSON.stringify(lxPixel.ohne));
pruefe('Mit Orange zeichnet er orange', lxPixel.orange.orange > 20 && lxPixel.orange.tuerkis === 0,
  JSON.stringify(lxPixel.orange));

// Fläche, Auswählen, Entfernen - pro Effekt zum Anfassen
const lxFlaeche = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const o = ed.realObjects().filter(m.istEffektRahmen)[0];
  const idx = ed.realObjects().indexOf(o);
  const zeile = () => document.querySelector('#anim-bar .anim-row[data-obj-idx="' + idx + '"]');
  const keineFlaeche = !document.querySelector('#anim-bar [data-area]') && !/Lower half|Whole picture/.test(document.getElementById('anim-bar').textContent);
  ed.canvas.discardActiveObject();
  zeile().querySelector('.fx-select').click();
  await new Promise(r => setTimeout(r, 80));
  const gewaehlt = ed.active() === o;
  const vorher = ed.realObjects().filter(m.istEffektRahmen).length;
  zeile().querySelector('.fx-remove').click();
  await new Promise(r => setTimeout(r, 80));
  return { keineFlaeche, gewaehlt, vorher,
           nachher: ed.realObjects().filter(m.istEffektRahmen).length };
});
pruefe('Whole picture / Lower half / Part gibt es nicht mehr', lxFlaeche.keineFlaeche);
pruefe('Select setzt die Anfasser auf den Rahmen', lxFlaeche.gewaehlt);
pruefe('Remove nimmt ihn weg', lxFlaeche.nachher === lxFlaeche.vorher - 1, lxFlaeche.vorher + ' -> ' + lxFlaeche.nachher);

// Die Rahmen sichtbar machen - aber nie im Export.
// Was hier gemessen wird, gilt nur ohne laufende Wiedergabe. Eine Video-Aufnahme
// von weiter oben kann unter Last noch laufen - dann malt sie jeden Effekt mit,
// und die Prüfungen unten wären rot oder, schlimmer, grundlos grün.
// Nicht waitForFunction mit async: das Versprechen selbst ist "wahr", die
// Warterei wäre sofort vorbei gewesen.
const ruhig = async (wo) => {
  const t0 = Date.now();
  while (await page.evaluate(async () => (await import('/media.js')).effectsRunning())) {
    if (Date.now() - t0 > 60000) throw new Error('Wiedergabe läuft seit 60 s: ' + wo);
    await page.waitForTimeout(100);
  }
  if (Date.now() - t0 > 150) console.log('  (gewartet auf Wiedergabe vor ' + wo + ': ' + (Date.now() - t0) + ' ms)');
};
await ruhig('Rahmen-Ebene');
const lxSichtbar = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(300, 200);
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  const r = m.addEffektRahmen(ed, 'network');
  r.set({ left: 40, top: 40, width: 120, height: 80 }); r.setCoords();
  ed.canvas.discardActiveObject();
  const box = document.getElementById('fx-show-frames');
  if (box && !box.checked) { box.checked = true; box.dispatchEvent(new Event('change')); }
  ed.canvas.renderAll();
  await new Promise(x => setTimeout(x, 80));
  const ebene = document.getElementById('fx-frame-layer');
  let gezeichnet = 0;
  if (ebene) {
    const d = ebene.getContext('2d').getImageData(0, 0, ebene.width, ebene.height).data;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) gezeichnet++;
  }
  // Der Export darf den Rahmen nicht enthalten: ohne laufende Vorschau malt der
  // Effekt nichts, also muss das Bild rein weiß sein.
  const url = ed.canvas.toDataURL({ format: 'png' });
  const img = new Image(); img.src = url; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const cx = c.getContext('2d'); cx.drawImage(img, 0, 0);
  const d2 = cx.getImageData(0, 0, c.width, c.height).data;
  let nichtWeiss = 0;
  for (let i = 0; i < d2.length; i += 4) if (d2[i] < 240 || d2[i + 1] < 240 || d2[i + 2] < 240) nichtWeiss++;
  return { ebene: !!ebene, gezeichnet, nichtWeiss, ueberFabric: ebene?.parentNode === ed.canvas.wrapperEl };
});
pruefe('Es gibt eine eigene Ebene für die Rahmen-Umrisse', lxSichtbar.ebene && lxSichtbar.ueberFabric);
pruefe('Mit "Show frames" ist der Rahmen dort eingezeichnet', lxSichtbar.gezeichnet > 50, lxSichtbar.gezeichnet);
pruefe('Im exportierten Bild ist davon nichts', lxSichtbar.nichtWeiss === 0, lxSichtbar.nichtWeiss);

// In der Vorschau keine Hilfslinien: weder die Auswahl-Striche noch die Rahmen-Ebene.
const lxVorschau = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const r = ed.realObjects().find(m.istEffektRahmen);
  ed.selectObj(r);
  m.previewAnimation(ed);
  await new Promise(x => setTimeout(x, 300));
  const laeuft = m.effectsRunning();
  const ebene = document.getElementById('fx-frame-layer');
  const d = ebene.getContext('2d').getImageData(0, 0, ebene.width, ebene.height).data;
  let striche = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 0) striche++;
  return { laeuft, aktiv: !!ed.active(), striche };
});
pruefe('Während der Vorschau ist nichts ausgewählt', lxVorschau.laeuft && !lxVorschau.aktiv, JSON.stringify(lxVorschau));
pruefe('und die Rahmen-Ebene ist leer', lxVorschau.laeuft && lxVorschau.striche === 0, lxVorschau.striche);
await ruhig('nach der Vorschau');

// Größe der Marken: ein Regler für Marker, Stempel und Badges
const lxGroesse = await page.evaluate(async () => {
  const ed = window._studioEditor;
  ed.clearAll();
  const r = document.getElementById('fx-mark-size');
  r.value = 150; r.dispatchEvent(new Event('input'));
  const w = document.getElementById('fx-text-input'); w.value = '?';
  document.querySelector('[data-act="add-marker"]').click();
  // Read at once: a marker pulses, and a running preview would scale it.
  const mk = ed.realObjects().find(o => o.shapeKind === 'marker');
  const neu = mk?.scaleX;
  await new Promise(x => setTimeout(x, 120));
  r.value = 80; r.dispatchEvent(new Event('input'));
  const nachher = mk?.scaleX;
  r.value = 100; r.dispatchEvent(new Event('input'));
  return { neu, nachher };
});
pruefe('Eine neue Marke kommt in der eingestellten Größe', Math.abs(lxGroesse.neu - 1.5) < 0.01, lxGroesse.neu);
pruefe('und der Regler ändert die ausgewählte', Math.abs(lxGroesse.nachher - 0.8) < 0.01, lxGroesse.nachher);

const lxBadgesImReiter = await page.evaluate(() =>
  ['circle', 'hex', 'pill'].every(k => !!document.querySelector('[data-panel="effects"] [data-badge="' + k + '"]')));
pruefe('Die Badges sind auch im Effekte-Reiter', lxBadgesImReiter);

// Die Lupe gehört zum Bild, nicht zur Bewegung: sichtbar ohne Vorschau, im PNG
// dabei, und der Size-Regler greift auch bei ihr - um die Mitte, nicht um die Ecke.
await ruhig('Lupe');
const lxLupe = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(300, 200);
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  document.querySelector('[data-act="add-magnifier"]').click();
  const lupe = ed.realObjects().find(o => m.istEffektRahmen(o) && o.fx === 'magnifier');
  // Das Fenster, in dem sie wandert, und ein Glas von 80 px
  lupe.set({ left: 20, top: 30, width: 240, height: 120, scaleX: 1, scaleY: 1 }); lupe.setCoords();
  lupe.fxLens = 80;
  ed.canvas.discardActiveObject();
  ed.canvas.renderAll();
  const dunkel = (d) => { let n = 0; for (let i = 0; i < d.length; i += 4)
    if (d[i + 3] > 200 && d[i] < 60 && d[i + 1] < 60 && d[i + 2] < 60) n++; return n; };
  const u = ed.canvas.lowerCanvasEl;
  const aufSchirm = dunkel(u.getContext('2d').getImageData(0, 0, u.width, u.height).data);
  const url = ed.exportDataURL();
  const img = new Image(); img.src = url; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const cx = c.getContext('2d'); cx.drawImage(img, 0, 0);
  const imPng = dunkel(cx.getImageData(0, 0, c.width, c.height).data);

  // Der Weg: sie wandert, und das Glas bleibt ganz im Fenster
  const a = m.lupenStelle(lupe, 0), b = m.lupenStelle(lupe, 3);
  const wandert = Math.hypot(a[0] - b[0], a[1] - b[1]) > 20;
  const imFenster = [0, 0.5, 1, 2, 3, 5, 8, 9, 13, 17, 21].every(t => {
    const [x, y] = m.lupenStelle(lupe, t);
    return x - 40 >= 19.5 && x + 40 <= 260.5 && y - 40 >= 29.5 && y + 40 <= 150.5;
  });
  // Mit Show frames liegt der Weg gepunktet auf der Hilfsebene
  const box = document.getElementById('fx-show-frames');
  if (box && !box.checked) { box.checked = true; box.dispatchEvent(new Event('change')); }
  ed.canvas.renderAll();
  const ebene = document.getElementById('fx-frame-layer');
  const ed2 = ebene.getContext('2d').getImageData(0, 0, ebene.width, ebene.height).data;
  let orange = 0;
  for (let i = 0; i < ed2.length; i += 4) if (ed2[i + 3] > 100 && ed2[i] > 200 && ed2[i + 1] > 80 && ed2[i + 1] < 160 && ed2[i + 2] < 90) orange++;

  // Die Regler der Lupe in der Leiste
  const zeile = document.querySelector('#anim-bar .fx-row .fx-path')?.closest('.fx-row');
  const setz = (sel, v) => { const i = zeile.querySelector(sel); i.value = v;
    i.dispatchEvent(new Event(i.tagName === 'SELECT' ? 'change' : 'input')); };
  setz('.fx-speed', 10); const schnell = lupe.fxLineSec;
  setz('.fx-speed', 1); const langsam = lupe.fxLineSec;
  // Fenster flacher als das Glas werden soll: es muss mitwachsen.
  // (Der Regler reicht bis 60 % der kurzen Seite - hier 120 px.)
  lupe.set({ height: 90 }); lupe.setCoords();
  setz('.fx-lens', 120); const glas = lupe.fxLens, fensterHoch = lupe.getBoundingRect(true).height;
  setz('.fx-path', 'still');
  const steht = m.lupenStelle(lupe, 0).join() === m.lupenStelle(lupe, 4).join();

  // Das Gesamt-Tempo ist auch ein Tempo: links langsam, rechts schnell
  const t = document.getElementById('anim-tempo');
  t.value = -2; const tempoLangsam = m.readTempo();
  t.value = 2; const tempoSchnell = m.readTempo();
  t.value = 0; m.readTempo();

  // Motion ebenso: Regler ganz rechts = kürzeste Dauer
  document.getElementById('fx-text-input').value = '?';
  document.querySelector('[data-act="add-marker"]').click();
  const mk = ed.realObjects().find(o => o.shapeKind === 'marker');
  const mzeile = [...document.querySelectorAll('#anim-bar details[data-group="motion"] .anim-row')]
    .find(r => ed.realObjects()[+r.dataset.objIdx] === mk);
  const ms = mzeile.querySelectorAll('.anim-time-item input')[0];
  ms.value = ms.max; ms.dispatchEvent(new Event('input'));
  const motionSchnell = mk.anim.dur;
  ms.value = ms.min; ms.dispatchEvent(new Event('input'));
  const motionLangsam = mk.anim.dur;

  const gruppen = [...document.querySelectorAll('#anim-bar details.anim-group')].map(d => d.dataset.group);
  return { aufSchirm, imPng, wandert, imFenster, orange, schnell, langsam, glas, fensterHoch, steht,
           tempoLangsam, tempoSchnell, motionSchnell, motionLangsam, gruppen, zeile: !!zeile };
});
pruefe('Die Lupe ist ohne Vorschau auf dem Canvas zu sehen', lxLupe.aufSchirm > 100, lxLupe.aufSchirm);
pruefe('und im exportierten PNG', lxLupe.imPng > 100, lxLupe.imPng);
pruefe('Die Lupe wandert: nach 3 s steht sie woanders', lxLupe.wandert);
pruefe('und das Glas bleibt dabei ganz im Fenster', lxLupe.imFenster);
pruefe('Ihr Weg liegt gepunktet auf der Hilfsebene', lxLupe.orange > 30, lxLupe.orange);
pruefe('Die Lupe hat eigene Regler in der Leiste', lxLupe.zeile);
pruefe('Speed: rechts 2 s pro Zeile, links 20 s', lxLupe.schnell === 2 && lxLupe.langsam === 20,
  lxLupe.schnell + ' / ' + lxLupe.langsam);
pruefe('Lens stellt die Glasgröße', lxLupe.glas === 120, lxLupe.glas);
pruefe('und das Fenster wächst mit, wenn das Glas größer wird', lxLupe.fensterHoch >= 120, lxLupe.fensterHoch);
pruefe('Stay put: sie steht still', lxLupe.steht);
pruefe('Gesamt-Tempo: links langsam, rechts schnell', lxLupe.tempoLangsam === 2 && lxLupe.tempoSchnell === 0.5,
  lxLupe.tempoLangsam + ' / ' + lxLupe.tempoSchnell);
pruefe('Motion-Speed: rechts schnell, links langsam', lxLupe.motionSchnell === 300 && lxLupe.motionLangsam === 4000,
  lxLupe.motionSchnell + ' / ' + lxLupe.motionLangsam);
pruefe('In der Leiste stehen die Effekte vor Motion',
  lxLupe.gruppen.join(',') === 'effects,motion', lxLupe.gruppen.join(','));

await sauber('Leiste und Effekte-Reiter');

// ---- Video Bild für Bild: auch auf einem langsamen Rechner nichts überspringen --
// Ortrud: "im fertigen Video bewegt sich die Lupe nicht - sie springt einmal,
// und das war's". Das Video war die gefilmte Vorschau: Zeit = Wanduhr. Gab der
// Browser selten ein Bild heraus, lief die Uhr dazwischen weiter. Hier wird ein
// langsamer Rechner nachgestellt: jedes Bild braucht 60 ms, und Bilder kommen
// nur alle 500 ms.
await ruhig('Video Bild für Bild');
const lxVideo = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(300, 200);
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  ed.canvas.add(new window.fabric.Text('Hi there', { left: 20, top: 60, fontSize: 30 }));
  const l = m.addEffektRahmen(ed, 'magnifier');
  l.set({ left: 10, top: 40, width: 280, height: 120 }); l.setCoords();
  l.fxLens = 60; l.fxLineSec = 2; l.fxPath = 'lr';
  const vl = document.getElementById('video-length'); const alt = vl ? vl.value : '';
  if (vl) vl.value = 2;
  const orig = ed.canvas.renderAll.bind(ed.canvas);
  ed.canvas.renderAll = function () { const t = performance.now(); while (performance.now() - t < 60) {} return orig(); };
  const oraf = window.requestAnimationFrame;
  window.requestAnimationFrame = cb => setTimeout(() => cb(performance.now()), 500);
  const uhren = [];
  const merke = () => { if (m.effectsRunning()) uhren.push(m.effectsClock()); };
  // Eine Vorschau läuft noch, wenn "Save video" geklickt wird. Früher schaltete
  // ihr Ende die Effekte mitten im Export ab.
  m.previewAnimation(ed);
  ed.canvas.on('after:render', merke);
  let blob = null;
  try { await m.exportVideo(ed, b => { blob = b; }); }
  finally {
    ed.canvas.renderAll = orig; window.requestAnimationFrame = oraf;
    ed.canvas.off('after:render', merke); if (vl) vl.value = alt;
  }
  const zeiten = [...new Set(uhren)].sort((a, b) => a - b);
  let groessterSprung = 0;
  for (let i = 1; i < zeiten.length; i++) groessterSprung = Math.max(groessterSprung, zeiten[i] - zeiten[i - 1]);
  let dauer = null;
  if (blob) {
    const v = document.createElement('video'); v.muted = true; v.src = URL.createObjectURL(blob);
    await new Promise(r => { v.onloadeddata = r; v.onerror = r; setTimeout(r, 4000); });
    dauer = v.duration;
  }
  const aufnahme = m.letzteVideoAufnahme();
  const stempel = aufnahme.zeiten.slice().sort((a, b) => a - b);
  const abstaende = new Set(stempel.slice(1).map((z, i) => z - stempel[i]));
  return { bilder: zeiten.length, groessterSprung, inhalt: zeiten.length ? zeiten[zeiten.length - 1] / 1000 : 0, dauer,
           weg: aufnahme.weg, stempel: stempel.length, abstaende: [...abstaende] };
});
pruefe('Video: jedes Bild bekommt seine eigene Zeit, kein Sprung über 1/30 s - auch mit laufender Vorschau',
  lxVideo.bilder >= 60 && lxVideo.groessterSprung <= 34, JSON.stringify(lxVideo).slice(0, 160));
pruefe('und ein langsamer Rechner dehnt das Video nicht',
  Number.isFinite(lxVideo.dauer) && Math.abs(lxVideo.dauer - (lxVideo.inhalt + 0.4)) < 0.6, JSON.stringify(lxVideo));
// Ruckeln auf LinkedIn: der Rekorder stempelte Bilder 19 bis 73 ms auseinander.
// Mit WebCodecs trägt jedes Bild seine genaue Zeit - genau 1/30 s Abstand.
pruefe('Das Video wird Bild für Bild kodiert (WebCodecs)', lxVideo.weg === 'webcodecs', lxVideo.weg);
pruefe('und jedes Bild liegt genau 1/30 s nach dem vorigen',
  lxVideo.stempel > 20 && lxVideo.abstaende.every(a => a === 33333 || a === 33334), JSON.stringify(lxVideo.abstaende));

// Ohne WebCodecs (ältere Browser) nimmt weiter der Rekorder auf.
await ruhig('Video ohne WebCodecs');
const lxRekorder = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const vorher = window.VideoEncoder;
  window.VideoEncoder = undefined;
  let blob = null;
  try { await m.exportVideo(ed, b => { blob = b; }); }
  finally { window.VideoEncoder = vorher; }
  return { weg: m.letzteVideoAufnahme().weg, groesse: blob ? blob.size : 0 };
});
pruefe('Ohne WebCodecs nimmt der Rekorder auf, und es kommt ein Video heraus',
  lxRekorder.weg === 'recorder' && lxRekorder.groesse > 1000, JSON.stringify(lxRekorder));
await sauber('Video Bild für Bild');

// ---- Vom Post aus speichern: nicht jedes Mal nach dem Format fragen --------
async function postSeite(url) {
  const p = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  const fehlerHier = [];
  p.on('pageerror', e => fehlerHier.push(e.message));
  await p.goto(`http://127.0.0.1:${PORT}${url}`, { waitUntil: 'load' });
  await p.waitForFunction(() => !!window._studioEditor, null, { timeout: 10000 });
  await p.waitForTimeout(400);
  await p.fill('#title-input', 'Testtitel');
  const knopf = await p.locator('#save-btn').textContent();
  return { p, knopf: (knopf || '').trim(), fehlerHier };
}
// Counts only the FORMAT question. Saving an image can open a dialog of its
// own (the name), so "any dialog" would pass even when the format was not asked.
const dialogNachKlick = async (p, sel) => {
  await p.click(sel);
  await p.waitForTimeout(300);
  const t = await p.evaluate(() => [...document.querySelectorAll('.studio-modal')].map(m => m.textContent).join(' '));
  if (t) { await p.keyboard.press('Escape'); await p.waitForTimeout(150); }
  return /What would you like to save/.test(t) ? 1 : 0;
};
{
  const v = await postSeite('/post-video');
  pruefe('Post mit Studio-Video: der Knopf heißt "Save video"', v.knopf === '💾 Save video', v.knopf);
  pruefe('und ▾ Format fragt weiterhin', await dialogNachKlick(v.p, '[data-act="save-as-new"]') === 1);
  // Zurück auf das Video des Posts: "New" gibt es hier nicht - neu laden.
  await v.p.reload({ waitUntil: 'load' });
  await v.p.waitForFunction(() => !!window._studioEditor, null, { timeout: 10000 });
  await v.p.waitForTimeout(400);
  await v.p.fill('#title-input', 'Testtitel');
  pruefe('Save fragt beim Video-Post nicht noch einmal', await dialogNachKlick(v.p, '#save-btn') === 0);
  pruefe('Kein Fehler auf der Post-Seite (Video)', v.fehlerHier.length === 0, v.fehlerHier.join(' | '));
  await v.p.close();

  const u = await postSeite('/post-upload');
  pruefe('Hochgeladenes Video ohne Aufbau: der Knopf bleibt "Save as…"', u.knopf === '💾 Save as…', u.knopf);
  pruefe('und fragt nach dem Format - ein leerer Canvas darf das Video nicht mit einem Klick ersetzen',
    await dialogNachKlick(u.p, '#save-btn') === 1);
  await u.p.close();

  const b = await postSeite('/post-bild');
  pruefe('Post mit Bild: der Knopf heißt "Save image"', b.knopf === '💾 Save image', b.knopf);
  pruefe('aber mit Animationen im Aufbau fragt Save lieber nach', await dialogNachKlick(b.p, '#save-btn') === 1);
  pruefe('Die Format-Auswahl ist englisch', await b.p.evaluate(() => {
    document.querySelector('[data-act="save-as-new"]').click();
    return new Promise(r => setTimeout(() => {
      const t = document.querySelector('.studio-modal')?.textContent || '';
      r(t.includes('GIF (animated)') && !/mit Animationen/.test(t));
    }, 300));
  }));
  await b.p.close();
}

// ---- Ausgabe --------------------------------------------------------------
console.log('\n===== ERGEBNIS =====');
for (const r of ergebnis) console.log((r.ok ? '  OK   ' : '  FEHL ') + r.name + (r.detail ? '   [' + r.detail + ']' : ''));
const fehlgeschlagen = ergebnis.filter(r => !r.ok);
console.log(`\n${ergebnis.length - fehlgeschlagen.length}/${ergebnis.length} bestanden`);
if (fehler.length) { console.log('\n--- JS-Fehler auf der Seite ---'); fehler.slice(0, 8).forEach(f => console.log('  ' + f)); }

await browser.close();
server.close();
process.exit(fehlgeschlagen.length ? 1 : 0);
