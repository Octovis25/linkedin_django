"""Writes the audit trail: every change made through the app, by whom.

A change is any POST, PUT, PATCH or DELETE. Reads (GET) are not recorded -
looking is not doing, and it would bury the changes.

Recorded for signed-in users, and for the Claude API (/api/claude/), which
signs in with a key instead of a user and appears as "Claude API".

What is kept of the request is deliberately little: a short list of harmless
fields (action, id, title, status, date ...) and the names and sizes of
uploaded files. Never a password, never a token, never a whole canvas or file
content. The login form is not read at all - sign-ins come from signals.py.

The request body is only read where it is safe:
  * form and multipart data only if the view has already parsed it, so a
    50 MB video upload is never read a second time into memory;
  * JSON only up to MAX_JSON bytes.
"""
import json

from django.urls import Resolver404, resolve

from . import store

WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
SKIP_PREFIXES = ('/static/', '/media/', '/login/', '/logout/', '/audit/',
                 '/password-reset/', '/reset/', '/change-password/')
CLAUDE_API_PREFIX = '/api/claude/'
CLAUDE_API_USER = 'Claude API'
MAX_JSON = 200 * 1024
KEEP_FIELDS = ('action', 'id', 'post_id', 'item_id', 'folder_id', 'topic_id', 'title',
               'name', 'status', 'datum', 'date', 'time', 'type', 'post_type', 'category',
               'folder', 'nc_path', 'path', 'link', 'source', 'target', 'kind', 'mode')
SECRET_WORDS = ('password', 'passwort', 'token', 'secret', 'api_key', 'apikey', 'key')
OBJECT_KEYS = ('post_id', 'id', 'item_id', 'pk', 'film_id', 'user_id', 'folder_id')


class AuditTrailMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if self._wanted(request):
                self._record(request, getattr(response, 'status_code', 0))
        except Exception as error:          # the trail must never break a request
            print('audit trail: %s' % error)
        return response

    def process_exception(self, request, exception):
        try:
            if self._wanted(request):
                self._record(request, 500, error=type(exception).__name__)
        except Exception:
            pass
        return None

    # -- what is recorded ------------------------------------------------------
    def _wanted(self, request):
        if request.method not in WRITE_METHODS:
            return False
        path = request.path
        if path.startswith(SKIP_PREFIXES):
            return False
        if path.startswith(CLAUDE_API_PREFIX):
            return True
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated)

    def _record(self, request, status, error=None):
        if getattr(request, '_audit_written', False):
            return          # process_exception and __call__ both fire on errors
        request._audit_written = True
        user = getattr(request, 'user', None)
        if request.path.startswith(CLAUDE_API_PREFIX) and not (user and user.is_authenticated):
            username, user_id = CLAUDE_API_USER, None
        else:
            username, user_id = user.get_username(), user.pk

        view, kwargs = view_of(request.path)
        fields = body_fields(request)
        details = {k: v for k, v in fields.items()}
        files = uploaded_files(request)
        if files:
            details['files'] = files
        if kwargs:
            details['url'] = kwargs
        if error:
            details['error'] = error
        store.write(username, request.method, request.path, view=view,
                    action=str(fields.get('action', ''))[:100],
                    object_id=object_of(kwargs, fields), status=status,
                    details=details, user_id=user_id)


def view_of(path):
    """('planner:post_api', {'post_id': 127}) - or the module and function name."""
    try:
        match = resolve(path)
    except Resolver404:
        return '', {}
    name = match.view_name or ''
    if not name or name == match._func_path:
        name = '%s.%s' % (getattr(match.func, '__module__', ''),
                          getattr(match.func, '__name__', ''))
    kwargs = {k: v for k, v in (match.kwargs or {}).items() if not _secret(k)}
    return name[:150], kwargs


def _secret(name):
    name = name.lower()
    return any(w in name for w in SECRET_WORDS) and name not in ('folder_key',)


def _short(value):
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    return text if len(text) <= 120 else text[:117] + '...'


def body_fields(request):
    """The harmless fields of the request, from form data or JSON."""
    source = {}
    post = getattr(request, '_post', None)          # only if the view parsed it
    if post is not None:
        source = {k: post.get(k) for k in post.keys()}
    elif 'json' in (request.content_type or ''):
        try:
            size = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            size = 0
        if 0 < size <= MAX_JSON:
            try:
                data = json.loads(request.body or b'{}')
            except Exception:
                data = {}
            if isinstance(data, dict):
                source = data
    out = {}
    for key in KEEP_FIELDS:
        if key in source and not _secret(key):
            value = source[key]
            if isinstance(value, (dict, list)):
                continue
            out[key] = _short(value)
    return out


def uploaded_files(request):
    files = getattr(request, '_files', None)        # only if the view parsed it
    if not files:
        return []
    out = []
    for field in files.keys():
        for f in files.getlist(field):
            out.append({'field': field, 'name': _short(getattr(f, 'name', '')),
                        'size': getattr(f, 'size', 0)})
    return out[:10]


def object_of(kwargs, fields):
    for key in OBJECT_KEYS:
        if kwargs.get(key) not in (None, ''):
            return kwargs[key]
    for key in OBJECT_KEYS:
        if fields.get(key) not in (None, ''):
            return fields[key]
    return ''
