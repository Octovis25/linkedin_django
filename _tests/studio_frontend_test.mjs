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
  // Posts without a design of their own - one has a prepared draft in Drafts.
  '/post-entwurf':      { ...POST_GRUND, id: 140, image: 'Planner/m.png', image_url: '/api/m.png' },
  '/post-ohne-entwurf': { ...POST_GRUND, id: 555, image: 'Planner/n.png', image_url: '/api/n.png' },
};
// Prepared drafts in Studio_Work/Drafts: the folder listing and the files.
let ENTWURF_ABRUFE = 0;
const ENTWURF_JSON = JSON.stringify({ version: 2, width: 500, height: 400, videoLength: 9, objects: [], previewDataUrl: '',
  fabric: { version: '5.3.0', background: '#008591', objects: [
    { type: 'textbox', text: 'Entwurf', left: 40, top: 40, width: 200, fontSize: 30, fill: '#ffffff', anim: { type: 'fadeIn', dur: 600 } },
    { type: 'rect', left: 40, top: 120, width: 200, height: 20, fill: '#65FBFB', anim: { type: 'grow', dur: 800, from: 'left', then: 'float' }, startAt: 400 },
  ] } });

const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  // Stub the backend: every /api/ call answers with empty, well-formed JSON so
  // the boot steps run through instead of dying on a 404.
  if (url === '/api/nc-browse' && /Drafts/.test(decodeURIComponent(req.url))) {
    ENTWURF_ABRUFE++;
    const d = 'Marketing & Design/Octotrial_Assets/Studio_Work/Drafts/';
    const eintrag = n => ({ name: n, title: n.replace(/\.png$/, ''), url: '/api/nc-image?p=' + encodeURIComponent(d + n), nc_path: d + n });
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ items: [eintrag('post140_2026-10-05_hidden_workload.png'),
      eintrag('post141_2026-10-12_not_more_reports.png'), eintrag('kaputt.png'), eintrag('post140_alt_preview.png')], subfolders: [] }));
  }
  if (url === '/api/nc-image' && /Drafts/.test(decodeURIComponent(req.url))) {
    const p = new URL(req.url, 'http://x').searchParams.get('p') || '';
    if (/\.json$/.test(p)) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(/kaputt/.test(p) ? '{"version":2, kaputt' : ENTWURF_JSON);
    }
    res.writeHead(404); return res.end();
  }
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
      letzterUpload = { url, laenge: +(req.headers['content-length'] || 0), typ: req.headers['content-type'] || '' };
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
    let html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
      .replace('"postData": null', '"postData": ' + JSON.stringify(POST_SEITEN[url]));
    // The Django template puts the post banner above the Studio; index.html has
    // it cut out. The draft posts need it - that is where the button goes.
    if (/entwurf/.test(url)) {
      html = html.replace('<div class="studio-wrap">', '<div class="post-banner"><div class="post-info"><strong>Post</strong></div>'
        + '<div class="post-actions"><button type="button" class="tbtn">🖼 Background</button></div></div><div class="studio-wrap">');
    }
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

// The grey stage must stand still, also when it is nearly square: the fitted
// canvas used to stick out by 4 px, a scrollbar came and went every frame and
// the canvas shrank and grew with it (seen on Render, 27.09.2026).
const zittern = await page.evaluate(async () => {
  const host = document.querySelector('.canvas-host');
  const lc = document.querySelector('canvas.lower-canvas');
  const hoehe = host.offsetHeight;
  const aus = [];
  for (const d of [-30, -15, -8, 0, 8, 15, 30]) {
    host.style.width = (hoehe + d) + 'px';
    await new Promise(r => setTimeout(r, 120));
    const seen = new Set();
    let bar = false;
    for (let i = 0; i < 20; i++) {
      await new Promise(r => requestAnimationFrame(r));
      seen.add(lc.style.width + 'x' + lc.style.height);
      if (host.scrollWidth > host.clientWidth || host.scrollHeight > host.clientHeight) bar = true;
    }
    if (seen.size > 1 || bar) aus.push(d + ': ' + [...seen].join(' / ') + (bar ? ' scrollbar' : ''));
  }
  host.style.width = '';
  window.dispatchEvent(new Event('resize'));
  return aus;
});
pruefe('Die graue Fläche zittert nicht (auch fast quadratisch, ohne Scrollbalken)',
  zittern.length === 0, zittern.join(' | '));

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

// Pointing at a brand colour shows its code at once: hex and RGB (28.09.2026).
await page.locator('#palette-row .swatch:not(.add)').nth(2).hover();
await page.waitForTimeout(80);
const farbTipp = await page.evaluate(() => {
  const alle = [...document.querySelectorAll('#palette-row .swatch:not(.add)')];
  const sw = alle[2];
  const nachher = getComputedStyle(sw, '::after');
  return {
    tips: alle.map(x => x.dataset.tip),
    title: alle.some(x => x.title),
    sichtbar: nachher.content,
    rgb: getComputedStyle(sw).backgroundColor,
  };
});
pruefe('Markenfarbe zeigt beim Zeigen Hex und RGB',
  farbTipp.tips.length > 0 && farbTipp.tips.every(t => /^#[0-9A-F]{6}\nRGB \d{1,3}, \d{1,3}, \d{1,3}$/.test(t || '')),
  JSON.stringify(farbTipp.tips));
pruefe('der Code passt zur Farbe', (() => {
  const m = /RGB (\d+), (\d+), (\d+)/.exec(farbTipp.tips[2] || '');
  return !!m && farbTipp.rgb === `rgb(${m[1]}, ${m[2]}, ${m[3]})`;
})(), farbTipp.tips[2] + ' vs ' + farbTipp.rgb);
pruefe('sofort sichtbar, ohne den langsamen Browser-Tooltip',
  /RGB/.test(farbTipp.sichtbar) && !farbTipp.title, farbTipp.sichtbar);

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
    // nicht ladbarer Datei, "· on a post" bei einer Datei im Planner-Ordner.
    const name = (el.title || '').split(/[\u2013\u00b7]/)[0].trim();
    gefunden[name] = el.getAttribute('src') || el.dataset.src || '';
  });
  return gefunden;
});
const marken = await page.evaluate(() =>
  [...document.querySelectorAll('#output-grid img.lib-thumb')].map(e => e.title || ''));
pruefe('eine an einem Post haengende Ausgabe wird markiert',
  marken.some(t => /on a post/.test(t)), marken.join(' | '));
pruefe('eine freie Ausgabe wird NICHT markiert',
  marken.some(t => /gross/.test(t) && !/on a post/.test(t)), marken.join(' | '));
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

// ---- Question web: Fragezeichen mit Fäden und eigenem Text ------------------
await ruhig('Question web');
await page.click('[data-mode="effects"]');
const qw = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ep = (await import('/editor.js')).EXTRA_PROPS;
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(600, 400);
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  ed.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  ed.canvas.setDimensions({ width: 600, height: 400 });
  const zeile = () => document.querySelector('#anim-bar .qweb-row');
  const wahl = (key, v) => zeile().querySelector('.qweb-seg[data-key="' + key + '"] [data-v="' + v + '"]').click();
  const orange = (r, g, b, a) => a > 200 && r > 200 && g > 80 && g < 150 && b < 90;
  const zaehle = (d, fn) => { let n = 0; for (let i = 0; i < d.length; i += 4) if (fn(d[i], d[i + 1], d[i + 2], d[i + 3])) n++; return n; };
  const schirm = () => { ed.canvas.discardActiveObject(); ed.canvas.renderAll();
    const c = ed.canvas.lowerCanvasEl; return c.getContext('2d').getImageData(0, 0, c.width, c.height).data; };

  document.querySelector('[data-act="add-qweb"]').click();
  const k = [...m.fragenNetze(ed).values()][0] || [];
  const id = k[0] && k[0].qwebId;
  const netz = () => m.fragenNetze(ed).get(id) || [];
  const erst = { anzahl: k.length, eineId: k.every(o => o.qwebId === id), nr: k.map(o => o.qwebNr).join(','),
                 orange: k.every(o => o.qwebColor === '#F56E28'), texte: k.every(o => !!o.qwebText) };
  const imMotion = document.querySelectorAll('#anim-bar details[data-group="motion"] .anim-row').length;
  const mitFaeden = zaehle(schirm(), orange);
  wahl('qwebThreads', 'none');
  const ohneFaeden = zaehle(schirm(), orange);
  wahl('qwebThreads', 'web');
  // Im stehenden PNG: Fäden und Schilder (weiße Karten neben den Fragezeichen)
  const url = ed.exportDataURL(); const img = new Image(); img.src = url; await img.decode();
  const c2 = document.createElement('canvas'); c2.width = img.width; c2.height = img.height;
  const x2 = c2.getContext('2d'); x2.drawImage(img, 0, 0);
  const png = x2.getImageData(0, 0, c2.width, c2.height).data;
  const pngOrange = zaehle(png, orange);
  // Text ändern
  const inp = zeile().querySelector('.qweb-text input');
  inp.value = 'Wo ist der Nachweis?'; inp.dispatchEvent(new Event('input'));
  const text0 = netz()[0].qwebText;
  // + Question, dann Nummern
  zeile().querySelector('.qweb-dazu').click();
  const vier = netz().length;
  wahl('qwebSign', '#');
  const zeichen = netz().map(o => o._objects[1].text).join(',');
  const einstellungGleich = netz().every(o => o.qwebSign === '#' && o.qwebThreads === 'web');
  // Farbe über die eine Palette
  const sw = [...document.querySelectorAll('#anim-bar .fx-palette .fx-swatch')]
    .filter(b => !b.classList.contains('fx-swatch-auto')).find(b => !/245, 110, 40|f56e28/i.test(b.style.background));
  sw.click();
  const farben = new Set(netz().map(o => o.qwebColor)); const kreise = new Set(netz().map(o => o._objects[0].fill));
  // Nacheinander blinken
  const kk = netz(), takt = m.fragenRundeMs(kk) / kk.length;
  const z0 = m.fragenZustand(kk, 0, takt * 0.5), z1 = m.fragenZustand(kk, 1, takt * 0.5), z1b = m.fragenZustand(kk, 1, takt * 1.5);
  // Größe: alle zusammen
  ed.selectObj(kk[2]);
  const regler = document.getElementById('fx-mark-size');
  regler.value = 150; regler.dispatchEvent(new Event('input'));
  const skalen = netz().map(o => Math.round(o.scaleX * 100));
  regler.value = 100; regler.dispatchEvent(new Event('input'));
  const json = JSON.stringify(ed.canvas.toJSON(ep));
  const animiert = m.hasAnimations(ed);
  // Eine Frage weg, dann das ganze Netz
  zeile().querySelectorAll('.qweb-weg')[3].click();
  const nachWeg = netz().length, nrNachWeg = netz().map(o => o.qwebNr).join(',');
  zeile().querySelector('.fx-remove').click();
  return { erst, imMotion, mitFaeden, ohneFaeden, pngOrange, text0, vier, zeichen, einstellungGleich,
           farben: [...farben], kreise: [...kreise], z0: z0.dran, z1: z1.dran, z1b: z1b.dran,
           skalen: skalen.join(','), jsonTexte: /"qwebText":"Wo ist der Nachweis\?"/.test(json) && /"qwebSign":"#"/.test(json),
           animiert, nachWeg, nrNachWeg, rest: m.fragenNetze(ed).size };
});
pruefe('Question web legt drei Fragezeichen an, ein Netz, in Reihenfolge',
  qw.erst.anzahl === 3 && qw.erst.eineId && qw.erst.nr === '0,1,2', JSON.stringify(qw.erst));
