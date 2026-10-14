"""The audit trail page - who changed what, and when. Owner only."""
from datetime import datetime, timedelta, timezone

from django.http import Http404
from django.shortcuts import render

from . import store
from .access import may_view
from planner.zeit import BERLIN, berlin_fmt

RANGES = {'1': 1, '7': 7, '30': 30, '90': 90, '365': 365}


def _utc(day):
    """Midnight of a Berlin day, as naive UTC."""
    local = datetime(day.year, day.month, day.day, tzinfo=BERLIN)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def describe(row):
    """A short line for the 'What' column."""
    if row['view'].startswith('auth:'):
        return {'login': 'Signed in', 'logout': 'Signed out',
                'login failed': 'Sign-in failed'}.get(row['action'], row['action'])
    view = row['view'] or row['path']
    area, _, name = view.partition(':')
    if not name:
        parts = view.split('.')
        area, name = (parts[0], parts[-1]) if len(parts) > 1 else ('', view)
    text = '%s · %s' % (area, name.replace('_', ' ')) if area else name.replace('_', ' ')
    if row['action']:
        text += ' · ' + row['action']
    return text


def trail(request):
    if not may_view(request.user):
        raise Http404            # the page does not exist for anybody else
    days = request.GET.get('days', '7')
    if days not in RANGES:
        days = '7'
    user = request.GET.get('user', '').strip()
    text = request.GET.get('q', '').strip()[:100]
    obj = request.GET.get('object', '').strip().lstrip('#')[:64]

    today = datetime.now(BERLIN).date()
    since = _utc(today - timedelta(days=RANGES[days] - 1))
    until = _utc(today + timedelta(days=1))

    rows = store.read(since, until, username=user, text=text, object_id=obj)
    for r in rows:
        r['when'] = berlin_fmt(r['at'])
        r['until'] = berlin_fmt(r['last_at']) if r['times'] > 1 else ''
        r['what'] = describe(r)
        r['ok'] = 200 <= (r['status'] or 0) < 400
        r['extra'] = ', '.join('%s: %s' % (k, v) for k, v in r['details'].items()
                               if k not in ('files', 'url', 'action'))
        r['files'] = r['details'].get('files') or []
    people = store.summary(since, until)
    for p in people:
        p['first'] = berlin_fmt(p['first'])
        p['last'] = berlin_fmt(p['last'])
    return render(request, 'audit/trail.html', {
        'rows': rows, 'people': people, 'users': store.usernames(),
        'days': days, 'ranges': [('1', 'Today'), ('7', '7 days'), ('30', '30 days'),
                                 ('90', '90 days'), ('365', '1 year')],
        'user': user, 'q': text, 'object': obj, 'limit_hit': len(rows) >= 300,
    })
