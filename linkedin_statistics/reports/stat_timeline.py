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
                       COALESCE(SUM(m.impressions), 0) AS impressions,
                       COALESCE(SUM(m.likes), 0) AS likes,
                       COALESCE(SUM(m.comments), 0) AS comments,
                       COALESCE(SUM(m.direct_shares), 0) AS shares,
                       COALESCE(SUM(m.clicks), 0) AS clicks
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                GROUP BY lp.post_id, lp.post_title, post_date, lp.post_url, lp.content_type
                ORDER BY post_date DESC
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
