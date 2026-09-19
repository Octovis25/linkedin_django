"""Does Buffer get an address that really holds an MP4?

The Studio records in the browser, and a browser records WebM. LinkedIn does
not take WebM, so a post built here went out with an empty video and nothing
said why - not the app, not Buffer, not LinkedIn.

Cloudinary converts on request: the same asset with a .mp4 extension. The catch
is that the first request is what starts the conversion. Asking for the address
and handing it to Buffer in the same breath can pass on something that is not
there yet, and Buffer fetches exactly once.

So the address is fetched here first and only passed on once it has arrived.
This test checks that decision - the function is cut out of planner/views.py,
the file that ships, and the web is stood in for.

    python _tests/mp4_test.py
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
QUELLE = os.path.join(os.path.dirname(HIER), 'planner', 'views.py')

with open(QUELLE, encoding='utf-8') as fh:
    SRC = fh.read()


def herausschneiden(name):
    marke = '\ndef %s(' % name
    if marke not in SRC:
        raise SystemExit('not found in planner/views.py: ' + name)
    zeilen = SRC[SRC.index(marke) + 1:].split('\n')
    raus = [zeilen[0]]
    for zeile in zeilen[1:]:
        if zeile and not zeile[0].isspace():
            break
        raus.append(zeile)
    return '\n'.join(raus)


class FakeAntwort:
    def __init__(self, status=200, typ='video/mp4', koerper=b'\x00\x00\x00\x18ftypmp42'):
        self.status_code = status
        self.headers = {'Content-Type': typ} if typ else {}
        self._koerper = koerper

    def iter_content(self, chunk_size=None):
        if self._koerper:
            yield self._koerper

    def close(self):
        pass


class FakeWeb:
    """The internet, reduced to: what does this address answer, and how often
    was it asked."""

    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.gefragt = []

    def get(self, url, **kw):
        self.gefragt.append(url)
        a = self.antworten[min(len(self.gefragt) - 1, len(self.antworten) - 1)]
        if isinstance(a, Exception):
            raise a
        return a


def baue(web):
    """The function under test, with the web and the waiting stood in for."""
    geschlafen = []

    class FakeTime:
        @staticmethod
        def sleep(s):
            geschlafen.append(s)

    raum = {'__builtins__': __builtins__}
    exec(compile(herausschneiden('_verified_mp4_url'), 'planner/views.py (cut out)', 'exec'), raum)
    fn = raum['_verified_mp4_url']

    # The function imports requests and time itself; hand it ours.
    import types
    modul_requests = types.ModuleType('requests')
    modul_requests.get = web.get
    sys.modules['requests'] = modul_requests
    sys.modules['time'] = FakeTime
    return fn, geschlafen


import time as _echte_zeit                                   # noqa: E402
_orig_requests = sys.modules.get('requests')

gut = 0
schlecht = 0


def pruefe(name, ok, extra=''):
    global gut, schlecht
    if ok:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FAIL ' + name + ('  -> ' + str(extra) if extra != '' else ''))


WEBM = 'https://res.cloudinary.com/x/video/upload/v1/post_53.webm'
MP4 = 'https://res.cloudinary.com/x/video/upload/v1/post_53.mp4'

print('\n=== The WebM address becomes an MP4 address ===')
web = FakeWeb([FakeAntwort()])
fn, _ = baue(web)
pruefe('the extension is swapped', fn(WEBM) == MP4, fn(WEBM))
pruefe('and that is the address that was checked', web.gefragt[0] == MP4, web.gefragt)

print('\n=== A GIF address goes the same way ===')
web = FakeWeb([FakeAntwort()])
fn, _ = baue(web)
gif = 'https://res.cloudinary.com/x/image/upload/v1/post_60.gif'
pruefe('.gif becomes .mp4', fn(gif).endswith('/post_60.mp4'), fn(gif))

print('\n=== An address that is already MP4 is left alone ===')
web = FakeWeb([FakeAntwort()])
fn, _ = baue(web)
pruefe('unchanged', fn(MP4) == MP4, fn(MP4))

print('\n=== Conversion that needs a moment ===')
# Cloudinary answers 423 while it is still producing the file. Buffer would
# have fetched exactly once and got nothing.
web = FakeWeb([FakeAntwort(status=423, typ='text/plain', koerper=b'busy'), FakeAntwort()])
fn, geschlafen = baue(web)
pruefe('it waits and asks again', fn(WEBM) == MP4)
pruefe('it really waited in between', len(geschlafen) >= 1, geschlafen)
pruefe('and did not ask a hundred times', len(web.gefragt) <= 4, len(web.gefragt))

print('\n=== What must never happen: passing on an address that is empty ===')
web = FakeWeb([FakeAntwort(status=404, typ='text/html', koerper=b'<html>')])
fn, _ = baue(web)
try:
    ergebnis = fn(WEBM, versuche=2, pause=0)
    pruefe('an address that answers 404 is refused', False, ergebnis)
except Exception as fehler:
    pruefe('an address that answers 404 is refused', True)
    pruefe('and the message says the post was not sent',
           'NOT sent' in str(fehler), str(fehler)[:90])

web = FakeWeb([FakeAntwort(status=200, typ='text/html', koerper=b'<html>')])
fn, _ = baue(web)
try:
    fn(WEBM, versuche=2, pause=0)
    pruefe('an HTML page pretending to be a video is refused', False)
except Exception:
    pruefe('an HTML page pretending to be a video is refused', True)

web = FakeWeb([FakeAntwort(status=200, typ='video/mp4', koerper=b'')])
fn, _ = baue(web)
try:
    fn(WEBM, versuche=2, pause=0)
    pruefe('an empty body is refused, whatever the type says', False)
except Exception:
    pruefe('an empty body is refused, whatever the type says', True)

web = FakeWeb([RuntimeError('connection reset')])
fn, _ = baue(web)
try:
    fn(WEBM, versuche=2, pause=0)
    pruefe('a connection that fails is refused', False)
except Exception:
    pruefe('a connection that fails is refused', True)

print('\n=== And the send really uses it ===')
_hochladen = herausschneiden('_upload_video_to_cloudinary')
pruefe('the upload returns the verified address',
       'return _verified_mp4_url(' in _hochladen)
pruefe('and no longer hands over the original',
       'return secure_url' not in _hochladen)

# Put the real modules back, so nothing else in this process is surprised.
if _orig_requests is not None:
    sys.modules['requests'] = _orig_requests
sys.modules['time'] = _echte_zeit

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
