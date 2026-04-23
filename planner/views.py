from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import connection
import json
import os
from django.conf import settings


def _q(c, sql, params=None):
    try:
        c.execute(sql, params or [])
        return c.fetchall()
    except Exception as e:
        print("SQL:", e)
        return []


def _topics(c):
    return [{'id': r[0], 'name': r[1], 'color': r[2]}
            for r in _q(c, "SELECT id, name, color FROM planner_topics ORDER BY name")]


COLOR_MAP = {
    'blue': ('#E6F1FB', '#185FA5'),
    'green': ('#E1F5EE', '#0F6E56'),
    'amber': ('#FAEEDA', '#633806'),
    'purple': ('#EEEDFE', '#3C3489'),
    'red': ('#FCEBEB', '#791F1F'),
    'gray': ('#f5f5f5', '#6c757d'),
}


@login_required
def planner_view(request):
    with connection.cursor() as c:
        topics = _topics(c)

        columns = []
        for t in topics:
            bg, fg = COLOR_MAP.get(t['color'], ('#f5f5f5', '#6c757d'))
            t['bg'] = bg
            t['fg'] = fg

            series = _q(c, """SELECT id, name FROM planner_series
                              WHERE topic_id=%s ORDER BY created_at""", [t['id']])

            series_list = []
            for s in series:
                parts = _q(c, """SELECT id, title, content, status, planned_date, image, series_order
                                 FROM planner_posts WHERE series_id=%s AND in_pipeline=0
                                 ORDER BY series_order""", [s[0]])
                series_list.append({
                    'id': s[0], 'name': s[1],
                    'parts': [{'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
                               'status': r[3], 'planned_date': r[4],
                               'image': r[5] or '', 'order': r[6]} for r in parts]
                })

            posts = _q(c, """SELECT id, title, content, status, planned_date, image
                             FROM planner_posts
                             WHERE topic_id=%s AND series_id IS NULL AND in_pipeline=0
                             ORDER BY COALESCE(planned_date,'9999-12-31'), created_at""", [t['id']])

            ideas = _q(c, """SELECT id, text FROM planner_ideas
                             WHERE topic_id=%s ORDER BY created_at DESC""", [t['id']])

            columns.append({
                'topic': t,
                'series': series_list,
                'posts': [{'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
                           'status': r[3], 'planned_date': r[4], 'image': r[5] or ''} for r in posts],
                'ideas': [{'id': r[0], 'text': r[1]} for r in ideas],
            })

    return render(request, 'planner/planner.html', {
        'columns': columns,
        'topics': topics,
        'statuses': ['Draft', 'Ready', 'Scheduled'],
        'tab': 'planner',
    })


@login_required
def pipeline_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.in_pipeline=1"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += " ORDER BY COALESCE(p.planned_date,'9999-12-31'), p.created_at"
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/pipeline.html', {
        'posts': posts_list,
        'topics': topics,
        'topic_filter': topic_filter,
        'statuses': ['Ready', 'Scheduled', 'Posted'],
        'tab': 'pipeline',
    })


@login_required
def api_post(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=400)
    data = json.loads(request.body)
    action = data.get('action')
    with connection.cursor() as c:
        if action == 'create':
            c.execute("""INSERT INTO planner_posts
                        (topic_id, title, content, status, planned_date, series_id, series_order, comment)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                [data.get('topic_id') or None, data.get('title'),
                 data.get('content'), data.get('status', 'Draft'),
                 data.get('planned_date') or None,
                 data.get('series_id') or None,
                 data.get('series_order', 0),
                 data.get('comment') or None])
            return JsonResponse({'ok': True, 'id': c.lastrowid})
        elif action == 'update':
            c.execute("""UPDATE planner_posts SET topic_id=%s, title=%s, content=%s,
                        status=%s, planned_date=%s, comment=%s WHERE id=%s""",
                [data.get('topic_id') or None, data.get('title'),
                 data.get('content'), data.get('status'),
                 data.get('planned_date') or None,
                 data.get('comment') or None, data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'delete':
            c.execute("DELETE FROM planner_posts WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'to_pipeline':
            c.execute("UPDATE planner_posts SET in_pipeline=1 WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'update_topic':
            c.execute("UPDATE planner_posts SET topic_id=%s WHERE id=%s",
                      [data.get('topic_id'), data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'from_pipeline':
            c.execute("UPDATE planner_posts SET in_pipeline=0 WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_series(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=400)
    data = json.loads(request.body)
    action = data.get('action')
    with connection.cursor() as c:
        if action == 'create':
            c.execute("INSERT INTO planner_series (name, topic_id) VALUES (%s,%s)",
                      [data.get('name'), data.get('topic_id') or None])
            return JsonResponse({'ok': True, 'id': c.lastrowid})
        elif action == 'delete':
            c.execute("DELETE FROM planner_posts WHERE series_id=%s", [data.get('id')])
            c.execute("DELETE FROM planner_series WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_topic(request):
    if request.method == 'GET':
        with connection.cursor() as c:
            cats = [{'id': r[0], 'name': r[1], 'color': r[2]}
                    for r in _q(c, "SELECT id, name, color FROM planner_topics ORDER BY name")]
        return JsonResponse({'categories': cats})
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=400)
    data = json.loads(request.body)
    action = data.get('action')
    with connection.cursor() as c:
        if action == 'create':
            c.execute("INSERT INTO planner_topics (name, color) VALUES (%s,%s)",
                      [data.get('name'), data.get('color', 'gray')])
            return JsonResponse({'ok': True, 'id': c.lastrowid})
        elif action == 'delete':
            c.execute("DELETE FROM planner_topics WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_idea(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=400)
    data = json.loads(request.body)
    action = data.get('action')
    with connection.cursor() as c:
        if action == 'create':
            c.execute("INSERT INTO planner_ideas (text, topic_id) VALUES (%s,%s)",
                      [data.get('text'), data.get('topic_id') or None])
            return JsonResponse({'ok': True, 'id': c.lastrowid})
        elif action == 'update':
            c.execute("UPDATE planner_ideas SET text=%s WHERE id=%s", [data.get('text'), data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'delete':
            c.execute("DELETE FROM planner_ideas WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_image(request, post_id):
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
