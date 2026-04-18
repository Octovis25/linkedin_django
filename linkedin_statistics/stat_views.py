"""
linkedin_statistics/stat_views.py
Overview + Timeline.
Alle Dateien in diesem Modul haben stat_ als Vorsilbe.
"""
from datetime import date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
import json


def _defaults():
    return (date.today() - timedelta(days=365)).isoformat(), date.today().isoformat()


def _safe(cur, sql, params=None):
    try:
        cur.execute(sql, params or [])
        return cur.fetchall()
    except Exception:
        return None


def _period_fmt(group_by):
    if group_by == 'day':
        return '%%Y-%%m-%%d'
    elif group_by == 'week':
        return '%%x-W%%v'
    return '%%Y-%%m'


def _overview_data(d_from, d_to, group_by='month'):
    data = {
        'total_followers': 0, 'followers_change': '+0',
        'total_posts': 0, 'total_impressions': 0, 'total_engagement': 0,
        'top_posts_impressions': [], 'top_posts_engagement': [],
        'chart_labels': [], 'chart_clicks': [],
        'chart_reactions': [], 'chart_comments': [], 'chart_shares': [],
    }

    fmt = _period_fmt(group_by)

    with connection.cursor() as c:

        # Followers
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

        # Posts count
        rows = _safe(c, """
            SELECT COUNT(*) FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
        """, [d_from, d_to])
        if rows:
            data['total_posts'] = rows[0][0] or 0

        # Impressions (letzter Snapshot pro Post)
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

        # Engagement (letzter Snapshot pro Post)
        rows = _safe(c, """
            SELECT COALESCE(SUM(eng), 0) FROM (
                SELECT (m.likes + m.comments + m.direct_shares) AS eng
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

        # Top 5 nach Impressions
        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url,
                   m.impressions,
                   m.likes,
                   m.comments,
                   m.direct_shares,
                   m.clicks
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date)
                FROM linkedin_posts_metrics m2
                WHERE m2.post_id = m.post_id
            )
            ORDER BY m.impressions DESC
            LIMIT 5
        """)
        if rows:
            data['top_posts_impressions'] = [{
                'title': r[1], 'post_date': r[2], 'link': r[3] or '',
                'impressions': r[4] or 0, 'likes': r[5] or 0,
                'comments': r[6] or 0, 'shares': r[7] or 0, 'clicks': r[8] or 0,
            } for r in rows]

        # Top 5 nach Engagement (Likes+Comments+Shares)
        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url,
                   m.impressions,
                   m.likes,
                   m.comments,
                   m.direct_shares,
                   m.clicks,
                   (m.likes + m.comments + m.direct_shares) AS engagement
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date)
                FROM linkedin_posts_metrics m2
                WHERE m2.post_id = m.post_id
            )
            ORDER BY engagement DESC
            LIMIT 5
        """)
        if rows:
            data['top_posts_engagement'] = [{
                'title': r[1], 'post_date': r[2], 'link': r[3] or '',
                'impressions': r[4] or 0, 'likes': r[5] or 0,
                'comments': r[6] or 0, 'shares': r[7] or 0, 'clicks': r[8] or 0,
                'engagement': r[9] or 0,
            } for r in rows]

        # Chart: Interaktionen pro Zeitraum (grouped bars)
        rows = _safe(c, """
            SELECT period_key,
                   COALESCE(SUM(clicks), 0),
                   COALESCE(SUM(likes), 0),
                   COALESCE(SUM(comments), 0),
                   COALESCE(SUM(direct_shares), 0)
            FROM (
                SELECT
                    DATE_FORMAT(m.metric_date, '""" + fmt + """') AS period_key,
                    m.post_id,
                    m.clicks,
                    m.likes,
                    m.comments,
                    m.direct_shares
                FROM linkedin_posts_metrics m
                WHERE m.metric_date BETWEEN %s AND %s
                  AND m.metric_date = (
                      SELECT MAX(m2.metric_date)
                      FROM linkedin_posts_metrics m2
                      WHERE m2.post_id = m.post_id
                        AND m2.metric_date BETWEEN %s AND %s
                        AND DATE_FORMAT(m2.metric_date, '""" + fmt + """') = DATE_FORMAT(m.metric_date, '""" + fmt + """')
                  )
            ) sub
            GROUP BY period_key
            ORDER BY period_key
        """, [d_from, d_to, d_from, d_to])
        if rows:
            data['chart_labels'] = [r[0] for r in rows]
            data['chart_clicks'] = [int(r[1] or 0) for r in rows]
            data['chart_reactions'] = [int(r[2] or 0) for r in rows]
            data['chart_comments'] = [int(r[3] or 0) for r in rows]
            data['chart_shares'] = [int(r[4] or 0) for r in rows]

    return data


@login_required
def overview(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to = request.GET.get('to', dt)
    group_by = request.GET.get('group_by', 'month')

    data = _overview_data(d_from, d_to, group_by=group_by)

    # Aggregations-Hinweis
    agg_labels = {'day': 'tageweise', 'week': 'wochenweise', 'month': 'monatsweise'}
    agg_text = agg_labels.get(group_by, 'monatsweise')

    return render(request, 'linkedin_statistics/stat_overview.html', {
        'data': data,
        'date_from': d_from, 'date_to': d_to,
        'tab': 'overview', 'group_by': group_by,
        'agg_text': agg_text,
        'chart_labels_json': json.dumps(data['chart_labels']),
        'chart_clicks_json': json.dumps(data['chart_clicks']),
        'chart_reactions_json': json.dumps(data['chart_reactions']),
        'chart_comments_json': json.dumps(data['chart_comments']),
        'chart_shares_json': json.dumps(data['chart_shares']),
    })


@login_required
def timeline(request):
    posts = []
    top5_json = '[]'
    max_days = 30
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url, lp.content_type,
                   COALESCE(m.impressions, 0),
                   COALESCE(m.likes, 0),
                   COALESCE(m.comments, 0),
                   COALESCE(m.direct_shares, 0),
                   COALESCE(m.clicks, 0)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                AND m.metric_date = (
                    SELECT MAX(m2.metric_date)
                    FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id
                )
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
        """)
        if rows:
            posts = [{
                'post_id': r[0], 'title': r[1], 'post_date': r[2],
                'link': r[3] or '', 'content_type': r[4] or '',
                'impressions': r[5], 'likes': r[6], 'comments': r[7],
                'shares': r[8], 'clicks': r[9],
                'engagement': (r[6] or 0) + (r[7] or 0) + (r[8] or 0),
            } for r in rows]

        # Top 5 fuer Chart (letzte 5 nach Datum mit Tagesverlauf)
        top5_posts = [p for p in posts if p.get('post_date')][:5]
        top5_data = []
        for tp in top5_posts:
            pid = tp['post_id']
            mrows = _safe(c, """
                SELECT
                    DATEDIFF(m.metric_date, COALESCE(pp.post_date, lp.post_date)) + 1 AS tag,
                    m.impressions
                FROM linkedin_posts_metrics m
                JOIN linkedin_posts lp ON lp.post_id = m.post_id
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                WHERE m.post_id = %s
                ORDER BY m.metric_date ASC
            """, [pid])
            if mrows:
                days = [int(r[0]) for r in mrows if r[0] and r[0] >= 1]
                imps = [int(r[1] or 0) for r in mrows if r[0] and r[0] >= 1]
                if days:
                    max_days = max(max_days, max(days))
                    top5_data.append({
                        'title': (tp['title'] or pid)[:40],
                        'days': days,
                        'impressions': imps,
                    })
        top5_json = json.dumps(top5_data)

    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'posts': posts, 'all_posts': posts, 'tab': 'timeline',
        'top5_json': top5_json, 'max_days': max_days,
    })


@login_required
def timeline_detail(request, post_id):
    """AJAX: Tagesverlauf fuer einen einzelnen Post."""
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT
                DATEDIFF(m.metric_date, COALESCE(pp.post_date, lp.post_date)) + 1 AS tag,
                m.impressions, m.clicks, m.likes, m.comments, m.direct_shares,
                m.engagement_rate
            FROM linkedin_posts_metrics m
            JOIN linkedin_posts lp ON lp.post_id = m.post_id
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE m.post_id = %s
            ORDER BY m.metric_date ASC
        """, [post_id])

    if not rows:
        return JsonResponse({'daily': []})

    daily = []
    for r in rows:
        if r[0] and r[0] >= 1:
            daily.append({
                'tag': int(r[0]),
                'impressions': int(r[1] or 0),
                'clicks': int(r[2] or 0),
                'likes': int(r[3] or 0),
                'comments': int(r[4] or 0),
                'shares': int(r[5] or 0),
                'engagement_rate': round(float(r[6] or 0) * 100, 2),
            })

    return JsonResponse({'daily': daily})
