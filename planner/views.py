from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import connection
from django.views.decorators.http import require_POST
import json
import os
from django.conf import settings


def _safe(c, sql, params=None):
    try:
        c.execute(sql, params or [])
        return c.fetchall()
    except Exception as e:
        print("SQL error:", e)
        return []


@login_required
def planner_view(request):
    topic_filter = request.GET.get('topic', '')
    status_filter = request.GET.get('status', '')

    with connection.cursor() as c:
        # Topics laden
        topics = _safe(c, "SELECT id, name, color FROM planner_topics ORDER BY name")

        # Posts laden
        sql = """
            SELECT p.id, p.title, p.content, p.status, p.planned_date,
                   p.image, t.name, t.color, p.topic_id
            FROM planner_posts p
            LEFT JOIN planner_topics t ON p.topic_id = t.id
            WHERE 1=1
        """
        params = []
        if topic_filter:
            sql += " AND p.topic_id = %s"
            params.append(topic_filter)
        if status_filter:
            sql += " AND p.status = %s"
            params.append(status_filter)
        sql += " ORDER BY COALESCE(p.planned_date, '9999-12-31'), p.created_at DESC"
        posts = _safe(c, sql, params)

        # Ideas laden
        ideas = _safe(c, "SELECT id, text FROM planner_ideas ORDER BY created_at DESC")

    posts_list = [{
        'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
        'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
        'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
        'topic_id': r[8],
    } for r in posts]

    return render(request, 'planner/planner.html', {
        'topics': [{'id': r[0], 'name': r[1], 'color': r[2]} for r in topics],
        'posts': posts_list,
        'ideas': [{'id': r[0], 'text': r[1]} for r in ideas],
        'topic_filter': topic_filter,
        'status_filter': status_filter,
    })


@login_required
def api_planner_post(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        action = data.get('action')
        with connection.cursor() as c:
            if action == 'create':
                c.execute("""INSERT INTO planner_posts (topic_id, title, content, status, planned_date)
                             VALUES (%s, %s, %s, %s, %s)""",
                    [data.get('topic_id') or None, data.get('title'),
                     data.get('content'), data.get('status', 'Draft'),
                     data.get('planned_date') or None])
                post_id = c.lastrowid
                return JsonResponse({'ok': True, 'id': post_id})
            elif action == 'update':
                c.execute("""UPDATE planner_posts SET topic_id=%s, title=%s, content=%s,
                             status=%s, planned_date=%s WHERE id=%s""",
                    [data.get('topic_id') or None, data.get('title'),
                     data.get('content'), data.get('status'),
                     data.get('planned_date') or None, data.get('id')])
                return JsonResponse({'ok': True})
            elif action == 'delete':
                c.execute("DELETE FROM planner_posts WHERE id=%s", [data.get('id')])
                return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_planner_topic(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        action = data.get('action')
        with connection.cursor() as c:
            if action == 'create':
                c.execute("INSERT INTO planner_topics (name, color) VALUES (%s, %s)",
                          [data.get('name'), data.get('color', 'gray')])
                return JsonResponse({'ok': True, 'id': c.lastrowid})
            elif action == 'delete':
                c.execute("DELETE FROM planner_topics WHERE id=%s", [data.get('id')])
                return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_planner_idea(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        action = data.get('action')
        with connection.cursor() as c:
            if action == 'create':
                c.execute("INSERT INTO planner_ideas (text) VALUES (%s)", [data.get('text')])
                return JsonResponse({'ok': True, 'id': c.lastrowid})
            elif action == 'delete':
                c.execute("DELETE FROM planner_ideas WHERE id=%s", [data.get('id')])
                return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_planner_image(request, post_id):
    if request.method == 'POST':
        image = request.FILES.get('image')
        if image:
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'planner')
            os.makedirs(upload_dir, exist_ok=True)
            filename = f"post_{post_id}_{image.name}"
            path = os.path.join(upload_dir, filename)
            with open(path, 'wb+') as f:
                for chunk in image.chunks():
                    f.write(chunk)
            rel_path = f"planner/{filename}"
            with connection.cursor() as c:
                c.execute("UPDATE planner_posts SET image=%s WHERE id=%s", [rel_path, post_id])
            return JsonResponse({'ok': True, 'image': rel_path})
    return JsonResponse({'ok': False}, status=400)
