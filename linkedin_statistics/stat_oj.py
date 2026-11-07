"""Statistics → OJ: Ortrud's personal LinkedIn profile.

Two sources side by side:
  * Buffer (automatic, daily): numbers per post and their course over the
    first ~30 days - see buffer_metrics.py.
  * LinkedIn's profile export (uploaded by hand about once a month):
    followers, the whole profile per month, top posts, demographics -
    see oj_export.py.

Only for superusers: it is one person's own profile ("da muss nur ich drauf").
"""
from datetime import date, timedelta

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
            # LinkedIn's words: Erreichte Mitglieder = reach, Aufrufe = video views,
            # Zuschauer = unique viewers (Ortrud, 06.11.2026: more columns).
            'cols': [['reach', 'Reach'], ['views', 'Video views'], ['viewers', 'Viewers'],
                     ['reactions', 'Reactions'], ['comments', 'Comments'], ['engagementRate', 'Eng. rate', 'pct']],
            'detail': [['shares', 'Shares'], ['totalTimeWatched', 'Watch time', 'vid', 'min']],
            'mini': [['impressions', 'Impressions', '#008591', 'y', 'line'], ['reach', 'Reach', '#20B8B0', 'y', 'line'],
                     ['views', 'Video views', '#185FA5', 'y', 'line'], ['reactions', 'Reactions', '#EB6E08', 'y1', 'bar'],
                     ['comments', 'Comments', '#6B21A8', 'y1', 'bar'], ['shares', 'Shares', '#5C6BC0', 'y1', 'bar'],
                     ['engagementRate', 'Eng. rate %', '#212529', 'y2', 'line']],
            'rates': ['engagementRate'],
            'maxGap': 3,
            'note': ('One line per post selected in the table below; with “+ Eng. rate %” its engagement rate is '
                     'drawn dashed in the same colour (right axis). X = the first 3, 7 or 30 days after posting (buttons above), counted '
                     'to the hour when Buffer got the numbers from LinkedIn (Buffer refreshes them about once a day; '
                     'the app asks every hour and keeps each refresh). '
                     '<b>Cumulative</b> = total up to that day, <b>Daily</b> = what came in on that day, <b>Per hour</b> = what came in between two measurements, per hour (a step from one measurement to the next – Buffer measures about twice a day). Buffer keeps '
                     'no history – the course of a post starts with the first daily fetch (01.11.2026; a few posts '
                     'also have three days from a test in June). In Cumulative the line starts at 0 on the day of '
                     'posting and is dashed up to the first fetch – that stretch is estimated. Posts without numbers '
                     'in the chosen days are greyed out on the right. Click a post on the right to hide or show it.'),
            'fetchUrl': reverse('linkedin_statistics:oj_fetch'),
            'csrf': get_token(request),
        },
    }
    # Months overview at the top (Ortrud, 06.11.2026: "diese Grafik zuerst") -
    # the same finding as on OJ analysis.
    months = None
    if meta:
        try:
            from . import oj_analysis as analysis
            found = analysis.analyse(posts, bm.posts_with_latest(buf['org_channel']), data['daily'],
                                     meta['followers_total'], contacts=data['contacts'])
            months = next((f for f in found['findings'] if f['key'] == 'months'), None)
            if months:
                months['chart'] = current_month_from_buffer(months['chart'], channel)
        except Exception:
            months = None
    return render(request, 'linkedin_statistics/stat_oj.html', {
        'data': data,
        'months': months,
        'channel_ok': bool(channel),
        'key_ok': bool(buf['token']),
        'last_fetch': bm.last_fetch_at(),
        'export': meta,
        'upload_msg': request.GET.get('upload'),
        'upload_n': request.GET.get('n'),
        'upload_err': request.session.pop('oj_upload_error', None),
        'fetch_msg': request.session.pop('oj_fetch_msg', None),
        'fetching': fetching,
        'tick_url': request.build_absolute_uri(reverse('linkedin_statistics:oj_tick')),
    })


def current_month_from_buffer(chart, channel, today=None):
    """The month the LinkedIn export does not cover yet: its impressions so
    far from Buffer (what the posts gained this month), marked 'partial';
    new followers are unknown there (null, the line stops). Ortrud,
    06.11.2026: "im aktuellen Monat das nehmen, was schon da ist"."""
    from datetime import date as _date
    today = today or bm.today_berlin()
    first = today.replace(day=1)
    key = first.strftime('%Y-%m')
    months = [dict(m) for m in chart.get('months', [])]
    entry = next((m for m in months if m['month'] == key), None)
    if entry and entry.get('days', 0) >= today.day:
        return chart                      # the export covers the month so far
    gain = bm.month_gain(channel, first)
    if not gain and not entry:
        return chart
    if not entry:
        entry = {'month': key, 'impressions': 0, 'followers': None, 'posts': 0, 'days': 0}
        months.append(entry)
    entry['impressions'] = (entry.get('impressions') or 0) + gain
    entry['followers'] = None             # the export has a day or two at most: no line there
    entry['partial'] = True
    if not entry.get('posts'):
        entry['posts'] = sum(1 for p in bm.posts_with_latest(channel) if p['date'] and p['date'] >= first)
    return {**chart, 'months': months}


