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
  const knopf = { onclick: null };
  return {
    id, dataset: { start: '9' }, value: '9', hidden: false, textContent: '',
    innerHTML: '', classList: { toggle() {}, contains: () => false, add() {}, remove() {} },
    addEventListener() {}, querySelectorAll: () => [], closest: () => null,
    querySelector: () => knopf, knopf,
    scrollIntoView() {}, onclick: null, onchange: null,
  };
}

function laufen(mitListe, fetchErgebnis) {
  const gefragt = [];
  const gesendet = [];
  const lauscher = {};
  const elemente = {};
  const document = {
    addEventListener(art, fn) { (lauscher[art] = lauscher[art] || []).push(fn); },
    getElementById(id) {
      gefragt.push(id);
      if (!mitListe && NUR_IM_PLANNER.has(id)) return null;
      return (elemente[id] = elemente[id] || element(id));
    },
    // The drag-and-drop tests put a page of their own here (globalThis.__seite).
    querySelectorAll: sel => (globalThis.__seite ? globalThis.__seite.alle(sel) : []),
    querySelector: sel => (globalThis.__seite ? globalThis.__seite.eins(sel) : null),
    cookie: '',
  };
  const window = {
    location: { href: '' }, alert(t) { window.gemeldet = t; },
    // The drag-and-drop tests answer the Buffer question through window.antwort.
    confirm(t) { (window.gefragt = window.gefragt || []).push(t); return window.antwort !== false; },
  };
  const location = { reload() { window.location.href = 'RELOAD'; } };
  const fetch = (url, opt) => {
    const koerper = opt && opt.body ? JSON.parse(opt.body) : null;
    if (koerper) gesendet.push(koerper);
    const antwort = typeof fetchErgebnis === 'function' ? fetchErgebnis(koerper) : fetchErgebnis;
    return Promise.resolve({ json: () => Promise.resolve(antwort || { termine: [] }) });
  };
  new Function('document', 'window', 'fetch', 'location', quelle)(document, window, fetch, location);
  gefragt.lauscher = lauscher;
  gefragt.gesendet = gesendet;
  gefragt.window = window;
  gefragt.elemente = elemente;
  return gefragt;
}

/* A stand-in for an element the user touched. */
function ziel(klasse, dataset, value) {
  return {
    classList: { contains: k => k === klasse },
    dataset, value,
    closest: sel => (sel === '.' + klasse ? ziel(klasse, dataset, value) : null),
  };
}
function ausloesen(lauf, art, target) {
  for (const fn of lauf.lauscher[art] || []) fn({ target });
}
const warten = () => new Promise(r => setTimeout(r, 0));

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
    addEventListener() {},
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

console.log('\n=== Moving a post from the calendar ===');
// Wired on the document, so the same two handlers must serve both calendars.
async function pruefeAsync(name, fn) {
  try { const e = await fn(); gut++; console.log('  ok   ' + name + (e ? '  (' + e + ')' : '')); }
  catch (fehler) { schlecht++; console.log('  FAIL ' + name + ': ' + fehler.message); }
}
for (const mitListe of [true, false]) {
  const welcher = mitListe ? 'planner calendar' : 'OJ calendar';
  await pruefeAsync('a new date in a row sends set_post_date (' + welcher + ')', async () => {
    const lauf = laufen(mitListe, { ok: true });
    ausloesen(lauf, 'change', ziel('kal-verschieben', { id: '119' }, '2026-09-29'));
    await warten(); await warten();
    const s = lauf.gesendet.find(d => d.action === 'set_post_date');
    if (!s) throw new Error('nothing was sent');
    if (s.id !== 119 || s.datum !== '2026-09-29') throw new Error(JSON.stringify(s));
    const soll = '/planner/kalender/2026/?m=9';
    if (lauf.window.location.href !== soll) throw new Error('went to ' + lauf.window.location.href);
    return 'then opens ' + soll;
  });
}
await pruefeAsync('a suggestion click places the post on its day', async () => {
  const lauf = laufen(true, { ok: true });
  ausloesen(lauf, 'click', ziel('kal-vorschlag', { id: '119', datum: '2027-01-04' }));
  await warten(); await warten();
  const s = lauf.gesendet.find(d => d.action === 'set_post_date');
  if (!s || s.id !== 119 || s.datum !== '2027-01-04') throw new Error(JSON.stringify(s));
  // Into another year: the page must follow it there, not stay in 2026.
  if (lauf.window.location.href !== '/planner/kalender/2027/?m=1') throw new Error(lauf.window.location.href);
  return 'follows it into 2027';
});
await pruefeAsync('a cleared date field sends nothing', async () => {
  const lauf = laufen(true, { ok: true });
  ausloesen(lauf, 'change', ziel('kal-verschieben', { id: '119' }, ''));
  await warten();
  if (lauf.gesendet.some(d => d.action === 'set_post_date')) throw new Error('sent an empty date');
});
await pruefeAsync('the list of recurring dates is not mistaken for a post', async () => {
  const lauf = laufen(true, { ok: true });
  ausloesen(lauf, 'change', ziel('verschieben', { id: '7' }, '2026-10-01'));
  await warten();
  if (lauf.gesendet.some(d => d.action === 'set_post_date')) throw new Error('moved post #7 instead of the date');
});
await pruefeAsync('a refusal from the server reloads instead of jumping', async () => {
  const lauf = laufen(true, { error: 'This post has gone out' });
  ausloesen(lauf, 'change', ziel('kal-verschieben', { id: '53' }, '2026-09-24'));
  await warten(); await warten();
  if (lauf.window.location.href !== 'RELOAD') throw new Error(lauf.window.location.href);
});