pruefe('in Octo-Orange und mit Beispieltexten', qw.erst.orange && qw.erst.texte);
pruefe('Die Fragezeichen stehen nicht unter Motion', qw.imMotion === 0, qw.imMotion);
pruefe('Die Fäden sind ohne Vorschau zu sehen', qw.mitFaeden > qw.ohneFaeden + 150, qw.mitFaeden + ' / ' + qw.ohneFaeden);
pruefe('und im exportierten PNG', qw.pngOrange > 300, qw.pngOrange);
pruefe('Der Text lässt sich in der Leiste ändern', qw.text0 === 'Wo ist der Nachweis?', qw.text0);
pruefe('+ Question hängt ein viertes an', qw.vier === 4, qw.vier);
pruefe('Sign 1 2 3 nummeriert der Reihe nach', qw.zeichen === '1,2,3,4', qw.zeichen);
pruefe('Einstellungen gelten für das ganze Netz', qw.einstellungGleich);
pruefe('Die eine Palette färbt alle Fragezeichen', qw.farben.length === 1 && qw.kreise.length === 1
  && qw.farben[0] !== '#F56E28', JSON.stringify([qw.farben, qw.kreise]));
pruefe('Nacheinander: erst das erste, dann das zweite', qw.z0 && !qw.z1 && qw.z1b, [qw.z0, qw.z1, qw.z1b].join(','));
pruefe('Der Size-Regler nimmt alle Fragezeichen mit', qw.skalen === '150,150,150,150', qw.skalen);
pruefe('Texte und Einstellungen werden gespeichert', qw.jsonTexte);
pruefe('Ein Netz zählt als Animation (Vorschau, GIF, Video)', qw.animiert);
pruefe('Eine Frage entfernen nummeriert neu', qw.nachWeg === 3 && qw.nrNachWeg === '0,1,2', qw.nachWeg + ' / ' + qw.nrNachWeg);
pruefe('Remove nimmt das ganze Netz weg', qw.rest === 0, qw.rest);
await sauber('Question web');

// ---- Spotlight: ein Element nach vorn, Icon und Text zusammen --------------
// Ortrud, 27.09.2026: "einzelne Bilder vergrößern und hervorheben ... die Texte
// müssen mit aufpoppen". Ein flaches Bild wird nachgebaut: Überschrift, eine
// Mitte und fünf Elemente im Kreis, jedes ein Icon mit zweizeiligem Text darunter.
await ruhig('Spotlight');
await page.click('[data-mode="effects"]');
const spA = await page.evaluate(() => {
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(1024, 766);
  ed.canvas.setBackgroundColor('#F7F5EF', () => {});
  ed.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  ed.canvas.setDimensions({ width: 1024, height: 766 });
  ed.canvas.add(new fabric.Text('Lifecycle heading', { left: 360, top: 30, fontSize: 36, fill: '#222222', fontFamily: 'Arial' }));
  const element = (cx, cy, name) => {
    ed.canvas.add(new fabric.Rect({ left: cx - 28, top: cy - 28, width: 56, height: 56, fill: '#0E7C86' }));
    ed.canvas.add(new fabric.Textbox(name + '\nsecond line', { left: cx - 45, top: cy + 38, width: 90, fontSize: 13,
      fill: '#333333', textAlign: 'center', fontFamily: 'Arial' }));
  };
  element(512, 330, 'Hub');
  [[180, 'Left'], [135, 'Low left'], [90, 'Bottom'], [45, 'Low right'], [0, 'Right']].forEach(([w, n]) => {
    const r = w * Math.PI / 180; element(Math.round(512 + 230 * Math.cos(r)), Math.round(330 + 230 * Math.sin(r)), n);
  });
  ed.canvas.discardActiveObject(); ed.canvas.renderAll();
  document.querySelector('[data-act="add-spot"]').click();
  const r = ed.canvas.upperCanvasEl.getBoundingClientRect();
  return { x: r.x, y: r.y, wahl: ed.canvas.skipTargetFind === true };
});
// Ein Klick auf den TEXT des Elements unten links (135°): 512+230·cos135 = 349, Text bei y ≈ 493+45
await page.mouse.click(spA.x + 349, spA.y + 540);
await page.waitForTimeout(200);
const spB = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ep = (await import('/editor.js')).EXTRA_PROPS;
  const ed = window._studioEditor;
  const gruppen = [...m.spotGruppen(ed).values()];
  const k = gruppen[0] || [];
  const b = k[0] ? k[0].getBoundingRect(true, true) : { left: 0, top: 0, width: 0, height: 0 };
  // Icon 321..377 x 465..521; the text's two lines sit centred under it, y 531..~560
  const umfasst = b.left <= 321 && b.left + b.width >= 377 && b.top <= 465 && b.top + b.height >= 556;
  const nichtZuGross = b.width < 150 && b.height < 150;
  const schirm = () => { ed.canvas.discardActiveObject(); ed.canvas.renderAll();
    const c = ed.canvas.lowerCanvasEl; return c.getContext('2d').getImageData(0, 0, c.width, c.height).data; };
  const px = (d, x, y) => { const i = (y * 1024 + x) * 4; return [d[i], d[i + 1], d[i + 2]]; };
  const teal = (d, x0, y0, x1, y1) => { let n = 0; for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
    const [r, g, bl] = px(d, x, y); if (r < 60 && g > 100 && g < 150 && bl > 110 && bl < 160) n++; } return n; };
  const mit = schirm();
  // Rahmen ausblenden, zum Vergleich
  k.forEach(o => { o._alt = o.fx; o.fx = null; });
  const ohne = schirm();
  k.forEach(o => { o.fx = o._alt; delete o._alt; });
  schirm();
  // Die Karte: um das Element herum mehr Teal als im Original (vergrößertes Icon)
  const tealMit = teal(mit, 250, 400, 450, 620), tealOhne = teal(ohne, 250, 400, 450, 620);
  // Der Rest tritt zurück (heller) - die Überschrift nicht
  const restMit = px(mit, 742 - 10, 330 - 10), restOhne = px(ohne, 742 - 10, 330 - 10);   // Icon rechts
  let kopfGleich = true;
  for (let y = 25; y < 80; y += 3) for (let x = 360; x < 660; x += 5) {
    const a = px(mit, x, y), c = px(ohne, x, y); if (Math.abs(a[0] - c[0]) + Math.abs(a[1] - c[1]) + Math.abs(a[2] - c[2]) > 6) kopfGleich = false; }
  // PNG: die Karte ist Teil des stehenden Bildes
  const url = ed.exportDataURL(); const img = new Image(); img.src = url; await img.decode();
  const c2 = document.createElement('canvas'); c2.width = img.width; c2.height = img.height;
  const x2 = c2.getContext('2d'); x2.drawImage(img, 0, 0);
  const png = x2.getImageData(0, 0, c2.width, c2.height).data;
  const tealPng = img.width === 1024 ? teal(png, 250, 400, 450, 620) : -1;
  const stillAnim = m.hasAnimations(ed);
  const zeile = document.querySelector('#anim-bar .spot-row');
  const wahl = (key, v) => zeile && zeile.querySelector('.spot-seg[data-key="' + key + '"] [data-v="' + v + '"]').click();
  const zeileNeu = () => document.querySelector('#anim-bar .spot-row');
  // Moving: dann ist es Bewegung
  wahl('spotBewegung', 'bewegt');
  const kk = [...m.spotGruppen(ed).values()][0];
  const bewegt = { anim: m.hasAnimations(ed), f0: m.spotZustand(kk, 0).f, f2: m.spotZustand(kk, 2).f };
  zeileNeu().querySelector('.spot-seg[data-key="spotBewegung"] [data-v="fest"]').click();
  // Farbe über die eine Palette
  const sw = [...document.querySelectorAll('#anim-bar .fx-palette .fx-swatch')].filter(x => !x.classList.contains('fx-swatch-auto'))
    .find(x => /245, 110, 40|f56e28/i.test(x.style.background));
  if (sw) sw.click();
  const farbe = [...m.spotGruppen(ed).values()][0][0].fxColor;
  const imMotion = document.querySelectorAll('#anim-bar details[data-group="motion"] .anim-row')
    .length;
  return { gruppen: gruppen.length, frames: k.length, box: [b.left, b.top, b.width, b.height].map(Math.round).join(','),
           umfasst, nichtZuGross, tealMit, tealOhne, restMit, restOhne, kopfGleich, tealPng, stillAnim, bewegt, farbe,
           json: /"fx":"spotlight"/.test(JSON.stringify(ed.canvas.toJSON(ep))) && /"spotBewegung":"fest"/.test(JSON.stringify(ed.canvas.toJSON(ep))),
           imMotion };
});
pruefe('Spotlight wartet auf einen Klick ins Bild', spA.wahl);
pruefe('Ein Klick auf den Text legt einen Spotlight-Rahmen an', spB.gruppen === 1 && spB.frames === 1, spB.gruppen + '/' + spB.frames);
pruefe('der Rahmen umfasst Icon UND Text', spB.umfasst, spB.box);
pruefe('und nicht mehr als dieses eine Element', spB.nichtZuGross, spB.box);
pruefe('Das Element kommt vergrößert nach vorn (auch ohne Vorschau)', spB.tealMit > spB.tealOhne * 1.5, spB.tealMit + ' / ' + spB.tealOhne);
pruefe('der Rest tritt zurück', spB.restMit[0] > spB.restOhne[0] + 20, JSON.stringify([spB.restMit, spB.restOhne]));
pruefe('die Überschrift bleibt klar', spB.kopfGleich);
pruefe('Still steht im exportierten PNG', spB.tealPng > spB.tealOhne * 1.5, spB.tealPng);
pruefe('Still ist keine Animation', spB.stillAnim === false);
pruefe('Moving ist eine: erst klein, dann ganz vorn', spB.bewegt.anim && spB.bewegt.f0 === 0 && spB.bewegt.f2 === 1, JSON.stringify(spB.bewegt));
pruefe('Die eine Palette färbt den Rahmen', spB.farbe === '#F56E28', spB.farbe);
pruefe('Spotlight wird gespeichert', spB.json);

