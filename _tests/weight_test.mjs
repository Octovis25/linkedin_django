/* Does the Normal/Bold field actually change anything?

   It did not. The field was read in exactly one place - when a NEW text was
   created - and never applied to something already on the canvas. Switching it
   with text selected did nothing, and because new text defaults to bold, the
   experience was "everything is always bold".

   What the fix must do, and just as importantly what it must NOT do: plain
   text changes, composed elements do not. A text block's heading is bold
   because it is a heading; a checklist's rows are bold by construction.
   Changing those as a whole would flatten them, and a single row can be had
   through the "Split rows" button instead.

       node _tests/weight_test.mjs
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

const src = readFileSync(find('studio.js'), 'utf8');
const FABRIC = find('vendor', 'fabric.min.js');

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

const CODE = ['istTextObj', 'gewichtVon', 'schriftStaerkeAufAuswahl', 'syncFontWeightInput',
              'wireWeightField']
  .map(cutOut).join('\n\n');

let good = 0, bad = 0;
function check(name, ok, extra = '') {
  if (ok) { good++; console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra ? '  -> ' + extra : '')); }
}

const SHELL = process.env.PW_CHROME
  || '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';
const browser = await chromium.launch(existsSync(SHELL) ? { executablePath: SHELL } : {});
const page = await browser.newPage();
page.on('pageerror', e => { console.log('  page error: ' + e.message); bad++; });

await page.setContent('<canvas id="c" width="400" height="300"></canvas>'
  + '<select id="font-weight"><option value="normal">Normal</option>'
  + '<option value="bold" selected>Bold</option></select>');
await page.addScriptTag({ path: FABRIC });

const r = await page.evaluate(({ code }) => {
  const canvas = new fabric.Canvas('c', { width: 400, height: 300 });
  let auswahl = [];
  const editor = { canvas, activeAll: () => auswahl, snapshot: () => {} };
  // eslint-disable-next-line no-eval
  eval(code);

  const text = (w) => new fabric.Textbox('Hello', { width: 120, fontWeight: w });
  const gruppe = (w) => new fabric.Group([new fabric.Textbox('Row', { width: 80, fontWeight: w })],
                                         { shapeKind: 'checklist' });

  const out = {};

  // --- plain text, both directions ---
  const t = text('bold');
  auswahl = [t];
  schriftStaerkeAufAuswahl('normal');
  out.nachNormal = t.fontWeight;
  schriftStaerkeAufAuswahl('bold');
  out.nachBold = t.fontWeight;

  // --- a composed element must be left alone ---
  const g = gruppe('bold');
  auswahl = [g];
  out.gruppeGeaendert = schriftStaerkeAufAuswahl('normal');
  out.gruppeInnen = g._objects[0].fontWeight;

  // --- a mixed selection: the text changes, the group does not ---
  const t2 = text('bold');
  const g2 = gruppe('bold');
  auswahl = [t2, g2];
  out.gemischt = schriftStaerkeAufAuswahl('normal');
  out.gemischtText = t2.fontWeight;
  out.gemischtGruppe = g2._objects[0].fontWeight;

  // --- nothing selected ---
  auswahl = [];
  out.leer = schriftStaerkeAufAuswahl('normal');

  // --- nonsense falls back to bold rather than writing it through ---
  const t3 = text('bold');
  auswahl = [t3];
  schriftStaerkeAufAuswahl('halbfett');
  out.unsinn = t3.fontWeight;

  // --- the field reports what is selected ---
  const feld = document.getElementById('font-weight');
  auswahl = [text('normal')];
  syncFontWeightInput();
  out.feldNormal = feld.value;
  auswahl = [text('bold')];
  syncFontWeightInput();
  out.feldBold = feld.value;
  // A numeric weight is bold too - the templates carry 700, not the word.
  auswahl = [text(700)];
  syncFontWeightInput();
  out.feld700 = feld.value;
  // With a group selected the field must not lie about it; it keeps its value.
  feld.value = 'normal';
  auswahl = [gruppe('bold')];
  syncFontWeightInput();
  out.feldGruppe = feld.value;

  // --- the field in the bar is actually wired to the canvas ---
  // Cutting out the function is not enough: it has to find the element, and a
  // plain change on the select has to reach the text. The bar is thrown away
  // and rebuilt on every change of selection, so this is where it breaks
  // quietly if the handler is ever attached only once at start-up.
  const leiste = document.createElement('div');
  leiste.innerHTML = '<select id="sel-font-weight">'
    + '<option value="normal">Normal</option>'
    + '<option value="bold" selected>Bold</option></select>';
  document.body.appendChild(leiste);
  const t4 = text('bold');
  auswahl = [t4];
  wireWeightField();
  const feld2 = document.getElementById('sel-font-weight');
  feld2.value = 'normal';
  feld2.dispatchEvent(new Event('change'));
  out.verdrahtet = t4.fontWeight;

  return out;
}, { code: CODE });

console.log('\n=== Plain text changes, in both directions ===');
check('Bold -> Normal really becomes normal', r.nachNormal === 'normal', r.nachNormal);
check('and back to Bold', r.nachBold === 'bold', r.nachBold);

console.log('\n=== Composed elements are left alone ===');
check('a checklist reports nothing changed', r.gruppeGeaendert === 0, r.gruppeGeaendert);
check('and its row is still bold', r.gruppeInnen === 'bold', r.gruppeInnen);

console.log('\n=== A mixed selection changes only the text ===');
check('exactly one element changed', r.gemischt === 1, r.gemischt);
check('the text is normal', r.gemischtText === 'normal', r.gemischtText);
check('the list stayed bold', r.gemischtGruppe === 'bold', r.gemischtGruppe);

console.log('\n=== Odd input ===');
check('nothing selected changes nothing', r.leer === 0, r.leer);
check('an unknown weight falls back to bold', r.unsinn === 'bold', r.unsinn);

console.log('\n=== The field shows what is selected ===');
check('normal text -> Normal', r.feldNormal === 'normal', r.feldNormal);
check('bold text -> Bold', r.feldBold === 'bold', r.feldBold);
check('fontWeight 700 -> Bold', r.feld700 === 'bold', r.feld700);
check('a group leaves the field as it was', r.feldGruppe === 'normal', r.feldGruppe);

await browser.close();

/* The second half of the story: the control has to be REACHABLE.
   The Normal/Bold field under Insert > Text sets what the next text will look
   like. While something is selected the user is in Build, where that panel is
   hidden - so for a long while the fix worked and still looked broken, because
   there was no control on screen to use it with. The weight now also sits in
   the bar above the canvas, and that bar is built from a spec: feed it a state
   and check what comes out. */
