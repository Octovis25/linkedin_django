/* Does splitting a checklist leave the picture untouched?

   The rows must land exactly where they sat inside the group. If the geometry
   is off, the list jumps on splitting and every layout has to be redone by
   hand - and the user would only notice after the fact.

   So this test does not check the arithmetic against itself. It renders the
   canvas to a PNG before the split and again afterwards and compares the
   pixels - the same thing the eye would do, independent of how the position
   is computed.

   One catch, and it cost an hour to find: with Fabric's object cache on (the
   default) the two images differ by a few hundred antialiased pixels even
   when every coordinate matches to the last digit. A group is rasterised into
   an offscreen canvas first, and three one-row groups hit a different
   sub-pixel phase than one three-row group. Nothing moves on screen - it is
   the cache, not the layout. The pixel comparison therefore runs with
   objectCaching off, and the coordinates are checked separately and exactly.

   The functions under test are cut out of the real studio.js - the file that
   ships - rather than copied here. A copy would drift.

       node _tests/split_test.mjs
*/
import { chromium } from 'playwright';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STUDIO_DIR = path.join(HERE, '..', 'media_library', 'static', 'media_library', 'studio');

// Same rule as the other tests here: look in the project first, then next to
// this file, so the test also runs from a folder of its own.
function find(...bits) {
  for (const p of [path.join(STUDIO_DIR, ...bits), path.join(HERE, bits[bits.length - 1])]) {
    if (existsSync(p)) return p;
  }
  throw new Error('not found: ' + bits.join('/'));
}
const STUDIO = find('studio.js');
const FABRIC = find('vendor', 'fabric.min.js');

// ---- cut the functions out of the shipping file --------------------------
const src = readFileSync(STUDIO, 'utf8');

function cutOut(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('not found in studio.js: ' + name);
  let depth = 0, i = src.indexOf('{', start);
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (!depth) return src.slice(start, j + 1); }
  }
  throw new Error('unbalanced braces in ' + name);
}

const CODE = ['isChecklist', 'buildCheckList', 'circleCentre', 'splitChecklist']
  .map(cutOut).join('\n\n');

let good = 0, bad = 0;
function check(name, ok, extra = '') {
  if (ok) { good++; console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra ? '  -> ' + extra : '')); }
}

// Playwright's own download is not always there; PW_CHROME points at an
// existing Chromium when it is not.
const SHELL = process.env.PW_CHROME
  || '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';
const browser = await chromium.launch(existsSync(SHELL) ? { executablePath: SHELL } : {});
const page = await browser.newPage();
page.on('pageerror', e => { console.log('  page error: ' + e.message); bad++; });

await page.setContent('<canvas id="c" width="600" height="400"></canvas>');
await page.addScriptTag({ path: FABRIC });

const result = await page.evaluate(({ code }) => {
  const out = {};
  const canvas = new fabric.Canvas('c', { width: 600, height: 400, backgroundColor: '#ffffff' });

  // The bare minimum of the studio the cut-out functions touch.
  const editor = {
    width: 600, height: 400, canvas,
    active: () => canvas.getActiveObject(),
    snapshot: () => {},
  };
  const toast = (m) => { out.toast = m; };
  // eslint-disable-next-line no-eval
  eval(code);

  function run(items, tweak) {
    canvas.clear();
    canvas.backgroundColor = '#ffffff';
    const g = buildCheckList(items, { width: 260, size: 22, color: '#161616' });
    if (tweak) g.set(tweak);
    // See the note at the top: the cache would blur an exact comparison.
    g.objectCaching = false; g._objects.forEach(o => { o.objectCaching = false; });
    canvas.add(g);
    canvas.renderAll();
    const before = canvas.toDataURL();
    // Where does each circle sit before the split? That is the anchor the rows
    // have to hit again.
    const anchors = g._objects.filter((_, i) => i % 3 === 0)
      .map(c => circleCentre(c, g.calcTransformMatrix())).map(p => ({ x: p.x, y: p.y }));
    const rows = splitChecklist(g);
    rows.forEach(r => { r.objectCaching = false; r._objects.forEach(o => { o.objectCaching = false; }); });
    canvas.renderAll();
    const moved = rows.map((r, i) => {
      const p = circleCentre(r._objects[0], r.calcTransformMatrix());
      return Math.max(Math.abs(p.x - anchors[i].x), Math.abs(p.y - anchors[i].y));
    });
    return { before, after: canvas.toDataURL(), identical: before === canvas.toDataURL(),
             moved: Math.max(...moved),
             count: rows ? rows.length : 0,
             objects: canvas.getObjects().length,
             kinds: canvas.getObjects().map(o => o.shapeKind),
             items: canvas.getObjects().map(o => (o.clItems || []).join('|')) };
  }

  out.plain = run(['traceable', 'auditable', 'accessible']);
  out.rotated = run(['one', 'two', 'three', 'four'], { angle: 17, scaleX: 1.4, scaleY: 1.4 });
  out.five = run(['a', 'b', 'c', 'd', 'e']);

  // A one-row list must refuse rather than do something odd.
  canvas.clear();
  const single = buildCheckList(['only'], { width: 260, size: 22, color: '#161616' });
  canvas.add(single);
  out.singleResult = splitChecklist(single);
  out.singleToast = out.toast;
  out.singleStillThere = canvas.getObjects().length;

  // Timing has to travel to every row.
  canvas.clear();
  const timed = buildCheckList(['x', 'y'], { width: 260, size: 22, color: '#161616' });
  timed.set({ anim: { type: 'fadeIn', dur: 900 }, startAt: 400, fx: 'glow', fxDelay: 400 });
  canvas.add(timed);
  const timedRows = splitChecklist(timed);
  out.timing = timedRows.map(o => ({ type: o.anim && o.anim.type, dur: o.anim && o.anim.dur,
                                     startAt: o.startAt, fx: o.fx }));
  // The copy must be a copy: changing one row may not move the other.
  timedRows[0].anim.dur = 1;
  out.animShared = timedRows[1].anim.dur === 1;

  return out;
}, { code: CODE });

