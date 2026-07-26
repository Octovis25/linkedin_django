// namen.js – Vergabe eindeutiger, stabiler Namen für Ausgaben.
//
// Der Name ist die Identität eines Entwurfs: Er steckt im Dateinamen und ist
// das, worüber Bild, GIF und Video desselben Designs zusammenfinden. Deshalb
// muss er ohne Leerzeichen auskommen und darf nie doppelt vergeben werden.
//
// Ablauf: Beim ersten Speichern fragt das Studio nach dem Namen und schlägt
// dabei einen aus den Textinhalten des Entwurfs vor. Umbenennen ist jederzeit
// möglich – die Eindeutigkeit wird dabei erneut geprüft.
import { URLS } from './config.js';

// Wörter, die in einer Abkürzung nichts verloren haben.
const STOPP = new Set([
  'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einer', 'eines', 'einem', 'einen',
  'und', 'oder', 'aber', 'auch', 'noch', 'nur', 'schon', 'sehr', 'mehr', 'viel', 'viele',
  'für', 'fuer', 'mit', 'ohne', 'von', 'vom', 'zum', 'zur', 'bei', 'aus', 'auf', 'über',
  'unter', 'nach', 'vor', 'ist', 'sind', 'war', 'wird', 'werden', 'haben', 'hat', 'kann',
  'ihre', 'ihr', 'ihren', 'ihrem', 'unser', 'unsere', 'sie', 'wir', 'uns', 'als', 'wie',
  'the', 'and', 'for', 'with', 'your', 'you', 'our',
]);

// Umlaute und Sonderzeichen in etwas verwandeln, das in einem Dateinamen
// nichts kaputt macht.
export function entschaerfe(text) {
  return String(text || '')
    .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue')
    .replace(/Ä/g, 'Ae').replace(/Ö/g, 'Oe').replace(/Ü/g, 'Ue')
    .replace(/ß/g, 'ss')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')   // restliche Akzente
    .replace(/[^A-Za-z0-9_-]+/g, '_')                    // alles andere → _
    .replace(/_+/g, '_')
    .replace(/^[_-]+|[_-]+$/g, '');
}

// Ist der Name als Dateiname brauchbar? (keine Leerzeichen, nicht leer)
export function nameOk(name) {
  const n = String(name || '').trim();
  return n.length >= 2 && n.length <= 80 && /^[A-Za-z0-9_-]+$/.test(n);
}

