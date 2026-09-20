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

console.log('\n' + gut + ' ok, ' + schlecht + ' failed');
process.exit(schlecht ? 1 : 0);
