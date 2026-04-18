from django.db import connection

def get_all_posts(date_from=None, date_to=None):
    posts = []
    with connection.cursor() as cur:
        try:
            cur.execute("""
                SELECT lp.post_id,
                       COALESCE(lp.post_title, lp.post_id) AS post_title,
                       COALESCE(pp.post_date, lp.post_date) AS post_date,
                       lp.post_url,
                       lp.content_type,
                       COALESCE(m.impressions, 0) AS impressions,
                       COALESCE(m.likes, 0) AS likes,
                       COALESCE(m.comments, 0) AS comments,
                       COALESCE(m.direct_shares, 0) AS shares,
                       COALESCE(m.clicks, 0) AS clicks
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                LEFT JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id AND m.metric_date = latest.max_date
                WHERE latest.max_date IS NOT NULL OR m.id IS NULL
                ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
            """)
            rows = cur.fetchall()
            posts = [{
                'post_id': r[0], 'post_title': r[1], 'post_date': r[2],
                'post_link': r[3] or '', 'content_type': r[4] or '',
                'impressions': r[5], 'likes': r[6], 'comments': r[7],
                'shares': r[8], 'clicks': r[9],
                'engagement': r[6] + r[7] + r[8],
            } for r in rows]
        except:
            posts = []
    return posts
