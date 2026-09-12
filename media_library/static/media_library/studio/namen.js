// namen.js - handing out unique, stable names for outputs.
//
// The name is a design's identity: it sits in the file name and it is what
// lets the image, GIF and video of one design find each other. So it has to
// manage without spaces, and it must never be given out twice.
//
// How it goes: on the first save the Studio asks for the name and suggests one
// built from the design's own text. Renaming is possible at any time - and
// uniqueness is checked again when it happens.
import { URLS } from './config.js';

// Words that have no business being in an abbreviation.
const STOPP = new Set([
  'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einer', 'eines', 'einem', 'einen',
  'und', 'oder', 'aber', 'auch', 'noch', 'nur', 'schon', 'sehr', 'mehr', 'viel', 'viele',
  'für', 'fuer', 'mit', 'ohne', 'von', 'vom', 'zum', 'zur', 'bei', 'aus', 'auf', 'über',
  'unter', 'nach', 'vor', 'ist', 'sind', 'war', 'wird', 'werden', 'haben', 'hat', 'kann',
  'ihre', 'ihr', 'ihren', 'ihrem', 'unser', 'unsere', 'sie', 'wir', 'uns', 'als', 'wie',
  'the', 'and', 'for', 'with', 'your', 'you', 'our',
]);

// Turn accented and special characters into something that breaks nothing in a
// file name.
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

// Is the name usable as a file name? (no spaces, not empty)
export function nameOk(name) {
  const n = String(name || '').trim();
  return n.length >= 2 && n.length <= 80 && /^[A-Za-z0-9_-]+$/.test(n);
}

// Builds a suggested name from the design's own text.
// "Studies for your practice 2026" → "StudiesPractice2026"
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
  // At most three words, each cut to 12 characters, joined in title case -
  // which gives short, readable names without spaces.
  const teile = woerter.slice(0, 3).map(w => {
    const s = entschaerfe(w).slice(0, 12);
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
  }).filter(Boolean);
  return teile.join('').slice(0, 48);
}

// Fetches every name already in use (images, GIFs, videos) from the server.
// The basis for the uniqueness check.
export async function vergebeneNamen() {
  const namen = new Set();
  try {
    const r = await fetch(URLS.apiSaved, { credentials: 'same-origin' });
    if (r.ok) {
      const d = await r.json();
      for (const gruppe of ['images', 'anim_images', 'videos']) {
        for (const it of (d[gruppe] || [])) {
          // Store them cleaned up: legacy titles with spaces ("Header Q3")
          // would otherwise never match a cleaned-up candidate.
          if (it && it.title) {
            const n = entschaerfe(it.title).toLowerCase();
            if (n) namen.add(n);
          }
        }
      }
    }
  } catch (e) { /* offline: dann eben ohne Prüfung */ }
  // Plus the files that are actually there - there can be files without a
  // database entry (uploaded by hand, for instance).
  const ordner = ['Studio_Work/Output/Images', 'Studio_Work/Output/GIFs', 'Studio_Work/Output/Videos'];
  await Promise.all(ordner.map(async f => {
    try {
      const r = await fetch(URLS.ncBrowse + '?folder=' + encodeURIComponent(f), { credentials: 'same-origin' });
      if (!r.ok) return;
      const d = await r.json();
      for (const it of (d.items || [])) {
        const n = String(it.name || '').replace(/\.[^.]+$/, '');
        // Hide only the preview file the Studio makes itself. A narrow filter
        // matters here: were a real name to slip through, a second design
        // could take that same name and overwrite the file. `_snap`/`_obj`/
        // `_fab` live in the `_data` subfolder, which the folder listing
        // leaves out anyway.
        if (!n || /_preview$/i.test(n)) continue;
        const sauber = entschaerfe(n).toLowerCase();
        if (sauber) namen.add(sauber);
      }
    } catch (e) { /* egal */ }
  }));
  return namen;
}

// Makes a name unique by appending _2, _3 … when needed.
// `eigener` is the name currently held - that one does not count as a clash.
export function eindeutig(name, belegt, eigener) {
  const basis = entschaerfe(name) || 'Draft';
  // Clean up the own name too: otherwise a legacy title with spaces
  // ("Header Q3") does not count as one's own, and the function appends an
  // unnecessary _2.
  const eigenerKlein = entschaerfe(eigener).toLowerCase();
  if (!belegt.has(basis.toLowerCase()) || basis.toLowerCase() === eigenerKlein) return basis;
  for (let i = 2; i < 1000; i++) {
    const k = `${basis}_${i}`;
    if (!belegt.has(k.toLowerCase()) || k.toLowerCase() === eigenerKlein) return k;
  }
  return `${basis}_${Date.now()}`;
}

// Dialog for entering a name. Returns the confirmed name, or null when
// cancelled. Checks uniqueness as you type and allows no spaces.
export function frageNachNamen({ vorschlag, belegt, eigener, titel, hinweis }) {
  return new Promise(resolve => {
    const bg = document.createElement('div');
    bg.className = 'studio-modal-bg';
    const box = document.createElement('div');
    box.className = 'studio-modal';
    box.innerHTML =
      `<h4>${titel || 'What should the output be called?'}</h4>` +
      `<div style="font-size:.82rem;color:#555;margin-bottom:10px">${hinweis ||
        'The name applies to all formats of this draft (image, GIF, video) and appears in the file name. ' +
        'Er muss eindeutig sein – Leerzeichen werden zu Unterstrichen.'}</div>` +
      `<input type="text" id="nm-feld" class="field" style="width:100%;font-size:1rem;padding:7px" ` +
      `value="${(vorschlag || '').replace(/"/g, '&quot;')}" spellcheck="false" autocomplete="off">` +
      `<div id="nm-hinweis" style="font-size:.74rem;margin:6px 0 2px;min-height:2.2em"></div>`;
    const btns = document.createElement('div');
    btns.className = 'modal-btns';
    const ok = document.createElement('button');
    ok.textContent = '✓ Apply';
    ok.className = 'primary';
    const ab = document.createElement('button');
    ab.textContent = 'Cancel';
    btns.appendChild(ab); btns.appendChild(ok);
    box.appendChild(btns); bg.appendChild(box);
    document.body.appendChild(bg);

    const feld = box.querySelector('#nm-feld');
    const info = box.querySelector('#nm-hinweis');
    const eigenerKlein = entschaerfe(eigener).toLowerCase();   // wie in eindeutig()

    // Judges the input and reports back whether it is usable.
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
        ? `<span style="color:#666">Will be saved as <b>${sauber}</b></span>`
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
    // capture=true: the Studio's global Escape handler must not switch the
    // tool off at the same time.
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
