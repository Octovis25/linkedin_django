"""A small, safe Nextcloud client: list, read, create, archive. Nothing else.

Why it exists (Nextcloud refactor, step 1, 14.10.2026): the app has four
separate sets of WebDAV helpers, and every one of them overwrites silently.
Controlled documents (Octovis, later OctoVal) need the opposite: a new file
is created only if its name is free, and nothing that exists is ever
changed, moved or deleted.

What it can do:
    list_folder(path)            entries of one folder
    read_file(path)              the bytes of one file
    create_folder(path)          a new folder (error if it exists)
    create_file(path, content)   a new file - PUT with If-None-Match: *, so
                                 Nextcloud itself refuses an existing name
    archive_file(path)           moves one file into the folder "Archive" next
                                 to it (29.10.2026), so old versions stop piling
                                 up. MOVE with Overwrite: F; a name taken in the
                                 archive gets the date added, nothing is replaced

What it cannot do, on purpose, and there is no hidden switch: overwrite,
delete, copy, rename, share, change properties, move anywhere but into an
archive. The class has no method for it and never sends DELETE, COPY,
PROPPATCH or LOCK; MOVE is sent only by archive_file, only into "Archive".

Own credentials: the client never reads the LinkedIn app's settings. It is
given URL, user and app password directly, or reads them from environment
variables with a prefix of its own (default OCTOVIS_NC_URL, OCTOVIS_NC_USER,
OCTOVIS_NC_APP_PASSWORD) - meant for a service user such as "claude-service"
whose Nextcloud rights end at its own folder.

Root: every path is relative to a fixed root folder (for example "Octovis").
Absolute paths, "..", backslashes and control characters are refused before
anything is sent.

No Django import: the module only needs `requests`, so it can be copied into
a separate service unchanged.
"""
import datetime
import email.utils
import os
import posixpath
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

import requests
from requests.auth import HTTPBasicAuth

DAV_NS = {'d': 'DAV:', 'oc': 'http://owncloud.org/ns'}
PROPFIND_BODY = (
    '<?xml version="1.0"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop>'
    '<d:resourcetype/><d:getcontentlength/><d:getcontenttype/>'
    '<d:getlastmodified/><d:getetag/>'
    '</d:prop></d:propfind>'
)
DEFAULT_MAX_READ = 25 * 1024 * 1024        # 25 MB - Render has 512 MB
ARCHIVE = 'Archive'                        # where archive_file puts old versions


def _today():
    return datetime.date.today().isoformat()


# -- errors --------------------------------------------------------------------
class NextcloudError(Exception):
    """Something went wrong; the message says what, in plain words."""


class NotConfigured(NextcloudError):
    pass


class PathNotAllowed(NextcloudError):
    pass


class NotFound(NextcloudError):
    pass


class AlreadyExists(NextcloudError):
    pass


class ParentMissing(NextcloudError):
    pass


class AccessDenied(NextcloudError):
    pass


class TooLarge(NextcloudError):
    pass


@dataclass
class Entry:
    name: str
    path: str               # relative to the client's root
    is_folder: bool
    size: int
    modified: str           # ISO 8601, UTC, or '' if Nextcloud gave none
    content_type: str
    etag: str


