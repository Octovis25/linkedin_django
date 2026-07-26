// util.js – kleine Helfer: Toast, Modal, Bild-Laden (immer crossOrigin-sauber).
import { proxyUrl } from './config.js';

export function toast(msg, kind = '', ms = 2600) {
  let t = document.querySelector('.studio-toast');
  if (!t) { t = document.createElement('div'); t.className = 'studio-toast'; document.body.appendChild(t); }
  t.textContent = msg;
  t.className = 'studio-toast ' + kind;
  requestAnimationFrame(() => t.classList.add('show'));
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), ms);
}

export function status(msg, color = '#008591') {
  const el = document.getElementById('status-msg');
  if (el) { el.textContent = msg; el.style.color = color; }
}

// Bestätigungs-/Auswahl-Modal. buttons: [{label, kind, value}]. Promise<value|null>.
export function modal(title, text, buttons) {
  return new Promise(resolve => {
    const bg = document.createElement('div');
    bg.className = 'studio-modal-bg';
    const box = document.createElement('div');
    box.className = 'studio-modal';
    box.innerHTML = `<h4>${title}</h4>${text ? `<div style="font-size:.82rem;color:#555;margin-bottom:14px">${text}</div>` : ''}`;
    const btnWrap = document.createElement('div');
    btnWrap.className = 'modal-btns';
    // Schließen über Button, Hintergrund-Klick ODER Escape. Ohne Escape-Ausweg
    // blieb ein Dialog, der aus irgendeinem Grund unsichtbar war, für immer
    // offen – und der darauf wartende Speichervorgang hing endlos.
    const zu = (wert) => {
      document.removeEventListener('keydown', esc);
      if (bg.parentNode) bg.parentNode.removeChild(bg);
      resolve(wert);
    };
    const esc = e => { if (e.key === 'Escape') { e.preventDefault(); zu(null); } };
    (buttons || [{ label: 'OK', value: true }]).forEach(b => {
      const el = document.createElement('button');
      el.textContent = b.label;
      el.onclick = () => zu(b.value);
      btnWrap.appendChild(el);
    });
    box.appendChild(btnWrap);
    bg.appendChild(box);
    bg.addEventListener('click', e => { if (e.target === bg) zu(null); });
    document.addEventListener('keydown', esc);
    document.body.appendChild(bg);
  });
}

// Lädt ein Bild crossOrigin='anonymous' über den Proxy → nie getaintet.
// Gibt Promise<HTMLImageElement> zurück.
export function loadImage(url) {
  return new Promise((resolve, reject) => {
    if (!url) { reject(new Error('Keine Bild-Adresse angegeben')); return; }
    const img = new Image();
    const ziel = proxyUrl(url);
    if (!ziel) { reject(new Error('Bild-Adresse konnte nicht aufgelöst werden')); return; }
    // Bei data:/blob: kein crossOrigin setzen – manche Browser brechen das Laden
    // dann komplett ab, statt das Bild einfach anzuzeigen.
    if (!/^(data:|blob:)/i.test(String(ziel))) img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    // Aussagekräftige Meldung statt eines nackten Event-Objekts – vorher stand
    // im Fehlertext nur „[object Event]".
    img.onerror = () => reject(new Error('Bild konnte nicht geladen werden: ' + String(ziel).slice(0, 120)));
    img.src = ziel;
  });
}

// Entfernt ein Element sicher aus dem Dokument.
// Ein rohes el.remove() wirft, wenn der Browser gerade ein blur-Ereignis
// desselben Elements abarbeitet („The node to be removed is no longer a child
// of this node") – das passierte beim Öffnen eines zweiten Inline-Editors,
// während der erste noch offen war.
export function wegDamit(el) {
  if (!el) return;
  try { el.remove(); }
  catch (e) { try { el.parentNode && el.parentNode.removeChild(el); } catch (_) { /* schon weg */ } }
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
