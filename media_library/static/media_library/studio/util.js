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
    // Close via the button, a click on the backdrop OR Escape. Without the
    // Escape route a dialog that had gone invisible for whatever reason stayed
    // open for good - and the save waiting behind it hung forever.
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

// Loads an image with crossOrigin='anonymous' through the proxy, so the canvas
// is never tainted. Returns Promise<HTMLImageElement>.
export function loadImage(url) {
  return new Promise((resolve, reject) => {
    if (!url) { reject(new Error('No image URL provided')); return; }
    const img = new Image();
    const ziel = proxyUrl(url);
    if (!ziel) { reject(new Error('Image URL could not be resolved')); return; }
    // No crossOrigin for data:/blob: - some browsers abort the load altogether
    // instead of simply showing the image.
    if (!/^(data:|blob:)/i.test(String(ziel))) img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    // Aussagekräftige Meldung statt eines nackten Event-Objekts – vorher stand
    // im Fehlertext nur „[object Event]".
    img.onerror = () => reject(new Error('Image could not be loaded: ' + String(ziel).slice(0, 120)));
    img.src = ziel;
  });
}

// Removes an element from the document safely.
// A bare el.remove() throws while the browser is working through a blur event
// of that same element ("The node to be removed is no longer a child of this
// node"). It happened when a second inline editor was opened while the first
// was still open.
export function wegDamit(el) {
  if (!el) return;
  try { el.remove(); }
  catch (e) { try { el.parentNode && el.parentNode.removeChild(el); } catch (_) { /* schon weg */ } }
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// Reads a server response as JSON - naming the cause instead of "error".
// ONE place for the whole app: io.js and library.js share this function, so an
// expired session is called the same everywhere, instead of ending up as
// "could not load" in one module and something else in another.
export async function readJson(res) {
  if (!res.ok) {
    // These three describe the connection, not the operation - our own wording
    // is more useful here than anything the server writes about them.
    // dazu schreibt.
    if (res.status === 413) throw new Error('File too large for the server (413)');
    if (res.status === 403) throw new Error('Not signed in, or the session has expired (403)');
    if (res.status === 401) throw new Error('Not signed in (401)');
    // Otherwise: when the server itself says what went wrong, that beats
    // "Server error 502". A deletion that fails on a locked file should be
    // allowed to say so.
    let grund = '';
    try {
      const d = JSON.parse(await res.text());
      if (d && typeof d.error === 'string') grund = d.error.trim();
    } catch { /* kein JSON - dann eben die Standardmeldung */ }
    throw new Error(grund || `Server error ${res.status}`);
  }
  const txt = await res.text();
  try { return JSON.parse(txt); }
  catch {
    // Not JSON: nearly always the sign-in page after the session expired.
    if (/<\s*html/i.test(txt)) throw new Error('Session expired – please sign in again');
    throw new Error('Unexpected server response');
  }
}