// Baut aus den Texten des Entwurfs einen Namensvorschlag.
// „Studien für Ihre Praxis 2026" → „StudienPraxis2026"
export function vorschlagAusInhalt(editor) {
  const stuecke = [];
  try {
    for (const o of editor.realObjects()) {
      // Textfelder, Textblöcke, Checklisten, Badges – alles, was Text trägt.
      const kandidaten = [
        o.text, o.tbHead, o.tbBody,
        Array.isArray(o.clItems) ? o.clItems.join(' ') : '',
      ];
      if (o._objects) for (const k of o._objects) if (k && k.text) kandidaten.push(k.text);
      for (const t of kandidaten) if (t) stuecke.push(String(t));
    }
  } catch (e) { /* Vorschlag ist Komfort, nie kritisch */ }

  const woerter = stuecke.join(' ')
    .split(/[\s\n\r\t.,;:!?()[\]{}"'„“”–—/\\|]+/)
    .map(w => w.trim())
    .filter(w => w.length >= 3 && !STOPP.has(w.toLowerCase()))
    .filter(w => /[A-Za-zÄÖÜäöüß0-9]/.test(w));

  if (!woerter.length) return '';
  // Höchstens drei Wörter, jedes auf 12 Zeichen gekürzt, in Großschreibung
  // verbunden – ergibt kurze, lesbare Namen ohne Leerzeichen.
  const teile = woerter.slice(0, 3).map(w => {
    const s = entschaerfe(w).slice(0, 12);
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
  }).filter(Boolean);
  return teile.join('').slice(0, 48);
}

// Holt alle bereits vergebenen Namen (Bilder, GIFs, Videos) vom Server.
// Grundlage für die Eindeutigkeitsprüfung.
export async function vergebeneNamen() {
  const namen = new Set();
  try {
    const r = await fetch(URLS.apiSaved, { credentials: 'same-origin' });
    if (r.ok) {
      const d = await r.json();
      for (const gruppe of ['images', 'anim_images', 'videos']) {
        for (const it of (d[gruppe] || [])) {
          // Bereinigt ablegen: Altbestand-Titel mit Leerzeichen („Header Q3")
          // hätten sonst nie gegen einen bereinigten Kandidaten gematcht.
          if (it && it.title) {
            const n = entschaerfe(it.title).toLowerCase();
            if (n) namen.add(n);
          }
        }
      }
    }
  } catch (e) { /* offline: dann eben ohne Prüfung */ }
  // Zusätzlich die tatsächlich vorhandenen Dateien – es kann Dateien ohne
  // Datenbankeintrag geben (z.B. von Hand hochgeladen).
  const ordner = ['Studio_Work/Output/Images', 'Studio_Work/Output/GIFs', 'Studio_Work/Output/Videos'];
  await Promise.all(ordner.map(async f => {
    try {
      const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(f), { credentials: 'same-origin' });
      if (!r.ok) return;
      const d = await r.json();
      for (const it of (d.items || [])) {
        const n = String(it.name || '').replace(/\.[^.]+$/, '');
        // Nur die vom Studio selbst erzeugte Vorschaudatei ausblenden. Ein
        // enger Filter ist wichtig: Würde hier ein echter Name durchrutschen,
        // dürfte ein zweites Design denselben Namen nehmen und die Datei
        // überschreiben. `_snap`/`_obj`/`_fab` liegen im Unterordner `_data`,
        // den die Ordnerauflistung ohnehin auslässt.
        if (!n || /_preview$/i.test(n)) continue;
        const sauber = entschaerfe(n).toLowerCase();
        if (sauber) namen.add(sauber);
      }
    } catch (e) { /* egal */ }
  }));
  return namen;
}

// Macht einen Namen eindeutig, indem bei Bedarf _2, _3 … angehängt wird.
// `eigener` ist der aktuell gehaltene Name – der gilt nicht als Kollision.
export function eindeutig(name, belegt, eigener) {
  const basis = entschaerfe(name) || 'Entwurf';
  // Auch den eigenen Namen bereinigen: sonst gilt ein Altbestand-Titel mit
  // Leerzeichen („Header Q3") nicht als der eigene und die Funktion hängt dem
  // Namen unnötig ein _2 an.
  const eigenerKlein = entschaerfe(eigener).toLowerCase();
  if (!belegt.has(basis.toLowerCase()) || basis.toLowerCase() === eigenerKlein) return basis;
  for (let i = 2; i < 1000; i++) {
    const k = `${basis}_${i}`;
    if (!belegt.has(k.toLowerCase()) || k.toLowerCase() === eigenerKlein) return k;
  }
  return `${basis}_${Date.now()}`;
}

// Dialog zur Namenseingabe. Gibt den bestätigten Namen zurück oder null
// (abgebrochen). Prüft live auf Eindeutigkeit und erlaubt keine Leerzeichen.
export function frageNachNamen({ vorschlag, belegt, eigener, titel, hinweis }) {
  return new Promise(resolve => {
    const bg = document.createElement('div');
    bg.className = 'studio-modal-bg';
    const box = document.createElement('div');
    box.className = 'studio-modal';
    box.innerHTML =
      `<h4>${titel || 'Wie soll die Ausgabe heißen?'}</h4>` +
      `<div style="font-size:.82rem;color:#555;margin-bottom:10px">${hinweis ||
        'Der Name gilt für alle Formate dieses Entwurfs (Bild, GIF, Video) und steht im Dateinamen. ' +
        'Er muss eindeutig sein – Leerzeichen werden zu Unterstrichen.'}</div>` +
      `<input type="text" id="nm-feld" class="field" style="width:100%;font-size:1rem;padding:7px" ` +
      `value="${(vorschlag || '').replace(/"/g, '&quot;')}" spellcheck="false" autocomplete="off">` +
      `<div id="nm-hinweis" style="font-size:.74rem;margin:6px 0 2px;min-height:2.2em"></div>`;
    const btns = document.createElement('div');
    btns.className = 'modal-btns';
    const ok = document.createElement('button');
    ok.textContent = '✓ Übernehmen';
    ok.className = 'primary';
    const ab = document.createElement('button');
    ab.textContent = 'Abbrechen';
    btns.appendChild(ab); btns.appendChild(ok);
    box.appendChild(btns); bg.appendChild(box);
    document.body.appendChild(bg);

    const feld = box.querySelector('#nm-feld');
    const info = box.querySelector('#nm-hinweis');
    const eigenerKlein = entschaerfe(eigener).toLowerCase();   // wie in eindeutig()

    // Bewertet die Eingabe und meldet zurück, ob sie brauchbar ist.
    const pruefe = () => {
      const roh = feld.value;
      const sauber = entschaerfe(roh);
      if (!sauber || sauber.length < 2) {
        info.innerHTML = '<span style="color:#b3261e">Bitte einen Namen mit mindestens 2 Zeichen.</span>';
        ok.disabled = true; return null;
      }
      const kollidiert = belegt.has(sauber.toLowerCase()) && sauber.toLowerCase() !== eigenerKlein;
      if (kollidiert) {
        const frei = eindeutig(sauber, belegt, eigener);
        info.innerHTML = `<span style="color:#b3261e">„${sauber}" ist schon vergeben.</span> ` +
          `<button type="button" id="nm-frei" class="tbtn" style="padding:1px 7px">„${frei}" nehmen</button>`;
        const b = info.querySelector('#nm-frei');
        if (b) b.onclick = () => { feld.value = frei; pruefe(); feld.focus(); };
        ok.disabled = true; return null;
      }
      info.innerHTML = (sauber !== roh.trim())
        ? `<span style="color:#666">Wird gespeichert als <b>${sauber}</b></span>`
        : '<span style="color:#198754">Name ist frei.</span>';
      ok.disabled = false;
      return sauber;
    };

    const zu = wert => {
      document.removeEventListener('keydown', esc, true);
      if (bg.parentNode) bg.parentNode.removeChild(bg);
      resolve(wert);
    };
    const esc = e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); zu(null); }
    };
    // capture=true: der globale Escape-Handler des Studios soll nicht
    // gleichzeitig das Werkzeug abschalten.
    document.addEventListener('keydown', esc, true);

    feld.addEventListener('input', pruefe);
    feld.addEventListener('keydown', e => {
      e.stopPropagation();                       // keine Studio-Tastenkürzel im Feld
      if (e.key === 'Enter') { e.preventDefault(); const n = pruefe(); if (n) zu(n); }
    });
    ok.onclick = () => { const n = pruefe(); if (n) zu(n); };
    ab.onclick = () => zu(null);
    bg.addEventListener('click', e => { if (e.target === bg) zu(null); });

    pruefe();
    feld.focus();
    feld.select();
  });
}
