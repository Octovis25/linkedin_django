// Test fuer den Ordnerdurchlauf der Mediathek (library.js).
//
// Warum getrennt vom grossen Studio-Test: hier faehrt kein Browser hoch. Es geht
// um zwei Zahlen, die man im Browser schlecht sieht und die im September 2026 das
// Studio langsam gemacht haben -
//
//   * wie viele Ordnerabrufe gleichzeitig laufen (zu viele ersticken den Server,
//     zu wenige machen die Wartezeit zur Summe aller Abrufe),
//   * in welcher Reihenfolge die Bilder herauskommen (die Umstellung auf
//     gleichzeitige Abrufe darf das Raster nicht durcheinanderwuerfeln).
//
// Der Test liest die echten Zeilen aus library.js heraus, statt sie abzuschreiben.
// Eine Abschrift haette den Fehler mitgetestet und nicht den Code.
//
//   node _tests/library_ordner_test.mjs
//
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const HIER = path.dirname(url.fileURLToPath(import.meta.url));
const KANDIDATEN = [
  path.join(HIER, '..', 'media_library', 'static', 'media_library', 'studio', 'library.js'),
  path.join(HIER, 'app', 'library.js'),
  path.join(HIER, 'library.js'),
];

const datei = KANDIDATEN.find(p => fs.existsSync(p));
if (!datei) {
  console.error('library.js nicht gefunden. Gesucht in:\n  ' + KANDIDATEN.join('\n  '));
  process.exit(2);
}
const quelle = fs.readFileSync(datei, 'utf8');

function schnitt(von, bis) {
  const a = quelle.indexOf(von);
  const b = quelle.indexOf(bis, a);
  if (a < 0 || b < 0) {
    console.error('Abschnitt nicht gefunden: "' + von.slice(0, 48) + '"');
    console.error('library.js wurde umgebaut - diesen Test nachziehen.');
    process.exit(2);
  }
  return quelle.slice(a, b);
}

// Drosselung und gatherImages im Original. fetchFolder wird nachgebaut, weil das
// Original ueber das Netz geht; der Rahmen darum ist Zeile fuer Zeile derselbe.
const drosselung = schnitt('const GRENZE =', 'let _editor = null;');
const sammeln = schnitt('async function gatherImages', '// Zeigt die Bilder');

const modul = `
export let anfragen = 0, hoechstwert = 0;
let gleichzeitig = 0;
const _cache = new Map(), _laufend = new Map();
let BAUM = {};
export function setzeBaum(b) {
  BAUM = b; _cache.clear(); _laufend.clear(); anfragen = 0; hoechstwert = 0;
}

${drosselung}

async function fetchFolder(pfad) {
  if (_cache.has(pfad)) return _cache.get(pfad);
  if (_laufend.has(pfad)) return _laufend.get(pfad);
  const lauf = (async () => {
    let data = { subfolders: [], items: [] };
    await _platz();
    gleichzeitig++; hoechstwert = Math.max(hoechstwert, gleichzeitig); anfragen++;
    try {
      await new Promise(r => setTimeout(r, 20));   // ein Ordnerabruf ueber Nextcloud
      data = BAUM[pfad] || { subfolders: [], items: [] };
    } finally { gleichzeitig--; _frei(); }
    _cache.set(pfad, data);
    _laufend.delete(pfad);
    return data;
  })();
  _laufend.set(pfad, lauf);
  return lauf;
}

${sammeln}
export { gatherImages };
`;

const tmp = path.join(HIER, '.library_ordner_test.tmp.mjs');
fs.writeFileSync(tmp, modul);
let T;
try {
  T = await import(url.pathToFileURL(tmp).href);
} finally {
  try { fs.unlinkSync(tmp); } catch (e) { /* egal */ }
}

let ok = 0, schlecht = 0;
const pruefe = (name, bedingung, zusatz = '') => {
  if (bedingung) { ok++; console.log('  ok   ' + name); }
  else { schlecht++; console.log('  FEHL ' + name + (zusatz ? '  -> ' + zusatz : '')); }
};

const bild = p => ({ nc_path: p, url: '/x/' + p, name: p });