// ---- comparing the two PNGs ----------------------------------------------
async function differingPixels(a, b) {
  return await page.evaluate(async ([da, db]) => {
    const load = src => new Promise(res => { const i = new Image(); i.onload = () => res(i); i.src = src; });
    const [ia, ib] = await Promise.all([load(da), load(db)]);
    if (ia.width !== ib.width || ia.height !== ib.height) return -1;
    const draw = img => {
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      c.getContext('2d').drawImage(img, 0, 0);
      return c.getContext('2d').getImageData(0, 0, img.width, img.height).data;
    };
    const pa = draw(ia), pb = draw(ib);
    let n = 0;
    for (let i = 0; i < pa.length; i += 4) {
      if (Math.abs(pa[i] - pb[i]) > 8 || Math.abs(pa[i + 1] - pb[i + 1]) > 8
          || Math.abs(pa[i + 2] - pb[i + 2]) > 8 || Math.abs(pa[i + 3] - pb[i + 3]) > 8) n++;
    }
    return n;
  }, [a, b]);
}

console.log('\n=== No row moves by even a fraction of a pixel ===');
// 1e-9 px is not a safety margin, it is the floating-point floor: a rotation
// matrix leaves a rest around 1e-14. Anything a person could see is orders of
// magnitude above this.
for (const [name, r] of [['3 rows, upright', result.plain],
                         ['4 rows, rotated 17 degrees and scaled 1.4x', result.rotated],
                         ['5 rows', result.five]]) {
  check(name + ': largest shift ' + r.moved.toExponential(1) + ' px', r.moved < 1e-9, r.moved);
}

console.log('\n=== And the rendered picture is identical, pixel for pixel ===');
for (const [name, r] of [['3 rows, upright', result.plain],
                         ['4 rows, rotated 17 degrees and scaled 1.4x', result.rotated],
                         ['5 rows', result.five]]) {
  const n = await differingPixels(r.before, r.after);
  check(name + ': ' + n + ' pixel(s) differ', n === 0, n);
}

console.log('\n=== What comes out of it ===');
check('3 rows produce 3 elements', result.plain.count === 3, result.plain.count);
check('5 rows produce 5 elements', result.five.count === 5, result.five.count);
check('nothing else is left on the canvas', result.five.objects === 5, result.five.objects);
check('every row is still a checklist',
      result.plain.kinds.every(k => k === 'checklist'), result.plain.kinds.join(','));
check('every row keeps its own text',
      result.plain.items.join(',') === 'traceable,auditable,accessible', result.plain.items.join(','));

console.log('\n=== A single row is refused ===');
check('splitting returns nothing', result.singleResult === null, result.singleResult);
check('and says why', /single row/i.test(result.singleToast || ''), result.singleToast);
check('the list is still there', result.singleStillThere === 1, result.singleStillThere);

console.log('\n=== Motion and Start travel along ===');
check('row 1 keeps the motion', result.timing[0].type === 'fadeIn', JSON.stringify(result.timing[0]));
check('row 2 keeps it too', result.timing[1].type === 'fadeIn', JSON.stringify(result.timing[1]));
check('the start travels', result.timing.every(t => t.startAt === 400), JSON.stringify(result.timing));
check('the effect travels', result.timing.every(t => t.fx === 'glow'), JSON.stringify(result.timing));
check('each row has its OWN motion object', !result.animShared,
      'changing row 1 changed row 2');

await browser.close();
console.log('\n%d ok, %d failed'.replace('%d', good).replace('%d', bad));
process.exit(bad ? 1 : 0);
