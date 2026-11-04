"""Read access to octotrial.com through the WordPress REST API.

Only GET, never anything that changes WordPress. The sign-in is the
application password of the user octovis-log (role editor) in WP_LOG_TOKEN
("octovis-log:xxxx xxxx ..."). Revisions need a user who may edit the page;
the Matomo user may not, so MATOMO_TOKEN is only the fallback while
WP_LOG_TOKEN is not set.

A 401 or 403 is never repeated: "King Addons Login Security" blocks an
address after failed sign-ins. The error goes up, the caller stops.
"""
import requests
from django.conf import settings

from matomo.client import MatomoError, _basis

KINDS = ('pages', 'posts')        # WordPress pages and blog posts ("Insights")
LIST_STATUS = 'publish,draft,private,pending,future'


class WordPressError(RuntimeError):
    pass


class AccessError(WordPressError):
    """401/403 - stop everything, do not ask again."""


def _zugang():
    token = (getattr(settings, 'WP_LOG_TOKEN', '') or '').strip()
    name = 'WP_LOG_TOKEN'
    if not token:
        token, name = (getattr(settings, 'MATOMO_TOKEN', '') or '').strip(), 'MATOMO_TOKEN'
    if ':' not in token:
        raise WordPressError('WP_LOG_TOKEN is not set. Expected "octovis-log:<application password>" '
                             'in .env or on Render under Environment.')
    user, password = token.split(':', 1)
    return (user, password), name


def _request(route, params):
    try:
        auth, name = _zugang()
        base = _basis()
    except MatomoError as fehler:
        raise WordPressError(str(fehler))
    try:
        antwort = requests.get(
            f"{base}/wp-json/wp/v2/{route}", params=params, auth=auth,
            timeout=getattr(settings, 'MATOMO_TIMEOUT', 30),
            headers={'User-Agent': 'octovis-website-log'})
    except requests.RequestException as fehler:
        raise WordPressError(f'WordPress not reachable: {fehler}')
    if antwort.status_code == 401:
        raise AccessError(f'WordPress did not accept the sign-in (401): check the application password '
                          f'in {name}. Not tried again - the login security blocks after failed sign-ins.')
    if antwort.status_code == 403:
        raise AccessError(f'WordPress refused (403) for {route}: the user in {name} may not edit it, '
                          'so it cannot read its revisions.')
    return antwort


def _json(antwort, route):
    try:
        return antwort.json()
    except ValueError:
        raise WordPressError(f'WordPress sent no JSON for {route}')


def _get(route, **params):
    antwort = _request(route, params)
    if antwort.status_code == 404:
        return None
    if antwort.status_code >= 400:
        raise WordPressError(f'WordPress answered HTTP {antwort.status_code} for {route}')
    return _json(antwort, route)


def get_all(route, **params):
    """Every item of a list, page by page (per_page=100, X-WP-TotalPages).
    A route WordPress does not know (404) gives an empty list."""
    params = {**params, 'per_page': 100}
    items, page = [], 1
    while True:
        antwort = _request(route, {**params, 'page': page})
        if antwort.status_code == 404:
            return items
        if antwort.status_code == 400 and page > 1:     # asked past the last page
            return items
        if antwort.status_code >= 400:
            raise WordPressError(f'WordPress answered HTTP {antwort.status_code} for {route}')
        daten = _json(antwort, route)
        if not isinstance(daten, list):
            return items
        items.extend(daten)
        try:
            total = int(antwort.headers.get('X-WP-TotalPages') or 1)
        except (TypeError, ValueError):
            total = 1
        if page >= total or not daten:
            return items
        page += 1


def _text(feld):
    if isinstance(feld, dict):
        return feld.get('raw') or feld.get('rendered') or ''
    return str(feld or '')


def page(post_id):
    """A page or a post by its ID, drafts included (context=edit)."""
    for kind in KINDS:
        d = _get(f'{kind}/{int(post_id)}', context='edit',
                 _fields='id,title,status,type,link,modified_gmt,author')
        if d:
            return {'id': d['id'], 'kind': kind, 'type': d.get('type', kind),
                    'title': _text(d.get('title')), 'status': d.get('status', ''),
                    'link': d.get('link', ''), 'modified_gmt': d.get('modified_gmt', ''),
                    'author': d.get('author')}
    return None


def objects():
    """All pages and posts, drafts included, as [{id, kind, title, link, modified_gmt}].

    A code snippet on the site hides the parts of a series from post lists,
    so the posts of every series are asked for as well and merged by id.
    """
    felder = 'id,title,link,modified_gmt'
    found = {}
    for kind in KINDS:
        for d in get_all(kind, status=LIST_STATUS, _fields=felder):
            found[d['id']] = (kind, d)
    for serie in get_all('series', _fields='id'):
        for d in get_all('posts', series=serie['id'], status=LIST_STATUS, _fields=felder):
            found.setdefault(d['id'], ('posts', d))
    return [{'id': i, 'kind': kind, 'title': _text(d.get('title')), 'link': d.get('link', ''),
             'modified_gmt': d.get('modified_gmt') or ''} for i, (kind, d) in found.items()]


def revisions(kind, post_id, limit=None):
    """Revisions of a page or post, newest first, autosaves left out.
    limit=None: all of them; a number: only the newest (the check page)."""
    felder = 'id,author,date_gmt,modified_gmt,slug,title,content'
    if limit:
        daten = _get(f'{kind}/{int(post_id)}/revisions', context='edit',
                     per_page=min(int(limit), 100), _fields=felder) or []
    else:
        daten = get_all(f'{kind}/{int(post_id)}/revisions', _fields=felder)
    raus = []
    for r in daten:
        if 'autosave' in str(r.get('slug', '')):
            continue
        raus.append({'id': r['id'], 'author_id': r.get('author'),
                     'modified_gmt': r.get('modified_gmt') or r.get('date_gmt') or '',
                     'title': _text(r.get('title')), 'content': _text(r.get('content'))})
    return raus


def media():
    """All uploads as [{id, author_id, date_gmt, title, url}]."""
    return [{'id': m['id'], 'author_id': m.get('author'), 'date_gmt': m.get('date_gmt') or '',
             'title': _text(m.get('title')), 'url': m.get('source_url') or ''}
            for m in get_all('media', _fields='id,author,date_gmt,source_url,title')]


_namen = {}


def author_name(user_id):
    """Display name of a WordPress user; "#id" when WordPress does not say.
    Only for the check page - the log maps ids in its own table."""
    if not user_id:
        return ''
    if user_id not in _namen:
        try:
            d = _get(f'users/{int(user_id)}', context='edit', _fields='id,name')
            _namen[user_id] = (d or {}).get('name') or f'#{user_id}'
        except WordPressError:
            _namen[user_id] = f'#{user_id}'
    return _namen[user_id]
