/* The video length travels with a post's design (29.10.2026).

   Twice a finished post video was cut short by a second save: #143 (needed
   10.3 s, saved with 8 s) and #155 (saved with 10.6 s, overwritten two minutes
   later with 7.2 s). The "Video length" field was not part of the design, so
   reopening the post left it empty, the Studio worked the length out by itself
   - capped at 8 s - and nobody was told.

   Now:
     1. the length is saved with the design and read back when the post opens
        (templates leave it out),
     2. before a GIF or video is saved, a length that cuts the animation short
        is asked about: use the length it needs, keep it, or cancel.

   Runs the REAL media.js and util.js in a browser; their other imports are
   answered with stubs. The wiring in io.js and studio.js is checked in the
   source that ships.

       node _tests/video_laenge_test.mjs
*/
import { chromium } from 'playwright';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STUDIO_DIR = path.join(HERE, '..', 'media_library', 'static', 'media_library', 'studio');
const lies = (...bits) => readFileSync(path.join(STUDIO_DIR, ...bits), 'utf8');

const MEDIA = lies('media.js');
const UTIL = lies('util.js');
const IO = lies('io.js');
const STUDIO = lies('studio.js');
const ENTWUERFE = lies('entwuerfe.js');
const FABRIC = lies('vendor', 'fabric.min.js');

let good = 0, bad = 0;
function check(name, ok, extra = '') {
  if (ok) { good++; console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra !== '' ? '  -> ' + extra : '')); }
}

const SHELL = process.env.PW_CHROME
  || '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';
const browser = await chromium.launch(existsSync(SHELL) ? { executablePath: SHELL } : {});
const page = await browser.newPage();
page.on('pageerror', e => { console.log('  page error: ' + e.message); bad++; });

await page.route('**/*', route => {
  const url = route.request().url();
  const js = body => route.fulfill({ contentType: 'application/javascript', body });
  if (url.endsWith('/media.js')) return js(MEDIA);
  if (url.endsWith('/util.js')) return js(UTIL);
  if (url.endsWith('/config.js')) return js('export const proxyUrl = u => u;\n');
  if (url.endsWith('/editor.js')) return js('export const fabric = window.fabric;\n');
  if (url.endsWith('/io.js')) return js('export const saveAnimation = () => {};\n');
  if (url.endsWith('/fabric.js')) return js(FABRIC);
  return route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><canvas id="c" width="400" height="300"></canvas>'
    + '<input type="range" id="anim-tempo" min="-4" max="4" step="0.5" value="0">'
    + '<input type="number" id="video-length" min="0" max="15" step="0.5">'
    + '<script src="/fabric.js"></script>' });
});
await page.goto('https://studio.test/');
await page.evaluate(async () => {
  window.media = await import('/media.js');
  window.util = await import('/util.js');
  // An editor as media.js sees it: a canvas with one element whose motion
  // ends at 10 s - longer than the automatic 8 s.
  const canvas = new fabric.StaticCanvas('c');
  const o = new fabric.Rect({ width: 10, height: 10 });
  o.anim = { type: 'fadeIn', dur: 500 };
  window.media.setStart(o, 9500);
  canvas.add(o);
  window.ed = { canvas };
  window.feld = v => { document.getElementById('video-length').value = v; };
  // Answers the dialog the way a user would, and notes what it said.
  window.pruefe = async (knopf) => {
    const lauf = window.media.laengePruefen(window.ed);
    await new Promise(r => setTimeout(r, 50));
    const box = document.querySelector('.studio-modal');
    const gesehen = box ? { titel: box.querySelector('h4').textContent, text: box.textContent,
                            knoepfe: [...box.querySelectorAll('button')].map(b => b.textContent) } : null;
    if (box && knopf) [...box.querySelectorAll('button')].find(b => b.textContent.startsWith(knopf)).click();
    return { weiter: await lauf, gesehen, feld: document.getElementById('video-length').value,
             merker: window._videoLen };
  };
});

console.log('\n=== How long the animation needs ===');
const dauer = await page.evaluate(() => {
  feld('');
  return { braucht: media.benoetigteDauer(ed) };
});
check('needs the end of its last motion plus the short tail (10.3 s)', dauer.braucht === 10300, dauer.braucht);

console.log('\n=== A length that cuts the animation is asked about ===');
let r = await page.evaluate(() => { feld('8'); return pruefe('Use'); });
check('the dialog comes up', !!r.gesehen, JSON.stringify(r));
check('it names the set length and what is needed',
  r.gesehen && /Video length 8 s cuts the animation/.test(r.gesehen.text) && /needs 10\.3 s/.test(r.gesehen.text),
  r.gesehen && r.gesehen.text);
