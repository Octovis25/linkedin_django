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
    (buttons || [{ label: 'OK', value: true }]).forEach(b => {
      const el = document.createElement('button');
      el.textContent = b.label;
      el.onclick = () => { document.body.removeChild(bg); resolve(b.value); };
      btnWrap.appendChild(el);
    });
    box.appendChild(btnWrap);
    bg.appendChild(box);
    bg.addEventListener('click', e => { if (e.target === bg) { document.body.removeChild(bg); resolve(null); } });
    document.body.appendChild(bg);
  });
}

// Lädt ein Bild crossOrigin='anonymous' über den Proxy → nie getaintet.
// Gibt Promise<HTMLImageElement> zurück.
export function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = e => reject(e);
    img.src = proxyUrl(url);
  });
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
