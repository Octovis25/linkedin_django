"""linkedin_statistics/stat_views.py – COMPLETE FIX (2026-04-18)

Layout:
  1) KPI-Kacheln: IMMER letzter Stand + Datum (NICHT von Von/Bis abhaengig)
  2) Von/Bis + Aggregation (beeinflusst NUR Charts)
  3) Chart: Impressions + Engagement Rate (Combo)
  4) Chart: Interaktionen absolut (Grouped Bar)
  5) Top 5 nach Impressions
  6) Top 5 nach Engagement
"""

import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.shortcuts import render


def _defaults():
    return (date.today() - timedelta(days=365)).isoformat(), date.today().isoformat()


def _safe(cur, sql, params=None):
    try:
        cur.execute(sql, params or [])
        return cur.fetchall()
    except Exception:
        return None


def _period_fmt(group_by):
    group_by = (group_by or 'month').lower()
    if group_by == 'day':
        return '%Y-%m-%d'
    if group_by == 'week':
        return '%x-W%v'
    return '%Y-%m'


def _agg_text(group_by):
    return {'day': 'tagesweise', 'week': 'wochenweise', 'month': 'monatsweise'}.get(
        (group_by or 'month').lower(), 'monatsweise')


def _chart_series(d_from, d_to, group_by):
    fmt = _period_fmt(group_by)
    sql = """
        SELECT period_key,
               COALESCE(SUM(impressions),0),
               COALESCE(SUM(clicks),0),
               COALESCE(SUM(likes),0),
               COALESCE(SUM(comments),0),
               COALESCE(SUM(direct_shares),0)
        FROM (
            SELECT DATE_FORMAT(m.metric_date, %s) AS period_key,
                   m.post_id, m.impressions, m.clicks, m.likes,
                   m.comments, m.direct_shares
            FROM linkedin_posts_metrics m
            WHERE m.metric_date BETWEEN %s AND %s
              AND m.metric_date = (
                  SELECT MAX(m2.metric_date)
                  FROM linkedin_posts_metrics m2
                  WHERE m2.post_id = m.post_id
                    AND m2.metric_date BETWEEN %s AND %s
                    AND DATE_FORMAT(m2.metric_date, %s) = DATE_FORMAT(m.metric_date, %s)
              )
        ) sub
        GROUP BY period_key
        ORDER BY period_key
    """
    with connection.cursor() as c:
        rows = _safe(c, sql, [fmt, d_from, d_to, d_from, d_to, fmt, fmt])
    if not rows:
        return [], [], [], [], [], [], []

    labels, imps, clicks, reactions, comments, shares, eng_rate = [], [], [], [], [], [], []
    for r in rows:
        labels.append(r[0])
        imp = int(r[1] or 0)
        cli = int(r[2] or 0)
        rea = int(r[3] or 0)
        com = int(r[4] or 0)
        sha = int(r[5] or 0)
        imps.append(imp)
        clicks.append(cli)
        reactions.append(rea)
        comments.append(com)
        shares.append(sha)
        total_int = rea + com + sha
        eng_rate.append(round((total_int / imp * 100) if imp else 0, 2))

    return labels, imps, clicks, reactions, comments, shares, eng_rate


def _kpi_snapshot():
    kpi = {
        'total_followers': 0, 'followers_date': None,
        'total_posts': 0, 'posts_date': None,
        'total_impressions': 0, 'total_engagement': 0, 'metrics_date': None,
    }
    with connection.cursor() as c:
        rows = _safe(c, "SELECT followers_total, date FROM linkedin_followers ORDER BY date DESC LIMIT 1")
        if rows and rows[0][0] is not None:
            kpi['total_followers'] = rows[0][0]
            kpi['followers_date'] = rows[0][1]

        rows = _safe(c, """
            SELECT COUNT(*), MAX(COALESCE(pp.post_date, lp.post_date))
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        """)
        if rows:
            kpi['total_posts'] = rows[0][0] or 0
            kpi['posts_date'] = rows[0][1]

        rows = _safe(c, """
            SELECT COALESCE(SUM(imp),0), COALESCE(SUM(eng),0), MAX(md)
            FROM (
                SELECT m.impressions AS imp,
                       (m.likes + m.comments + m.direct_shares) AS eng,
                       m.metric_date AS md
                FROM linkedin_posts_metrics m
                WHERE m.metric_date = (
                    SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id)
                GROUP BY m.post_id
            ) sub
        """)
        if rows and rows[0]:
            kpi['total_impressions'] = rows[0][0] or 0
            kpi['total_engagement'] = rows[0][1] or 0
            kpi['metrics_date'] = rows[0][2]
    return kpi


