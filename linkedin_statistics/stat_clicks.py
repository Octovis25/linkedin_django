"""Statistics → Clicks: is a post clicked because it reached more people, or
because its content did unusually well for that reach?

The numbers come from ``clicks_model.analyse`` (count models), the topics from
``clicks_topics``. Mockup and decisions: ``claude/klick-analyse-2026-10-03.md``
in the project notes, ``Claude outputs/klicks_statistik_mockup_v4.html``.
"""
import datetime
import json

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from . import clicks_model, clicks_topics
from .post_text import TITEL

SQL = """
    SELECT lp.post_id, """ + TITEL + """ AS titel,
           COALESCE(pp.post_date, lp.post_date) AS datum,
           lp.post_url, COALESCE(lp.content_type, '') AS art,
           COALESCE(m.impressions, 0) AS imp, COALESCE(m.clicks, 0) AS klicks,
           COALESCE(pp.category, '') AS kategorie
    FROM linkedin_posts lp
    LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
    LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
        AND m.metric_date = (
            SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
            WHERE m2.post_id = m.post_id)
    ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
"""


def _as_date(d):
    if isinstance(d, datetime.datetime):
        return d.date()
    if isinstance(d, datetime.date):
        return d
    try:
        return datetime.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def _full_texts():
    """post_id -> Buffer text. Posts from before Buffer (mid 2025) have none;
    for them only the LinkedIn title is known."""
    from .post_text import posts_mit_text
    try:
        return {str(z['post_id']): z['text'] or '' for z in posts_mit_text(alle_fassungen=True)}
    except Exception as e:      # the page still works on titles alone
        print("Clicks: no post texts:", e)
        return {}


def _planner_formats(raw):
    """post_id -> 'short' | 'company' from the Planner field post_type.

    There is no key between planner_posts and linkedin_posts; like everywhere
    else the text decides (first 45 characters without white space, see
    post_text.py). Only unambiguous matches count."""
    from .post_text import _inhalts_schluessel
    try:
        with connection.cursor() as c:
            c.execute("SELECT content, post_type FROM planner_posts "
                      "WHERE post_type IN ('short', 'company') AND content IS NOT NULL")
            planner = c.fetchall()
    except Exception as e:          # older database without the column
        print("Clicks: no planner post types:", e)
        return {}
    by_key = {}
    for content, typ in planner:
        k = _inhalts_schluessel(content)
        if k:
            by_key.setdefault(k, set()).add(typ)
    out = {}
    for r in raw:
        k = _inhalts_schluessel(r['titel'])
        typen = by_key.get(k) if k else None
        if typen and len(typen) == 1:
            out[str(r['post_id'])] = next(iter(typen))
    return out


def load_posts():
    with connection.cursor() as c:
        c.execute(SQL)
        cols = [s[0] for s in c.description]
        raw = [dict(zip(cols, r)) for r in c.fetchall()]
    texts = _full_texts()
    manual, manual_formats = clicks_topics.manual_choices()
    planner = _planner_formats(raw)
    posts = []
    for r in raw:
        d = _as_date(r['datum'])
        if d is None:
            continue
        pid = str(r['post_id'])
        title = (r['titel'] or '').strip()
        text = texts.get(pid, '')
        topic, source = clicks_topics.resolve(pid, text or title, title, r['kategorie'], manual)
        fmt, fmt_source = clicks_topics.resolve_format(pid, manual_formats, planner)
        posts.append({
            'id': pid, 'date': d, 'title': title, 'url': r['post_url'] or '',
            'video': (r['art'] or '').lower() == 'video',
            'imp': int(r['imp'] or 0), 'clicks': int(r['klicks'] or 0),
            'topic': topic, 'source': source, 'format': fmt, 'format_source': fmt_source,
            'hook': clicks_topics.hook_type(title),
            'length': len(text) if text else None,
        })
    return posts


def _verdict_topic(res):
    p = res['topic']['p']
    if p is None:
        return 'too few topics to compare.'
    gain = round((res['explained']['topic'] - res['explained']['video']) * 100)
    better = res['aic']['topic'] is not None and res['aic']['topic'] < res['aic']['video']
    params = res['topic']['df']
    if p < 0.05 and better:
        return (f"<b>Yes.</b> Topic adds {gain} points and the model gets better "
                f"(p = {p:.2f}, AIC goes down). Some content areas do systematically better or worse than their reach.")
    if p < 0.15:
        return (f"<b>Possibly.</b> Topic adds {gain} points (p = {p:.2f}). A hint, not yet reliable – "
                f"more posts will tell.")
    return (f"<b>Not clearly.</b> Topic adds {gain} points, but with {params} extra parameters and "
            f"{res['n']} posts that is about what chance gives (p = {p:.2f}"
            f"{', AIC gets worse' if not better else ''}). Reach, date and video carry the explainable part.")


def _format_row(f):
    if not f:
        return ('Short vs. company post', 'not enough posts of both kinds', 'weak', '')
    return ('Short vs. company post', f"short ×{f['factor']:.2f} clicks", clicks_model.evidence(f['p']),
            f"95 % range ×{f['lo']:.1f} – ×{f['hi']:.1f}, p = {f['p']:.2f}; "
            f"{f['n_short']} short posts, unknown type counts as company")