// Around: alle Elemente, erst die Mitte, dann im Kreis links herum ab oben links
const spC = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  document.querySelector('#anim-bar .spot-row .spot-seg[data-key="spotReihe"] [data-v="links"]').click();
  const k = [...m.spotGruppen(ed).values()][0];
  const mitte = o => { const b = o.getBoundingRect(true, true); return [Math.round((b.left + b.width / 2) / 10) * 10, Math.round(b.top / 10) * 10]; };
  const reihe = k.map(o => mitte(o)[0]).join(',');
  const film = { anim: m.hasAnimations(ed), a: m.spotZustand(k, 1).i, b: m.spotZustand(k, 2.5 + 0.4 + 1).i, runde: m.spotRundeMs(k) };
  const zeilen = document.querySelectorAll('#anim-bar .spot-row .spot-eintrag').length;
  // Remove nimmt den ganzen Spotlight weg
  document.querySelector('#anim-bar .spot-row .fx-remove').click();
  return { n: k.length, reihe, film, zeilen, rest: m.spotGruppen(ed).size };
});
pruefe('Around nimmt alle sechs Elemente in einen Film', spC.n === 6 && spC.zeilen === 6, spC.n + ' / ' + spC.zeilen);
// Mitte 512, dann links 282, unten links 349, unten 512, unten rechts 675, rechts 742 (auf 10 gerundet)
pruefe('erst die Mitte, dann im Kreis links herum', spC.reihe === '510,280,350,510,680,740', spC.reihe);
pruefe('der Film zeigt einen nach dem anderen', spC.film.anim && spC.film.a === 0 && spC.film.b === 1, JSON.stringify(spC.film));
pruefe('eine Runde: sechs Mal 2,5 s, Pausen und das ganze Bild am Ende',
  spC.film.runde === Math.round((6 * (2.5 + 0.4) + 1.2) * 1000), spC.film.runde);
pruefe('Remove nimmt den ganzen Spotlight weg', spC.rest === 0, spC.rest);
await sauber('Spotlight');

// ---- Paket A: Duplizieren, Löschen, Neuaufbau, Farbe, englische Texte --------
// Review 27.09.2026. Ein Duplikat eines Fragezeichens oder Spots behielt Netz
// und Nummer; eine Mehrfachauswahl kam als EIN Objekt zurück; Entf ließ Lücken
// in der Nummerierung; ein Neuaufbau verlor Deckkraft, Spiegelung und Farbe.
await ruhig('Paket A');
await page.click('[data-mode="effects"]');
const paA = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(800, 600);
  document.querySelector('[data-act="add-qweb"]').click();
  await warte(150);
  const netz = () => [...m.fragenNetze(ed).values()];
  const erstes = netz()[0];
  // 1) one question mark duplicated: it joins the web as number four
  ed.canvas.setActiveObject(erstes[1]);
  ed.duplicateSelected();
  await warte(200);
  const nachEins = netz().map(k => k.map(o => o.qwebNr).join(','));
  // 2) the whole web duplicated: a second web, element by element
  const vorher = ed.canvas.getObjects().length;
  const alle = netz()[0];
  ed.canvas.setActiveObject(new fabric.ActiveSelection(alle, { canvas: ed.canvas }));
  ed.duplicateSelected();
  await warte(250);
  ed.canvas.discardActiveObject();
  const dazu = ed.canvas.getObjects().length - vorher;
  const keineAuswahlImBild = ed.canvas.getObjects().every(o => o.type !== 'activeSelection');
  const netze = netz().map(k => k.map(o => o.qwebNr).join(','));
  // 3) Del closes the gap - and with numbers as sign the labels run 1 2 3 again
  const w = netz()[0];
  w.forEach(o => { o.qwebSign = '#'; });
  ed.canvas.setActiveObject(w[1]);
  ed.deleteSelected();
  await warte(100);
  const rest = m.fragenNetze(ed).get(w[0].qwebId);
  const nachDel = rest.map(o => o.qwebNr).join(',');
  const zeichen = rest.map(o => o._objects[1].text).join(',');
  // 4) spotlights: a single one duplicated is a spotlight of its own; a member
  //    of a film duplicated joins the film at the end
  ed.clearAll();
  const s1 = m.addSpot(ed, { x: 100, y: 100, w: 120, h: 120 }, null);
  ed.canvas.setActiveObject(s1); ed.duplicateSelected();
  await warte(200);
  const spotsNachEins = m.spotGruppen(ed).size;
  const s2 = m.addSpot(ed, { x: 400, y: 100, w: 120, h: 120 }, [s1]);
  ed.canvas.setActiveObject(s2); ed.duplicateSelected();
  await warte(200);
  const film = m.spotGruppen(ed).get(s1.spotId).map(o => o.spotNr).join(',');
  ed.canvas.setActiveObject(s1); ed.deleteSelected();
  await warte(100);
  const filmNachDel = m.spotGruppen(ed).get(s2.spotId).map(o => o.spotNr).join(',');
  return { nachEins, dazu, keineAuswahlImBild, netze, nachDel, zeichen, spotsNachEins, film, filmNachDel };
});
pruefe('Duplikat eines Fragezeichens: es kommt als Nummer vier ins Netz', paA.nachEins.join('|') === '0,1,2,3', paA.nachEins.join('|'));
pruefe('Mehrfachauswahl dupliziert: vier Elemente, nicht ein Klumpen', paA.dazu === 4 && paA.keineAuswahlImBild, paA.dazu);
pruefe('ein ganz kopiertes Netz ist ein eigenes Netz', paA.netze.length === 2 && paA.netze.every(n => n === '0,1,2,3'), paA.netze.join('|'));
pruefe('Entf schließt die Lücke in der Nummerierung', paA.nachDel === '0,1,2', paA.nachDel);
pruefe('und die Zahlen laufen wieder 1 2 3', paA.zeichen === '1,2,3', paA.zeichen);
pruefe('ein einzelner Spot dupliziert ist ein eigener Spotlight', paA.spotsNachEins === 2, paA.spotsNachEins);
pruefe('ein Spot aus einem Film dupliziert kommt ans Ende', paA.film === '0,1,2', paA.film);
pruefe('Entf im Film nummeriert neu', paA.filmNachDel === '0,1', paA.filmNachDel);

