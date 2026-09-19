/* Where does Exit take you?

   It took you back through the referrer - and because the Studio opens in a
   tab of its own, that meant a second copy of the page the post was already
   open in. Worse, there was no way out of the post at all: the post id sits in
   the address, so every exit either kept it or threw the canvas away.

   Now Exit asks, but only when there is something to decide: with a post
   attached, "back" can mean the post or away from it. Without one it is just
   an exit and asks nothing.

   This runs the real handler out of studio.js - no browser, no Fabric. The
   handler only needs a button, a dialog and somewhere to navigate to, and all
   three are stood in for here.

       node _tests/exit_test.mjs
*/
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STUDIO_DIR = path.join(HERE, '..', 'media_library', 'static', 'media_library', 'studio');

function find(name) {
  for (const p of [path.join(STUDIO_DIR, name), path.join(HERE, name)]) {
    if (existsSync(p)) return p;
  }
  throw new Error('not found: ' + name);
}

const src = readFileSync(find('studio.js'), 'utf8');

// Cut the handler out of the file that ships. A copy here would drift.
function cutOutAction(key) {
  const marke = "  '" + key + "': ";
  const start = src.indexOf(marke);
  if (start < 0) throw new Error('action not found in studio.js: ' + key);
  let depth = 0, begonnen = false;
  for (let i = src.indexOf('{', start); i < src.length; i++) {
    if (src[i] === '{') { depth++; begonnen = true; }
    else if (src[i] === '}') {
      depth--;
      if (begonnen && depth === 0) return src.slice(start + marke.length, i + 1);
    }
  }
  throw new Error('unbalanced braces in action ' + key);
}

const QUELLE = cutOutAction('go-back');

let good = 0, bad = 0;
function check(name, ok, extra = '') {
  if (ok) { good++; console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra !== '' ? '  -> ' + extra : '')); }
}

/* Build the handler with everything around it stood in for. `antwort` is what
   the user picks in the dialog; `gefragt` records whether a dialog appeared at
   all, which is half of what this test is about. */
function baue(config, antwort) {
  const zustand = { ziel: null, gefragt: null };
  const window = { location: { set href(v) { zustand.ziel = v; }, get href() { return zustand.ziel; } } };
  const modal = async (titel, text, optionen) => {
    zustand.gefragt = optionen.map(o => o.label);
    const treffer = optionen.find(o => o.value === antwort);
    return treffer ? treffer.value : undefined;
  };
  const fn = new Function('CONFIG', 'modal', 'window',
                          'return (' + QUELLE + ');')(config, modal, window);
  return { fn, zustand };
}

const knopf = (back) => ({ getAttribute: () => back });

console.log('\n=== With a post attached, Exit asks ===');
{
  const { fn, zustand } = baue({ postId: 42 }, 'post');
  await fn(knopf('/planner/'));
  check('a dialog appears', Array.isArray(zustand.gefragt), zustand.gefragt);
  check('and it offers the post by number',
        (zustand.gefragt || []).some(l => l.includes('42')), zustand.gefragt);
  check('"to post" opens the post editor',
        zustand.ziel.startsWith('/planner/?edit=42'), zustand.ziel);
  check('and carries the list we came from',
        zustand.ziel.includes('back=' + encodeURIComponent('/planner/')), zustand.ziel);
}
{
  const { fn, zustand } = baue({ postId: 42 }, 'blank');
  await fn(knopf('/planner/'));
  check('"empty canvas" goes to a Studio without post_id - the binding is gone',
        zustand.ziel === '/library/studio/', zustand.ziel);
}
{
  const { fn, zustand } = baue({ postId: 42 }, false);
  await fn(knopf('/planner/'));
  check('"stay here" navigates nowhere', zustand.ziel === null, zustand.ziel);
}
{
  // The banner knows the post even when postId is not set separately.
  const { fn, zustand } = baue({ postData: { id: 7 } }, 'post');
  await fn(knopf('/planner/'));
  check('the post from the banner counts too',
        zustand.ziel.startsWith('/planner/?edit=7'), zustand.ziel);
}

console.log('\n=== Back to the list you came from ===');
{
  // The sub-tabs are what people work in. Coming back to a different list
  // means hunting for the post again.
  const { fn, zustand } = baue({ postId: 42 }, 'post');
  await fn(knopf('/planner/scheduled/'));
  check('Scheduled brings you back to Scheduled',
        zustand.ziel.includes('back=' + encodeURIComponent('/planner/scheduled/')), zustand.ziel);
}
{
  // The full overview is sorted newest first, so it opens on what is already
  // published - never the place to land after drawing.
  const { fn, zustand } = baue({ postId: 42 }, 'post');
  await fn(knopf('/planner/uebersicht/'));
  check('but the full overview is refused as an origin',
        zustand.ziel.includes('back=' + encodeURIComponent('/planner/')), zustand.ziel);
  check('and it really is not in there',
        !zustand.ziel.includes('uebersicht'), zustand.ziel);
}
{
  const { fn, zustand } = baue({ postId: 42 }, 'post');
  await fn(knopf('/library/studio/?post_id=9'));
  check('an origin outside the planner falls back to the planner',
        zustand.ziel.includes('back=' + encodeURIComponent('/planner/')), zustand.ziel);
}

console.log('\n=== Without a post there is nothing to decide ===');
{
  const { fn, zustand } = baue({}, 'post');
  await fn(knopf('/planner/'));
  check('no dialog', zustand.gefragt === null, zustand.gefragt);
  check('straight back where we came from',
        zustand.ziel === '/planner/', zustand.ziel);
}

console.log('\n=== A referrer is not to be trusted ===');
{
  const { fn, zustand } = baue({}, null);
  await fn(knopf('https://example.com/'));
  check('an address off this site falls back to the planner',
        zustand.ziel === '/planner/', zustand.ziel);
}
{
  const { fn, zustand } = baue({}, null);
  await fn(knopf('/library/studio/?post_id=9'));
  check('and so does one that leads back into the Studio',
        zustand.ziel === '/planner/', zustand.ziel);
}

console.log('\n=== The other side still has the door ===');
{
  // Exit now points at a deep link in the post page. If that ever goes away,
  // Exit lands on the list with nothing open and nobody would connect the two.
  const planner = readFileSync(
    path.join(HERE, '..', 'planner', 'templates', 'planner', 'planner.html'), 'utf8');
  check('planner.html still understands ?edit=<id>',
        /params\.get\('edit'\)/.test(planner) && /openEditModal\(/.test(planner));
  // Without this, the post page falls back to the full overview and the whole
  // point of carrying the origin along is lost - silently.
  check('and it still reads the origin we send with it',
        /params\.get\('back'\)/.test(planner));
}

console.log('\n' + good + ' ok, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
