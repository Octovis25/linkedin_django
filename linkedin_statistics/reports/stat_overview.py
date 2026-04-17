from django.db import connection

def get_overview_data(date_from=None, date_to=None):
    data = {}
    with connection.cursor() as cur:
        # Followers
        try:
            cur.execute("SELECT followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 1")
            row = cur.fetchone()
            data['total_followers'] = row[0] if row else 0
        except: data['total_followers'] = 0

        # Follower growth
        try:
            cur.execute("SELECT followers_total FROM linkedin_followers WHERE date >= %s ORDER BY date ASC LIMIT 1", [date_from])
            first = cur.fetchone()
            cur.execute("SELECT followers_total FROM linkedin_followers WHERE date <= %s ORDER BY date DESC LIMIT 1", [date_to])
            last = cur.fetchone()
            if first and last and first[0] and first[0] > 0:
                data['follower_growth'] = round(((last[0] - first[0]) / first[0]) * 100, 1)
            else: data['follower_growth'] = 0
        except: data['follower_growth'] = 0

        # Total posts
        try:
            cur.execute("SELECT COUNT(*) FROM linkedin_posts")
            row = cur.fetchone()
            data['total_posts'] = row[0] if row else 0
        except: data['total_posts'] = 0

        # Impressions from linkedin_posts_metrics
        try:
            cur.execute("SELECT COALESCE(SUM(impressions),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [date_from, date_to])
            row = cur.fetchone()
            data['total_impressions'] = row[0] if row else 0
        except: data['total_impressions'] = 0

        # Engagement from linkedin_posts_metrics
        try:
            cur.execute("SELECT COALESCE(SUM(likes + comments + direct_shares),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [date_from, date_to])
            row = cur.fetchone()
            data['total_engagement'] = row[0] if row else 0
        except: data['total_engagement'] = 0

        # Top 5 posts - JOIN with metrics table
        try:
            cur.execute("""
                SELECT lp.post_id,
                       COALESCE(lp.post_title, lp.post_id) AS post_title,
                       lp.post_date,
                       lp.post_url,
                       COALESCE(SUM(m.impressions), 0) AS impressions,
                       COALESCE(SUM(m.likes), 0) AS likes,
                       COALESCE(SUM(m.comments), 0) AS comments,
                       COALESCE(SUM(m.direct_shares), 0) AS shares
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                GROUP BY lp.post_id, lp.post_title, lp.post_date, lp.post_url
                ORDER BY impressions DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            data['top_posts'] = [{
                'post_id': r[0], 'post_title': r[1], 'post_date': r[2],
                'post_link': r[3] or '', 'impressions': r[4],
                'likes': r[5], 'comments': r[6], 'shares': r[7],
            } for r in rows]
        except: data['top_posts'] = []

        # Content Metrics Chart (Impressions + Engagement Rate per month)
        try:
            cur.execute("""
                SELECT DATE_FORMAT(metric_date, '%%Y-%%m') AS month,
                       COALESCE(SUM(impressions), 0) AS impressions,
                       COALESCE(AVG(engagement_rate) * 100, 0) AS eng_rate
                FROM linkedin_posts_metrics
                WHERE metric_date IS NOT NULL
                GROUP BY month
                ORDER BY month ASC
            """)
            rows = cur.fetchall()
            data['content_chart_labels'] = [r[0] for r in rows]
            data['content_chart_impressions'] = [int(r[1]) for r in rows]
            data['content_chart_engagement'] = [round(float(r[2]), 2) for r in rows]
        except:
            data['content_chart_labels'] = []
            data['content_chart_impressions'] = []
            data['content_chart_engagement'] = []

    return data