# -- the client ------------------------------------------------------------------
class NextcloudClient:

    def __init__(self, url, user, app_password, root='', timeout=30,
                 max_read=DEFAULT_MAX_READ, on_call=None, session=None):
        url = (url or '').strip().rstrip('/')
        user = (user or '').strip()
        app_password = (app_password or '').strip()
        if not (url and user and app_password):
            raise NotConfigured('Nextcloud is not configured (URL, user or app password missing)')
        if not url.startswith('https://') and not url.startswith('http://localhost'):
            raise NotConfigured('The Nextcloud URL must start with https://')
        self.url = url
        self.user = user
        self._auth = HTTPBasicAuth(user, app_password)
        self.root = self._clean_root(root)
        self.timeout = timeout
        self.max_read = max_read
        self.on_call = on_call          # on_call(method, path, outcome) - for an audit log
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls, prefix='OCTOVIS_NC', root='', environ=None, **kwargs):
        env = os.environ if environ is None else environ
        return cls(env.get(prefix + '_URL', ''), env.get(prefix + '_USER', ''),
                   env.get(prefix + '_APP_PASSWORD', ''), root=root, **kwargs)

    def __repr__(self):
        # Never the password - a repr ends up in logs and tracebacks.
        return '<NextcloudClient %s as %s, root %r>' % (self.url, self.user, self.root)

    # -- paths ---------------------------------------------------------------
    @staticmethod
    def _check_segments(text):
        for ch in text:
            if ord(ch) < 32 or ch in '\\\x7f':
                raise PathNotAllowed('Path contains a character that is not allowed')
        parts = [p for p in text.split('/')]
        for p in parts:
            if p in ('.', '..'):
                raise PathNotAllowed('Paths with "." or ".." are not allowed')
        return [p for p in parts if p]

    def _clean_root(self, root):
        root = (root or '').strip()
        if root.startswith('/'):
            root = root.lstrip('/')
        return '/'.join(self._check_segments(root))

    def full_path(self, path):
        """'Policies/a.md' -> 'Octovis/Policies/a.md'. Refuses everything that
        could leave the root."""
        path = '' if path is None else str(path)
        if path.startswith('/'):
            raise PathNotAllowed('Use a path relative to the root, without a leading "/"')
        parts = self._check_segments(path)
        joined = '/'.join(([self.root] if self.root else []) + parts)
        # belt and braces: normalising must not change anything
        if posixpath.normpath('/' + joined).lstrip('/') != joined and joined:
            raise PathNotAllowed('Path is not allowed')
        return joined

    def _dav_url(self, full):
        base = '%s/remote.php/dav/files/%s' % (self.url, quote(self.user, safe=''))
        return base + ('/' + quote(full, safe='/') if full else '')

    def _relative(self, full):
        if not self.root:
            return full
        if full == self.root:
            return ''
        return full[len(self.root) + 1:] if full.startswith(self.root + '/') else full

    # -- one request ---------------------------------------------------------
    def _request(self, method, full, **kwargs):
        try:
            return self._session.request(method, self._dav_url(full), auth=self._auth,
                                         timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise NextcloudError('Nextcloud could not be reached: %s' % type(e).__name__)

    def _log(self, method, path, outcome):
        if self.on_call:
            try:
                self.on_call(method, path, outcome)
            except Exception:
                pass

    @staticmethod
    def _raise_for(status, what):
        if status in (401, 403):
            raise AccessDenied('Nextcloud refused access to %s (%d)' % (what, status))
        if status == 404:
            raise NotFound('%s does not exist' % what)
        if status == 409:
            raise ParentMissing('The folder for %s does not exist' % what)
        if status in (405, 412):
            raise AlreadyExists('%s already exists - nothing was changed' % what)
        if status == 423:
            raise NextcloudError('%s is locked in Nextcloud (423)' % what)
        if status == 507:
            raise NextcloudError('Nextcloud has no space left (507)')
        raise NextcloudError('Nextcloud answered %d for %s' % (status, what))

    # -- the four operations ---------------------------------------------------
    def list_folder(self, path=''):
        full = self.full_path(path)
        r = self._request('PROPFIND', full, data=PROPFIND_BODY,
                          headers={'Depth': '1', 'Content-Type': 'application/xml'})
        if r.status_code not in (207, 200):
            self._log('list_folder', path, 'error %d' % r.status_code)
            self._raise_for(r.status_code, path or 'the root folder')
        entries = self._parse(r.content, full)
        self._log('list_folder', path, 'ok, %d entries' % len(entries))
        return entries

    def read_file(self, path):
        full = self.full_path(path)
        if not full or full == self.root:
            raise PathNotAllowed('Name a file to read')
        r = self._request('GET', full, stream=True)
        try:
            if r.status_code != 200:
                self._log('read_file', path, 'error %d' % r.status_code)
                self._raise_for(r.status_code, path)
            size = int(r.headers.get('Content-Length') or 0)
            if size > self.max_read:
                self._log('read_file', path, 'too large')
                raise TooLarge('%s is larger than %d MB' % (path, self.max_read // (1024 * 1024)))
            chunks, total = [], 0
            for chunk in r.iter_content(64 * 1024):
                total += len(chunk)
                if total > self.max_read:
                    self._log('read_file', path, 'too large')
                    raise TooLarge('%s is larger than %d MB' % (path, self.max_read // (1024 * 1024)))
                chunks.append(chunk)
        finally:
            r.close()
        self._log('read_file', path, 'ok, %d bytes' % total)
        return b''.join(chunks)

    def create_folder(self, path):
        full = self.full_path(path)
        if not full or full == self.root:
            raise PathNotAllowed('Name the new folder')
        r = self._request('MKCOL', full)
        if r.status_code != 201:
            self._log('create_folder', path, 'error %d' % r.status_code)
            self._raise_for(r.status_code, path)
        self._log('create_folder', path, 'created')
        return self._relative(full)

    def create_file(self, path, content, content_type='application/octet-stream'):
        """Create a NEW file. If the name exists, AlreadyExists - the existing
        file is not touched. The check is Nextcloud's own (If-None-Match: *),
        so there is no gap between "is it there?" and "write it"."""
        full = self.full_path(path)
        if not full or full == self.root or path.endswith('/'):
            raise PathNotAllowed('Name the new file')
        if isinstance(content, str):
            content = content.encode('utf-8')
        if not isinstance(content, (bytes, bytearray)):
            raise NextcloudError('Content must be bytes or text')
        r = self._request('PUT', full, data=bytes(content),
                          headers={'If-None-Match': '*', 'Content-Type': content_type})
        if r.status_code == 204:
            # 204 means Nextcloud REPLACED a file - which If-None-Match must
            # prevent. If it ever happens, say so loudly instead of "ok".
            self._log('create_file', path, 'ERROR: server replaced an existing file')
            raise NextcloudError('Nextcloud replaced an existing file although it was told not to')
        if r.status_code != 201:
            self._log('create_file', path, 'error %d' % r.status_code)
            self._raise_for(r.status_code, path)
        self._log('create_file', path, 'created, %d bytes' % len(content))
        return self._relative(full)

    def archive_file(self, path):
        """Move one file into the folder "Archive" next to it:
        'SOPs/SOP-001_v1.docx' -> 'SOPs/Archive/SOP-001_v1.docx'. The archive
        folder is created when it is missing. A name already taken there gets
        the date, then a number: 'SOP-001_v1_2026-10-29.docx', '..._2.docx'.
        Nothing is ever replaced - Overwrite: F lets Nextcloud itself refuse a
        taken name. Only files, and not ones that are in an archive already.
        Returns (old path, new path), both relative to the root."""
        full = self.full_path(path)
        if not full or full == self.root or str(path).endswith('/'):
            raise PathNotAllowed('Name the file to archive')
        parent, _, name = full.rpartition('/')
        inside = self._relative(parent).split('/') if self._relative(parent) else []
        if any(p.lower() == ARCHIVE.lower() for p in inside):
            raise PathNotAllowed('%s is in an archive already' % path)
        entry = self._stat(full, path)
        if entry.is_folder:
            raise PathNotAllowed('%s is a folder - only files can be archived' % path)

        archive = (parent + '/' if parent else '') + ARCHIVE
        r = self._request('MKCOL', archive)
        if r.status_code not in (201, 405):          # 405: the archive is there already
            self._log('archive_file', path, 'error %d (archive folder)' % r.status_code)
            self._raise_for(r.status_code, self._relative(archive) or ARCHIVE)

        stem, dot, ext = name.rpartition('.')
        if not stem:                                 # '.env' or a name without a dot
            stem, dot, ext = name, '', ''
        names = [name] + ['%s_%s%s%s' % (stem, _today(), suffix, dot + ext if dot else '')
                          for suffix in [''] + ['_%d' % i for i in range(2, 10)]]
        for candidate in names:
            target = archive + '/' + candidate
            r = self._request('MOVE', full, headers={'Destination': self._dav_url(target),
                                                     'Overwrite': 'F'})
            if r.status_code == 201:
                self._log('archive_file', path, 'moved to %s' % self._relative(target))
                return self._relative(full), self._relative(target)
            if r.status_code == 204:
                # 204 means a file was REPLACED - which Overwrite: F must prevent.
                self._log('archive_file', path, 'ERROR: server replaced an existing file')
                raise NextcloudError('Nextcloud replaced a file in the archive although it was '
                                     'told not to')
            if r.status_code != 412:                 # 412: name taken, try the next one
                self._log('archive_file', path, 'error %d' % r.status_code)
                self._raise_for(r.status_code, path)
        self._log('archive_file', path, 'no free name in the archive')
        raise AlreadyExists('No free name for %s in %s' % (name, self._relative(archive) or ARCHIVE))

    def _stat(self, full, what):
        r = self._request('PROPFIND', full, data=PROPFIND_BODY,
                          headers={'Depth': '0', 'Content-Type': 'application/xml'})
        if r.status_code not in (207, 200):
            self._raise_for(r.status_code, what)
        entries = self._parse(r.content, '', keep_self=True)
        if not entries:
            raise NotFound('%s does not exist' % what)
        return entries[0]

    # -- parsing ---------------------------------------------------------------
    def _parse(self, xml_bytes, folder_full, keep_self=False):
        try:
            tree = ET.fromstring(xml_bytes)
        except ET.ParseError:
            raise NextcloudError('Nextcloud sent an answer that could not be read')
        prefix = '/remote.php/dav/files/%s/' % self.user
        out = []
        for resp in tree.findall('d:response', DAV_NS):
            href = unquote(urlsplit(resp.findtext('d:href', '', DAV_NS)).path)
            pos = href.find(prefix)
            full = href[pos + len(prefix):] if pos >= 0 else href
            full = full.strip('/')
            if full == folder_full.strip('/') and not keep_self:
                continue                         # the folder itself
            if self.root and not (full == self.root or full.startswith(self.root + '/')):
                continue                         # never report anything outside the root
            prop = resp.find('d:propstat/d:prop', DAV_NS)
            if prop is None:
                continue
            is_folder = prop.find('d:resourcetype/d:collection', DAV_NS) is not None
            try:
                size = int(prop.findtext('d:getcontentlength', '0', DAV_NS) or 0)
            except ValueError:
                size = 0
            modified = prop.findtext('d:getlastmodified', '', DAV_NS)
            if modified:
                try:
                    modified = email.utils.parsedate_to_datetime(modified).isoformat()
                except (TypeError, ValueError):
                    pass
            out.append(Entry(name=full.rsplit('/', 1)[-1], path=self._relative(full),
                             is_folder=is_folder, size=size, modified=modified,
                             content_type=prop.findtext('d:getcontenttype', '', DAV_NS),
                             etag=(prop.findtext('d:getetag', '', DAV_NS) or '').strip('"')))
        out.sort(key=lambda e: (not e.is_folder, e.name.lower()))
        return out
