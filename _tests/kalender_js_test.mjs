/* Does the calendar's script survive a page that has half its elements?

   One template serves two calendars. The OJ one carries no list of recurring
   dates, so every getElementById for that list comes back null - and a single
   unguarded null ends the script. Not with a visible error: the page renders,
   looks finished, and then the month filter does nothing when clicked.

   So the script is pulled straight out of the template and run twice against a
   stubbed page: once with the list, once without. No browser, no Django, no
   Fabric - the script only needs a handful of elements, and all of them are
   stood in for here.

       node _tests/kalender_js_test.mjs
*/
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const VORLAGE = path.join(HERE, '..', 'planner', 'templates', 'planner', 'kalender.html');

const seite = readFileSync(VORLAGE, 'utf8');
const anfang = seite.lastIndexOf('<script>');
const ende = seite.lastIndexOf('</script>');
if (anfang < 0 || ende < anfang) throw new Error('no script block in kalender.html');

let quelle = seite.slice(anfang + '<script>'.length, ende)
  .replace(/\{\{ jahr \}\}/g, '2026')
  .replace(/'\{\{ basis \}\}'/g, "'/planner/kalender/'");

// Anything left would be a template tag inside the script that the stand-ins
// above do not cover - the script would then be run in a shape the browser
// never sees, and a green result would mean nothing.
const uebrig = quelle.match(/\{[{%][^]*?[%}]\}/g);
if (uebrig) throw new Error('unhandled template tags in the script: ' + uebrig.join(', '));

/* The elements that exist only on the planner calendar. */
const NUR_IM_PLANNER = new Set(['kal-zur-liste', 'kal-regeln', 'kal-liste',
  'nf-rule', 'nf-add', 'nf-fehler', 'nf-name', 'nf-kind', 'nf-month', 'nf-day',
  'nf-weekday', 'nf-nth', 'nf-weeks', 'nf-easter', 'nf-lead', 'nf-series']);

function element(id) {
  return {
    id, dataset: { start: '9' }, value: '9', hidden: false, textContent: '',
    innerHTML: '', classList: { toggle() {}, contains: () => false },
    addEventListener() {}, querySelectorAll: () => [], closest: () => null,
    scrollIntoView() {}, onclick: null, onchange: null,
  };
}

function laufen(mitListe) {
  const gefragt = [];
  const document = {
    getElementById(id) {
      gefragt.push(id);
      if (!mitListe && NUR_IM_PLANNER.has(id)) return null;
      return element(id);
    },
    querySelectorAll: () => [],
    querySelector: () => null,
    cookie: '',
  };
  const window = { location: { href: '' } };
  const fetch = () => Promise.resolve({ json: () => Promise.resolve({ termine: [] }) });
  new Function('document', 'window', 'fetch', quelle)(document, window, fetch);
  return gefragt;
}

let gut = 0, schlecht = 0;
function pruefe(name, fn) {
  try {
    const ergebnis = fn();
    gut++;
    console.log('  ok   ' + name + (ergebnis ? '  (' + ergebnis + ')' : ''));
  } catch (fehler) {
    schlecht++;
    console.log('  FAIL ' + name + ': ' + fehler.message);
  }
}

console.log('\n=== The script runs on both calendars ===');
pruefe('the planner calendar, with the list of recurring dates',
       () => laufen(true).length + ' elements asked for');
pruefe('the OJ calendar, without it',
       () => laufen(false).length + ' elements asked for');

console.log('\n=== And it really does ask for the missing ones ===');
// If the script never touched those elements, the test above would pass for
// the wrong reason - it would be proving nothing at all.
pruefe('the planner run touches the list', () => {
  const gefragt = laufen(true);
  const beruehrt = gefragt.filter(id => NUR_IM_PLANNER.has(id));
  if (!beruehrt.length) throw new Error('the script never asks for the list at all');
  return beruehrt.length + ' of them';
});
pruefe('and the OJ run asks for them too, and copes with null', () => {
  const gefragt = laufen(false);
  const beruehrt = gefragt.filter(id => NUR_IM_PLANNER.has(id));
  if (!beruehrt.length) throw new Error('nothing was asked for, so nothing was guarded');
  return beruehrt.length + ' asked for, all null';
});

