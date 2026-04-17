"""
linkedin_statistics/views.py  –  KORRIGIERTE VERSION
Benutzt die richtigen Tabellen:
  - linkedin_posts_metrics  → impressions, clicks, likes, comments, direct_shares
  - linkedin_followers      → followers_total
  - linkedin_content_metrics → monatliche Gesamtzahlen (für Content-Chart)
  - linkedin_posts          → Stammdaten (post_id, post_title, post_date)
  - linkedin_posts_posted   → manuell gepflegtes post_date
"""
from datetime import date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
import json


def _default_from():
    return (date.today() - timedelta(days=30)).isoformat()

def _default_to():
    return date.today().isoformat()


def _get_overview_data(d_from, d_to):
    data = {
        'total_followers': '—',
        'followers_change': '—',
        'total_posts': '—',
        'total_impressions': '—',
        'total_engagement': '—',
        'top_posts': [],
        'content_chart_labels': [],
        'content_chart_impressions': [],
        'content_chart_engagement': [],
    }

    with connection.cursor() as cur:

        # ── Follower (aktuell + Änderung im Zeitraum) ─────────────────
        try:
            cur.execute("""
                SELECT followers_total
                FROM linkedin_followers
                ORDER BY date DESC LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                data['total_followers'] = row[0]

            # Follower-Veränderung im Zeitraum
            cur.execute("""
                SELECT
                    MAX(CASE WHEN date <= %s THEN followers_total END) AS f_end,
                    MAX(CASE WHEN date <= %s THEN followers_total END) AS f_start
                FROM linkedin_followers
                WHERE date BETWEEN DATE_SUB(%s, INTERVAL 7 DAY) AND %s
            """, [d_to, d_from, d_from, d_to])
            row = cur.fetchone()
            if row and row[0] and row[1]:
                delta = row[0] - row[1]
                data['followers_change'] = f"+{delta}" if delta >= 0 else str(delta)
        except Exception as e:
            data['followers_change'] = str(e)

        # ── Posts im Zeitraum (aus linkedin_posts) ────────────────────
        try:
            cur.execute("""
                SELECT COUNT(*) FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                WHERE COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
            """, [d_from, d_to])
            row = cur.fetchone()
            data['total_posts'] = row[0] if row else 0
        except Exception as e:
            # Fallback: alle Posts
            try:
                cur.execute("SELECT COUNT(*) FROM linkedin_posts")
                row = cur.fetchone()
                data['total_posts'] = f"~{row[0]}" if row else '—'
            except Exception:
                pass

        # ── Impressionen im Zeitraum (aus linkedin_posts_metrics) ─────
        try:
            cur.execute("""
                SELECT COALESCE(SUM(impressions), 0)
                FROM linkedin_posts_metrics
                WHERE metric_date BETWEEN %s AND %s
            """, [d_from, d_to])
            row = cur.fetchone()
            data['total_impressions'] = row[0] if row else 0
        except Exception as e:
            # Fallback: content_metrics
            try:
                cur.execute("""
                    SELECT COALESCE(SUM(impressions_total), 0)
                    FROM linkedin_content_metrics
                    WHERE metric_date BETWEEN %s AND %s
                """, [d_from, d_to])
                row = cur.fetchone()
                data['total_impressions'] = row[0] if row else '—'
            except Exception:
                pass

        # ── Engagement im Zeitraum ────────────────────────────────────
        try:
            cur.execute("""
                SELECT COALESCE(SUM(likes + comments + direct_shares), 0)
                FROM linkedin_posts_metrics
                WHERE metric_date BETWEEN %s AND %s
            """, [d_from, d_to])
            row = cur.fetchone()
            data['total_engagement'] = row[0] if row else 0
        except Exception as e:
            try:
                cur.execute("""
                    SELECT COALESCE(
                        SUM(reactions_total + comments_total + shares_direct_total), 0)
                    FROM linkedin_content_metrics
                    WHERE metric_date BETWEEN %s AND %s
                """, [d_from, d_to])
                row = cur.fetchone()
                data['total_engagement'] = row[0] if row else '—'
            except Exception:
                pass

        # ── Top 5 Posts nach Impressionen ─────────────────────────────
        try:
            cur.execute("""
                SELECT
                    lp.post_id,
                    COALESCE(lp.post_title, lp.post_id)        AS post_title,
                    COALESCE(pp.post_date, lp.post_date)        AS post_date,
                    COALESCE(lp.post_url, pp.post_link)         AS post_url,
                    COALESCE(SUM(m.impressions),   0)           AS impressions,
                    COALESCE(SUM(m.likes),         0)           AS likes,
                    COALESCE(SUM(m.comments),      0)           AS comments,
                    COALESCE(SUM(m.direct_shares), 0)           AS shares,
                    COALESCE(SUM(m.clicks),        0)           AS clicks
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp  ON lp.post_id = pp.post_id
                LEFT JOIN linkedin_posts_metrics m  ON lp.post_id = m.post_id
                GROUP BY lp.post_id, lp.post_title, post_date, post_url
                ORDER BY impressions DESC
                LIMIT 5
            """)
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
            data['top_posts'] = [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            data['top_posts'] = []

        # ── Content-Chart: Impressionen + Engagement-Rate nach Monat ──
        # Wie im Screenshot: linkedin_content_metrics
        try:
            cur.execute("""
                SELECT
                    DATE_FORMAT(metric_date, '%Y-%m')               AS month,
                    COALESCE(SUM(impressions_total), 0)             AS impressions,
                    COALESCE(AVG(engagement_rate_total) * 100, 0)   AS eng_rate
                FROM linkedin_content_metrics
                WHERE metric_date >= DATE_SUB(%s, INTERVAL 15 MONTH)
                GROUP BY month
                ORDER BY month ASC
            """, [d_to])
            rows = cur.fetchall()
            data['content_chart_labels']      = [r[0] for r in rows]
            data['content_chart_impressions'] = [float(r[1]) for r in rows]
            data['content_chart_engagement']  = [round(float(r[2]), 2) for r in rows]
        except Exception as e:
            # Fallback: aus linkedin_posts_metrics
            try:
                cur.execute("""
                    SELECT
                        DATE_FORMAT(metric_date, '%Y-%m')         AS month,
                        COALESCE(SUM(impressions), 0)             AS impressions,
                        COALESCE(AVG(engagement_rate) * 100, 0)  AS eng_rate
                    FROM linkedin_posts_metrics
                    GROUP BY month
                    ORDER BY month ASC
                """)
                rows = cur.fetchall()
                data['content_chart_labels']      = [r[0] for r in rows]
                data['content_chart_impressions'] = [float(r[1]) for r in rows]
                data['content_chart_engagement']  = [round(float(r[2]), 2) for r in rows]
            except Exception:
                pass

    return data


@login_required
def overview(request):
    d_from = request.GET.get('date_from', _default_from())
    d_to   = request.GET.get('date_to',   _default_to())

    data     = {}
    db_error = None
    try:
        data = _get_overview_data(d_from, d_to)
    except Exception as e:
        db_error = str(e)

    return render(request, 'linkedin_statistics/overview.html', {
        'active_tab': 'overview',
        'date_from':  d_from,
        'date_to':    d_to,
        'data':       data,
        'db_error':   db_error,
        'content_chart_json': json.dumps({
            'labels':      data.get('content_chart_labels', []),
            'impressions': data.get('content_chart_impressions', []),
            'engagement':  data.get('content_chart_engagement', []),
        }),
    })


@login_required
def timeline(request):
    d_from = request.GET.get('date_from', _default_from())
    d_to   = request.GET.get('date_to',   _default_to())
    search = request.GET.get('q', '').strip().lower()

    posts    = []
    db_error = None

    try:
        sql = """
            SELECT
                lp.post_id,
                COALESCE(lp.post_title, lp.post_id)     AS post_title,
                COALESCE(pp.post_date, lp.post_date)     AS post_date,
                COALESCE(lp.post_url, pp.post_link)      AS post_url,
                lp.content_type
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
        """
        with connection.cursor() as cur:
            cur.execute(sql, [d_from, d_to])
            cols = [c[0] for c in cur.description]
            posts = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        db_error = str(e)

    if search:
        posts = [p for p in posts if
                 search in (p.get('post_title') or '').lower() or
                 search in (p.get('post_id')    or '').lower()]

    return render(request, 'linkedin_statistics/timeline.html', {
        'active_tab': 'timeline',
        'date_from':  d_from,
        'date_to':    d_to,
        'search':     search,
        'posts':      posts,
        'db_error':   db_error,
    })


@login_required
def timeline_detail(request, post_id):
    group_by = request.GET.get('group_by', 'week')
    back_from = request.GET.get('back_from', _default_from())
    back_to   = request.GET.get('back_to',   _default_to())

    db_error   = None
    post       = None
    chart_data = None

    try:
        with connection.cursor() as cur:
            # Post-Stammdaten
            cur.execute("""
                SELECT
                    lp.post_id,
                    COALESCE(lp.post_title, lp.post_id)   AS post_title,
                    COALESCE(pp.post_date, lp.post_date)   AS post_date,
                    COALESCE(lp.post_url, pp.post_link)    AS post_url
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                WHERE lp.post_id = %s LIMIT 1
            """, [post_id])
            cols = [c[0] for c in cur.description]
            row  = cur.fetchone()
            if row:
                post = dict(zip(cols, row))

        # Metriken-Zeitreihe
        if group_by == 'week':
            period = "DATE_FORMAT(metric_date, '%x-W%v')"
            label  = "DATE_FORMAT(MIN(metric_date), '%d.%m.%Y')"
        elif group_by == 'month':
            period = "DATE_FORMAT(metric_date, '%Y-%m')"
            label  = "DATE_FORMAT(MIN(metric_date), '%m/%Y')"
        else:
            period = "DATE(metric_date)"
            label  = "DATE_FORMAT(MIN(metric_date), '%d.%m.%Y')"

        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    {period}                            AS period_key,
                    {label}                             AS label,
                    COALESCE(SUM(impressions),   0)     AS impressions,
                    COALESCE(SUM(clicks),        0)     AS clicks,
                    COALESCE(SUM(likes),         0)     AS likes,
                    COALESCE(SUM(comments),      0)     AS comments,
                    COALESCE(SUM(direct_shares), 0)     AS shares
                FROM linkedin_posts_metrics
                WHERE post_id = %s
                GROUP BY period_key
                ORDER BY period_key ASC
            """, [post_id])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        if rows:
            chart_data = {
                'labels':      [r['label']       for r in rows],
                'impressions': [r['impressions']  for r in rows],
                'clicks':      [r['clicks']       for r in rows],
                'likes':       [r['likes']        for r in rows],
                'comments':    [r['comments']     for r in rows],
                'shares':      [r['shares']       for r in rows],
            }
    except Exception as e:
        db_error = str(e)

    return render(request, 'linkedin_statistics/timeline_detail.html', {
        'active_tab':      'timeline',
        'post':            post,
        'group_by':        group_by,
        'chart_data_json': json.dumps(chart_data) if chart_data else 'null',
        'db_error':        db_error,
        'back_from':       back_from,
        'back_to':         back_to,
    })