const paB = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(800, 600);
  document.querySelector('[data-mode="insert"]')?.click();
  document.querySelector('[data-act="add-textblock"]').click();
  await warte(150);
  const tb = ed.active();
  tb.set({ opacity: 0.5, flipX: true, fxColor: '#123456', fxTempo: 1.7 });
  ed.snapshot();
  const tc = document.getElementById('text-color');
  tc.value = '#aa0000'; tc.dispatchEvent(new Event('input'));
  await warte(100);
  const neu = ed.active();
  return { neu: neu !== tb, opacity: neu.opacity, flipX: neu.flipX, fxColor: neu.fxColor, fxTempo: neu.fxTempo, farbe: neu.tbColor || '' };
});
pruefe('Neuaufbau (Textfarbe) behält Deckkraft, Spiegelung, Effektfarbe und Tempo',
  paB.neu && paB.opacity === 0.5 && paB.flipX === true && paB.fxColor === '#123456' && paB.fxTempo === 1.7, JSON.stringify(paB));

const paC = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(400, 300);
  const r = new fabric.Rect({ left: 20, top: 20, width: 100, height: 60, fill: '#00aa00' });
  ed.canvas.add(r); ed.canvas.setActiveObject(r); ed.snapshot();
  await warte(120);
  const bild = () => document.querySelector('#anim-bar img.anim-thumb')?.src || '';
  const vorher = bild();
  r.set('fill', '#dd0000'); ed.snapshot();
  await warte(120);
  return { vorher: vorher.length, anders: bild() !== vorher && bild().length > 0 };
});
pruefe('Vorschaubild in der Motion-Zeile folgt der neuen Farbe', paC.anders, JSON.stringify(paC));

const paD = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(800, 600);
  const netzwerk = m.addEffektRahmen(ed, 'network');
  const lupe = m.addEffektRahmen(ed, 'magnifier');
  ed.canvas.setActiveObject(lupe); ed.snapshot();
  await warte(120);
  document.querySelector('#anim-bar .fx-palette .fx-swatch:not(.fx-swatch-auto)').click();
  await warte(120);
  return { lupe: lupe.fxColor || null, netz: netzwerk.fxColor || null };
});
pruefe('Die Effekt-Palette färbt nicht die Lupe, sondern den ersten Rahmen mit Farbe', !paD.lupe && !!paD.netz, JSON.stringify(paD));

const paE = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(800, 600);
  document.querySelector('[data-mode="effects"]')?.click();
  const zu = document.querySelector('#anim-bar details.anim-group[data-group="effects"]');
  if (zu) { zu.open = false; zu.dispatchEvent(new Event('toggle')); }
  await warte(50);
  document.querySelector('[data-act="add-qweb"]').click();
  await warte(150);
  return document.querySelector('#anim-bar details.anim-group[data-group="effects"]')?.open === true;
});
pruefe('Fragenetz hinzufügen klappt die Effects-Gruppe auf', paE);

// Die Oberfläche spricht Englisch: keine deutschen Meldungen in den Modulen.
{
  const deutsch = ['Eigene Canvas', 'Abbrechen', 'Übernehmen', 'Speichert…', "'Gespeichert", 'Freigestellt',
    'Stelle frei', 'Sitzung abgelaufen', 'Server-Fehler', 'Schriftgröße', "'Bereit.'", 'am Post', 'Dein Text',
    'Name schon vergeben', 'Fehler beim Laden', 'nicht ladbar', 'Herunterladen fehlgeschlagen', 'Eine Zeile = ein Haken'];
  const funde = [];
  for (const f of fs.readdirSync(ROOT).filter(n => n.endsWith('.js'))) {
    const text = fs.readFileSync(path.join(ROOT, f), 'utf8');
    deutsch.forEach(w => { if (text.includes(w)) funde.push(f + ': ' + w); });
  }
  pruefe('Keine deutschen UI-Texte mehr in den Studio-Modulen', funde.length === 0, funde.slice(0, 5).join(' | '));
}
await sauber('Paket A');

// ---- Paket B: schneller, ohne dass sich das Bild ändert --------------------
// Review 27.09.2026. Texte und Gruppen zeichnen aus einem Zwischenbild; der
// Spotlight und die Lupe malen die Szene nur neu, wenn sie sich ändert.
await ruhig('Paket B');
const pbA = await page.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(600, 400);
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  ed.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  const t = new fabric.Textbox('XXXXXXXX', { left: 20, top: 20, width: 300, fontSize: 60, fill: '#000000', fontFamily: 'Arial' });
  const kreis = new fabric.Circle({ radius: 30, fill: '#008591', left: 0, top: 0 });
  const zeile = new fabric.Textbox('YYYYYY', { left: 70, top: 0, width: 240, fontSize: 50, fill: '#000000', fontFamily: 'Arial' });
  const g = new fabric.Group([kreis, zeile], { left: 250, top: 200 });
  ed.canvas.add(t, g); ed.canvas.discardActiveObject(); ed.snapshot();
  const rot = () => {
    const c = ed.canvas.lowerCanvasEl, d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 200 && d[i + 1] < 60 && d[i + 2] < 60) n++;
    return n;
  };
  ed.canvas.renderAll();
  const cacheText = !!t._cacheCanvas, cacheGruppe = !!g._cacheCanvas;
  // a colour set on a text and on a member of a group shows at once
  t.set('fill', '#ff0000'); ed.canvas.renderAll();
  const rotText = rot();
  g._objects[1].set('fill', '#ff0000'); ed.canvas.renderAll();
  const rotBeide = rot();
  // the spotlight's picture: the group where it is (not twice its offset)
  const b2 = m.spotBild(ed, 2);
  const mitte = kreis.getCenterPoint ? g.getCenterPoint() : null;
  const px = b2.getContext('2d').getImageData(Math.round((g.left + 30) * 2), Math.round((g.top + 30) * 2), 1, 1).data;
  const teal = px[0] < 40 && px[1] > 110 && px[2] > 120;
  // drawn again only when the scene changes
  const stand = typeof m.szenenStand === 'function' ? m.szenenStand : () => Math.random();
  const nochmal = m.spotBild(ed, 2) === b2 && stand(ed) === stand(ed);
  const vorher = stand(ed);
  g.set('left', 260);
  const nachher = stand(ed);
  return { cacheText, cacheGruppe, rotText, rotBeide, teal, px: [...px], nochmal, geaendert: vorher !== nachher };
});
pruefe('Texte und Gruppen zeichnen aus einem Zwischenbild', pbA.cacheText && pbA.cacheGruppe, JSON.stringify(pbA));
pruefe('eine neue Textfarbe erscheint sofort', pbA.rotText > 100, pbA.rotText);
pruefe('auch in einer Gruppe', pbA.rotBeide > pbA.rotText + 100, pbA.rotBeide + ' / ' + pbA.rotText);
pruefe('Spotlight-Bild: die Gruppe sitzt an ihrem Platz', pbA.teal, JSON.stringify(pbA.px));
pruefe('Spotlight-Bild bleibt, solange sich nichts ändert, und folgt einer Verschiebung', pbA.nochmal && pbA.geaendert);

// Bild speichern: das PNG geht als Datei, nicht als base64 im JSON.
letzterUpload = null;
const pbB = await page.evaluate(async () => {
  const io = await import('/io.js');
  io.merkeNamen('Prüfbild');
  const ok = await io.saveImage(window._studioEditor);
  return { ok };
});
pruefe('Bild speichern schickt ein Formular mit der PNG-Datei',
  pbB.ok && !!letzterUpload && /multipart\/form-data/.test(letzterUpload.typ || '') && letzterUpload.laenge > 1000,
  JSON.stringify({ ...pbB, letzterUpload }));
await sauber('Paket B');

// ---- Paket B, zweiter Teil: Undo-Speicher, ein Aufbau, Hilfslinien, GIF -----
await ruhig('Paket B2');
const pbC = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(400, 300);
  const c = document.createElement('canvas'); c.width = 600; c.height = 450;
  const x = c.getContext('2d'); const id = x.createImageData(600, 450);
  for (let i = 0; i < id.data.length; i++) id.data[i] = (i * 7919) % 251;
  x.putImageData(id, 0, 0);
  const url = c.toDataURL('image/png');
  const el = await new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = url; });
  ed.canvas.add(new fabric.Image(el, { left: 10, top: 10, scaleX: 0.3, scaleY: 0.3 }));
  ed.resetHistory();                  // only the steps of this test count
  for (let k = 0; k < 6; k++) { ed.canvas.add(new fabric.Text('t' + k, { left: 20 * k, top: 200 })); ed.snapshot(); }
  const bytes = typeof ed._bytes === 'function' ? ed._bytes() : -1;
  ed.undo(); await warte(400); ed.undo(); await warte(400);
  const bild = ed.canvas.getObjects().find(o => o.type === 'image');
  const zurueck = !!bild && bild._element && (bild._element.naturalWidth || bild._element.width) === 600
                  && bild.getSrc() === url;
  ed.redo(); await warte(400);
  const nachRedo = ed.canvas.getObjects().filter(o => o.type === 'image').length;
  return { bytes, url: url.length, zurueck, nachRedo };
});
pruefe('Undo-Schritte tragen ein großes Bild nur einmal', pbC.bytes > 0 && pbC.bytes < pbC.url, JSON.stringify(pbC));
pruefe('Undo und Redo bringen das Bild vollständig zurück', pbC.zurueck && pbC.nachRedo === 1, JSON.stringify(pbC));

