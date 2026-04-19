import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
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
    if group_by == 'day':   return '%Y-%m-%d'
    if group_by == 'week':  return '%x-W%v'
    return '%Y-%m'


def _agg_text(group_by):
    return {'day': 'tagesweise', 'week': 'wochenweise', 'month': 'monatsweise'}.get(
        (group_by or 'month').lower(), 'monatsweise')


def _chart_series(d_from, d_to, group_by):
    fmt = _period_fmt(group_by)
    sql = """
        SELECT DATE_FORMAT(metric_date, %s) AS period,
               COALESCE(SUM(impressions_total), 0),
               COALESCE(SUM(clicks_total), 0),
               COALESCE(SUM(reactions_total), 0),
               COALESCE(SUM(comments_total), 0),
               COALESCE(SUM(shares_direct_total), 0)
        FROM linkedin_content_metrics
        WHERE metric_date BETWEEN %s AND %s
        GROUP BY period ORDER BY period
    """
    with connection.cursor() as c:
        rows = _safe(c, sql, [fmt, d_from, d_to])
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

    by_imp = _safe(cursor, base + " ORDER BY COALESCE(pp.post_date, lp.post_date) DESC LIMIT 5")
    by_eng = _safe(cursor, base + " ORDER BY (m.likes+m.comments+m.direct_shares) DESC LIMIT 5")
    return to_list(by_imp), to_list(by_eng)


@login_required
def overview(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to   = request.GET.get('to', dt)
    group_by = request.GET.get('group_by', 'month')

    kpi = _kpi_snapshot()
    with connection.cursor() as c:
        top_imp, top_eng = _top5(c)

    labels, imps, clicks, reactions, comments, shares, eng_rate = _chart_series(d_from, d_to, group_by)

    return render(request, 'linkedin_statistics/stat_overview.html', {
        'kpi': kpi,
        'top_posts_impressions': top_imp,
        'top_posts_engagement': top_eng,
        'date_from': d_from, 'date_to': d_to,
        'tab': 'overview', 'group_by': group_by,
        'agg_text': _agg_text(group_by),
        'chart_labels_json':     json.dumps(labels),
        'chart_impressions_json': json.dumps(imps),
        'chart_engagement_json':  json.dumps(eng_rate),
        'chart_clicks_json':      json.dumps(clicks),
        'chart_reactions_json':   json.dumps(reactions),
        'chart_comments_json':    json.dumps(comments),
        'chart_shares_json':      json.dumps(shares),
    })


@login_required
def timeline(request):
    df, dt = _defaults()
    d_from   = request.GET.get('from', df)
    d_to     = request.GET.get('to', dt)
    group_by = request.GET.get('group_by', 'month')

    # Alle Posts laden
    all_posts = []
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
                all_posts.append({
                    'post_id': r[0], 'title': r[1], 'post_date': r[2],
                    'link': r[3] or '', 'content_type': r[4] or '',
                    'impressions': r[5], 'likes': r[6], 'comments': r[7],
                    'shares': r[8], 'clicks': r[9],
                })

        # Top 5 nach Impressions für Chart
        top5_raw = _safe(c, """
            SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                WHERE m2.post_id = m.post_id)
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC LIMIT 5
        """)

        top5_json = []
        max_days = 30
        if top5_raw:
            for post_id, title in top5_raw:
                detail = _safe(c, """
                    SELECT metric_date, impressions
                    FROM linkedin_posts_metrics
                    WHERE post_id = %s
                    ORDER BY metric_date
                """, [post_id])
                if detail:
                    first_date = detail[0][0]
                    days, impressions = [], []
                    for row in detail:
                        day_nr = (row[0] - first_date).days + 1
                        days.append(day_nr)
                        impressions.append(int(row[1] or 0))
                    max_days = max(max_days, max(days))
                    top5_json.append({
                        'title': title[:40],
                        'days': days,
                        'impressions': impressions,
                    })

    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'all_posts': all_posts,
        'top5_json': json.dumps(top5_json),
        'max_days':  max_days,
        'date_from': d_from, 'date_to': d_to,
        'tab': 'timeline', 'group_by': group_by,
        'agg_text': _agg_text(group_by),
    })


@login_required
def timeline_detail(request, post_id):
    """Tagesverlauf für einen einzelnen Post – AJAX."""
    daily = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT metric_date, impressions, clicks, likes, comments, direct_shares
            FROM linkedin_posts_metrics
            WHERE post_id = %s
            ORDER BY metric_date
        """, [post_id])
        if rows:
            first = rows[0][0]
            for r in rows:
                imp = int(r[1] or 0)
                rea = int(r[3] or 0)
                com = int(r[4] or 0)
                sha = int(r[5] or 0)
                eng = round(((rea + com + sha) / imp * 100) if imp else 0, 2)
                daily.append({
                    'tag':             (r[0] - first).days + 1,
                    'impressions':     imp,
                    'clicks':          int(r[2] or 0),
                    'likes':           rea,
                    'comments':        com,
                    'shares':          sha,
                    'engagement_rate': eng,
                })
    return JsonResponse({'daily': daily})