console.log('\n=== The x next to a world day: out of this year only ===');
// The note after the reload comes from sessionStorage. Node has none, so a
// stand-in is put where the browser keeps it, and taken away again after.
function ablage(inhalt) {
  const speicher = Object.assign({}, inhalt || {});
  return {
    speicher,
    getItem: k => (k in speicher ? speicher[k] : null),
    setItem: (k, v) => { speicher[k] = String(v); },
    removeItem: k => { delete speicher[k]; },
  };
}
await pruefeAsync('a click on the x hides the date in this year and reloads', async () => {
  globalThis.sessionStorage = ablage();
  try {
    const lauf = laufen(true, { ok: true });
    ausloesen(lauf, 'click', ziel('kal-weg', { id: '12', name: 'International Coffee Day' }));
    await warten(); await warten();
    const s = lauf.gesendet.find(d => d.action === 'hide_year');
    if (!s || s.id !== 12 || s.jahr !== 2026) throw new Error(JSON.stringify(lauf.gesendet));
    if (lauf.gesendet.some(d => d.action === 'delete' || d.action === 'set_active'))
      throw new Error('it touched the list itself');
    if (lauf.window.location.href !== 'RELOAD') throw new Error(lauf.window.location.href);
    const notiz = JSON.parse(globalThis.sessionStorage.getItem('kalWeg'));
    if (notiz.id !== 12 || notiz.jahr !== 2026) throw new Error(JSON.stringify(notiz));
    return 'hide_year, then a note for after the reload';
  } finally { delete globalThis.sessionStorage; }
});
await pruefeAsync('a refusal leaves the page as it is', async () => {
  globalThis.sessionStorage = ablage();
  try {
    const lauf = laufen(true, { error: 'Which date, and which year?' });
    ausloesen(lauf, 'click', ziel('kal-weg', { id: '12', name: 'X' }));
    await warten(); await warten();
    if (lauf.window.location.href === 'RELOAD') throw new Error('reloaded as if it had worked');
    if (globalThis.sessionStorage.getItem('kalWeg')) throw new Error('left a note for nothing');
  } finally { delete globalThis.sessionStorage; }
});
await pruefeAsync('after the reload: the note, escaped, with an Undo that shows it again', async () => {
  globalThis.sessionStorage = ablage({ kalWeg: JSON.stringify({ id: 12, name: 'Tea & "<b>Coffee</b>"', jahr: 2026 }) });
  try {
    const lauf = laufen(true, { ok: true });
    const toast = lauf.elemente['kal-toast'];
    if (!toast || toast.hidden) throw new Error('no note shown');
    if (toast.innerHTML.includes('<b>')) throw new Error('name not escaped: ' + toast.innerHTML);
    if (!toast.innerHTML.includes('Tea &amp; &quot;&lt;b&gt;Coffee')) throw new Error(toast.innerHTML);
    if (globalThis.sessionStorage.getItem('kalWeg')) throw new Error('the note would show again on the next load');
    toast.knopf.onclick();
    await warten(); await warten();
    const s = lauf.gesendet.find(d => d.action === 'show_year');
    if (!s || s.id !== 12 || s.jahr !== 2026) throw new Error(JSON.stringify(lauf.gesendet));
    return 'Undo sends show_year';
  } finally { delete globalThis.sessionStorage; }
});
await pruefeAsync('a note from another year is not shown here', async () => {
  globalThis.sessionStorage = ablage({ kalWeg: JSON.stringify({ id: 12, name: 'X', jahr: 2027 }) });
  try {
    const lauf = laufen(true, { ok: true });
    if (lauf.elemente['kal-toast'].innerHTML) throw new Error('shown: ' + lauf.elemente['kal-toast'].innerHTML);
  } finally { delete globalThis.sessionStorage; }
});
await pruefeAsync('no sessionStorage at all (private window): the page still runs', async () => {
  const lauf = laufen(false, { ok: true });
  return lauf.length + ' elements asked for';
});

