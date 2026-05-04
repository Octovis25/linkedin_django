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
ACCENT_MAP = {
    'blue': '#185FA5',
    'green': '#1D9E75',
    'amber': '#BA7517',
    'purple': '#7F77DD',
    'red': '#A32D2D',
    'gray': '#888780',
}


@login_required
def planner_view(request):
    with connection.cursor() as c:
        topics = _topics(c)
        topics_data = []
        for t in topics:
            bg, fg = COLOR_MAP.get(t['color'], ('#f5f5f5', '#6c757d'))
            accent = ACCENT_MAP.get(t['color'], '#888780')
            posts = _q(c, """SELECT id, title, content, status, planned_date, image, COALESCE(comment,'') as comment
                             FROM planner_posts
                             WHERE topic_id=%s
                             ORDER BY COALESCE(planned_date,'9999-12-31'), created_at""", [t['id']])
            ideas = _q(c, """SELECT id, text FROM planner_ideas
                             WHERE topic_id=%s ORDER BY created_at DESC""", [t['id']])
            topics_data.append({
                'id': t['id'], 'name': t['name'], 'color': t['color'],
                'bg': bg, 'fg': fg, 'accent': accent,
                'posts': [{'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
                           'status': r[3], 'planned_date': r[4],
                           'image': r[5] or '', 'comment': r[6] or ''} for r in posts],
                'ideas': [{'id': r[0], 'text': r[1]} for r in ideas],
            })

    return render(request, 'planner/planner.html', {
        'topics_data': topics_data,
        'topics': topics,
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'],
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
                 WHERE p.status IN ('Draft', 'Review')"""
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

    return render(request, 'planner/pipeline.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'], 'tab': 'pipeline', 'page_title': '→ Pipeline'})


@login_required
def ready_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Ready' AND p.in_pipeline = 1"""
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
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/ready.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'], 'tab': 'ready', 'page_title': '🚀 Ready to post'})


@login_required
def scheduled_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Scheduled' AND p.in_pipeline = 1"""
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
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/scheduled.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'], 'tab': 'scheduled', 'page_title': '📅 Scheduled'})


@login_required
def scheduled_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Scheduled' AND p.in_pipeline = 1"""
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
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/scheduled.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'], 'tab': 'scheduled', 'page_title': '📅 Scheduled'})


@login_required
def scheduled_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Scheduled' AND p.in_pipeline = 1"""
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
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/scheduled.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'], 'tab': 'scheduled', 'page_title': '📅 Scheduled'})


@login_required
def archive_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Posted' AND p.in_pipeline = 1"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += " ORDER BY COALESCE(p.planned_date,'9999-12-31') DESC, p.created_at DESC"
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/archive.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'], 'tab': 'archive', 'page_title': '📦 Archive'})


@login_required
def all_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE 1=1"""
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
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/all_posts.html', {
        'posts': posts_list,
        'topics': topics,
        'topic_filter': topic_filter,
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted'],
        'tab': 'all',
    })


@login_required
def planner_image(request, post_id):
    """Proxy: lädt Planner-Bild von Nextcloud"""
    from django.http import HttpResponse, Http404
    from posts_posted.nc_storage import download_image_from_nextcloud
    with connection.cursor() as c:
        rows = _q(c, "SELECT image FROM planner_posts WHERE id=%s", [post_id])
    if not rows or not rows[0][0]:
        raise Http404
    nc_path = rows[0][0]
    # Wenn lokaler Pfad (planner/...) → Nextcloud Pfad bauen
    if not nc_path.startswith('Marketing'):
        filename = nc_path.split('/')[-1]
        nc_path = f"Marketing & Design/LinkedIn/Statistics/data/Post-Bilder/image_ready/{filename}"
    content, ct = download_image_from_nextcloud(nc_path)
    if not content:
        raise Http404
    return HttpResponse(content, content_type=ct or 'image/jpeg')


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
            status = data.get('status')
            in_pipeline = 0 if status == 'Draft' else 1
            if 'in_pipeline' in data:
                in_pipeline = data.get('in_pipeline')
            c.execute("""UPDATE planner_posts SET topic_id=%s, title=%s, content=%s,
                        status=%s, planned_date=%s, comment=%s, in_pipeline=%s WHERE id=%s""",
                [data.get('topic_id') or None, data.get('title'),
                 data.get('content'), status,
                 data.get('planned_date') or None,
                 data.get('comment') or None, in_pipeline, data.get('id')])
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
        elif action == 'delete_image':
            c.execute("UPDATE planner_posts SET image=NULL WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'to_archive':
            c.execute("UPDATE planner_posts SET status='Posted', in_pipeline=1 WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'from_archive':
            c.execute("UPDATE planner_posts SET status='Scheduled', in_pipeline=1 WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'set_status':
            status = data.get('status')
            if status == 'Draft':
                in_pipeline = 0
            elif status == 'Review':
                in_pipeline = 1
            else:
                in_pipeline = 1
            c.execute("UPDATE planner_posts SET status=%s, in_pipeline=%s WHERE id=%s",
                      [status, in_pipeline, data.get('id')])
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
        elif action == 'rename':
            c.execute("UPDATE planner_topics SET name=%s WHERE id=%s",
                      [data.get('name'), data.get('id')])
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
            filename = f"post_{post_id}_{image.name}"
            try:
                from posts_posted.nc_storage import upload_image_to_nextcloud
                nc_path = upload_image_to_nextcloud(image, filename)
                if nc_path:
                    with connection.cursor() as c:
                        c.execute("UPDATE planner_posts SET image=%s WHERE id=%s", [nc_path, post_id])
                    return JsonResponse({'ok': True, 'image': nc_path})
            except Exception as e:
                print(f"NC image upload error: {e}")
            return JsonResponse({'ok': False, 'error': 'Upload failed'}, status=500)
    return JsonResponse({'ok': False}, status=400)