// ── Ein Baum in der Groessenordnung der echten Mediathek ────────────────────
// 1 Wurzel + 12 Ordner + 36 Unterordner = 49 Abrufe a 20 ms.
// Nacheinander waeren das 980 ms, und genau so lange hat es vorher gedauert.
const baum = {};
const wurzel = { subfolders: [], items: [bild('root/a')] };
for (let i = 0; i < 12; i++) {
  const k = 'k' + i;
  wurzel.subfolders.push(k);
  const kind = { subfolders: [], items: [bild('root/' + k + '/i')] };
  for (let j = 0; j < 3; j++) {
    kind.subfolders.push('e' + j);
    baum['root/' + k + '/e' + j] = { subfolders: [], items: [bild('root/' + k + '/e' + j + '/i')] };
  }
  baum['root/' + k] = kind;
}
baum['root'] = wurzel;

console.log('\n=== Ordnerdurchlauf: Drosselung, Reihenfolge, Dauer ===');
T.setzeBaum(baum);
const t0 = Date.now();
const erg = await T.gatherImages('root', new Set());
const dauer = Date.now() - t0;

pruefe('alle 49 Bilder gefunden', erg.length === 49, 'waren ' + erg.length);
pruefe('49 Ordner abgerufen', T.anfragen === 49, 'waren ' + T.anfragen);
pruefe('nie mehr als 6 Abrufe gleichzeitig', T.hoechstwert <= 6, 'Spitze war ' + T.hoechstwert);
pruefe('die 6 werden auch ausgenutzt', T.hoechstwert === 6, 'Spitze war ' + T.hoechstwert);

const erwartet = ['root/a'];
for (let i = 0; i < 12; i++) {
  erwartet.push('root/k' + i + '/i');
  for (let j = 0; j < 3; j++) erwartet.push('root/k' + i + '/e' + j + '/i');
}
const ist = erg.map(x => x.nc_path);
pruefe('Reihenfolge wie bei der alten Tiefensuche',
  JSON.stringify(ist) === JSON.stringify(erwartet),
  'erste Abweichung an Stelle ' + ist.findIndex((v, k) => v !== erwartet[k]));

pruefe('deutlich schneller als nacheinander', dauer < 600,
  dauer + ' ms, nacheinander waeren es rund 980');
console.log('  (Dauer ' + dauer + ' ms)');

// ── Derselbe Ordner in zwei Aesten: nur ein Abruf ───────────────────────────
console.log('\n=== Gleichzeitig derselbe Ordner ===');
T.setzeBaum(baum);
const [a, b] = await Promise.all([
  T.gatherImages('root/k0', new Set()),
  T.gatherImages('root/k0', new Set()),
]);
pruefe('beide Aufrufe liefern dasselbe', JSON.stringify(a) === JSON.stringify(b));
pruefe('4 Abrufe statt 8 - der Cache greift auch bei laufenden Anfragen',
  T.anfragen === 4, 'waren ' + T.anfragen);

// ── Dasselbe Bild in zwei Ordnern ───────────────────────────────────────────
console.log('\n=== Doppelte Bilder ===');
T.setzeBaum({
  d: { subfolders: ['u1', 'u2'], items: [] },
  'd/u1': { subfolders: [], items: [bild('gleich')] },
  'd/u2': { subfolders: [], items: [bild('gleich'), bild('anders')] },
});
const d = await T.gatherImages('d', new Set());
pruefe('zaehlt einmal, nicht zweimal', d.length === 2, 'waren ' + d.length);

// ── Tiefenbegrenzung ────────────────────────────────────────────────────────
console.log('\n=== Tiefenbegrenzung ===');
const tief = {};
let pfad = 't';
for (let i = 0; i < 12; i++) { tief[pfad] = { subfolders: ['s'], items: [bild('n' + i)] }; pfad += '/s'; }
T.setzeBaum(tief);
const t = await T.gatherImages('t', new Set());
pruefe('bricht nach 7 Ebenen ab (depth > 6)', t.length === 7, 'waren ' + t.length);

console.log('\n' + ok + ' ok, ' + schlecht + ' fehlgeschlagen');
process.exit(schlecht ? 1 : 0);