console.log('\n=== Drag and drop: drop a post on a day, the one there goes to Review ===');
// A small stand-in page: rows that know their day, posts that know their id.
function post(id, extra) {
  const el = { dataset: Object.assign({ post: String(id), titel: 'Post ' + id }, extra || {}),
               klassen: new Set() };
  el.classList = { add: k => el.klassen.add(k), remove: (...k) => k.forEach(x => el.klassen.delete(x)) };
  return el;
}
function zeile(tag, posts) {
  const z = { dataset: { tag }, posts, klassen: new Set() };
  z.classList = { add: k => z.klassen.add(k), remove: (...k) => k.forEach(x => z.klassen.delete(x)) };
  z.querySelectorAll = sel => (sel === '[data-post]' ? posts : []);
  posts.forEach(p => { p.zeile = z; p.closest = sel => (sel === '.kal-zeile' ? z : null); });
  return z;
}
function nachbau(zeilen, liste) {
  const allePosts = zeilen.flatMap(z => z.posts).concat(liste || []);
  return {
    zeilen, allePosts,
    alle(sel) {
      const tag = /data-tag="([^"]+)"/.exec(sel);
      if (tag) return zeilen.filter(z => z.dataset.tag === tag[1]);
      if (sel.includes('kal-ziel-ok')) return [...zeilen, ...allePosts].filter(x => x.klassen.size);
      return [];
    },
    eins(sel) {
      const id = /data-post="([^"]+)"/.exec(sel);
      return id ? allePosts.find(p => p.dataset.post === id[1]) || null : null;
    },
  };
}
// Event targets: something inside a post (drag start) or inside a row / the drop bar.
const griff = p => ({ closest: sel => (sel === '[data-post][draggable="true"]' ? p : null) });
const aufZeile = z => ({ closest: sel => (sel === '.kal-zeile[data-tag]' ? z : null) });
const aufAblage = () => ({ closest: sel => (sel === '#kal-ablage' ? {} : null) });
function feuern(lauf, art, target) {
  let verhindert = false;
  for (const fn of lauf.lauscher[art] || []) fn({ target, preventDefault() { verhindert = true; } });
  return verhindert;
}
async function ziehen(aufbau, antwort, schritte) {
  globalThis.__seite = aufbau;
  globalThis.sessionStorage = ablage();
  try {
    const lauf = laufen(true, antwort);
    await schritte(lauf);
    await warten(); await warten(); await warten();
    return lauf;
  } finally { delete globalThis.__seite; }
}