check('three choices: use, keep, cancel',
  r.gesehen && r.gesehen.knoepfe.join('|') === 'Use 10.5 s|Keep 8 s|Cancel', r.gesehen && r.gesehen.knoepfe.join('|'));
check('"Use" saves on with the length it needs, in half seconds', r.weiter === true && r.feld === '10.5' && r.merker === '10.5',
  JSON.stringify(r));

r = await page.evaluate(() => { feld('8'); return pruefe('Keep'); });
check('"Keep" saves on with 8 s', r.weiter === true && r.feld === '8', JSON.stringify(r));

r = await page.evaluate(() => { feld('8'); return pruefe('Cancel'); });
check('"Cancel" calls the save off', r.weiter === false && r.feld === '8', JSON.stringify(r));

r = await page.evaluate(() => { feld(''); return pruefe('Use'); });
check('an empty field (automatic, 8 s) is caught too - that was #143',
  r.gesehen && /The automatic length \(8 s\) cuts/.test(r.gesehen.text) && r.feld === '10.5', JSON.stringify(r));

r = await page.evaluate(() => { feld('11'); return pruefe(null); });
check('a length that is long enough saves without a question', r.weiter === true && !r.gesehen, JSON.stringify(r));

r = await page.evaluate(() => {
  ed.canvas.getObjects()[0].anim.dur = 0; media.setStart(ed.canvas.getObjects()[0], 0);
  ed.canvas.getObjects()[0].anim = { type: 'fadeIn', dur: 600 };
  feld(''); return pruefe(null);
});
check('a short animation on automatic saves without a question', r.weiter === true && !r.gesehen, JSON.stringify(r));

console.log('\n=== The length a design carries ===');
const aus = await page.evaluate(() => ({
  text: util.laengeAus(JSON.stringify({ version: 2, videoLength: 9 })),
  objekt: util.laengeAus({ videoLength: '10.5' }),
  ohne: util.laengeAus('{"version":2}'),
  kaputt: util.laengeAus('{"version":2, kaputt'),
  zuLang: util.laengeAus({ videoLength: 40 }),
  null: util.laengeAus(null),
}));
check('read from the JSON text and from the object', aus.text === 9 && aus.objekt === 10.5, JSON.stringify(aus));
check('no length, unreadable text or nothing: 0 (automatic)', aus.ohne === 0 && aus.kaputt === 0 && aus.null === 0, JSON.stringify(aus));
check('never more than the 15 s ceiling', aus.zuLang === 15, JSON.stringify(aus));

const setzen = await page.evaluate(() => {
  util.laengeSetzen(9); const a = [document.getElementById('video-length').value, window._videoLen, util.eingestellteLaenge()];
  util.laengeSetzen(0); const b = [document.getElementById('video-length').value, window._videoLen, util.eingestellteLaenge()];
  // Before the animation bar has built the field, the length waits in _videoLen.
  const f = document.getElementById('video-length'); f.remove();
  util.laengeSetzen(12); const c = [window._videoLen, util.eingestellteLaenge()];
  return { a, b, c };
});
check('setting a length fills the field and the memo the field is built from',
  setzen.a.join('|') === '9|9|9', setzen.a.join('|'));
check('0 empties both again (automatic)', setzen.b.join('|') === '||0', setzen.b.join('|'));
check('without the field the length still counts', setzen.c.join('|') === '12|12', setzen.c.join('|'));

console.log('\n=== Wired where it ships ===');
const einmal = (quelle, teil) => quelle.split(teil).length - 1;
check('io.js: the design carries videoLength when one is set',
  /\.\.\.\(videoLength > 0 \? \{ videoLength \} : \{\}\)/.test(IO));
check('io.js: image and video saves both pass the field',
  einmal(IO, 'buildCanvasJson(editor, preview, eingestellteLaenge())') === 2);
check('studio.js: a template is saved without a length',
  /io\.buildCanvasJson\(editor, preview\);/.test(STUDIO));
check('studio.js: post, output and "continue editing" bring the length back',
  einmal(STUDIO, 'mitLaenge: true') === 3);
check('studio.js: a template is opened without it',
  /ladeCanvas\(tpl\.canvas_json, \{ frisch: true \}\)/.test(STUDIO));
check('studio.js: both save paths ask before a GIF or video',
  einmal(STUDIO, 'await media.laengePruefen(editor)') === 2);
check('entwuerfe.js: prepared drafts use the same helpers', /laengeAus\(zustand\)/.test(ENTWUERFE));

await browser.close();
console.log(`\n${good} ok, ${bad} failed`);
process.exit(bad ? 1 : 0);