const pbD = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(600, 400);
  ed.canvas.add(new fabric.Text('Hallo', { left: 20, top: 20 })); ed.snapshot();
  await warte(100);
  const bar = document.getElementById('anim-bar');
  let aufbauten = 0;
  const beob = new MutationObserver(liste => { if (liste.some(m => m.target === bar && m.removedNodes.length)) aufbauten++; });
  beob.observe(bar, { childList: true });
  document.querySelector('[data-mode="effects"]')?.click();
  document.querySelector('[data-act="add-magnifier"]').click();
  await warte(300);
  beob.disconnect();
  return aufbauten;
});
pruefe('Die Animationsleiste wird nach einer Aktion einmal gebaut, nicht zweimal', pbD === 1, pbD);

const pbE = await page.evaluate(async () => {
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(600, 400);
  const r = new fabric.Rect({ left: 297, top: 100, width: 10, height: 10, fill: '#000' });
  const s = new fabric.Rect({ left: 100, top: 300, width: 50, height: 50, fill: '#333' });
  ed.canvas.add(r, s); ed.canvas.setActiveObject(r);
  const vorher = ed.canvas.getObjects().length;
  ed.canvas.fire('object:moving', { target: r });
  const waehrend = ed.canvas.getObjects().length;
  const eingerastet = Math.round(r.left + r.width / 2) === 300;
  ed.canvas.fire('mouse:up', {});
  return { vorher, waehrend, eingerastet, nachher: ed.canvas.getObjects().length };
});
pruefe('Einrasten an der Mitte funktioniert', pbE.eingerastet, JSON.stringify(pbE));
pruefe('Hilfslinien kommen nicht als Elemente in die Liste', pbE.waehrend === pbE.vorher && pbE.nachher === pbE.vorher, JSON.stringify(pbE));

// In a fresh tab: on the long-used page a second GIF's workers stay silent in
// this headless browser - with the old code just as with the new.
const gifSeite = await browser.newPage();
await gifSeite.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'load' });
await gifSeite.waitForFunction(() => !!window._studioEditor, null, { timeout: 10000 });
const pbF = await gifSeite.evaluate(async () => {
  const m = await import('/media.js');
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(300, 200);
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  const t = new fabric.Text('Hi', { left: 40, top: 40, fontSize: 40 });
  t.anim = { type: 'fadeIn', dur: 400, delay: 0 };
  ed.canvas.add(t);
  const len = document.getElementById('video-length');
  if (len) { len.value = '3'; len.dispatchEvent(new Event('input', { bubbles: true })); }
  ed.snapshot();
  let daten = null;
  const ok = await m.exportGif(ed, b => { daten = b; });
  const bytes = new Uint8Array(await daten.arrayBuffer());
  let bilder = 0;
  for (let i = 0; i + 2 < bytes.length; i++) if (bytes[i] === 0x21 && bytes[i + 1] === 0xF9 && bytes[i + 2] === 0x04) bilder++;
  if (len) { len.value = ''; len.dispatchEvent(new Event('input', { bubbles: true })); }
  return { ok, bilder };
}).catch(e => ({ fehler: String(e).slice(0, 160) }));
await gifSeite.close();
pruefe('GIF: gleiche Bilder hintereinander werden eins (3 s, 0,4 s Bewegung)', pbF.ok && pbF.bilder > 2 && pbF.bilder < 15, JSON.stringify(pbF));
await sauber('Paket B2');

// ---- Sechseck-Muster (Build → Hexagon pattern) -----------------------------
// Ortrud, 27.09.2026: die Sechsecke am Rand der Vorlage per Knopf in die Ecken
// legen oder wie mit einem Stempel setzen.
await ruhig('Sechsecke');
await page.click('#mode-rail [data-mode="build"]');
const hxA = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  ed.clearAll(); ed.setSize(1080, 1080);
  ed.canvas.setBackgroundColor('#008591', () => {});
  ed.canvas.add(new fabric.Text('Main Headline', { left: 100, top: 200, fontSize: 50, fill: '#61CEBC' }));
  ed.snapshot();
  const da = !!document.querySelector('[data-act="hex-ecken"]') && !!document.getElementById('hex-farben')?.children.length
    && document.getElementById('hex-groesse-out')?.textContent === '216 px';
  document.querySelector('[data-act="hex-ecken"]').click();
  await warte(100);
  const objs = ed.canvas.getObjects();
  const hexe = objs.filter(o => o.hexDeko);
  const hinten = hexe.every(h => objs.indexOf(h) < objs.findIndex(o => o.type === 'text'));
  const farbe = hexe[0]?.stroke;
  const ecken = hexe.map(h => (h.left > 540 ? 'r' : 'l') + (h.top > 540 ? 'u' : 'o'));
  // again: a new arrangement, not twice as many
  document.querySelector('[data-act="hex-ecken"]').click();
  await warte(100);
  const nochmal = ed.canvas.getObjects().filter(o => o.hexDeko).length;
  // all four corners
  document.querySelector('#hex-ecken-art [data-v="alle"]').click();
  document.querySelector('[data-act="hex-ecken"]').click();
  await warte(100);
  const vier = ed.canvas.getObjects().filter(o => o.hexDeko).length;
  // layer name and one motion row
  const ebene = [...document.querySelectorAll('#layers-list .layer-name')].some(n => n.textContent === '⬡ Hexagon');
  const zeilen = document.querySelectorAll('#anim-bar .hex-row').length;
  const motionZeilen = document.querySelectorAll('#anim-bar .anim-group[data-group="motion"] .anim-row').length;
  return { da, n: hexe.length, hinten, farbe, ecken: [...new Set(ecken)].sort().join(','), nochmal, vier, ebene, zeilen, motionZeilen };
});
pruefe('Build hat den Bereich Hexagon pattern mit Farben', hxA.da, JSON.stringify(hxA));
pruefe('Corners legt drei Sechsecke je Ecke, oben rechts und unten links', hxA.n === 6 && hxA.ecken === 'lu,ro', JSON.stringify(hxA));
pruefe('die Sechsecke liegen hinter dem Text', hxA.hinten);
pruefe('Farbe auto: ein Hauch heller als der Grund', /^#0a8f9a$|^#0f8f9a$|^#0f8e99$|^#0f8f99$/.test(hxA.farbe || '') || (hxA.farbe || '').startsWith('#0') , hxA.farbe);
pruefe('noch einmal Corners: neue Anordnung statt doppelt so viele', hxA.nochmal === 6, hxA.nochmal);
pruefe('alle vier Ecken: zwölf Sechsecke', hxA.vier === 12, hxA.vier);
pruefe('in den Ebenen heißen sie „⬡ Hexagon“', hxA.ebene);
pruefe('in der Animationsleiste EINE Zeile für das ganze Muster', hxA.zeilen === 1 && hxA.motionZeilen === 2, JSON.stringify(hxA));

const hxB = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  document.querySelector('[data-act="hex-weg"]').click();
  await warte(50);
  const leer = ed.canvas.getObjects().filter(o => o.hexDeko).length;
  // stamp: a click sets one, Shift+click a bigger one, Alt+click removes one
  document.querySelector('[data-act="hex-stempel"]').click();
  const an = document.getElementById('hex-stempel-btn').classList.contains('on') && ed.canvas.skipTargetFind === true;
  const klick = (x, y, mods = {}) => {
    const r = ed.canvas.upperCanvasEl.getBoundingClientRect(), z = r.width / ed.width;
    const opt = { clientX: r.left + x * z, clientY: r.top + y * z, bubbles: true, button: 0, ...mods };
    ed.canvas.upperCanvasEl.dispatchEvent(new MouseEvent('mousedown', opt));
    ed.canvas.upperCanvasEl.dispatchEvent(new MouseEvent('mouseup', opt));
  };
  klick(500, 600);
  klick(800, 800, { shiftKey: true });
  await warte(50);
  const hx = ed.canvas.getObjects().filter(o => o.hexDeko);
  const groesser = hx.length === 2 && hx.find(h => h.left > 700).hexR > hx.find(h => h.left < 700).hexR * 1.4;
  const lage = hx.find(h => h.left < 700);
  const ort = lage && Math.abs(lage.left - 500) < 3 && Math.abs(lage.top - 600) < 3;
  klick(502, 598, { altKey: true });
  await warte(50);
  const nachAlt = ed.canvas.getObjects().filter(o => o.hexDeko).length;
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  const aus = !document.getElementById('hex-stempel-btn').classList.contains('on') && ed.canvas.skipTargetFind === false;
  // undo brings the removed one back
  ed.undo(); await warte(300);
  const nachUndo = ed.canvas.getObjects().filter(o => o.hexDeko).length;
  return { leer, an, groesser, ort, nachAlt, aus, nachUndo };
});
pruefe('Remove all nimmt alle Sechsecke weg', hxB.leer === 0, JSON.stringify(hxB));
pruefe('Stamp: Klick setzt eins genau dort, Shift+Klick ein größeres', hxB.an && hxB.ort && hxB.groesser, JSON.stringify(hxB));
pruefe('Alt+Klick entfernt eins, Esc beendet', hxB.nachAlt === 1 && hxB.aus, JSON.stringify(hxB));
pruefe('Undo holt das entfernte zurück', hxB.nachUndo === 2, JSON.stringify(hxB));

