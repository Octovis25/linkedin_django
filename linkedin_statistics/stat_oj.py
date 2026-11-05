"""Statistics → OJ: Ortrud's personal LinkedIn profile.

Two sources side by side:
  * Buffer (automatic, daily): numbers per post and their course over the
    first ~30 days - see buffer_metrics.py.
  * LinkedIn's profile export (uploaded by hand about once a month):
    followers, the whole profile per month, top posts, demographics -
    see oj_export.py.

Only for superusers: it is one person's own profile ("da muss nur ich drauf").
"""
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import buffer_metrics as bm
from . import oj_contacts, oj_export

superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser)



def _post_json(p):
    return {'id': p['id'], 'date': p['date'].isoformat() if p['date'] else '', 'title': p['title'],
            'full': p['text'][:1500], 'img': p.get('thumb') or '', 'img2': p.get('thumb2') or '', 'days': p['days'],
            'm': {k: v for k, v in p['m'].items() if v is not None}}


@superuser_required
def oj(request):
    buf = bm.superuser_buffer()
    channel = buf['person_channel']
    # Today's numbers are fetched in the background when they are missing
    # (there is no cron job). They show after a reload.
    fetching = False
    if buf['token']:
        try:
            from posts_posted.buffer_sync import snapshot_missing_today, sync_for_today_in_background
            fetching = snapshot_missing_today() and sync_for_today_in_background()
        except Exception:
            fetching = False
        try:
            bm.fetch_hourly()             # the hour's numbers, if nobody fetched them yet
        except Exception:
            pass
    posts = bm.posts_with_latest(channel)
    timelines = bm.channel_timelines(channel)
    meta = oj_export.meta()
    export = oj_export.summary() if meta else None
    data = {
        'today': bm.today_berlin().isoformat(),
        'posts': [_post_json(p) for p in posts],
        'timelines': timelines,
        'daily': oj_export.daily(),
        'followers_total': meta['followers_total'] if meta else None,
        'followers_date': meta['followers_date'].isoformat() if meta and meta['followers_date'] else None,
        'demo': export['demo'] if export else {},
        'demo_categories': export['demo_categories'] if export else [],
        'contacts': oj_contacts.listing(),
        'cfg': {
            'chips': [['impressions', 'Impressions'], ['reach', 'Reach'], ['reactions', 'Reactions'], ['views', 'Video views']],
            'cols': [['reactions', 'Reactions'], ['comments', 'Comments'], ['engagementRate', 'Eng. rate', 'pct']],
            'detail': [['reach', 'Reach'], ['shares', 'Shares'], ['views', 'Video views', 'vid'],
                       ['viewers', 'Unique viewers', 'vid'], ['totalTimeWatched', 'Watch time', 'vid', 'min']],
            'mini': [['impressions', 'Impressions', '#008591', 'y', 'line'], ['reach', 'Reach', '#20B8B0', 'y', 'line'],
                     ['views', 'Video views', '#185FA5', 'y', 'line'], ['reactions', 'Reactions', '#EB6E08', 'y1', 'bar'],
                     ['comments', 'Comments', '#6B21A8', 'y1', 'bar'], ['shares', 'Shares', '#5C6BC0', 'y1', 'bar'],
                     ['engagementRate', 'Eng. rate %', '#212529', 'y2', 'line']],
            'rates': ['engagementRate'],
            'maxGap': 3,
            'note': ('One line per post selected in the table below; with “+ Eng. rate %” its engagement rate is '
                     'drawn dashed in the same colour (right axis). X = the first 30 days after posting, counted '
                     'to the hour when Buffer got the numbers from LinkedIn (Buffer refreshes them about once a day; '
                     'the app asks every hour and keeps each refresh). '
                     '<b>Cumulative</b> = total up to that day, <b>Daily</b> = what came in on that day. Buffer keeps '
                     'no history – the course of a post starts with the first daily fetch (01.11.2026; a few posts '
                     'also have three days from a test in June). In Cumulative the line starts at 0 on the day of '
                     'posting and is dashed up to the first fetch – that stretch is estimated. Posts without numbers '
                     'in their first 30 days are greyed out on the right. Click a post on the right to hide or show it.'),
            'fetchUrl': reverse('linkedin_statistics:oj_fetch'),
            'csrf': get_token(request),
        },
    }
    return render(request, 'linkedin_statistics/stat_oj.html', {
        'data': data,
        'channel_ok': bool(channel),
        'key_ok': bool(buf['token']),
        'last_fetch': bm.last_fetch_day(),
        'export': meta,
        'upload_msg': request.GET.get('upload'),
        'upload_n': request.GET.get('n'),
        'upload_err': request.session.pop('oj_upload_error', None),
        'fetch_msg': request.session.pop('oj_fetch_msg', None),
        'fetching': fetching,
        'tick_url': request.build_absolute_uri(reverse('linkedin_statistics:oj_tick')) + '?key=' + bm.tick_key(),
    })