def _top5(cursor):
    base = """
        SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id),
               COALESCE(pp.post_date, lp.post_date), lp.post_url,
               m.impressions, m.clicks, m.likes, m.comments, m.direct_shares
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
        WHERE m.metric_date = (
            SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
            WHERE m2.post_id = m.post_id)
    """
    def to_list(rows):
        return [{
            'title': r[1], 'post_date': r[2], 'link': r[3] or '',
            'impressions': r[4] or 0, 'clicks': r[5] or 0,
            'likes': r[6] or 0, 'comments': r[7] or 0, 'shares': r[8] or 0,
            'engagement': (r[6] or 0) + (r[7] or 0) + (r[8] or 0),
        } for r in (rows or [])]

    by_imp = _safe(cursor, base + " ORDER BY m.impressions DESC LIMIT 5")
    by_eng = _safe(cursor, base + " ORDER BY (m.likes+m.comments+m.direct_shares) DESC LIMIT 5")
    return to_list(by_imp), to_list(by_eng)


@login_required
def overview(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to = request.GET.get('to', dt)
    group_by = request.GET.get('group_by', 'month')

    kpi = _kpi_snapshot()
    with connection.cursor() as c:
        top_imp, top_eng = _top5(c)

    labels, imps, clicks, reactions, comments, shares, eng_rate = _chart_series(d_from, d_to, group_by)

    return render(request, 'linkedin_statistics/stat_overview.html', {
        'kpi': kpi,
        'top_posts_impressions': top_imp,
        'top_posts_engagement': top_eng,
        'date_from': d_from,
        'date_to': d_to,
        'tab': 'overview',
        'group_by': group_by,
        'agg_text': _agg_text(group_by),
        'chart_labels_json': json.dumps(labels),
        'chart_impressions_json': json.dumps(imps),
        'chart_engagement_json': json.dumps(eng_rate),
        'chart_clicks_json': json.dumps(clicks),
        'chart_reactions_json': json.dumps(reactions),
        'chart_comments_json': json.dumps(comments),
        'chart_shares_json': json.dumps(shares),
    })


@login_required
def timeline(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to = request.GET.get('to', dt)
    group_by = request.GET.get('group_by', 'month')

    posts = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url, lp.content_type,
                   COALESCE(m.impressions,0), COALESCE(m.likes,0),
                   COALESCE(m.comments,0), COALESCE(m.direct_shares,0),
                   COALESCE(m.clicks,0)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                AND m.metric_date = (
                    SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id)
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
        """)
        if rows:
            for r in rows:
                posts.append({
                    'post_id': r[0], 'title': r[1], 'post_date': r[2],
                    'link': r[3] or '', 'content_type': r[4] or '',
                    'impressions': r[5], 'likes': r[6], 'comments': r[7],
                    'shares': r[8], 'clicks': r[9],
                })

    labels, imps, clicks, reactions, comments, shares, eng_rate = _chart_series(d_from, d_to, group_by)

    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'posts': posts,
        'date_from': d_from, 'date_to': d_to,
        'tab': 'timeline', 'group_by': group_by,
        'agg_text': _agg_text(group_by),
        'chart_labels_json': json.dumps(labels),
        'chart_impressions_json': json.dumps(imps),
        'chart_engagement_json': json.dumps(eng_rate),
        'chart_clicks_json': json.dumps(clicks),
        'chart_reactions_json': json.dumps(reactions),
        'chart_comments_json': json.dumps(comments),
        'chart_shares_json': json.dumps(shares),
    })


@login_required
def timeline_detail(request, post_id):
    """Detail-Chart fuer einen einzelnen Post (Tagesverlauf)."""
    data = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT metric_date, impressions, clicks, likes, comments, direct_shares
            FROM linkedin_posts_metrics
            WHERE post_id = %s
            ORDER BY metric_date
        """, [post_id])
        if rows:
            for r in rows:
                data.append({
                    'date': r[0].isoformat() if r[0] else '',
                    'impressions': int(r[1] or 0),
                    'clicks': int(r[2] or 0),
                    'likes': int(r[3] or 0),
                    'comments': int(r[4] or 0),
                    'shares': int(r[5] or 0),
                })

    from django.http import JsonResponse
    return JsonResponse({'series': data})