const { buildContext } = await import(
  'file://' + find('toolbar.js').replace(/\\/g, '/'));

const bar = (extra) => buildContext(Object.assign(
  { hasSel: true, count: 1, gridOn: false, maxi: false, keepRatio: true,
    label: 'Text', w: 10, h: 10, x: 0, y: 0 }, extra));

console.log('\n=== The field in the bar is wired to the canvas ===');
check('switching it really changes the text', r.verdrahtet === 'normal', r.verdrahtet);

console.log('\n=== And it is where the selection is ===');
const balkenBold = bar({ isText: true, fontWeight: 'bold' });
const balkenNormal = bar({ isText: true, fontWeight: 'normal' });
check('selected text brings the field up',
      /id="sel-font-weight"/.test(balkenBold));
check('bold text shows Bold',
      /value="bold" selected>Bold</.test(balkenBold), balkenBold.slice(0, 0));
check('normal text shows Normal',
      /value="normal" selected>Normal</.test(balkenNormal));
check('exactly one option is preselected',
      (balkenBold.match(/ selected>/g) || []).length === 1);
check('a checklist gets no field at all',
      !/sel-font-weight/.test(bar({ isText: false, isChecklist: true })));
check('and neither does an empty canvas',
      !/sel-font-weight/.test(buildContext({ hasSel: false, count: 0,
        gridOn: false, maxi: false })));

console.log('\n' + good + ' ok, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