console.log('\n=== The rows it writes into the list ===');
// The rows are built by joining strings, which is exactly where a quote in a
// name breaks an attribute and nobody notices until a name has one.
const REGELN = [
  { id: 1, name: 'World Cancer Day', kind: 'awareness', rule_text: 'fixed', lead_days: 21,
    series: 'Oncology', active: 1, datum: '2026-02-04', berechnet: '2026-02-04',
    name_im_jahr: 'World Cancer Day', verschoben: false, umbenannt: false,
    art_text: 'Awareness', dieses_jahr_versteckt: false },
  { id: 2, name: 'Whit Monday', kind: 'holiday', rule_text: 'moves', lead_days: 7,
    series: '', active: 1, datum: '2026-05-26', berechnet: '2026-05-25',
    name_im_jahr: 'Whit Monday (moved)', verschoben: true, umbenannt: true,
    art_text: 'Holiday', dieses_jahr_versteckt: false },
  { id: 3, name: 'He said "go"', kind: 'own', rule_text: 'fixed', lead_days: 14,
    series: '', active: 0, datum: '2026-07-01', berechnet: '2026-07-01',
    name_im_jahr: 'He said "go"', verschoben: false, umbenannt: false,
    art_text: 'Ours', dieses_jahr_versteckt: false },
];

async function zeilenBauen() {
  let geschrieben = '';
  const document = {
    getElementById(id) {
      const el = element(id);
      if (id === 'kal-regeln') {
        Object.defineProperty(el, 'innerHTML', {
          get: () => geschrieben, set: (v) => { geschrieben = v; },
        });
      }
      return el;
    },
    querySelectorAll: () => [], querySelector: () => null, cookie: '',
  };
  const window = { location: { href: '' }, alert() {} };
  const fetch = () => Promise.resolve({
    json: () => Promise.resolve({ jahr: 2026, termine: REGELN.map(r => ({ ...r })) }),
  });
  new Function('document', 'window', 'fetch', quelle)(document, window, fetch);
  await new Promise(r => setTimeout(r, 0));   // let the fetch settle
  return geschrieben;
}

const zeilen = await zeilenBauen();

pruefe('the list really was written', () => {
  if (!zeilen || zeilen.length < 100) throw new Error('nothing was written into the list');
  return zeilen.length + ' characters';
});
pruefe('each row carries a date for this year',
       () => (zeilen.match(/type="date"/g) || []).length === 3
             ? '3 date fields'
             : (() => { throw new Error('found ' + (zeilen.match(/type="date"/g) || []).length); })());
pruefe('the moved one shows the day it was moved TO', () => {
  if (!zeilen.includes('value="2026-05-26"')) throw new Error('the moved date is not in the row');
  return '26.05.';
});
pruefe('and offers a way back to the rule', () => {
  const zurueck = (zeilen.match(/class="zurueck"/g) || []).length;
  if (zurueck !== 1) throw new Error(zurueck + ' reset buttons, expected 1');
  return 'on the changed row only';
});
pruefe('the rename shows this year\'s name, not the list\'s', () => {
  if (!zeilen.includes('value="Whit Monday (moved)"')) throw new Error('missing');
  return 'ok';
});
pruefe('a quote in a name cannot break out of the attribute', () => {
  if (zeilen.includes('value="He said "go""')) throw new Error('the attribute is broken open');
  if (!zeilen.includes('&quot;go&quot;')) throw new Error('the quote was not escaped at all');
  return 'escaped';
});
pruefe('an entry taken out of the list cannot be edited', () => {
  const aus = zeilen.slice(zeilen.lastIndexOf('<tr'));
  if (!aus.includes('disabled')) throw new Error('its fields are still live');
  return 'its fields are disabled';
});

console.log('\n' + gut + ' ok, ' + schlecht + ' failed');
process.exit(schlecht ? 1 : 0);
