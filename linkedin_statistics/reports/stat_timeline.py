"""
Post Timeline Report
Shows per-post performance metrics
Step 2 of statistics module
"""
from django.db import connection


def get_all_posts(date_from=None, date_to=None):
    """
    Returns list of all posts with their metrics
    """
    posts = []
    with connection.cursor() as cur:
        try:
            query = """
                SELECT p.post_id, p.impressions, p.likes, p.comments,
                       p.shares, p.clicks, p.date,
                       pp.post_link, pp.post_date
                FROM linkedin_posts p
                LEFT JOIN linkedin_posts_posted pp ON p.post_id = pp.post_id
                ORDER BY p.impressions DESC
            """
            cur.execute(query)
            rows = cur.fetchall()
            posts = [
                {
                    'post_id': r[0],
                    'impressions': r[1] or 0,
                    'likes': r[2] or 0,
                    'comments': r[3] or 0,
                    'shares': r[4] or 0,
                    'clicks': r[5] or 0,
                    'date': r[6],
                    'post_link': r[7] or '',
                    'post_date': r[8],
                    'engagement': (r[2] or 0) + (r[3] or 0) + (r[4] or 0),
                }
                for r in rows
            ]
        except Exception as e:
            posts = []
    return posts
