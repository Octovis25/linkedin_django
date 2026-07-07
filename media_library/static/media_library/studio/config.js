// config.js – liest die vom Django-Backend injizierte Konfiguration.
const el = document.getElementById('studio-config');
let cfg = {};
try { cfg = el ? JSON.parse(el.textContent) : {}; }
catch (e) { console.warn('studio-config parse error', e); }

export const CONFIG = cfg;
export const URLS   = cfg.urls || {};
export const POST_ID = cfg.postId || null;

// CSRF-Token aus Cookie (für POST-Requests an Django).
export function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? decodeURIComponent(m.pop()) : '';
}

// Nextcloud-/nc:// Quelle → same-origin Proxy-URL (verhindert Canvas-Tainting).
export function proxyUrl(src) {
  if (!src) return src;
  if (src.startsWith('nc://')) {
    return URLS.ncImage + '?p=' + encodeURIComponent(src.slice(5));
  }
  const ncUrl = CONFIG.ncUrl || '';
  if (ncUrl && src.startsWith(ncUrl)) {
    const m = src.match(/\/remote\.php\/dav\/files\/[^/]+\/(.+)$/);
    if (m) return URLS.ncImage + '?p=' + encodeURIComponent(decodeURIComponent(m[1]));
  }
  return src;
}
