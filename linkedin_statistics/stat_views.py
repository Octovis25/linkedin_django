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


def _all_periods(d_from, d_to, group_by):
    """Generate every period label between d_from and d_to (inclusive)."""
    import datetime
    try:
        start = datetime.date.fromisoformat(d_from)
        end   = datetime.date.fromisoformat(d_to)
    except Exception:
        return []

    periods = []
    gb = (group_by or 'month').lower()
    if gb == 'day':
        cur = start
        while cur <= end:
            periods.append(cur.strftime('%Y-%m-%d'))
            cur += datetime.timedelta(days=1)
    elif gb == 'week':
        # align to Monday of the start week
        cur = start - datetime.timedelta(days=start.weekday())
        while cur <= end:
            iso = cur.isocalendar()
            periods.append(f'{iso[0]}-W{iso[1]:02d}')
            cur += datetime.timedelta(weeks=1)
    else:  # month
        y, m = start.year, start.month
        ey, em = end.year, end.month
        while (y, m) <= (ey, em):
            periods.append(f'{y}-{m:02d}')
            m += 1
            if m > 12:
                m, y = 1, y + 1
    return periods


def _views_series(d_from, d_to, group_by):
    """
    Views per period based on the post's PUBLISH DATE, using the latest available
    snapshot for each post. A video published in December gets its views counted
    in December – regardless of when the export happened.
    """
    fmt = _period_fmt(group_by)
    sql = """
        SELECT DATE_FORMAT(COALESCE(pp.post_date, lp.post_date), %s) AS period,
               COALESCE(SUM(m.views), 0)
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
        WHERE m.metric_date = (
            SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
            WHERE m2.post_id = m.post_id
        )
          AND m.views IS NOT NULL
          AND m.views > 0
          AND COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
        GROUP BY period
        ORDER BY period
    """
    with connection.cursor() as c:
        rows = _safe(c, sql, [fmt, d_from, d_to])

    db_views = {r[0]: int(r[1] or 0) for r in (rows or [])}

    all_labels = _all_periods(d_from, d_to, group_by)
    return [db_views.get(lbl, 0) for lbl in all_labels]


def _agg_text(group_by):
    return {'day': 'daily', 'week': 'weekly', 'month': 'monthly'}.get(
        (group_by or 'month').lower(), 'monthly')


def _chart_content_metrics(d_from, d_to, group_by):
    """
    Chart 1: Impressions + Engagement Rate.
    Uses linkedin_content_metrics – general page-level daily aggregates from LinkedIn.
    Simple SUM per period is correct here (values are already daily totals, not cumulative).
    All periods in range are returned; missing ones filled with 0.
    """
    fmt = _period_fmt(group_by)
    sql = """
        SELECT DATE_FORMAT(metric_date, %s) AS period,
               COALESCE(SUM(impressions_total), 0)
        FROM linkedin_content_metrics
        WHERE metric_date BETWEEN %s AND %s
        GROUP BY period ORDER BY period
    """
    with connection.cursor() as c:
        rows = _safe(c, sql, [fmt, d_from, d_to])

    db_imps = {r[0]: int(r[1] or 0) for r in (rows or [])}

    all_labels = _all_periods(d_from, d_to, group_by)
    labels, imps, eng_rate = [], [], []
    for lbl in all_labels:
        imp = db_imps.get(lbl, 0)
        labels.append(lbl)
        imps.append(imp)
        eng_rate.append(0)   # engagement rate needs reactions/shares/comments – see below

    return labels, imps, eng_rate


