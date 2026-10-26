"""A Nextcloud WebDAV server in memory, for tests only.

Why it exists: before the Nextcloud code is refactored, today's behaviour has
to be written down in tests. These tests must never reach the real Nextcloud,
so every HTTP call made through ``requests`` is answered here instead.

How it plugs in: all Nextcloud code in this app uses ``requests`` (requests.put,
requests.get, requests.request('MKCOL', ...) and so on). Every one of those
ends in ``requests.Session.request``. That single method is replaced while the
fake is active. A call to any other host fails the test at once - nothing can
slip through to the network.

What it imitates (the parts the app relies on):

    PUT       201 new, 204 replaced (silently, as Nextcloud does),
              409 parent folder missing, 412 with If-None-Match: * on an
              existing file
    GET       200, 206 for a Range request, 404
    DELETE    204 (files and whole folders), 404
    MKCOL     201, 405 already there, 409 parent missing
    MOVE      201 new, 204 replaced, 412 Overwrite: F on a taken name,
              404 source missing, 409 target folder missing
    PROPFIND  207 multistatus for Depth 0 / 1 / infinity, 404

Every call is recorded (method, path, headers, user) so a test can say
exactly what the app sent. ``force[(METHOD, path)] = status`` makes a single
request fail the way the real server sometimes does (423 locked, 401, 507).

Usage::

    with FakeNextcloud() as nc:
        nc.add_folder('Marketing_and_Design/LinkedIn/Planner/Images')
        ... call app code ...
        nc.calls      -> list of Call
        nc.files      -> {path: FakeFile}
"""
import email.utils
from collections import namedtuple
from unittest import mock
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

import requests
from requests.structures import CaseInsensitiveDict

FAKE_URL = 'https://nc.fake.test'
FAKE_USER = 'fake-user'
FAKE_PASSWORD = 'fake-app-password'

Call = namedtuple('Call', 'method path headers user body')


class FakeFile:
    def __init__(self, content, content_type, mtime):
        self.content = content
        self.content_type = content_type
        self.mtime = mtime


class ForeignHostError(AssertionError):
    """A test tried to reach something other than the fake Nextcloud."""


