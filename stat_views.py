"""
linkedin_statistics/stat_views.py
FINAL: Overview + Timeline mit Tagesverlauf pro Post.
MySQL-Queries.
"""
from datetime import date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
import json


def _defaults():
    return (date.today() - timedelta(days=365)).isoformat(), date.today().isoformat()


def _safe(cur, sql, params=None):
    try:
        cur.execute(sql, params or [])
        return cur.fetchall()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# OVERVIEW (unveraendert)
# ══════════════════════════════════════════════════════════════

def _overview_data(d_from, d_to):
    data = {
        'total_followers': 0, 'followers_change': '—',
        'total_posts': 0, 'total_impressions': 0, 'total_engagement': 0,
        'top_posts': [],
        'chart_labels': [], 'chart_impressions': [], 'chart_engagement': [],
    }
    with connection.cursor() as c:

        rows = _safe(c, "SELECT followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 1")
        if rows and rows[0][0]:
            data['total_followers'] = rows[0][0]

        rows = _safe(c, """
            SELECT
              (SELECT followers_total FROM linkedin_followers WHERE date <= %s ORDER BY date DESC LIMIT 1),
              (SELECT followers_total FROM linkedin_followers WHERE date <= %s ORDER BY date DESC LIMIT 1)
        """, [d_to, d_from])
        if rows and rows[0][0] is not None and rows[0][1] is not None:
            delta = rows[0][0] - rows[0][1]
            data['followers_change'] = f"+{delta}" if delta >= 0 else str(delta)

        rows = _safe(c, """
            SELECT COUNT(*) FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
        """, [d_from, d_to])
        if rows:
            data['total_posts'] = rows[0][0] or 0

        rows = _safe(c, """
            SELECT COALESCE(SUM(latest_imp), 0) FROM (
                SELECT m.impressions AS latest_imp
                FROM linkedin_posts_metrics m
                WHERE m.metric_date = (
                    SELECT MAX(m2.metric_date)
                    FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id
                )
                GROUP BY m.post_id
            ) sub
        """)
        if rows:
            data['total_impressions'] = rows[0][0] or 0

        rows = _safe(c, """
            SELECT COALESCE(SUM(latest_eng), 0) FROM (
                SELECT (m.likes + m.comments + m.direct_shares) AS latest_eng
                FROM linkedin_posts_metrics m
                WHERE m.metric_date = (
                    SELECT MAX(m2.metric_date)
                    FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id
                )
                GROUP BY m.post_id
            ) sub
        """)
        if rows:
            data['total_engagement'] = rows[0][0] or 0

        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url, m.impressions, m.likes, m.comments, m.direct_shares
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2 WHERE m2.post_id = m.post_id
            )
            ORDER BY m.impressions DESC LIMIT 5
        """)
        if rows:
            data['top_posts'] = [{
                'title': r[1], 'post_date': r[2], 'link': r[3] or '',
                'impressions': r[4] or 0, 'likes': r[5] or 0,
                'comments': r[6] or 0, 'shares': r[7] or 0,
            } for r in rows]

        rows = _safe(c, """
            SELECT monat, COALESCE(SUM(imp), 0), COALESCE(AVG(eng) * 100, 0)
            FROM (
                SELECT DATE_FORMAT(m.metric_date, '%%Y-%%m') AS monat,
                       m.impressions AS imp, m.engagement_rate AS eng
                FROM linkedin_posts_metrics m
                WHERE m.metric_date = (
                    SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id
                      AND DATE_FORMAT(m2.metric_date, '%%Y-%%m') = DATE_FORMAT(m.metric_date, '%%Y-%%m')
                )
            ) sub GROUP BY monat ORDER BY monat
        """)
        if rows:
            data['chart_labels'] = [r[0] for r in rows]
            data['chart_impressions'] = [int(r[1]) for r in rows]
            data['chart_engagement'] = [round(float(r[2]), 2) for r in rows]

    return data


@login_required
def overview(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to = request.GET.get('to', dt)
    return render(request, 'linkedin_statistics/stat_overview.html', {
        'data': _overview_data(d_from, d_to),
        'date_from': d_from, 'date_to': d_to, 'tab': 'overview',
    })


# ══════════════════════════════════════════════════════════════
# TIMELINE: Tagesverlauf pro Post
# ══════════════════════════════════════════════════════════════

def _get_post_daily_data(cur, post_id, post_date):
    """Holt den Tagesverlauf fuer einen Post.
    Tag 1 = post_date, Tag N = DATEDIFF(metric_date, post_date) + 1.
    Gibt Liste von dicts zurueck, sortiert nach Tag."""
    rows = _safe(cur, """
        SELECT
            DATEDIFF(m.metric_date, %s) + 1 AS tag,
            m.metric_date,
            COALESCE(m.impressions, 0),
            COALESCE(m.clicks, 0),
            COALESCE(m.likes, 0),
            COALESCE(m.comments, 0),
            COALESCE(m.direct_shares, 0),
            COALESCE(m.engagement_rate, 0)
        FROM linkedin_posts_metrics m
        WHERE m.post_id = %s
          AND m.metric_date >= %s
        ORDER BY m.metric_date ASC
    """, [post_date, post_id, post_date])
    if not rows:
        return []
    return [{
        'tag': r[0], 'metric_date': r[1],
        'impressions': r[2], 'clicks': r[3],
        'likes': r[4], 'comments': r[5],
        'shares': r[6], 'engagement_rate': round(float(r[7]) * 100, 2) if r[7] else 0,
    } for r in rows if r[0] and r[0] > 0]


@login_required
def timeline(request):
    all_posts = []
    top5_chart_data = []

    with connection.cursor() as c:
        # Alle Posts mit post_date aus linkedin_posts_posted holen
        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id) AS title,
                   pp.post_date,
                   lp.post_url,
                   lp.content_type
            FROM linkedin_posts lp
            INNER JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE pp.post_date IS NOT NULL
            ORDER BY pp.post_date DESC
        """)
        if rows:
            for r in rows:
                post = {
                    'post_id': r[0], 'title': r[1], 'post_date': r[2],
                    'link': r[3] or '', 'content_type': r[4] or '',
                }
                all_posts.append(post)

            # Top 5 (neueste) mit Tagesverlauf laden
            for post in all_posts[:5]:
                daily = _get_post_daily_data(c, post['post_id'], post['post_date'])
                top5_chart_data.append({
                    'title': post['title'][:40],
                    'post_id': post['post_id'],
                    'days': [d['tag'] for d in daily],
                    'impressions': [d['impressions'] for d in daily],
                    'clicks': [d['clicks'] for d in daily],
                    'likes': [d['likes'] for d in daily],
                })

    # Max Tage fuer X-Achse bestimmen
    max_days = 0
    for p in top5_chart_data:
        if p['days']:
            max_days = max(max_days, max(p['days']))

    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'all_posts': all_posts,
        'top5_json': json.dumps(top5_chart_data, default=str),
        'max_days': max_days,
        'remaining_posts': all_posts[5:],
        'tab': 'timeline',
    })


@login_required
def timeline_detail(request, post_id):
    """Einzelpost-Tagesverlauf als JSON fuer AJAX."""
    post_info = {}
    daily = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id),
                   pp.post_date,
                   lp.post_url, lp.content_type
            FROM linkedin_posts lp
            INNER JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE lp.post_id = %s
        """, [post_id])
        if rows:
            r = rows[0]
            post_info = {
                'post_id': r[0], 'title': r[1], 'post_date': str(r[2]),
                'link': r[3] or '', 'content_type': r[4] or '',
            }
            daily = _get_post_daily_data(c, r[0], r[2])

    from django.http import JsonResponse
    return JsonResponse({
        'post': post_info,
        'daily': daily,
    }, json_dumps_params={'default': str})