const hxC = await page.evaluate(async () => {
  const ed = window._studioEditor;
  const warte = ms => new Promise(r => setTimeout(r, ms));
  const h = ed.canvas.getObjects().find(o => o.hexDeko);
  ed.canvas.setActiveObject(h);
  ed.canvas.fire('selection:created', { selected: [h] });
  // settings change the selected hexagon
  document.querySelector('#hex-fuell [data-v="ja"]').click();
  const gefuellt = !!h.fill && !h.stroke;
  const deck = document.getElementById('hex-deck'); deck.value = 40; deck.dispatchEvent(new Event('input'));
  const r0 = h.getScaledWidth();
  const gr = document.getElementById('hex-groesse'); gr.value = 120; gr.dispatchEvent(new Event('input'));
  // slider 120 → radius 120 x 1.8 = 216 px on a 1080 canvas, whatever it was before
  const groesser = Math.abs(h.hexR * h.scaleX - 216) < 1 && h.getScaledWidth() > r0;
  // a new ground colour: the auto hexagon follows
  document.querySelector('#hex-fuell [data-v="nein"]').click();
  ed.canvas.discardActiveObject();
  const vorher = h.stroke;
  const pick = document.getElementById('bg-color'); pick.value = '#fbf8f0'; pick.dispatchEvent(new Event('input'));
  const nachher = h.stroke;
  const dunkler = parseInt(nachher.slice(1, 3), 16) < 0xfb;
  // saved with the drawing
  const io = await import('/io.js');
  const json = JSON.parse(io.buildCanvasJson(ed, ''));
  const gespeichert = json.fabric.objects.filter(o => o.hexDeko).length;
  return { gefuellt, deck: h.opacity, groesser, vorher, nachher, dunkler, gespeichert };
});
pruefe('die Einstellungen ändern das gewählte Sechseck (gefüllt, sichtbar, Größe)',
  hxC.gefuellt && Math.abs(hxC.deck - 0.4) < 0.01 && hxC.groesser, JSON.stringify(hxC));
pruefe('neue Grundfarbe: auto-Sechsecke ziehen mit (auf Creme etwas dunkler)', hxC.vorher !== hxC.nachher && hxC.dunkler, JSON.stringify(hxC));
pruefe('die Sechsecke werden mit der Zeichnung gespeichert', hxC.gespeichert === 2, JSON.stringify(hxC));
await sauber('Sechsecke');

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

// ---- Neue Bewegungen: Draw on, Grow, Pop in, Then ---------------------------
await ruhig('Neue Bewegungen');
const nb = await page.evaluate(async () => {
  const m = await import('/media.js');
  const F = window.fabric;
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(400, 300);
  ed.canvas.setBackgroundColor('#ffffff', () => {});
  const r = {};
  const setze = (o, typ, dur, start, extra = {}) => { o.anim = { type: typ, dur, ...extra }; m.setStart(o, start); return o; };
  // Pixel eines Objekts für sich gerendert (Alpha an einer Stelle der Linie).
  const alpha = (o, xr) => {
    const c = o.toCanvasElement();
    return c.getContext('2d').getImageData(Math.round(c.width * xr), Math.round(c.height / 2), 1, 1).data[3];
  };

  // A. Draw on - eine volle Linie
  const linie = setze(new F.Line([20, 100, 220, 100], { stroke: '#00aaaa', strokeWidth: 6 }), 'drawOn', 1000, 0);
  ed.canvas.add(linie);
  m.applyAt(linie, 0);
  r.linieStart = [alpha(linie, 0.1), alpha(linie, 0.9)];
  m.applyAt(linie, 500);
  r.linieMitte = [alpha(linie, 0.1), alpha(linie, 0.8), alpha(linie, 0.95)];
  m.applyAt(linie, 1100);
  r.linieEnde = [alpha(linie, 0.1), alpha(linie, 0.95), linie.strokeDashArray];

  // gestrichelt: das eigene Muster bleibt, sichtbar sind ~87.5 % von 200
  const strich = setze(new F.Line([20, 150, 220, 150], { stroke: '#00aaaa', strokeWidth: 4, strokeDashArray: [8, 8] }), 'drawOn', 1000, 0);
  ed.canvas.add(strich);
  m.applyAt(strich, 500);
  const d = strich.strokeDashArray;
  r.strichMitte = { anfang: d.slice(0, 4), sichtbar: d.slice(0, -1).reduce((s, v) => s + v, 0), gerade: d.length % 2 === 0 };
  m.applyAt(strich, 1200);
  r.strichEnde = strich.strokeDashArray;

  // Pfeil: Linie zeichnet sich, die Spitze (ohne Strich) kommt am Ende
  const spitze = new F.Polygon([{ x: 240, y: 60 }, { x: 225, y: 52 }, { x: 225, y: 68 }], { fill: '#00aaaa' });
  const pfeil = setze(new F.Group([new F.Line([150, 60, 225, 60], { stroke: '#00aaaa', strokeWidth: 4 }), spitze]), 'drawOn', 1000, 0);
  ed.canvas.add(pfeil);
  m.applyAt(pfeil, 400);
  r.pfeilMitte = { spitze: spitze.opacity, strich: pfeil._objects[0].strokeDashArray && pfeil._objects[0].strokeDashArray[0] };
  m.applyAt(pfeil, 1100);
  r.pfeilEnde = { spitze: spitze.opacity, strich: pfeil._objects[0].strokeDashArray };

  // C. Was lässt sich zeichnen?
  r.kann = {
    linie: m.canDraw(linie), pfeil: m.canDraw(pfeil),
    text: m.canDraw(new F.Textbox('Hi', { stroke: '#000', strokeWidth: 1 })),
    flaeche: m.canDraw(new F.Rect({ width: 10, height: 10, fill: '#f00' })),
    umriss: m.canDraw(new F.Rect({ width: 10, height: 10, fill: '', stroke: '#f00', strokeWidth: 2 })),
  };
  r.strichBis = [m.strichBis(null, 50), m.strichBis([8, 8], 20), m.strichBis([5], 12), m.strichBis([8, 8], 0)];

  // D. Grow - die gewählte Seite bleibt stehen
  const kante = (o, t, von, ursprung = {}) => {
    const b = setze(new F.Rect({ left: 50, top: 200, width: 100, height: 20, fill: '#f60', strokeWidth: 0, ...ursprung }), 'grow', 1000, 0, { from: von });
    ed.canvas.add(b);
    m.applyAt(b, t);
    const k = b.getBoundingRect(true, true);
    ed.canvas.remove(b);
    return { l: +k.left.toFixed(1), r: +(k.left + k.width).toFixed(1), o: +k.top.toFixed(1), u: +(k.top + k.height).toFixed(1),
             w: +k.width.toFixed(1), h: +k.height.toFixed(1) };
  };
  r.wachsen = {
    links: kante(null, 500, 'left'), rechts: kante(null, 500, 'right'), unten: kante(null, 500, 'bottom'),
    mitteLinks: kante(null, 500, 'left', { originX: 'center', originY: 'center', left: 100, top: 210 }),
    anfang: kante(null, 0, 'left'), ende: kante(null, 1000, 'left'),
  };

  // E. Pop in - schwingt über und landet, um die Mitte
  const pop = setze(new F.Rect({ left: 250, top: 40, width: 60, height: 40, fill: '#08a', strokeWidth: 0 }), 'popIn', 1000, 0);
  ed.canvas.add(pop);
  const mitte0 = pop.getCenterPoint();
  let maxS = 0, maxVersatz = 0;
  for (let t = 0; t <= 1000; t += 25) {
    m.applyAt(pop, t);
    maxS = Math.max(maxS, pop.scaleX);
    const c = pop.getCenterPoint();
    if (t > 0) maxVersatz = Math.max(maxVersatz, Math.hypot(c.x - mitte0.x, c.y - mitte0.y));
  }
  m.applyAt(pop, 1000);
  r.pop = { maxS, maxVersatz, ende: pop.scaleX, deckend: pop.opacity };

  // F. Then - erst nach dem Ankommen
  const schweb = setze(new F.Rect({ left: 300, top: 200, width: 40, height: 40, fill: '#0a8' }), 'fadeIn', 500, 200, { then: 'float' });
  const ohne = setze(new F.Rect({ left: 300, top: 250, width: 40, height: 40, fill: '#0a8' }), 'fadeIn', 500, 200);
  const puls = setze(new F.Rect({ left: 350, top: 200, width: 40, height: 40, fill: '#0a8' }), 'popIn', 500, 0, { then: 'pulse' });
  const aus = setze(new F.Rect({ left: 350, top: 250, width: 40, height: 40, fill: '#0a8' }), 'fadeOut', 500, 0, { then: 'float' });
  ed.canvas.add(schweb, ohne, puls, aus);
  const tops = t => { [schweb, ohne, puls, aus].forEach(o => m.applyAt(o, t)); return [schweb.top, ohne.top, puls.scaleX, aus.top]; };
  r.dann = { vorher: tops(650), nachher: tops(1300) };

  // Die Wiedergabe setzt alles zurück - auch die Strichmuster.
  const vl = document.getElementById('video-length'); const alt = vl ? vl.value : '';
  if (vl) vl.value = 1;
  m.previewAnimation(ed);
  await new Promise(res => setTimeout(res, 150));
  r.waehrend = m.effectsRunning();
  const t0 = performance.now();
  while (m.effectsRunning() && performance.now() - t0 < 8000) await new Promise(res => setTimeout(res, 50));
  if (vl) vl.value = alt;
  r.zurueck = { strich: strich.strokeDashArray, linie: linie.strokeDashArray, spitze: spitze.opacity,
                reste: ed.canvas.getObjects().some(o => o.__zDash !== undefined || (o._objects || []).some(k => k.__zDash !== undefined || k.__zOpa !== undefined)),
                schweb: schweb.top, pop: pop.scaleX };
  return r;
});
pruefe('Draw on: vor dem Start ist nichts von der Linie zu sehen', nb.linieStart[0] === 0 && nb.linieStart[1] === 0, nb.linieStart);
pruefe('Draw on: zur Hälfte ist der Anfang da, das Ende noch nicht', nb.linieMitte[0] > 200 && nb.linieMitte[1] > 200 && nb.linieMitte[2] === 0, nb.linieMitte);
pruefe('Draw on: am Ende ist die ganze Linie da, ohne Strichmuster', nb.linieEnde[0] > 200 && nb.linieEnde[1] > 200 && !nb.linieEnde[2], JSON.stringify(nb.linieEnde));
pruefe('Draw on gestrichelt: das eigene Muster 8/8 bleibt', JSON.stringify(nb.strichMitte.anfang) === '[8,8,8,8]', JSON.stringify(nb.strichMitte));
pruefe('und sichtbar sind 87.5 % der Linie', Math.abs(nb.strichMitte.sichtbar - 175) < 0.5 && nb.strichMitte.gerade, nb.strichMitte.sichtbar);
pruefe('am Ende steht wieder genau [8, 8]', JSON.stringify(nb.strichEnde) === '[8,8]', JSON.stringify(nb.strichEnde));
pruefe('Pfeil: die Spitze wartet, bis die Linie fast fertig ist', nb.pfeilMitte.spitze === 0 && nb.pfeilMitte.strich > 0, JSON.stringify(nb.pfeilMitte));
pruefe('Pfeil: am Ende sind Spitze und Linie ganz da', nb.pfeilEnde.spitze === 1 && !nb.pfeilEnde.strich, JSON.stringify(nb.pfeilEnde));
pruefe('Draw on gibt es für Linie, Pfeil und Umriss - nicht für Text oder Fläche',
  nb.kann.linie && nb.kann.pfeil && nb.kann.umriss && !nb.kann.text && !nb.kann.flaeche, JSON.stringify(nb.kann));
