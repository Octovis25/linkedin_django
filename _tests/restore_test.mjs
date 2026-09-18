/* What is on the canvas when the Studio opens?

   Opening the Studio from a post and finding an empty board is the one thing
   nobody expects - and it happened whenever the post's picture had been
   attached in the post rather than built here: without a saved design there
   was no branch that put the picture on the canvas, although the very same
   fallback existed for a library image.

   The order matters as much as the branches. A template beats a design, a
   design beats a bare picture, and nothing is ever loaded twice.

   This runs the real start-up block out of studio.js - no browser, no Fabric.
   It only needs an editor, a loader and a status line, and all three are stood
   in for here, which is what makes the order visible in the first place.

       node _tests/restore_test.mjs
*/
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STUDIO_DIR = path.join(HERE, '..', 'media_library', 'static', 'media_library', 'studio');

function find(name) {
  for (const p of [path.join(STUDIO_DIR, name), path.join(HERE, name)]) {
    if (existsSync(p)) return p;
  }
  throw new Error('not found: ' + name);
}

const src = readFileSync(find('studio.js'), 'utf8');

// Cut the block out of the file that ships. A copy here would drift.
const MARKE = '(async function restoreInitial() {';
const start = src.indexOf(MARKE);
if (start < 0) throw new Error('restoreInitial not found in studio.js');
let depth = 0, ende = -1;
for (let i = src.indexOf('{', start); i < src.length; i++) {
  if (src[i] === '{') depth++;
  else if (src[i] === '}') {
    depth--;
    if (depth === 0) { ende = i; break; }
  }
}
if (ende < 0) throw new Error('unbalanced braces in restoreInitial');
const QUELLE = src.slice(start, src.indexOf(')', src.indexOf('(', ende)) + 1);

let good = 0, bad = 0;
function check(name, ok, extra = '') {
  if (ok) { good++; console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra !== '' ? '  -> ' + extra : '')); }
}

/* Everything the block touches, reduced to a note of what it was asked to do. */
async function starte(config, { bildFehler = false } = {}) {
  const tat = { wiederhergestellt: [], bilder: [], groesse: null, meldungen: [], geladen: false };
  const editor = {
    addImageUrl: async (url) => {
      if (bildFehler) throw new Error('404');
      tat.bilder.push(url);
    },
    resetHistory: () => {},
    setSize: (w, h) => { tat.groesse = [w, h]; },
    _locked: false,
  };
  const io = {
    restoreCanvas: async (_ed, json) => { tat.wiederhergestellt.push(json); return true; },
  };
  const status = (text) => { tat.meldungen.push(String(text)); };
  const toast = () => {};
  const fit = () => {};
  const window = { dispatchEvent: () => { tat.geladen = true; } };
  const lauf = new Function('CONFIG', 'io', 'editor', 'status', 'toast', 'fit', 'window',
                            'return ' + QUELLE)(config, io, editor, status, toast, fit, window);
  await lauf;
  return tat;
}

const BILD = '/library/studio/api/post-image/42/';

console.log('\n=== A post whose picture was attached, not built here ===');
{
  // This is the regression: image on the post, no design - and the board stayed
  // empty.
  const tat = await starte({ postData: { id: 42, image_url: BILD } });
  check('the picture lands on the canvas', tat.bilder.length === 1 && tat.bilder[0] === BILD,
        JSON.stringify(tat.bilder));
  check('and nothing was restored from a design', tat.wiederhergestellt.length === 0,
        tat.wiederhergestellt.length);
}
{
  const tat = await starte({ postData: { id: 42, image_url: BILD } }, { bildFehler: true });
  check('a missing file says so instead of sitting there empty',
        tat.meldungen.some(m => m.includes('could not be loaded')), JSON.stringify(tat.meldungen));
}

console.log('\n=== A saved design wins over the bare picture ===');
{
  const tat = await starte({ postData: { id: 42, image_url: BILD, canvas_json: '{"post":1}' } });
  check('the design is loaded', tat.wiederhergestellt.length === 1, tat.wiederhergestellt);
  check('and the picture is NOT put on top of it', tat.bilder.length === 0, tat.bilder);
}

console.log('\n=== A template beats everything ===');
{
  const tat = await starte({
    tplData: { id: 3, canvas_json: '{"tpl":1}', width: 1350, height: 1350 },
    postData: { id: 42, image_url: BILD, canvas_json: '{"post":1}' },
  });
  check('the template is what loads', tat.wiederhergestellt[0] === '{"tpl":1}', tat.wiederhergestellt);
  check('and it sets the canvas size', String(tat.groesse) === '1350,1350', tat.groesse);
}

console.log('\n=== The library keeps working as before ===');
{
  const tat = await starte({ libData: { canvas_json: '{"lib":1}', image_url: '/library/image/9/' } });
  check('its design is loaded', tat.wiederhergestellt[0] === '{"lib":1}', tat.wiederhergestellt);
  check('without also loading the picture', tat.bilder.length === 0, tat.bilder);
}
{
  const tat = await starte({ libData: { image_url: '/library/image/9/' } });
  check('a library entry without a design loads its picture',
        tat.bilder[0] === '/library/image/9/', tat.bilder);
}

console.log('\n=== Nothing to open ===');
{
  const tat = await starte({});
  check('no design, no picture, no crash',
        tat.wiederhergestellt.length === 0 && tat.bilder.length === 0);
  check('and the Studio still reports itself ready', tat.geladen === true);
}

console.log('\n=== A GIF or video on the post is left to the banner ===');
{
  // Flattening either onto the canvas and saving over it would cost the
  // animation, so they stay a deliberate click.
  const tat = await starte({ postData: { id: 42, image_url: '', gif_url: '/nc/x.gif',
                                          video_url: '/nc/x.webm' } });
  check('nothing is loaded by itself', tat.bilder.length === 0, tat.bilder);
}

console.log('\n' + good + ' ok, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
