/* What is on the canvas when the Studio opens - and does it say why?

   Three different things used to look identical: a draft that is really empty,
   a draft whose picture answers 404, and a post carrying a file that was never
   built here. All three showed a blank artboard and not one word.

   The 404 case is the one that cost the most: Fabric builds an image object for
   a dead source without complaint, so the element is there and the picture is
   not. And a source went dead routinely, because a draft saved on the
   development server stored http://127.0.0.1:8000/... and opened on Render
   pointing at a machine that does not exist there.

   This runs the real start-up block and the real address handling out of the
   files that ship - no browser, no Fabric.

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
const ioSrc = readFileSync(find('io.js'), 'utf8');

// Cut the block out of the file that ships. A copy here would drift.
function schneideBlock(quelle, marke, name) {
  const start = quelle.indexOf(marke);
  if (start < 0) throw new Error(name + ' not found');
  let depth = 0, ende = -1;
  for (let i = quelle.indexOf('{', start); i < quelle.length; i++) {
    if (quelle[i] === '{') depth++;
    else if (quelle[i] === '}') { depth--; if (depth === 0) { ende = i; break; } }
  }
  if (ende < 0) throw new Error('unbalanced braces in ' + name);
  return { start, ende };
}

const b = schneideBlock(src, '(async function restoreInitial() {', 'restoreInitial');
const QUELLE = src.slice(b.start, src.indexOf(')', src.indexOf('(', b.ende)) + 1);

function schneideFunktion(quelle, name) {
  const b2 = schneideBlock(quelle, 'function ' + name + '(', name);
  return quelle.slice(b2.start, b2.ende + 1);
}

let good = 0, bad = 0;
function check(name, ok, extra = '') {
  if (ok) { good++; console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra !== '' ? '  -> ' + extra : '')); }
}

/* Everything the block touches, reduced to a note of what it was asked to do. */
async function starte(config, { bildFehler = false, fehlend = 0 } = {}) {
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
  const fehlendeBilder = () => fehlend;
  const window = { dispatchEvent: () => { tat.geladen = true; } };
  const lauf = new Function('CONFIG', 'io', 'editor', 'status', 'toast', 'fit',
                            'fehlendeBilder', 'window', 'return ' + QUELLE)(
    config, io, editor, status, toast, fit, fehlendeBilder, window);
  await lauf;
  tat.text = tat.meldungen.join(' | ');
  return tat;
}

const BILD = '/library/studio/api/post-image/42/';
const GIF = '/library/studio/nc-image/?p=Planner/Videos/Clip.gif';

console.log('\n=== A draft whose picture is gone says so ===');
{
  // The element is on the artboard, the picture behind it answers 404. Without
  // a word about it the artboard looks like an empty draft.
  const tat = await starte({ postData: { id: 42, canvas_json: '{"post":1}' } }, { fehlend: 1 });
  check('the draft is loaded', tat.wiederhergestellt.length === 1, tat.wiederhergestellt);
  check('and the missing picture is named',
        /no longer there/.test(tat.text), tat.text);
}
{
  const tat = await starte({ postData: { id: 42, canvas_json: '{"post":1}' } }, { fehlend: 0 });
  check('an intact draft says nothing of the sort', !/no longer there/.test(tat.text), tat.text);
}

console.log('\n=== A post whose picture was attached, not built here ===');
{
  const tat = await starte({ postData: { id: 42, image_url: BILD } });
  check('the picture lands on the canvas', tat.bilder.length === 1 && tat.bilder[0] === BILD,
        JSON.stringify(tat.bilder));
  check('and nothing was restored from a draft', tat.wiederhergestellt.length === 0,
        tat.wiederhergestellt.length);
}
{
  const tat = await starte({ postData: { id: 42, image_url: BILD } }, { bildFehler: true });
  check('a missing file says so instead of sitting there empty',
        /could not be loaded/.test(tat.text), tat.text);
}