def _chart_interactions(d_from, d_to, group_by):
    """
    Chart 2: Interactions (Clicks, Likes, Comments, Shares, Views) + Engagement Rate.
    All metrics from linkedin_posts_metrics – latest snapshot per post,
    grouped by the post's PUBLISH DATE. Same logic as _views_series.
    """
    fmt = _period_fmt(group_by)
    sql = """
        SELECT DATE_FORMAT(COALESCE(pp.post_date, lp.post_date), %s) AS period,
               COALESCE(SUM(m.clicks), 0),
               COALESCE(SUM(m.likes), 0),
               COALESCE(SUM(m.comments), 0),
               COALESCE(SUM(m.direct_shares), 0),
               COALESCE(SUM(m.impressions), 0)
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
        WHERE m.metric_date = (
            SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
            WHERE m2.post_id = m.post_id
        )
          AND COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
        GROUP BY period
        ORDER BY period
    """
    with connection.cursor() as c:
        rows = _safe(c, sql, [fmt, d_from, d_to])

    db_data = {}
    if rows:
        for r in rows:
            db_data[r[0]] = (int(r[1] or 0), int(r[2] or 0),
                             int(r[3] or 0), int(r[4] or 0), int(r[5] or 0))

    all_labels = _all_periods(d_from, d_to, group_by)
    if not all_labels:
        return [], [], [], [], [], [], []

    views_list = _views_series(d_from, d_to, group_by)

    labels, clicks, reactions, comments, shares, eng_rate, views = [], [], [], [], [], [], []
    for i, lbl in enumerate(all_labels):
        cli, rea, com, sha, imp = db_data.get(lbl, (0, 0, 0, 0, 0))
        labels.append(lbl)
        clicks.append(cli)
        reactions.append(rea)
        comments.append(com)
        shares.append(sha)
        views.append(views_list[i] if i < len(views_list) else 0)
        total_int = rea + com + sha
        eng_rate.append(round((total_int / imp * 100) if imp else 0, 2))

    return labels, clicks, reactions, comments, shares, eng_rate, views


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
               m.impressions, m.clicks, m.likes, m.comments, m.direct_shares,
               m.views, lp.content_type
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
            'views': r[9], 'content_type': r[10] or '',
        } for r in (rows or [])]

    by_imp = _safe(cursor, base + " ORDER BY m.impressions DESC LIMIT 5")
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

    # Chart 1: Impressions + Engagement Rate (from linkedin_content_metrics)
    labels, imps, _ = _chart_content_metrics(d_from, d_to, group_by)

    # Chart 2: Interactions + Views (from linkedin_content_metrics + linkedin_posts_metrics for views)
    _, clicks, reactions, comments, shares, eng_rate, views_data = _chart_interactions(d_from, d_to, group_by)

    # Summary: Video vs No Video averages + CTR
    with connection.cursor() as c:
        rows_summary = _safe(c, """
            SELECT
                CASE WHEN lp.content_type = 'Video' THEN 'video' ELSE 'novideo' END AS ctype,
                COUNT(*) AS post_count,
                ROUND(AVG(m.impressions), 0) AS avg_imp,
                ROUND(AVG(m.clicks), 1) AS avg_cli,
                ROUND(SUM(m.clicks) / NULLIF(SUM(m.impressions), 0) * 100, 2) AS ctr
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                WHERE m2.post_id = m.post_id
            )
              AND COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
              AND (pp.category IS NULL OR pp.category != 'Event')
            GROUP BY ctype
        """, [d_from, d_to])

    video_summary = {'video': {}, 'novideo': {}}
    for r in (rows_summary or []):
        ctype = r[0]
        video_summary[ctype] = {
            'count':   int(r[1] or 0),
            'avg_imp': int(r[2] or 0),
            'avg_cli': float(r[3] or 0),
            'ctr':     float(r[4] or 0),
        }

    # Chart 3: per-post Impressions, sorted desc, colored by Video vs No Video
    with connection.cursor() as c:
        rows_posts = _safe(c, """
            SELECT COALESCE(pp.post_title, lp.post_title, lp.post_id),
                   CASE WHEN lp.content_type = 'Video' THEN 'video' ELSE 'novideo' END AS ctype,
                   COALESCE(m.impressions, 0),
                   COALESCE(m.clicks, 0),
                   COALESCE(pp.post_date, lp.post_date)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                WHERE m2.post_id = m.post_id
            )
              AND COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
              AND (pp.category IS NULL OR pp.category != 'Event')
            ORDER BY m.impressions DESC
        """, [d_from, d_to])

    post_labels, imp_video, imp_novideo, cli_video, cli_novideo = [], [], [], [], []
    for r in (rows_posts or []):
        title = (r[0] or '')[:40]
        ctype = r[1]
        imp   = int(r[2] or 0)
        cli   = int(r[3] or 0)
        post_labels.append(title)
        imp_video.append(imp if ctype == 'video' else None)
        imp_novideo.append(imp if ctype == 'novideo' else None)
        cli_video.append(cli if ctype == 'video' else None)
        cli_novideo.append(cli if ctype == 'novideo' else None)

    return render(request, 'linkedin_statistics/stat_overview.html', {
        'kpi': kpi,
        'top_posts_impressions': top_imp,
        'top_posts_engagement': top_eng,
        'date_from': d_from, 'date_to': d_to,
        'tab': 'overview', 'group_by': group_by,
        'agg_text': _agg_text(group_by),
        'chart_labels_json':      json.dumps(labels),
        'chart_impressions_json': json.dumps(imps),
        'chart_engagement_json':  json.dumps(eng_rate),
        'chart_clicks_json':      json.dumps(clicks),
        'chart_reactions_json':   json.dumps(reactions),
        'chart_comments_json':    json.dumps(comments),
        'chart_shares_json':      json.dumps(shares),
        'chart_views_json':       json.dumps(views_data),
        'chart_post_labels_json':   json.dumps(post_labels),
        'chart_imp_video_json':     json.dumps(imp_video),
        'chart_imp_novideo_json':   json.dumps(imp_novideo),
        'chart_cli_video_json':     json.dumps(cli_video),
        'chart_cli_novideo_json':   json.dumps(cli_novideo),
        'video_summary':            video_summary,
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
                   COALESCE(m.clicks,0), m.views
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
                    'shares': r[8], 'clicks': r[9], 'views': r[10],
                })

        # Top 10 aktuellste Posts
        top5_raw = _safe(c, """
            SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                WHERE m2.post_id = m.post_id)
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC LIMIT 10
        """)
        # Top 10 nach Impressionen
        top_imp_raw = _safe(c, """
            SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id)
            FROM linkedin_posts lp
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            WHERE m.metric_date = (
                SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                WHERE m2.post_id = m.post_id)
            ORDER BY m.impressions DESC LIMIT 10
        """)

        top5_json = []
        # max_days = Tage seit ältestem Post bis heute
        import datetime
        oldest = _safe(c, "SELECT MIN(DATE(created_at)) FROM linkedin_posts WHERE created_at IS NOT NULL")
        if oldest and oldest[0][0]:
            max_days = (datetime.date.today() - oldest[0][0]).days + 1
        else:
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
                    # Tag 1 = Post-Erstelldatum aus linkedin_posts
                    post_date_row = _safe(c, """
                        SELECT COALESCE(DATE(lp.created_at), pp.post_date)
                        FROM linkedin_posts lp
                        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                        WHERE lp.post_id = %s
                    """, [post_id])
                    import datetime
                    if post_date_row and post_date_row[0][0]:
                        first_date = post_date_row[0][0]
                        if isinstance(first_date, datetime.datetime):
                            first_date = first_date.date()
                    else:
                        first_date = detail[0][0]
                    days, impressions = [], []
                    import datetime
                    today_day = (datetime.date.today() - first_date).days + 1
                    for row in detail:
                        day_nr = (row[0] - first_date).days + 1
                        if day_nr >= 1:
                            days.append(day_nr)
                            impressions.append(int(row[1] or 0))
                    # Ersten Wert auch an Tag 1 setzen damit Linie von Tag 1 startet
                    if days and days[0] > 1:
                        days.insert(0, 1)
                        impressions.insert(0, impressions[0])
                    # Letzten Wert bis heute verlängern
                    if days and days[-1] < today_day:
                        days.append(today_day)
                        impressions.append(impressions[-1])
                    max_days = max(max_days, max(days))
                    top5_json.append({
                        'title': title[:40],
                        'days': days,
                        'impressions': impressions,
                    })

        # Top Impressions Chart Daten aufbauen
        top_imp_json = []
        if top_imp_raw:
            for post_id, title in top_imp_raw:
                detail = _safe(c, """
                    SELECT metric_date, impressions
                    FROM linkedin_posts_metrics
                    WHERE post_id = %s
                    ORDER BY metric_date
                """, [post_id])
                if detail:
                    post_date_row = _safe(c, """
                        SELECT COALESCE(DATE(lp.created_at), pp.post_date)
                        FROM linkedin_posts lp
                        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                        WHERE lp.post_id = %s
                    """, [post_id])
                    import datetime
                    if post_date_row and post_date_row[0][0]:
                        first = post_date_row[0][0]
                        if isinstance(first, datetime.datetime):
                            first = first.date()
                    else:
                        first = detail[0][0]
                    days, impressions = [], []
                    today_day = (datetime.date.today() - first).days + 1
                    for row in detail:
                        day_nr = (row[0] - first).days + 1
                        if day_nr >= 1:
                            days.append(day_nr)
                            impressions.append(int(row[1] or 0))
                    if days and days[0] > 1:
                        days.insert(0, 1)
                        impressions.insert(0, impressions[0])
                    if days and days[-1] < today_day:
                        days.append(today_day)
                        impressions.append(impressions[-1])
                    top_imp_json.append({'title': title[:40], 'days': days, 'impressions': impressions})

    # Charts: Content Metrics + Interactions (same as Overview)
    tl_labels, tl_imps, _ = _chart_content_metrics(d_from, d_to, group_by)
    _, tl_clicks, tl_reactions, tl_comments, tl_shares, tl_eng_rate, tl_views = \
        _chart_interactions(d_from, d_to, group_by)

    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'all_posts': all_posts,
        'top5_json': json.dumps(top5_json),
        'top_impressions_json': json.dumps(top_imp_json),
        'max_days':  max_days,
        'date_from': d_from, 'date_to': d_to,
        'tab': 'timeline', 'group_by': group_by,
        'agg_text': _agg_text(group_by),
        'chart_labels_json':      json.dumps(tl_labels),
        'chart_impressions_json': json.dumps(tl_imps),
        'chart_clicks_json':      json.dumps(tl_clicks),
        'chart_reactions_json':   json.dumps(tl_reactions),
        'chart_comments_json':    json.dumps(tl_comments),
        'chart_shares_json':      json.dumps(tl_shares),
        'chart_views_json':       json.dumps(tl_views),
        'chart_engagement_json':  json.dumps(tl_eng_rate),
    })


