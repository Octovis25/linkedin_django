from datetime import date
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
import json

@login_required
def overview(request):
    d_from = request.GET.get('date_from', '2024-01-01')
    d_to   = request.GET.get('date_to', date.today().isoformat())
    
    data = {
        'total_followers': 0,
        'total_posts': 0,
        'total_impressions': 0,
        'total_engagement': 0,
        'top_posts': [],
        'content_chart_labels': [],
        'content_chart_impressions': [],
        'content_chart_engagement': [],
    }
    
    with connection.cursor() as cur:
        # Followers
        cur.execute("SELECT followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 1")
        row = cur.fetchone()
        if row: data['total_followers'] = row[0]
        
        # Posts
        cur.execute("SELECT COUNT(*) FROM linkedin_posts")
        row = cur.fetchone()
        if row: data['total_posts'] = row[0]
        
        # Impressionen
        cur.execute("SELECT COALESCE(SUM(impressions),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [d_from, d_to])
        row = cur.fetchone()
        if row: data['total_impressions'] = row[0]
        
        # Engagement
        cur.execute("SELECT COALESCE(SUM(likes+comments+direct_shares),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [d_from, d_to])
        row = cur.fetchone()
        if row: data['total_engagement'] = row[0]
        
        # Top Posts
        cur.execute("""
            SELECT lp.post_id, 
                   COALESCE(lp.post_title, lp.post_id) AS title,
                   lp.post_date,
                   lp.post_url,
                   COALESCE(SUM(m.impressions),0) AS impressions,
                   COALESCE(SUM(m.likes),0) AS likes,
                   COALESCE(SUM(m.comments),0) AS comments,
                   COALESCE(SUM(m.direct_shares),0) AS shares
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            GROUP BY lp.post_id, lp.post_title, lp.post_date, lp.post_url
            ORDER BY impressions DESC LIMIT 5
        """)
        cols = [c[0] for c in cur.description]
        data['top_posts'] = [dict(zip(cols, r)) for r in cur.fetchall()]
        
        # Chart
        cur.execute("""
            SELECT DATE_FORMAT(metric_date,'%Y-%m') AS month,
                   COALESCE(SUM(impressions),0) AS impressions,
                   COALESCE(SUM(likes+comments+direct_shares),0) AS engagement
            FROM linkedin_posts_metrics
            WHERE metric_date IS NOT NULL
            GROUP BY month ORDER BY month ASC
        """)
        rows = cur.fetchall()
        data['content_chart_labels'] = [r[0] for r in rows]
        data['content_chart_impressions'] = [int(r[1]) for r in rows]
        data['content_chart_engagement'] = [int(r[2]) for r in rows]
    
    return render(request, 'linkedin_statistics/overview.html', {
        'date_from': d_from,
        'date_to': d_to,
        'data': data,
        'chart_json': json.dumps({
            'labels': data['content_chart_labels'],
            'impressions': data['content_chart_impressions'],
            'engagement': data['content_chart_engagement'],
        }),
    })

@login_required
def timeline(request):
    posts = []
    with connection.cursor() as cur:
        cur.execute("""
            SELECT lp.post_id, 
                   COALESCE(lp.post_title, lp.post_id) AS title,
                   COALESCE(pp.post_date, lp.post_date) AS post_date,
                   lp.post_url
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
        """)
        cols = [c[0] for c in cur.description]
        posts = [dict(zip(cols, r)) for r in cur.fetchall()]
    
    return render(request, 'linkedin_statistics/timeline.html', {'posts': posts})

@login_required
def timeline_detail(request, post_id):
    post = None
    chart_data = None
    
    with connection.cursor() as cur:
        cur.execute("""
            SELECT lp.post_id, COALESCE(lp.post_title,lp.post_id) AS title,
                   lp.post_date, lp.post_url
            FROM linkedin_posts lp WHERE lp.post_id=%s
        """, [post_id])
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        if row: post = dict(zip(cols, row))
        
        cur.execute("""
            SELECT DATE_FORMAT(metric_date,'%Y-%m') AS month,
                   COALESCE(SUM(impressions),0) AS impressions,
                   COALESCE(SUM(clicks),0) AS clicks,
                   COALESCE(SUM(likes),0) AS likes
            FROM linkedin_posts_metrics WHERE post_id=%s AND metric_date IS NOT NULL
            GROUP BY month ORDER BY month ASC
        """, [post_id])
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols,r)) for r in cur.fetchall()]
        if rows:
            chart_data = {
                'labels': [r['month'] for r in rows],
                'impressions': [r['impressions'] for r in rows],
                'clicks': [r['clicks'] for r in rows],
                'likes': [r['likes'] for r in rows],
            }
    
    return render(request, 'linkedin_statistics/timeline_detail.html', {
        'post': post,
        'chart_json': json.dumps(chart_data) if chart_data else 'null',
    })