console.log('\n=== A GIF on the post: the still frame, and a warning with it ===');
{
  const tat = await starte({ postData: { id: 60, image_url: '', gif: 'x/Clip.gif', gif_url: GIF } });
  check('the first frame is put on the canvas', tat.bilder[0] === GIF, tat.bilder);
  check('and it is said what it is', /Still frame/.test(tat.text), tat.text);
  check('including what saving over it would do',
        /back to your outputs/.test(tat.text), tat.text);
}
{
  // A .gif parked in the video column is a GIF all the same.
  const tat = await starte({ postData: { id: 60, video: 'x/Clip.gif', video_url: GIF } });
  check('a .gif in the video slot counts too', tat.bilder[0] === GIF, tat.bilder);
}
{
  const tat = await starte({ postData: { id: 61, video: 'x/Clip.webm', video_url: '/nc/Clip.webm' } });
  check('a real video is not flattened onto the canvas', tat.bilder.length === 0, tat.bilder);
  check('but the artboard is no longer blank without explanation',
        /video that was not built here/.test(tat.text), tat.text);
}

console.log('\n=== A saved draft still wins over the bare file ===');
{
  const tat = await starte({ postData: { id: 42, image_url: BILD, canvas_json: '{"post":1}' } });
  check('the draft is loaded', tat.wiederhergestellt.length === 1, tat.wiederhergestellt);
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
  check('its draft is loaded', tat.wiederhergestellt[0] === '{"lib":1}', tat.wiederhergestellt);
  check('without also loading the picture', tat.bilder.length === 0, tat.bilder);
}
{
  const tat = await starte({ libData: { image_url: '/library/image/9/' } });
  check('a library entry without a draft loads its picture',
        tat.bilder[0] === '/library/image/9/', tat.bilder);
}

console.log('\n=== Nothing to open ===');
{
  const tat = await starte({});
  check('no draft, no picture, no crash',
        tat.wiederhergestellt.length === 0 && tat.bilder.length === 0);
  check('and the Studio still reports itself ready', tat.geladen === true);
}

console.log('\n=== Addresses do not carry a machine name ===');
{
  const speichern = new Function('window',
    'return ' + schneideFunktion(ioSrc, 'alsPfadSpeichern'))(
    { location: { origin: 'http://127.0.0.1:8000' } });
  const lesen = new Function('window',
    'return ' + schneideFunktion(ioSrc, 'alsPfadLesen'))(
    { location: { origin: 'https://linkedin-django-wd7a.onrender.com' } });

  check('saving strips our own host',
        speichern('http://127.0.0.1:8000/library/studio/api/post-image/60/')
        === '/library/studio/api/post-image/60/');
  check('a foreign address is left alone',
        speichern('https://cloud.example.com/remote.php/x.png')
        === 'https://cloud.example.com/remote.php/x.png');
  check('a path stays a path', speichern('/library/image/9/') === '/library/image/9/');
  check('and nothing chokes on an empty value', speichern('') === '' && speichern(null) === null);

  // This is the case from post #60: saved locally, opened on Render.
  check('opening repairs an address from another machine',
        lesen('http://127.0.0.1:8000/library/studio/api/post-image/60/')
        === '/library/studio/api/post-image/60/');
  check('Nextcloud addresses are not touched',
        lesen('https://cloud.example.com/remote.php/dav/files/x/y.png')
        === 'https://cloud.example.com/remote.php/dav/files/x/y.png');
  check('and neither is an nc:// reference', lesen('nc://Planner/Images/x.png') === 'nc://Planner/Images/x.png');
  check('a data: image survives untouched',
        lesen('data:image/png;base64,AAAA') === 'data:image/png;base64,AAAA');
}

console.log('\n=== And both ends really use it ===');
{
  // The functions above are only worth anything if saving and opening actually
  // run the addresses through them. Testing them on their own would pass
  // happily while nothing in io.js called them.
  const bauen = ioSrc.slice(ioSrc.indexOf('export function buildCanvasJson'));
  check('saving flattens the addresses',
        /pfadeEinebnen\([^)]*alsPfadSpeichern\)/.test(bauen.slice(0, 900)));
  const laden = ioSrc.slice(ioSrc.indexOf('export function restoreCanvas'));
  check('opening repairs them',
        /pfadeEinebnen\([^)]*alsPfadLesen\)/.test(laden));
  check('the helper list for the backend is flattened too',
        /imgSrc: alsPfadSpeichern\(/.test(ioSrc));
}

console.log('\n' + good + ' ok, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
