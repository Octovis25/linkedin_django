"""Website log of octotrial.com (superusers only) and the earlier check page."""
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import inhalt, log, wp

superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser)


def _day(text, default):
    try:
        return date.fromisoformat(text) if text else default
    except ValueError:
        return default


@superuser_required
def index(request):
    heute = datetime.now(log.BERLIN).date()
    day_to = _day(request.GET.get('to'), heute)
    day_from = _day(request.GET.get('from'), day_to - timedelta(days=30))
    if day_from > day_to:
        day_from, day_to = day_to, day_from
    person = request.GET.get('person', '')
    page = request.GET.get('page', '')
    kind = request.GET.get('kind', '')
    rows, total = log.changes(day_from, day_to, person=person, wp_id=page if page.isdigit() else None, kind=kind)
    return render(request, 'website_changes/log.html', {
        'rows': rows, 'total': total, 'day_from': day_from, 'day_to': day_to,
        'person': person, 'page': page, 'kind': kind, 'kinds': log.KIND_FILTERS,
        'people': log.people(), 'pages': log.pages(), 'sync': log.last_sync(),
        'notes': log.notes(), 'authors': log.authors(), 'tab': request.GET.get('tab', 'changes'),
    })


@superuser_required
def detail(request):
    d = log.detail(request.GET.get('key', ''))
    if d is None:
        raise Http404('No such change')
    return JsonResponse({
        'before': d['before'], 'after': d['after'],
        'before_when': d['before_when'].strftime('%d.%m.%Y %H:%M') if d['before_when'] else '',
        'before_who': d['before_who'], 'title_changed': d['title_changed'],
        'title_before': d['title_before'], 'title_after': d['title_after'],
    })


@superuser_required
@require_POST
def sync_now(request):
    res = log.sync()
    (messages.success if res['ok'] else messages.error)(request, res['message'])
    return redirect('website_changes:index')


def _back(request, tab=None):
    ziel = request.POST.get('next') or ''
    if not ziel.startswith('/webstats/changes/'):
        ziel = '/webstats/changes/' + (f'?tab={tab}' if tab else '')
    return redirect(ziel)


@superuser_required
@require_POST
def note(request):
    wp_id = request.POST.get('wp_id') or None
    if wp_id and not str(wp_id).isdigit():
        wp_id = None
    name = request.user.get_full_name() or request.user.get_username()
    if not log.add_note(request.POST.get('text'), name, wp_id=wp_id, key=request.POST.get('key')):
        messages.error(request, 'The note is empty.')
    return _back(request, 'notes')


@superuser_required
@require_POST
def author(request):
    try:
        uid = int(request.POST.get('wp_user_id'))
    except (TypeError, ValueError):
        messages.error(request, 'WordPress user id must be a number.')
        return _back(request, 'notes')
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, 'Name is missing.')
        return _back(request, 'notes')
    log.save_author(uid, name, request.POST.get('person'), request.POST.get('with_claude') == '1')
    return _back(request, 'notes')


@superuser_required
def check(request):
    """Does WordPress hand out the revisions of a page? (08.10.2026)"""
    try:
        post_id = int(request.GET.get('post') or 1260)
    except ValueError:
        post_id = 1260
    daten = {'post_id': post_id}
    try:
        seite = wp.page(post_id)
        daten['page'] = seite
        if seite:
            revs = wp.revisions(seite['kind'], post_id, 10)
            for r in revs:
                r['author'] = wp.author_name(r['author_id'])
                r['found'] = inhalt.summary(r['content'])
            daten['revisions'] = revs
    except wp.WordPressError as fehler:
        daten['error'] = str(fehler)
    return render(request, 'website_changes/check.html', daten)