class FakeNextcloud:
    def __init__(self, base_url=FAKE_URL):
        self.base_url = base_url.rstrip('/')
        self.host = urlsplit(self.base_url).netloc
        self.files = {}            # path -> FakeFile
        self.folders = {''}        # '' is the user's root folder
        self.calls = []
        self.force = {}            # (METHOD, path) -> status code
        self.overwritten = []      # paths a PUT or MOVE replaced
        self.foreign = []          # URLs that were not for this fake - must stay empty
        self._clock = 1_790_000_000
        self._patch = None

    # -- set-up helpers ------------------------------------------------------
    def add_folder(self, path):
        path = path.strip('/')
        parts = path.split('/') if path else []
        for i in range(1, len(parts) + 1):
            self.folders.add('/'.join(parts[:i]))

    def add_file(self, path, content=b'x', content_type='application/octet-stream'):
        path = path.strip('/')
        self.add_folder(path.rsplit('/', 1)[0] if '/' in path else '')
        self.files[path] = FakeFile(content, content_type, self._tick())

    def calls_of(self, method):
        return [c for c in self.calls if c.method == method.upper()]

    def methods(self):
        return [c.method for c in self.calls]

    # -- context manager -----------------------------------------------------
    def __enter__(self):
        fake = self

        def request(session, method, url, **kwargs):
            return fake._handle(method, url, **kwargs)

        self._patch = mock.patch.object(requests.sessions.Session, 'request', request)
        self._patch.start()
        return self

    def __exit__(self, *_):
        self._patch.stop()
        return False

    # -- the server ----------------------------------------------------------
    def _tick(self):
        self._clock += 1
        return self._clock

    def _path_of(self, url):
        parts = urlsplit(url)
        if parts.netloc != self.host:
            # App code catches every exception, so raising alone could go
            # unnoticed. The URL is kept and NextcloudTest checks the list.
            self.foreign.append(url)
            raise ForeignHostError('Request to a foreign host: %s' % url)
        marker = '/remote.php/dav/files/'
        p = parts.path
        if marker not in p:
            self.foreign.append(url)
            raise ForeignHostError('Not a WebDAV files URL: %s' % url)
        rest = p.split(marker, 1)[1]
        user, _, rel = rest.partition('/')
        return unquote(user), unquote(rel).strip('/')

    def _handle(self, method, url, data=None, headers=None, auth=None, **_kw):
        method = method.upper()
        headers = CaseInsensitiveDict(headers or {})
        user, path = self._path_of(url)
        body = data
        if hasattr(body, 'read'):
            body = body.read()
        if isinstance(body, str):
            body = body.encode('utf-8')
        auth_user = getattr(auth, 'username', None)
        if auth_user is None and isinstance(auth, tuple):
            auth_user = auth[0]
        self.calls.append(Call(method, path, dict(headers), auth_user, body))

        forced = self.force.get((method, path))
        if forced:
            return self._response(forced, url)
        handler = getattr(self, '_do_' + method, None)
        if handler is None:
            return self._response(405, url)
        return handler(path, url, body or b'', headers, user)

    def _parent(self, path):
        return path.rsplit('/', 1)[0] if '/' in path else ''

    def _do_PUT(self, path, url, body, headers, user):
        if path in self.folders:
            return self._response(405, url)
        if self._parent(path) not in self.folders:
            return self._response(409, url)
        exists = path in self.files
        if exists and headers.get('If-None-Match') == '*':
            return self._response(412, url)
        if exists:
            self.overwritten.append(path)
        self.files[path] = FakeFile(body, headers.get('Content-Type', 'application/octet-stream'),
                                    self._tick())
        return self._response(204 if exists else 201, url)

    def _do_GET(self, path, url, body, headers, user):
        f = self.files.get(path)
        if f is None:
            return self._response(404, url)
        content = f.content
        out = {'Content-Type': f.content_type}
        rng = headers.get('Range')
        if rng and rng.startswith('bytes='):
            von, _, bis = rng[6:].partition('-')
            start = int(von) if von else 0
            end = min(int(bis) if bis else len(content) - 1, len(content) - 1)
            out['Content-Range'] = 'bytes %d-%d/%d' % (start, end, len(content))
            content = content[start:end + 1]
            out['Content-Length'] = str(len(content))
            return self._response(206, url, content, out)
        out['Content-Length'] = str(len(content))
        return self._response(200, url, content, out)

    def _do_DELETE(self, path, url, body, headers, user):
        if path in self.files:
            del self.files[path]
            return self._response(204, url)
        if path in self.folders and path:
            prefix = path + '/'
            self.folders = {f for f in self.folders if f != path and not f.startswith(prefix)}
            self.files = {k: v for k, v in self.files.items() if not k.startswith(prefix)}
            return self._response(204, url)
        return self._response(404, url)

    def _do_MKCOL(self, path, url, body, headers, user):
        if path in self.folders or path in self.files:
            return self._response(405, url)
        if self._parent(path) not in self.folders:
            return self._response(409, url)
        self.folders.add(path)
        return self._response(201, url)

    def _do_MOVE(self, path, url, body, headers, user):
        if path not in self.files:
            return self._response(404, url)
        dest_url = headers.get('Destination')
        if not dest_url:
            return self._response(400, url)
        _u, dest = self._path_of(dest_url)
        if self._parent(dest) not in self.folders:
            return self._response(409, url)
        taken = dest in self.files
        if taken and headers.get('Overwrite', 'T').upper() == 'F':
            return self._response(412, url)
        if taken:
            self.overwritten.append(dest)
        self.files[dest] = self.files.pop(path)
        return self._response(204 if taken else 201, url)

    def _do_PROPFIND(self, path, url, body, headers, user):
        if path not in self.folders and path not in self.files:
            return self._response(404, url)
        depth = headers.get('Depth', 'infinity')
        entries = [path]
        if path in self.folders and depth != '0':
            prefix = path + '/' if path else ''
            for p in sorted(self.folders | set(self.files)):
                if p == path or not p.startswith(prefix):
                    continue
                if depth == '1' and '/' in p[len(prefix):]:
                    continue
                entries.append(p)
        xml = ['<?xml version="1.0"?>',
               '<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" '
               'xmlns:nc="http://nextcloud.org/ns">']
        for p in entries:
            is_dir = p in self.folders
            href = '/remote.php/dav/files/%s/%s' % (quote(user), quote(p, safe='/'))
            if is_dir and not href.endswith('/'):
                href += '/'
            name = p.rsplit('/', 1)[-1]
            props = ['<d:displayname>%s</d:displayname>' % escape(name)]
            if is_dir:
                props.append('<d:resourcetype><d:collection/></d:resourcetype>')
            else:
                f = self.files[p]
                props.append('<d:resourcetype/>')
                props.append('<d:getcontenttype>%s</d:getcontenttype>' % escape(f.content_type))
                props.append('<d:getcontentlength>%d</d:getcontentlength>' % len(f.content))
                props.append('<d:getlastmodified>%s</d:getlastmodified>'
                             % email.utils.formatdate(f.mtime, usegmt=True))
            xml.append('<d:response><d:href>%s</d:href><d:propstat><d:prop>%s</d:prop>'
                       '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                       % (href, ''.join(props)))
        xml.append('</d:multistatus>')
        return self._response(207, url, '\n'.join(xml).encode('utf-8'),
                              {'Content-Type': 'application/xml; charset=utf-8'})

    def _response(self, status, url, content=b'', headers=None):
        r = requests.Response()
        r.status_code = status
        r._content = content
        r._content_consumed = True     # iter_content then slices _content
        r.headers = CaseInsensitiveDict(headers or {})
        r.url = url
        r.encoding = 'utf-8'
        return r