await pruefeAsync('#126 onto 16.10., where #128 is: #128 has to give way', async () => {
  const p126 = post(126), p128 = post(128);
  const s = nachbau([zeile('2026-10-09', [p126]), zeile('2026-10-16', [p128])]);
  const lauf = await ziehen(s, { ok: true, vorher: [{ id: 126 }, { id: 128 }], buffer_geloescht: [] }, async l => {
    feuern(l, 'dragstart', griff(p126));
    if (!feuern(l, 'dragover', aufZeile(s.zeilen[1]))) throw new Error('the day did not accept the drop');
    if (!p128.klassen.has('kal-weicht')) throw new Error('#128 is not marked as giving way');
    feuern(l, 'drop', aufZeile(s.zeilen[1]));
  });
  try {
    const d = lauf.gesendet.find(x => x.action === 'drop_post');
    if (!d || d.id !== 126 || d.datum !== '2026-10-16' || JSON.stringify(d.weichen) !== '[128]' || d.buffer_ok)
      throw new Error(JSON.stringify(lauf.gesendet));
    if (lauf.window.gefragt) throw new Error('asked about Buffer although nothing is there');
    if (lauf.window.location.href !== 'RELOAD') throw new Error(lauf.window.location.href);
    const notiz = JSON.parse(globalThis.sessionStorage.getItem('kalDrop'));
    if (!/#128 to Review/.test(notiz.text) || notiz.vorher.length !== 2) throw new Error(JSON.stringify(notiz));
    return 'drop_post, weichen [128], a note for Undo';
  } finally { delete globalThis.sessionStorage; }
});
await pruefeAsync('onto the drop bar: out of the calendar, no day', async () => {
  const p126 = post(126);
  const s = nachbau([zeile('2026-10-09', [p126])]);
  const lauf = await ziehen(s, { ok: true, vorher: [] }, async l => {
    feuern(l, 'dragstart', griff(p126));
    feuern(l, 'drop', aufAblage());
  });
  delete globalThis.sessionStorage;
  const d = lauf.gesendet.find(x => x.action === 'drop_post');
  if (!d || d.datum !== '' || d.weichen.length) throw new Error(JSON.stringify(lauf.gesendet));
});
await pruefeAsync('a post Buffer holds on the day: asked first, and No sends nothing', async () => {
  const p126 = post(126), p150 = post(150, { buffer: '10.10.2026 10:00' });
  const s = nachbau([zeile('2026-10-09', [p126]), zeile('2026-10-10', [p150])]);
  const lauf = await ziehen(s, { ok: true }, async l => {
    l.window.antwort = false;
    feuern(l, 'dragstart', griff(p126));
    feuern(l, 'drop', aufZeile(s.zeilen[1]));
  });
  delete globalThis.sessionStorage;
  if (!lauf.window.gefragt || !/#150/.test(lauf.window.gefragt[0]) || !/Undo brings back the dates, not the Buffer slot/.test(lauf.window.gefragt[0]))
    throw new Error('no proper question: ' + JSON.stringify(lauf.window.gefragt));
  if (lauf.gesendet.some(x => x.action === 'drop_post')) throw new Error('sent although she said No');
});
await pruefeAsync('and Yes sends it with buffer_ok', async () => {
  const p126 = post(126), p150 = post(150, { buffer: '10.10.2026 10:00' });
  const s = nachbau([zeile('2026-10-09', [p126]), zeile('2026-10-10', [p150])]);
  const lauf = await ziehen(s, { ok: true, vorher: [] }, async l => {
    feuern(l, 'dragstart', griff(p126));
    feuern(l, 'drop', aufZeile(s.zeilen[1]));
  });
  delete globalThis.sessionStorage;
  const d = lauf.gesendet.find(x => x.action === 'drop_post');
  if (!d || d.buffer_ok !== true) throw new Error(JSON.stringify(lauf.gesendet));
});
await pruefeAsync('dragging a Buffer post itself asks too, and says it goes to Ready', async () => {
  const p150 = post(150, { buffer: '10.10.2026 10:00' });
  const s = nachbau([zeile('2026-10-10', [p150]), zeile('2026-10-15', [])]);
  const lauf = await ziehen(s, { ok: true, vorher: [] }, async l => {
    feuern(l, 'dragstart', griff(p150));
    feuern(l, 'drop', aufZeile(s.zeilen[1]));
  });
  delete globalThis.sessionStorage;
  if (!lauf.window.gefragt || !/#150 goes to Ready on 15\.10\./.test(lauf.window.gefragt[0]))
    throw new Error(JSON.stringify(lauf.window.gefragt));
});
await pruefeAsync('a published post on the day: refused, nothing sent, nothing asked', async () => {
  const p126 = post(126), p77 = post(77, { raus: '1' });
  const s = nachbau([zeile('2026-10-09', [p126]), zeile('2026-10-14', [p77])]);
  let angenommen;
  const lauf = await ziehen(s, { ok: true }, async l => {
    feuern(l, 'dragstart', griff(p126));
    angenommen = feuern(l, 'dragover', aufZeile(s.zeilen[1]));
    feuern(l, 'drop', aufZeile(s.zeilen[1]));
  });
  delete globalThis.sessionStorage;
  if (angenommen) throw new Error('the day accepted the drop');
  if (!s.zeilen[1].klassen.has('kal-ziel-nein')) throw new Error('the day is not shown as refused');
  if (lauf.gesendet.length || lauf.window.gefragt) throw new Error(JSON.stringify(lauf.gesendet));
});
await pruefeAsync('back onto its own day does nothing', async () => {
  const p126 = post(126);
  const s = nachbau([zeile('2026-10-09', [p126])]);
  const lauf = await ziehen(s, { ok: true }, async l => {
    feuern(l, 'dragstart', griff(p126));
    feuern(l, 'drop', aufZeile(s.zeilen[0]));
  });
  delete globalThis.sessionStorage;
  if (lauf.gesendet.length) throw new Error(JSON.stringify(lauf.gesendet));
});
await pruefeAsync('the server asks about Buffer the page did not know of: asked, then sent again', async () => {
  const p126 = post(126), p128 = post(128);
  const s = nachbau([zeile('2026-10-09', [p126]), zeile('2026-10-16', [p128])]);
  const lauf = await ziehen(s, k => (k && k.action === 'drop_post' && !k.buffer_ok
                                     ? { frage: 'buffer', bei_buffer: [128] } : { ok: true, vorher: [] }), async l => {
    feuern(l, 'dragstart', griff(p126));
    feuern(l, 'drop', aufZeile(s.zeilen[1]));
  });
  delete globalThis.sessionStorage;
  const drops = lauf.gesendet.filter(x => x.action === 'drop_post');
  if (drops.length !== 2 || drops[0].buffer_ok || !drops[1].buffer_ok) throw new Error(JSON.stringify(drops));
  if (!lauf.window.gefragt || !/#128/.test(lauf.window.gefragt[0])) throw new Error('not asked');
});
await pruefeAsync('an error from the server: said, reloaded, no note', async () => {
  const p126 = post(126), p128 = post(128);
  const s = nachbau([zeile('2026-10-09', [p126]), zeile('2026-10-16', [p128])]);
  globalThis.__seite = s;
  const speicher = ablage();
  globalThis.sessionStorage = speicher;
  try {
    const lauf = laufen(true, { error: '#128 has gone out' });
    feuern(lauf, 'dragstart', griff(p126));
    feuern(lauf, 'drop', aufZeile(s.zeilen[1]));
    await warten(); await warten(); await warten();
    if (lauf.window.gemeldet !== '#128 has gone out') throw new Error('not said: ' + lauf.window.gemeldet);
    if (lauf.window.location.href !== 'RELOAD') throw new Error(lauf.window.location.href);
    if (speicher.getItem('kalDrop')) throw new Error('left a note for something that did not happen');
  } finally { delete globalThis.__seite; delete globalThis.sessionStorage; }
});
await pruefeAsync('after the reload: the note, escaped, and Undo sends back what the server gave', async () => {
  const vorher = [{ id: 126, planned_date: '2026-10-09', status: 'Review', in_pipeline: 1 },
                  { id: 128, planned_date: '2026-10-16', status: 'Draft', in_pipeline: 0 }];
  globalThis.sessionStorage = ablage({ kalDrop: JSON.stringify({ text: '#126 now on 16.10. <b>x</b>', vorher, jahr: 2026 }) });
  try {
    const lauf = laufen(true, { ok: true });
    const toast = lauf.elemente['kal-toast'];
    if (toast.hidden || toast.innerHTML.includes('<b>')) throw new Error(toast.innerHTML);
    if (globalThis.sessionStorage.getItem('kalDrop')) throw new Error('the note would show twice');
    toast.knopf.onclick();
    await warten(); await warten();
    const u = lauf.gesendet.find(x => x.action === 'undo_drop');
    if (!u || JSON.stringify(u.vorher) !== JSON.stringify(vorher)) throw new Error(JSON.stringify(lauf.gesendet));
    return 'undo_drop with both posts';
  } finally { delete globalThis.sessionStorage; }
});

console.log('\n' + gut + ' ok, ' + schlecht + ' failed');
process.exit(schlecht ? 1 : 0);
