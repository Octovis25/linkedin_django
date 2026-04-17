#!/bin/bash
set -e
echo "=== SCHRITT 1: views.py direkt schreiben ==="

cat > linkedin_statistics/views.py << 'PYEOF'
from datetime import date
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
import json

@login_required
def overview(request):
    d_from = request.GET.get('date_from', '2024-01-01')
    d_to   = request.GET.get('date_to',   date.today().isoformat())
    data = {}
    db_error = None
    try:
        with connection.cursor() as cur:
            try:
                cur.execute("SELECT followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 1")
                row = cur.fetchone()
                data['total_followers'] = row[0] if row else '—'
            except: data['total_followers'] = '—'

            try:
                cur.execute("SELECT COUNT(*) FROM linkedin_posts")
                row = cur.fetchone()
                data['total_posts'] = row[0] if row else 0
            except: data['total_posts'] = '—'

            try:
                cur.execute("SELECT COALESCE(SUM(impressions),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [d_from, d_to])
                row = cur.fetchone()
                data['total_impressions'] = row[0] if row else 0
            except Exception as e: data['total_impressions'] = str(e)

            try:
                cur.execute("SELECT COALESCE(SUM(likes+comments+direct_shares),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [d_from, d_to])
                row = cur.fetchone()
                data['total_engagement'] = row[0] if row else 0
            except Exception as e: data['total_engagement'] = str(e)

            try:
                cur.execute("""
                    SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id) AS post_title,
                           lp.post_date, lp.post_url,
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
            except: data['top_posts'] = []

            try:
                cur.execute("""
                    SELECT DATE_FORMAT(metric_date,'%Y-%m') AS month,
                           COALESCE(SUM(impressions),0) AS impressions,
                           COALESCE(SUM(likes+comments+direct_shares),0) AS engagement
                    FROM linkedin_posts_metrics
                    WHERE metric_date IS NOT NULL
                    GROUP BY month ORDER BY month ASC
                """)
                rows = cur.fetchall()
                data['content_chart_labels']      = [r[0] for r in rows]
                data['content_chart_impressions'] = [float(r[1]) for r in rows]
                data['content_chart_engagement']  = [float(r[2]) for r in rows]
            except:
                data['content_chart_labels'] = []
                data['content_chart_impressions'] = []
                data['content_chart_engagement'] = []
    except Exception as e:
        db_error = str(e)

    return render(request, 'linkedin_statistics/overview.html', {
        'active_tab': 'overview', 'date_from': d_from, 'date_to': d_to,
        'data': data, 'db_error': db_error,
        'content_chart_json': json.dumps({
            'labels': data.get('content_chart_labels',[]),
            'impressions': data.get('content_chart_impressions',[]),
            'engagement': data.get('content_chart_engagement',[]),
        }),
    })

@login_required
def timeline(request):
    d_from = request.GET.get('date_from', '2024-01-01')
    d_to   = request.GET.get('date_to', date.today().isoformat())
    search = request.GET.get('q','').strip().lower()
    posts = []; db_error = None
    try:
        with connection.cursor() as cur:
            cur.execute("""
                SELECT lp.post_id,
                       COALESCE(lp.post_title, lp.post_id) AS post_title,
                       COALESCE(pp.post_date, lp.post_date) AS post_date,
                       COALESCE(lp.post_url, pp.post_link) AS post_url,
                       lp.content_type
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
            """)
            cols = [c[0] for c in cur.description]
            posts = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e: db_error = str(e)
    if search:
        posts = [p for p in posts if search in (p.get('post_title') or '').lower()]
    return render(request, 'linkedin_statistics/timeline.html', {
        'active_tab': 'timeline', 'date_from': d_from, 'date_to': d_to,
        'search': search, 'posts': posts, 'db_error': db_error,
    })

@login_required
def timeline_detail(request, post_id):
    group_by = request.GET.get('group_by','week')
    db_error = None; post = None; chart_data = None
    try:
        with connection.cursor() as cur:
            cur.execute("""
                SELECT lp.post_id, COALESCE(lp.post_title,lp.post_id) AS post_title,
                       COALESCE(pp.post_date,lp.post_date) AS post_date,
                       COALESCE(lp.post_url,pp.post_link) AS post_url
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id=pp.post_id
                WHERE lp.post_id=%s LIMIT 1
            """, [post_id])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            if row: post = dict(zip(cols, row))
        period = "DATE_FORMAT(metric_date,'%Y-%m')" if group_by=='month' else "DATE_FORMAT(metric_date,'%x-W%v')"
        label  = "DATE_FORMAT(MIN(metric_date),'%m/%Y')" if group_by=='month' else "DATE_FORMAT(MIN(metric_date),'%d.%m.%Y')"
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT {period} AS pk, {label} AS label,
                       COALESCE(SUM(impressions),0) AS impressions,
                       COALESCE(SUM(clicks),0) AS clicks,
                       COALESCE(SUM(likes),0) AS likes,
                       COALESCE(SUM(comments),0) AS comments,
                       COALESCE(SUM(direct_shares),0) AS shares
                FROM linkedin_posts_metrics WHERE post_id=%s AND metric_date IS NOT NULL
                GROUP BY pk ORDER BY pk ASC
            """, [post_id])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols,r)) for r in cur.fetchall()]
        if rows:
            chart_data = {
                'labels': [r['label'] for r in rows],
                'impressions': [r['impressions'] for r in rows],
                'clicks': [r['clicks'] for r in rows],
                'likes': [r['likes'] for r in rows],
                'comments': [r['comments'] for r in rows],
                'shares': [r['shares'] for r in rows],
            }
    except Exception as e: db_error = str(e)
    return render(request, 'linkedin_statistics/timeline_detail.html', {
        'active_tab': 'timeline', 'post': post, 'group_by': group_by,
        'chart_data_json': json.dumps(chart_data) if chart_data else 'null',
        'db_error': db_error,
    })
PYEOF

echo "✅ views.py geschrieben"

echo ""
echo "=== SCHRITT 2: Alle alten .sh-Dateien loeschen ==="
find . -maxdepth 1 -name "*.sh" -not -name "DEPLOY_NOW.sh" -delete
echo "✅ .sh-Dateien geloescht"

echo ""
echo "=== SCHRITT 3: Commit & Push ==="
git add -A
git commit -m "fix: statistics views neu + alte sh-Dateien bereinigt"
git push

echo ""
echo "=== FERTIG ==="