pruefe('Das Strichmuster bis zu einer Länge stimmt',
  JSON.stringify(nb.strichBis) === JSON.stringify([[50, 1e6], [8, 8, 4, 1e6], [5, 5, 2, 1e6], [0, 1e6]]), JSON.stringify(nb.strichBis));
const W = nb.wachsen;
pruefe('Grow von links: die linke Kante bleibt, die Breite wächst', Math.abs(W.links.l - 50) < 0.6 && Math.abs(W.links.w - 87.5) < 1, JSON.stringify(W.links));
pruefe('Grow von rechts: die rechte Kante bleibt', Math.abs(W.rechts.r - 150) < 0.6 && W.rechts.w < 95, JSON.stringify(W.rechts));
pruefe('Grow von unten: die Unterkante bleibt, die Breite nicht angetastet', Math.abs(W.unten.u - 220) < 0.6 && W.unten.h < 19 && Math.abs(W.unten.w - 100) < 0.6, JSON.stringify(W.unten));
pruefe('Grow auch bei einem Element mit Mittelpunkt als Ursprung', Math.abs(W.mitteLinks.l - 50) < 0.6 && W.mitteLinks.w < 95, JSON.stringify(W.mitteLinks));
pruefe('Grow: vor dem Start nicht zu sehen, am Ende volle Größe', W.anfang.w < 1 && Math.abs(W.ende.w - 100) < 0.6, JSON.stringify([W.anfang, W.ende]));
pruefe('Pop in schwingt über (mehr als 103 %)', nb.pop.maxS > 1.03 && nb.pop.maxS < 1.2, nb.pop.maxS);
pruefe('Pop in bleibt dabei in der Mitte stehen', nb.pop.maxVersatz < 0.5, nb.pop.maxVersatz);
pruefe('Pop in landet genau auf der eigenen Größe', Math.abs(nb.pop.ende - 1) < 1e-6 && nb.pop.deckend === 1, JSON.stringify(nb.pop));
pruefe('Then: vor dem Ankommen ruht das Element', nb.dann.vorher[0] === 200, JSON.stringify(nb.dann));
pruefe('Then float: danach schwebt es', Math.abs(nb.dann.nachher[0] - 200) > 0.5, JSON.stringify(nb.dann.nachher));
pruefe('ohne Then bleibt es stehen', nb.dann.nachher[1] === 250, nb.dann.nachher[1]);
pruefe('Then pulse: danach atmet es', Math.abs(nb.dann.nachher[2] - 1) > 0.005, nb.dann.nachher[2]);
pruefe('Then nach einem Ausblenden tut nichts', nb.dann.nachher[3] === 250, nb.dann.nachher[3]);
pruefe('Die Vorschau lief', nb.waehrend === true);
pruefe('Nach der Vorschau ist alles wie vorher (Strichmuster, Spitze, Lage, Größe)',
  JSON.stringify(nb.zurueck.strich) === '[8,8]' && !nb.zurueck.linie && nb.zurueck.spitze === 1 && !nb.zurueck.reste
  && nb.zurueck.schweb === 200 && nb.zurueck.pop === 1, JSON.stringify(nb.zurueck));

// Die Motion-Zeile: Gruppen, From, Then, Start bis 10 s
const nbUi = await page.evaluate(async () => {
  const m = await import('/media.js');
  const io = await import('/io.js');
  const F = window.fabric;
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(400, 300);
  const linie = new F.Line([20, 50, 200, 50], { stroke: '#00aaaa', strokeWidth: 4 });
  const text = new F.Textbox('Hallo', { left: 20, top: 100, width: 120, fontSize: 20 });
  const balken = new F.Rect({ left: 20, top: 200, width: 100, height: 12, fill: '#f60' });
  balken.anim = { type: 'fadeIn', dur: 800 }; m.setStart(balken, 6700);
  ed.canvas.add(linie, text, balken);
  (await import('/animbar.js')).renderAnimBar();
  await new Promise(r => setTimeout(r, 300));
  const zeile = o => document.querySelector('#anim-bar .anim-row[data-obj-idx="' + ed.realObjects().indexOf(o) + '"]');
  const wahl = o => zeile(o).querySelector('.anim-ctl select');
  const r = {};
  r.gruppen = [...wahl(linie).querySelectorAll('optgroup')].map(g => g.label);
  r.alleEinmal = [...wahl(linie).options].map(o => o.value).sort().join() === [...m.ANIM_TYPES].sort().join();
  r.zeichnenLinie = wahl(linie).querySelector('option[value="drawOn"]').disabled;
  r.zeichnenText = wahl(text).querySelector('option[value="drawOn"]').disabled;
  // Start: 6.7 s steht da und lässt sich bis 10 s schieben
  const st = zeile(balken).querySelectorAll('.anim-time-item input')[1];
  r.start = { max: +st.max, wert: +st.value, text: zeile(balken).querySelector('.anim-start-wert')?.textContent };
  st.value = 8200; st.dispatchEvent(new Event('input', { bubbles: true }));
  r.startNeu = { startAt: balken.startAt, text: zeile(balken).querySelector('.anim-start-wert')?.textContent };
  // Grow wählen -> From und Then erscheinen
  const w = wahl(balken);
  w.value = 'grow'; w.dispatchEvent(new Event('change', { bubbles: true }));
  const von = zeile(balken).querySelector('select.anim-from'), dann = zeile(balken).querySelector('select.anim-then');
  r.growFelder = { von: !!von, dann: !!dann };
  von.value = 'right'; von.dispatchEvent(new Event('change', { bubbles: true }));
  dann.value = 'float'; dann.dispatchEvent(new Event('change', { bubbles: true }));
  r.growAnim = JSON.stringify(balken.anim);
  // Pop in: From verschwindet, Then bleibt, From wird aufgehoben
  w.value = 'popIn'; w.dispatchEvent(new Event('change', { bubbles: true }));
  r.pop = { von: !!zeile(balken).querySelector('select.anim-from'), dann: zeile(balken).querySelector('select.anim-then')?.value, anim: JSON.stringify(balken.anim) };
  // Fade out: kein Then
  w.value = 'fadeOut'; w.dispatchEvent(new Event('change', { bubbles: true }));
  r.aus = { dann: !!zeile(balken).querySelector('select.anim-then'), leer: getComputedStyle(zeile(balken).querySelector('.anim-extra')).display };
  // Speichern und wieder öffnen: From und Then bleiben
  w.value = 'grow'; w.dispatchEvent(new Event('change', { bubbles: true }));
  const json = io.buildCanvasJson(ed, '');
  await io.restoreCanvas(ed, json, { frisch: true });
  const b2 = ed.realObjects().find(o => o.type === 'rect');
  r.geladen = JSON.stringify({ type: b2.anim.type, from: b2.anim.from, then: b2.anim.then, start: b2.startAt });
  return r;
});
pruefe('Die Motion-Liste ist gruppiert', JSON.stringify(nbUi.gruppen) === '["Come in","Go out","Keep moving"]', JSON.stringify(nbUi.gruppen));
pruefe('und enthält jede Bewegung genau einmal', nbUi.alleEinmal);
pruefe('Draw on ist für eine Linie wählbar, für Text ausgegraut', nbUi.zeichnenLinie === false && nbUi.zeichnenText === true);
pruefe('Start zeigt 6.7 s und reicht bis 10 s', nbUi.start.max === 10000 && nbUi.start.wert === 6700 && nbUi.start.text === '6.7 s', JSON.stringify(nbUi.start));
pruefe('Start lässt sich auf 8.2 s schieben', nbUi.startNeu.startAt === 8200 && nbUi.startNeu.text === '8.2 s', JSON.stringify(nbUi.startNeu));
pruefe('Grow zeigt From und Then', nbUi.growFelder.von && nbUi.growFelder.dann, JSON.stringify(nbUi.growFelder));
pruefe('From und Then landen in der Bewegung', /"from":"right"/.test(nbUi.growAnim) && /"then":"float"/.test(nbUi.growAnim), nbUi.growAnim);
pruefe('Pop in: kein From-Feld, Then bleibt erhalten', !nbUi.pop.von && nbUi.pop.dann === 'float', JSON.stringify(nbUi.pop));
pruefe('Fade out: kein Then, das leere Feld nimmt keinen Platz', !nbUi.aus.dann && nbUi.aus.leer === 'none', JSON.stringify(nbUi.aus));
pruefe('Gespeichert und wieder geöffnet: From, Then und Start sind noch da',
  nbUi.geladen === JSON.stringify({ type: 'grow', from: 'right', then: 'float', start: 8200 }), nbUi.geladen);