@login_required
def clicks(request):
    posts, events = clicks_topics.split_events(load_posts())
    keys = [k for k in clicks_topics.TOPIC_KEYS if k != clicks_topics.EVENTS]
    res = clicks_model.analyse(posts, keys)
    rows = []
    if res:
        for p, e in zip(res['posts'], res['expected']):
            p['expected'] = round(e, 1)
    for p in posts:
        rows.append([p['date'].strftime('%d.%m.%y'), p['date'].isoformat(), 1 if p['video'] else 0,
                     p['imp'], p['clicks'], p.get('expected'), p['title'][:90], p['topic'],
                     p['source'], p['id'], p['url'], p['format'], p['format_source']])
    ev_rows = [[p['date'].strftime('%d.%m.%y'), p['date'].isoformat(), p['imp'], p['clicks'],
                p['title'][:90], p['source'], p['id'], p['url']] for p in events]
    data = {'rows': rows, 'events': ev_rows,
            'topics': [{'key': k, 'name': n} for k, n in clicks_topics.TOPICS],
            'formats': [{'key': k, 'name': n} for k, n in clicks_topics.FORMATS]}
    ev_imp, ev_cl = sum(p['imp'] for p in events), sum(p['clicks'] for p in events)
    ctx = {'tab': 'clicks', 'res': res, 'n_all': len(posts),
           'events': {'n': len(events), 'imp': ev_imp, 'clicks': ev_cl,
                      'ctr': (100.0 * ev_cl / ev_imp) if ev_imp else None}}
    if res:
        ex = res['explained']
        data['model'] = {
            'scatter': res['scatter'],
            'explained': [['Impressions', ex['imp'], 0],
                          ['+ Posting date', ex['date'], 0],
                          ['+ Video', ex['video'], 0],
                          ['+ Topic', ex['video'], max(0.0, ex['topic'] - ex['video'])]],
            'topic_clear': res['topic']['p'] is not None and res['topic']['p'] < 0.05,
            'per_topic': [dict(t, name=clicks_topics.TOPIC_NAMES[t['key']]) for t in res['topic']['per_topic']],
        }
        length = res['length']
        ctx.update({
            'verdict_topic': _verdict_topic(res),
            'explained_imp': round(ex['imp'] * 100),
            'r2': res['scatter']['r2'],
            'double': res['scatter']['double'],
            'factors': [
                ('Posting date', f"{(res['date']['per_month'] - 1) * 100:+.0f} % per month",
                 clicks_model.evidence(res['date']['p']),
                 f"p = {res['date']['p']:.3f}; partly older posts collecting clicks for longer"),
                ('Video', f"×{res['video']['factor']:.2f} clicks", clicks_model.evidence(res['video']['p']),
                 f"95 % range ×{res['video']['lo']:.1f} – ×{res['video']['hi']:.1f}, p = {res['video']['p']:.3f}, "
                 f"{res['video']['n']} videos"),
                _format_row(res['format']),
                ('Topic', f"+{max(0, round((ex['topic'] - ex['video']) * 100))} points explained",
                 clicks_model.evidence(res['topic']['p']),
                 f"p = {res['topic']['p']:.2f} for all {res['topic']['groups']} topics together"
                 if res['topic']['p'] is not None else 'too few topics'),
                ('Post length', 'no clear effect' if not length or length['p'] >= 0.05 else 'see detail',
                 clicks_model.evidence(length['p'] if length else None),
                 f"p = {length['p']:.2f} ({length['n']} posts with full text)" if length else 'too few posts with full text'),
                ('Hook type', 'no clear effect' if (res['hook']['p'] or 1) >= 0.05 else 'see detail',
                 clicks_model.evidence(res['hook']['p']),
                 'question / number / “We…” / statement' + (f", p = {res['hook']['p']:.2f}" if res['hook']['p'] is not None else '')),
            ],
            'tests': [
                ('+ Video vs. impressions + date', res['video']['p'], res['aic']['date'], res['aic']['video']),
                (f"+ Topic ({res['topic']['groups']} groups) vs. + video", res['topic']['p'],
                 res['aic']['video'], res['aic']['topic']),
            ],
        })
    ctx['data'] = data
    return render(request, 'linkedin_statistics/stat_clicks.html', ctx)


@login_required
@require_POST
def clicks_topic(request):
    """Set (or clear) the topic or the format (short/company) of one post
    from the Clicks table: {post_id, topic} or {post_id, format}."""
    try:
        body = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    pid = str(body.get('post_id') or '').strip()
    if not pid or len(pid) > 64:
        return JsonResponse({'error': 'post_id missing'}, status=400)
    if 'format' in body:
        fmt = (body.get('format') or '').strip()
        if fmt and fmt not in clicks_topics.FORMAT_NAMES:
            return JsonResponse({'error': 'Unknown format'}, status=400)
    else:
        topic = (body.get('topic') or '').strip()
        if topic and topic not in clicks_topics.TOPIC_NAMES:
            return JsonResponse({'error': 'Unknown topic'}, status=400)
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM linkedin_posts WHERE post_id = %s", [pid])
        if not c.fetchone()[0]:
            return JsonResponse({'error': 'Unknown post'}, status=404)
    if 'format' in body:
        clicks_topics.set_format(pid, fmt)
        return JsonResponse({'ok': True, 'format': fmt})
    clicks_topics.set_topic(pid, topic)
    return JsonResponse({'ok': True, 'topic': topic})