@superuser_required
def oj_analysis(request):
    """The posting-time heatmap under a timeline of the chosen period
    (07.11.2026: the six findings are gone, "nur noch die Heatmap" and
    "Zeiträume auswählen wie bei der Webanalyse")."""
    from . import posting_times
    von, bis, hinweis = _period(request.GET)
    buf = bm.superuser_buffer()
    inside = lambda posts: [p for p in posts if p['date'] and von <= p['date'] <= bis]
    company = inside(bm.posts_with_latest(buf['org_channel']))
    person = inside(bm.posts_with_latest(buf['person_channel']))
    meta = oj_export.meta()
    daily = [d for d in oj_export.daily() if von.isoformat() <= d[0] <= bis.isoformat()]
    imp = lambda p: int(round(float((p.get('m') or {}).get('impressions') or 0)))
    timeline = {
        'von': von.isoformat(), 'bis': bis.isoformat(),
        'company': [{'date': p['date'].isoformat(), 'imp': imp(p), 'title': p['title'][:90]} for p in company],
        'oj': [{'date': p['date'].isoformat(), 'imp': imp(p), 'title': p['title'][:90]} for p in person],
        'profile': [[d[0], d[1]] for d in daily],          # the whole profile per day, LinkedIn export
    }
    today = bm.today_berlin()
    quick = [(label, (today - timedelta(days=days - 1)).isoformat()) for label, days in
             (('3 months', 91), ('6 months', 182), ('12 months', 365))]
    return render(request, 'linkedin_statistics/stat_oj_analysis.html', {
        'von': von.isoformat(), 'bis': bis.isoformat(), 'hinweis': hinweis, 'heute': today.isoformat(),
        'quick': quick, 'since': OLDEST_SHOWN.isoformat(),
        'timeline': timeline, 'n_company': len(company), 'n_oj': len(person),
        'first_days': {'company': first_days(company, buf['org_channel']),
                       'oj': first_days(person, buf['person_channel'])},
        'export': meta, 'last_fetch': bm.last_fetch_at(),
        'heatmaps': {'company': posting_times.heatmap(company), 'oj': posting_times.heatmap(person)},
    })


FIRST_HOURS = 120


def first_days(posts, channel):
    """The first five days of every post, to compare them hour by hour
    (07.11.2026: "damit ich die Posts über die ersten 5 Tage vergleichen
    kann"). [[hours after posting, impressions so far], ...] at the moments
    Buffer had new numbers; 'young' while the five days are not over. One
    point past the five days is kept, so the value at 120 h can be read
    between two measurements."""
    if not posts:
        return []
    from datetime import datetime as _dt
    tl = bm.channel_timelines(channel)
    now = _dt.utcnow()
    out = []
    for p in posts:
        pts = [[round(d['day'] * 24, 1), int(round(float(d['impressions'])))] for d in tl.get(p['id'], [])
               if d.get('impressions') is not None and d['day'] * 24 <= FIRST_HOURS + 36]
        if not pts:
            continue
        sent = bm._ts(p['sent_at'])
        out.append({'id': p['id'], 'date': p['date'].isoformat(), 'title': p['title'][:70], 'pts': pts,
                    'young': bool(sent) and (now - sent).total_seconds() < FIRST_HOURS * 3600})
    return sorted(out, key=lambda x: x['date'], reverse=True)


OLDEST_SHOWN = date(2023, 1, 1)           # posts before 2023 never show


def _period(get):
    """From/to out of ?von=&bis= (like Web Analytics); 12 months by default."""
    today = bm.today_berlin()
    hinweis = ''
    try:
        bis = date.fromisoformat(get.get('bis') or '') if get.get('bis') else today
        von = date.fromisoformat(get.get('von') or '') if get.get('von') else bis - timedelta(days=364)
    except ValueError:
        bis, von, hinweis = today, today - timedelta(days=364), 'That date could not be read – showing the last 12 months.'
    if von > bis:
        von, bis = bis, von
    if von < OLDEST_SHOWN:
        von = OLDEST_SHOWN
    if bis > today:
        bis = today
    return von, bis, hinweis


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

    No login and no key (07.11.2026): all it can do is start a fetch, at most
    one per hour, and it hands out nothing. With a key it answered 403 to
    Make's saved address, and Make switches a scenario off after a 403 - the
    hourly fetch had stopped on 05.11. after its first scheduled run.
    Every call is noted, so the page can tell when Make stopped calling.
    """
    bm.note_tick()
    return JsonResponse({'ok': True, 'started': bool(bm.fetch_hourly())})
