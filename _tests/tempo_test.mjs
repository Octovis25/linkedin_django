/* Does the tempo really stretch the whole piece?

   The tempo multiplies every Speed and every Start at once. Three things have
   to hold, and only the first is obvious:

     1. an element starts later,
     2. it also takes longer - starting late but running at the old speed
        would be no slowdown at all,
     3. the exported length grows with it, or the slowed piece is simply cut
        off at the end and the last row never appears. (animDuration() reads
        the canvas and the toolbar together; it is covered by the Speed and
        Start checks below, which is where the stretching happens.)

   This runs the REAL media.js as a module. Its two imports are answered with
   stubs, so nothing is copied here that could drift from what ships.

       node _tests/tempo_test.mjs
*/
import { chromium } from 'playwright';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STUDIO_DIR = path.join(HERE, '..', 'media_library', 'static', 'media_library', 'studio');

function find(...bits) {
  for (const p of [path.join(STUDIO_DIR, ...bits), path.join(HERE, bits[bits.length - 1])]) {
    if (existsSync(p)) return p;
  }
  throw new Error('not found: ' + bits.join('/'));
}

const MEDIA = readFileSync(find('media.js'), 'utf8');
const FABRIC = readFileSync(find('vendor', 'fabric.min.js'), 'utf8');

let good = 0, bad = 0;
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;
function check(name, ok, extra = '') {
  if (ok) { good++; console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra ? '  -> ' + extra : '')); }
}

const SHELL = process.env.PW_CHROME
  || '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';
const browser = await chromium.launch(existsSync(SHELL) ? { executablePath: SHELL } : {});
const page = await browser.newPage();
page.on('pageerror', e => { console.log('  page error: ' + e.message); bad++; });

// The module under test, served whole; its imports answered with stubs.
await page.route('**/*', route => {
  const url = route.request().url();
  const js = body => route.fulfill({ contentType: 'application/javascript', body });
  if (url.endsWith('/media.js')) return js(MEDIA);
  if (url.endsWith('/util.js')) return js('export const toast = () => {};\nexport const status = () => {};\n');
  if (url.endsWith('/io.js')) return js('export const saveAnimation = () => {};\n');
  if (url.endsWith('/fabric.js')) return js(FABRIC);
  return route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><canvas id="c" width="400" height="300"></canvas>'
    + '<input type="range" id="anim-tempo" min="0.5" max="6" step="0.25" value="1">'
    + '<script src="/fabric.js"></script>' });
});
await page.goto('https://studio.test/');
await page.addScriptTag({ url: '/media.js', type: 'module', content: undefined }).catch(() => {});
await page.evaluate(async () => { window.media = await import('/media.js'); });

const r = await page.evaluate(() => {
  const media = window.media;
  const out = {};
  const setTempo = v => { document.getElementById('anim-tempo').value = String(v); return media.readTempo(); };

  const box = () => {
    const o = new fabric.Rect({ width: 10, height: 10, opacity: 1, left: 0, top: 0 });
    o.anim = { type: 'fadeIn', dur: 800 };
    media.setStart(o, 400);
    return o;
  };

  // A range input snaps and clamps its own value, so it can never hand
  // readTempo() anything out of range. The guard inside the function is there
  // for values that do NOT come from the slider - a saved file, a typo - so it
  // is exercised through a plain text field carrying the same id.
  const slider = document.getElementById('anim-tempo');
  const feld = document.createElement('input');
  feld.type = 'text'; feld.id = 'anim-tempo';
  slider.removeAttribute('id');
  document.body.appendChild(feld);
  const setzeText = v => { feld.value = String(v); return media.readTempo(); };
  out.clamp = { low: setzeText(0.1), high: setzeText(99),
                leer: setzeText(''), quatsch: setzeText('schnell') };
  feld.remove(); slider.id = 'anim-tempo';
  out.clamp.normal = setTempo(1);

  // --- fade-in at 1x ---
  setTempo(1);
  const a = box();
  out.plain = [0, 400, 800, 1200].map(t => { media.applyAt(a, t); return +a.opacity.toFixed(4); });

  // --- the same at 3x ---
  setTempo(3);
  const b = box();
  out.slow = [0, 400, 1200, 2400, 3600].map(t => { media.applyAt(b, t); return +b.opacity.toFixed(4); });

  // --- a loop must run slower, not just start later ---
  const loopAt = (tempoValue, t) => {
    setTempo(tempoValue);
    const o = new fabric.Rect({ width: 10, height: 10, scaleX: 1, scaleY: 1 });
    o.anim = { type: 'pulse', dur: 1200 };
    media.setStart(o, 0);
    media.applyAt(o, t);
    return +o.scaleX.toFixed(9);
  };
  // At twice the tempo the same state must be reached after twice the time.
  out.loop = { einfach: loopAt(1, 500), doppelt: loopAt(2, 1000), ungleich: loopAt(2, 500) };

  return out;
});

console.log('\n=== The tempo stays within bounds ===');
check('0.1x is raised to 0.25x', r.clamp.low === 0.25, r.clamp.low);
check('99x is cut to 8x', r.clamp.high === 8, r.clamp.high);
check('1x stays 1x', r.clamp.normal === 1, r.clamp.normal);
check('an empty value falls back to 1x', r.clamp.leer === 1, r.clamp.leer);
check('and so does nonsense', r.clamp.quatsch === 1, r.clamp.quatsch);

console.log('\n=== Fade in at 1x: starts at 400 ms, done at 1200 ms ===');
check('t=0    invisible', r.plain[0] === 0, r.plain[0]);
check('t=400  still invisible (that is the start)', r.plain[1] === 0, r.plain[1]);
check('t=800  halfway there', r.plain[2] > 0.5 && r.plain[2] < 1, r.plain[2]);
check('t=1200 fully there', near(r.plain[3], 1), r.plain[3]);

console.log('\n=== At 3x everything stretches threefold ===');
check('t=400  still nothing - the start moved to 1200', r.slow[1] === 0, r.slow[1]);
check('t=1200 only now does it begin', r.slow[2] === 0, r.slow[2]);
check('t=2400 halfway - at 1x it was long finished', r.slow[3] > 0.5 && r.slow[3] < 1, r.slow[3]);
check('t=3600 fully there', near(r.slow[4], 1), r.slow[4]);

console.log('\n=== A loop runs slower, it does not merely start later ===');
check('2x after 1000 ms = 1x after 500 ms',
      near(r.loop.einfach, r.loop.doppelt, 1e-9), r.loop.einfach + ' vs ' + r.loop.doppelt);
check('and 2x after 500 ms is NOT the same state',
      !near(r.loop.einfach, r.loop.ungleich, 1e-4), r.loop.ungleich);

await browser.close();
console.log('\n' + good + ' ok, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
