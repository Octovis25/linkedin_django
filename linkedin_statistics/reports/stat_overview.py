"""
Overview Report
Reads directly from existing DB tables via raw SQL
Tables used:
  - linkedin_followers
  - linkedin_visitors
  - linkedin_posts
  - linkedin_posts_posted
"""
from django.db import connection


def get_overview_data(date_from=None, date_to=None):
    """
    Returns dict with KPI card data from existing database tables
    """
    data = {}

    with connection.cursor() as cur:

        # ── Card 1: Latest total followers ──────────────────────────
        try:
            cur.execute("""
                SELECT followers_total
                FROM linkedin_followers
                ORDER BY date DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            data['total_followers'] = row[0] if row else '—'
        except Exception:
            data['total_followers'] = '—'

        # ── Follower growth (first vs last in range) ─────────────────
        try:
            cur.execute("""
                SELECT followers_total FROM linkedin_followers
                WHERE date >= %s ORDER BY date ASC LIMIT 1
            """, [date_from])
            first = cur.fetchone()

            cur.execute("""
                SELECT followers_total FROM linkedin_followers
                WHERE date <= %s ORDER BY date DESC LIMIT 1
            """, [date_to])
            last = cur.fetchone()

            if first and last and first[0] and first[0] > 0:
                growth = round(((last[0] - first[0]) / first[0]) * 100, 1)
                data['follower_growth'] = growth
            else:
                data['follower_growth'] = 0
        except Exception:
            data['follower_growth'] = 0

        # ── Card 2: Total posts ──────────────────────────────────────
        try:
            cur.execute("SELECT COUNT(*) FROM linkedin_posts_posted")
            row = cur.fetchone()
            data['total_posts'] = row[0] if row else 0
        except Exception:
            data['total_posts'] = '—'

        # ── Card 3: Total impressions ────────────────────────────────
        try:
            cur.execute("""
                SELECT COALESCE(SUM(impressions),0)
                FROM linkedin_posts_metrics
                WHERE metric_date >= %s AND metric_date <= %s
            """, [date_from, date_to])
            row = cur.fetchone()
            data['total_impressions'] = row[0] if row and row[0] else 0
        except Exception:
            # Fallback: try without date filter
            try:
                cur.execute("SELECT COALESCE(SUM(impressions),0) FROM linkedin_posts")
                row = cur.fetchone()
                data['total_impressions'] = row[0] if row and row[0] else '—'
            except Exception:
                data['total_impressions'] = '—'

        # ── Card 4: Total engagement ─────────────────────────────────
        try:
            cur.execute("""
                SELECT COALESCE(SUM(likes + comments + direct_shares),0)
                FROM linkedin_posts_metrics
                WHERE metric_date >= %s AND metric_date <= %s
            """, [date_from, date_to])
            row = cur.fetchone()
            data['total_engagement'] = row[0] if row and row[0] else 0
        except Exception:
            try:
                cur.execute("""
                    SELECT COALESCE(SUM(likes + comments + direct_shares),0)
                    FROM linkedin_posts_metrics
                """)
                row = cur.fetchone()
                data['total_engagement'] = row[0] if row and row[0] else '—'
            except Exception:
                data['total_engagement'] = '—'

        # ── Top 5 posts by impressions ───────────────────────────────
        try:
            cur.execute("""
                SELECT p.post_id, p.impressions, p.likes, p.comments, p.direct_shares,
                       pp.post_link, pp.post_date
                FROM linkedin_posts p
                LEFT JOIN linkedin_posts_posted pp ON p.post_id = pp.post_id
                ORDER BY p.impressions DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            data['top_posts'] = [
                {
                    'post_id': r[0],
                    'impressions': r[1] or 0,
                    'likes': r[2] or 0,
                    'comments': r[3] or 0,
                    'shares': r[4] or 0,
                    'post_link': r[5] or '',
                    'post_date': r[6],
                }
                for r in rows
            ]
        except Exception:
            data['top_posts'] = []

        # ── Follower chart data (last 12 months) ─────────────────────
        try:
            cur.execute("""
                SELECT DATE_FORMAT(date, '%Y-%m') as month,
                       MAX(followers_total) as count
                FROM linkedin_followers
                WHERE date >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
                GROUP BY month
                ORDER BY month ASC
            """)
            rows = cur.fetchall()
            data['follower_chart_labels'] = [r[0] for r in rows]
            data['follower_chart_values'] = [r[1] for r in rows]
        except Exception:
            data['follower_chart_labels'] = []
            data['follower_chart_values'] = []

    return data