@login_required
def timeline_detail(request, post_id):
    """Tagesverlauf für einen einzelnen Post – AJAX."""
    daily = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT metric_date, impressions, clicks, likes, comments, direct_shares, views
            FROM linkedin_posts_metrics
            WHERE post_id = %s
            ORDER BY metric_date
        """, [post_id])
        if rows:
            # Tag 1 = Post-Erstelldatum aus linkedin_posts
            c.execute("SELECT created_at FROM linkedin_posts WHERE post_id = %s", [post_id])
            created = c.fetchone()
            if created and created[0]:
                import datetime
                first = created[0].date() if isinstance(created[0], datetime.datetime) else created[0]
            else:
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
                    'views':           int(r[6] or 0) if r[6] is not None else None,
                    'engagement_rate': eng,
                })
    return JsonResponse({'daily': daily})


@login_required
def post_image(request, post_id):
    """Proxy: lädt Bild von Nextcloud und liefert es aus."""
    from django.http import HttpResponse
    with connection.cursor() as c:
        rows = _safe(c, "SELECT post_image FROM linkedin_posts_posted WHERE post_id = %s", [post_id])
    if not rows or not rows[0][0]:
        from django.http import Http404
        raise Http404

    nc_path = rows[0][0]
    from posts_posted.nc_storage import download_image_from_nextcloud
    content, ct = download_image_from_nextcloud(nc_path)
    if not content:
        from django.http import Http404
        raise Http404
    return HttpResponse(content, content_type=ct or 'image/png')


@login_required
def posts(request):
    content_type = request.GET.get('content_type', '')
    search = request.GET.get('search', '')

    all_posts = []
    with connection.cursor() as c:
        sql = """
            SELECT lp.post_id, COALESCE(pp.post_title, lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url, lp.content_type,
                   COALESCE(m.impressions,0), COALESCE(m.likes,0),
                   COALESCE(m.comments,0), COALESCE(m.direct_shares,0),
                   COALESCE(m.clicks,0), pp.post_image, m.views
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                AND m.metric_date = (
                    SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id)
            WHERE 1=1
        """
        params = []
        if content_type == 'video':
            sql += " AND lp.content_type = 'Video'"
        elif content_type == 'novideo':
            sql += " AND (lp.content_type != 'Video' OR lp.content_type IS NULL)"
        if search:
            sql += " AND (lp.post_title LIKE %s OR pp.post_title LIKE %s)"
            params += [f'%{search}%', f'%{search}%']
        sql += " ORDER BY COALESCE(pp.post_date, lp.post_date) DESC"

        rows = _safe(c, sql, params)
        if rows:
            for r in rows:
                all_posts.append({
                    'post_id':      r[0],
                    'title':        r[1],
                    'post_date':    r[2],
                    'link':         r[3] or '',
                    'content_type': r[4] or '',
                    'impressions':  r[5],
                    'likes':        r[6],
                    'comments':     r[7],
                    'shares':       r[8],
                    'clicks':       r[9],
                    'has_image':    bool(r[10]),
                    'views':        r[11],
                })

    return render(request, 'linkedin_statistics/stat_posts.html', {
        'all_posts':    all_posts,
        'content_type': content_type,
        'search':       search,
        'tab':          'posts',
    })