@superuser_required
def oj_analysis(request):
    from . import oj_analysis as analysis
    buf = bm.superuser_buffer()
    meta = oj_export.meta()
    result = analysis.analyse(bm.posts_with_latest(buf['person_channel']),
                              bm.posts_with_latest(buf['org_channel']),
                              oj_export.daily(), meta['followers_total'] if meta else None,
                              contacts=oj_contacts.listing())
    return render(request, 'linkedin_statistics/stat_oj_analysis.html', {
        'result': result, 'charts': {f['key']: f.get('chart') for f in result['findings']},
        'export': meta, 'last_fetch': bm.last_fetch_day(),
    })


@superuser_required
def oj_post(request, buffer_post_id):
    """Day-by-day course of one post (JSON for the expandable row)."""
    return JsonResponse({'days': bm.post_timeline(buffer_post_id),
                         'labels': dict(bm.METRICS)})


@superuser_required
@require_POST
def oj_upload(request):
    """One upload box for both LinkedIn files: the analytics export (.xlsx)
    and the data archive (.zip) or its Connections.csv."""
    f = request.FILES.get('export')
    if not f:
        request.session['oj_upload_error'] = 'Please choose the .xlsx (analytics) or the .zip (data archive) LinkedIn gave you.'
        return redirect('linkedin_statistics:oj')
    name = f.name.lower()
    if name.endswith(('.zip', '.csv')):
        if f.size > 200 * 1024 * 1024:
            request.session['oj_upload_error'] = 'The archive is larger than 200 MB – upload only Connections.csv from it.'
            return redirect('linkedin_statistics:oj')
        try:
            rows = oj_contacts.read_connections(f, f.name)
            oj_contacts.store(rows)
        except oj_contacts.ContactsError as e:
            request.session['oj_upload_error'] = str(e)
            return redirect('linkedin_statistics:oj')
        return redirect(f"{_url()}?upload=contacts&n={len(rows)}")
    if f.size > 10 * 1024 * 1024:
        request.session['oj_upload_error'] = 'The file is larger than 10 MB - that is not a LinkedIn export.'
        return redirect('linkedin_statistics:oj')
    try:
        data = oj_export.parse_workbook(f)
        oj_export.store(data, f.name)
    except oj_export.ExportError as e:
        request.session['oj_upload_error'] = str(e)
        return redirect('linkedin_statistics:oj')
    return redirect(f"{_url()}?upload=ok")


@superuser_required
@require_POST
def oj_fetch(request):
    """Fetch today's Buffer numbers now."""
    buf = bm.superuser_buffer()
    if not buf['token']:
        request.session['oj_fetch_msg'] = 'No Buffer key saved under API Connect.'
        return redirect('linkedin_statistics:oj')
    try:
        n_posts, _ = bm.fetch_and_store(buf['token'])
        request.session['oj_fetch_msg'] = f'Fetched: numbers for {n_posts} posts (both channels).'
    except Exception as e:
        # The message of _buffer_graphql never contains the key.
        request.session['oj_fetch_msg'] = f'Buffer did not answer as expected: {str(e)[:300]}'
    return redirect('linkedin_statistics:oj')


def _url():
    from django.urls import reverse
    return reverse('linkedin_statistics:oj')


def oj_tick(request):
    """For a scheduler, once an hour: fetch Buffer's numbers (05.11.2026).

    No login - the key in the address is the permission, and all it can do
    is start a fetch, at most one per hour. Wrong key: 403.
    """
    import hmac
    if not hmac.compare_digest(request.GET.get('key', ''), bm.tick_key()):
        return JsonResponse({'error': 'forbidden'}, status=403)
    return JsonResponse({'ok': True, 'started': bool(bm.fetch_hourly())})
