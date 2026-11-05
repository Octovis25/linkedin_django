"""Posts of the company page for the post timeline under Statistics → Timeline.

Source: the LinkedIn CSV exports (linkedin_posts, linkedin_posts_metrics) -
one row per post and export day. That gives each post a course since the
first import (17.02.2026), with clicks, which Buffer does not have.

Two rules about the numbers:
  * Totals never go down. An export that covers a shorter period shows less
    for older posts (20.10.2026: 118 → 48 impressions); such a dip is not a
    real loss, so every count is carried as the highest value so far.
  * Rates are computed from those totals: engagement rate =
    (reactions + comments + shares) / impressions, CTR = clicks / impressions,
    both in percent - the same formula as the rest of Statistics.
"""
from datetime import date, datetime

from django.db import connection
from django.urls import reverse

COUNTS = ['impressions', 'clicks', 'reactions', 'comments', 'shares', 'views']


def _rates(d):
    imp = d.get('impressions') or 0
    if imp:
        d['engagementRate'] = round(((d.get('reactions') or 0) + (d.get('comments') or 0) + (d.get('shares') or 0)) / imp * 100, 2)
        d['ctr'] = round((d.get('clicks') or 0) / imp * 100, 2)
    return d


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    return v


def posts_and_timelines():
    """(posts, timelines) in the shape _post_timeline.html expects."""
    with connection.cursor() as c:
        try:
            c.execute("""
                SELECT lp.post_id, COALESCE(lp.post_title, ''), COALESCE(pp.post_date, lp.post_date),
                       lp.post_url, lp.content_type,
                       (pp.post_image IS NOT NULL AND pp.post_image <> '')
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON pp.post_id = lp.post_id
            """)
            head = c.fetchall()
            c.execute("""SELECT post_id, metric_date, impressions, clicks, likes, comments, direct_shares, views
                         FROM linkedin_posts_metrics ORDER BY post_id, metric_date""")
            rows = c.fetchall()
        except Exception:
            return [], {}
    posted = {}
    for pid, title, pdate, url, ctype, has_img in head:
        pdate = _as_date(pdate)
        if not pdate:
            continue
        posted[pid] = {'date': pdate, 'title': title or '', 'url': url or '', 'video': (ctype or '').lower() == 'video',
                       'img': reverse('linkedin_statistics:post_image', args=[pid]) if has_img else ''}

    timelines, latest = {}, {}
    for pid, mdate, imp, clk, rea, com, sha, vws in rows:
        if pid not in posted:
            continue
        mdate = _as_date(mdate)
        day = (mdate - posted[pid]['date']).days
        if day < 0:
            continue
        prev = latest.get(pid, {})
        d = {'date': mdate.isoformat(), 'day': day}
        for k, val in zip(COUNTS, (imp, clk, rea, com, sha, vws)):
            if val is None and k == 'views':
                continue
            d[k] = max(int(val or 0), prev.get(k) or 0)
        timelines.setdefault(pid, []).append(_rates(d))
        latest[pid] = d

    posts = []
    for pid, p in posted.items():
        m = {k: v for k, v in latest.get(pid, {}).items() if k not in ('date', 'day')}
        title = p['title'].replace('\n', ' ').strip()
        posts.append({'id': pid, 'date': p['date'].isoformat(),
                      'title': (title[:110] + '…') if len(title) > 110 else title,
                      'full': p['title'][:1500], 'img': p['img'], 'link': p['url'], 'video': p['video'],
                      'days': len(timelines.get(pid, [])), 'm': m})
    posts.sort(key=lambda p: p['date'], reverse=True)
    return posts, timelines


CFG = {
    'chips': [['impressions', 'Impressions'], ['clicks', 'Clicks'], ['reactions', 'Reactions'], ['views', 'Video views']],
    'cols': [['clicks', 'Clicks'], ['ctr', 'CTR', 'pct'], ['reactions', 'Reactions'], ['comments', 'Comments'],
             ['engagementRate', 'Eng. rate', 'pct']],
    'detail': [['shares', 'Shares'], ['views', 'Video views', 'vid']],
    'mini': [['impressions', 'Impressions', '#008591', 'y', 'line'], ['views', 'Video views', '#185FA5', 'y', 'line'],
             ['clicks', 'Clicks', '#0F6E56', 'y1', 'bar'], ['reactions', 'Reactions', '#EB6E08', 'y1', 'bar'],
             ['comments', 'Comments', '#6B21A8', 'y1', 'bar'], ['shares', 'Shares', '#5C6BC0', 'y1', 'bar'],
             ['engagementRate', 'Eng. rate %', '#212529', 'y2', 'line'], ['ctr', 'CTR %', '#A61B1B', 'y2', 'line']],
    'rates': ['engagementRate', 'ctr'],
    'maxGap': 14,
    'note': ('One line per post selected in the table below; with “+ Eng. rate %” its engagement rate is drawn '
             'dashed in the same colour (right axis). X = the first 3, 7 or 30 days after posting (buttons above). <b>Cumulative</b> = '
             'total up to that day, <b>Daily</b> = what came in on that day. The numbers come from the LinkedIn '
             'exports under Data – one point per export since 17.02.2026; exports more than 14 days apart are not '
             'joined. Totals never go down: an export over a shorter period that shows less is ignored.'),
}
