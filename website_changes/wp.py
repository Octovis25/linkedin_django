"""Read access to octotrial.com through the WordPress REST API.

The same way the app already reads Matomo and the list of pages: HTTP with
the WordPress application password in MATOMO_TOKEN ("user:app-password").
No database, nothing at Host Europe (Ortrud, 08.10.2026).

Revisions need a user who may edit the page. Without that right WordPress
answers 401/403 - wp_error() turns that into a sentence.
"""
import requests
from django.conf import settings

from matomo.client import MatomoError, _basis, _zugang

KINDS = ('pages', 'posts')        # WordPress pages and blog posts ("Insights")


class WordPressError(RuntimeError):
    pass


def _get(route, **params):
    try:
        auth = _zugang()
    except MatomoError as fehler:
        raise WordPressError(str(fehler))
    try:
        antwort = requests.get(
            f"{_basis()}/wp-json/wp/v2/{route}", params=params, auth=auth,
            timeout=getattr(settings, 'MATOMO_TIMEOUT', 30),
            headers={'User-Agent': 'octovis-website-changes'})
    except requests.RequestException as fehler:
        raise WordPressError(f'WordPress not reachable: {fehler}')
    if antwort.status_code == 401:
        raise WordPressError('WordPress did not accept the sign-in (401): check the '
                             'application password in MATOMO_TOKEN.')
    if antwort.status_code == 403:
        raise WordPressError('WordPress refused (403): the user of the application password '
                             'may not edit this page, so it cannot read its revisions.')
    if antwort.status_code == 404:
        return None
    if antwort.status_code >= 400:
        raise WordPressError(f'WordPress answered HTTP {antwort.status_code} for {route}')
    try:
        return antwort.json()
    except ValueError:
        raise WordPressError(f'WordPress sent no JSON for {route}')


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


def revisions(kind, post_id, limit=10):
    """The newest revisions, newest first, autosaves left out."""
    daten = _get(f'{kind}/{int(post_id)}/revisions', context='edit', per_page=min(int(limit), 100),
                 _fields='id,author,date_gmt,modified_gmt,slug,title,content') or []
    raus = []
    for r in daten:
        if 'autosave' in str(r.get('slug', '')):
            continue
        raus.append({'id': r['id'], 'author_id': r.get('author'),
                     'modified_gmt': r.get('modified_gmt') or r.get('date_gmt') or '',
                     'title': _text(r.get('title')), 'content': _text(r.get('content'))})
    return raus


_namen = {}


def author_name(user_id):
    """Display name of a WordPress user; "#id" when WordPress does not say."""
    if not user_id:
        return ''
    if user_id not in _namen:
        try:
            d = _get(f'users/{int(user_id)}', context='edit', _fields='id,name')
            _namen[user_id] = (d or {}).get('name') or f'#{user_id}'
        except WordPressError:
            _namen[user_id] = f'#{user_id}'
    return _namen[user_id]