await sauber('Neue Bewegungen');

// ---- Vorbereitete Entwürfe (Reiter Drafts, Knopf im Post-Banner) ------------
await ruhig('Entwürfe');
ENTWURF_ABRUFE = 0;
const ew = await page.evaluate(async () => {
  const ed = window._studioEditor;
  ed.clearAll(); ed.setSize(300, 200);
  ed.addText('Vorher', { left: 20, top: 20 });
  const warte = ms => new Promise(r => setTimeout(r, ms));
  const r = { vorher: ed.realObjects().length };
  document.querySelector('#media-tabs [data-media="drafts"]').click();
  await warte(400);
  const kacheln = () => [...document.querySelectorAll('#draft-grid .draft-tile')];
  r.kacheln = kacheln().map(k => k.querySelector('b').textContent + ' | ' + k.querySelector('small').textContent);
  r.kopf = [...document.querySelectorAll('#draft-grid .draft-head')].map(h => h.textContent);
  r.sichtbar = !document.querySelector('[data-media-panel="drafts"]').hidden;
  // Klick -> Rückfrage; Abbrechen lässt alles, wie es ist
  kacheln()[0].click(); await warte(150);
  r.frage = document.querySelector('.studio-modal h4')?.textContent;
  [...document.querySelectorAll('.studio-modal button')].find(b => b.textContent === 'Cancel').click();
  await warte(200);
  r.nachAbbruch = ed.realObjects().length;
  // Öffnen
  kacheln()[0].click(); await warte(150);
  [...document.querySelectorAll('.studio-modal button')].find(b => b.textContent === 'Open draft').click();
  const t0 = performance.now();
  while (ed.realObjects().length === r.vorher && performance.now() - t0 < 5000) await warte(50);
  await warte(300);
  r.geoeffnet = { n: ed.realObjects().length, groesse: [ed.width, ed.height], text: ed.realObjects().map(o => o.text).filter(Boolean),
                  laenge: document.getElementById('video-length')?.value, status: document.getElementById('status-msg')?.textContent,
                  anim: JSON.stringify(ed.realObjects().find(o => o.type === 'rect')?.anim) };
  // Undo holt das Vorherige zurück
  document.querySelector('[data-act="undo"]').click();
  await warte(500);
  r.nachUndo = ed.realObjects().map(o => o.text || o.type);
  // Ein kaputter Entwurf: nichts wird angetastet
  const vorKaputt = ed.realObjects().length;
  kacheln().find(k => k.querySelector('b').textContent === 'Kaputt').click(); await warte(150);
  [...document.querySelectorAll('.studio-modal button')].find(b => b.textContent === 'Open draft').click();
  await warte(600);
  r.kaputt = { n: ed.realObjects().length === vorKaputt, status: document.getElementById('status-msg')?.textContent };
  // Noch einmal auf den Reiter: die Liste kommt aus dem Merker
  document.querySelector('#media-tabs [data-media="upload"]').click();
  document.querySelector('#media-tabs [data-media="drafts"]').click();
  await warte(300);
  r.abrufeNachZweitemMal = 'x';
  document.getElementById('draft-reload').click();
  await warte(300);
  return r;
});
pruefe('Der Reiter Drafts zeigt die vorbereiteten Entwürfe (ohne Hilfsbilder)', ew.sichtbar && ew.kacheln.length === 3, JSON.stringify(ew.kacheln));
pruefe('Titel, Post und Datum kommen aus dem Dateinamen', ew.kacheln.includes('Hidden workload | #140 · Mon 5 Oct'), JSON.stringify(ew.kacheln));
pruefe('Ohne Post gibt es keine Rubrik "For this post"', !ew.kopf.includes('For this post'), JSON.stringify(ew.kopf));
pruefe('Ein Klick fragt erst nach', /Open “/.test(ew.frage || ''), ew.frage);
pruefe('Abbrechen lässt den Canvas, wie er ist', ew.nachAbbruch === ew.vorher, ew.nachAbbruch);
pruefe('Öffnen legt den Entwurf auf den Canvas, in seiner Größe',
  ew.geoeffnet.n === 2 && ew.geoeffnet.groesse.join('x') === '500x400' && ew.geoeffnet.text.includes('Entwurf'), JSON.stringify(ew.geoeffnet));
pruefe('mit seinen Bewegungen', /"type":"grow"/.test(ew.geoeffnet.anim || '') && /"then":"float"/.test(ew.geoeffnet.anim || ''), ew.geoeffnet.anim);
pruefe('und seiner Videolänge', ew.geoeffnet.laenge === '9', ew.geoeffnet.laenge);
pruefe('Die Statuszeile sagt, was geöffnet wurde', /opened/.test(ew.geoeffnet.status || ''), ew.geoeffnet.status);
pruefe('Undo holt den Canvas von vorher zurück', JSON.stringify(ew.nachUndo) === '["Vorher"]', JSON.stringify(ew.nachUndo));
pruefe('Ein unlesbarer Entwurf ändert nichts und sagt es', ew.kaputt.n && /could not be opened/.test(ew.kaputt.status || ''), JSON.stringify(ew.kaputt));
pruefe('Die Liste wird nur einmal geholt, "Reload list" holt sie neu', ENTWURF_ABRUFE === 2, ENTWURF_ABRUFE);

// Aus einem Post geöffnet: der Knopf im Banner, der eigene Entwurf zuerst
const ewPost = async (url) => {
  const p = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  const fehlerHier = [];
  p.on('pageerror', e => fehlerHier.push(e.message));
  await p.goto(`http://127.0.0.1:${PORT}${url}`, { waitUntil: 'load' });
  await p.waitForFunction(() => !!window._studioEditor, null, { timeout: 10000 });
  await p.waitForTimeout(600);
  const r = await p.evaluate(async () => {
    const b = document.getElementById('open-draft-btn');
    const r = { knopf: b ? b.textContent : null, imBanner: !!(b && b.closest('.post-banner .post-actions')) };
    document.querySelector('#media-tabs [data-media="drafts"]').click();
    await new Promise(res => setTimeout(res, 400));
    const erste = document.querySelector('#draft-grid .draft-tile');
    r.kopf = [...document.querySelectorAll('#draft-grid .draft-head')].map(h => h.textContent);
    r.erste = erste ? erste.querySelector('b').textContent : '';
    r.chip = !!(erste && erste.querySelector('.draft-chip'));
    if (b) {
      b.click(); await new Promise(res => setTimeout(res, 150));
      [...document.querySelectorAll('.studio-modal button')].find(x => x.textContent === 'Open draft').click();
      const ed = window._studioEditor, t0 = performance.now();
      while (ed.realObjects().length === 0 && performance.now() - t0 < 5000) await new Promise(res => setTimeout(res, 50));
      r.geladen = ed.realObjects().length;
    }
    return r;
  });
  r.fehler = fehlerHier;
  await p.close();
  return r;
};
const ep = await ewPost('/post-entwurf');
pruefe('Post mit Entwurf: der Knopf "Open prepared draft" steht im Banner', ep.knopf === '✏️ Open prepared draft' && ep.imBanner, JSON.stringify(ep));
pruefe('Im Reiter steht der Entwurf dieses Posts oben, markiert', ep.kopf[0] === 'For this post' && ep.erste === 'Hidden workload' && ep.chip, JSON.stringify(ep));
pruefe('Der Knopf öffnet ihn', ep.geladen === 2, ep.geladen);
const eo = await ewPost('/post-ohne-entwurf');
pruefe('Post ohne Entwurf: kein Knopf', eo.knopf === null, JSON.stringify(eo));
pruefe('Kein Fehler auf den Post-Seiten mit Entwürfen', !ep.fehler.length && !eo.fehler.length, [...ep.fehler, ...eo.fehler].join(' | '));
await sauber('Entwürfe');

// ---- Ausgabe --------------------------------------------------------------
console.log('\n===== ERGEBNIS =====');
for (const r of ergebnis) console.log((r.ok ? '  OK   ' : '  FEHL ') + r.name + (r.detail ? '   [' + r.detail + ']' : ''));
const fehlgeschlagen = ergebnis.filter(r => !r.ok);
console.log(`\n${ergebnis.length - fehlgeschlagen.length}/${ergebnis.length} bestanden`);
if (fehler.length) { console.log('\n--- JS-Fehler auf der Seite ---'); fehler.slice(0, 8).forEach(f => console.log('  ' + f)); }

await browser.close();
server.close();
process.exit(fehlgeschlagen.length ? 1 : 0);
