from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.db import connection
from django.views.decorators.csrf import csrf_exempt
import json
import os
import secrets
import urllib.parse
import urllib.request
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


def _posts_to_json(posts_list):
    """Safely serialize posts for embedding in a <script> block."""
    safe = []
    for p in posts_list:
        date = p['planned_date']
        safe.append({
            'id': p['id'],
            'title': p.get('title') or '',
            'content': p.get('content') or '',
            'status': p.get('status') or '',
            'date': date.strftime('%Y-%m-%d') if date else '',
            'comment': p.get('comment') or '',
            'image': p.get('image') or '',
            'topic_id': p.get('topic_id') or 0,
        })
    # Replace </ to prevent </script> injection
    return json.dumps(safe, ensure_ascii=False).replace('</', '<\\/')


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
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'],
        'tab': 'planner',
    })


@login_required
def pipeline_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, COALESCE(p.comment,'') as comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status IN ('Draft', 'Review') AND COALESCE(p.is_oj,0) = 0"""
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

    return render(request, 'planner/pipeline.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'pipeline', 'page_title': '→ Pipeline', 'posts_json': _posts_to_json(posts_list)})


@login_required
def ready_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Ready' AND p.in_pipeline = 1 AND COALESCE(p.is_oj,0) = 0"""
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

    return render(request, 'planner/ready.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'ready', 'page_title': '🚀 Ready to post', 'posts_json': _posts_to_json(posts_list)})


@login_required
def scheduled_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Scheduled' AND p.in_pipeline = 1 AND COALESCE(p.is_oj,0) = 0"""
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

    return render(request, 'planner/scheduled.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'scheduled', 'page_title': '📅 Scheduled', 'posts_json': _posts_to_json(posts_list)})


@login_required
def archive_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status IN ('Posted', 'Archive')"""
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

    return render(request, 'planner/archive.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'archive', 'page_title': '📦 Archive', 'posts_json': _posts_to_json(posts_list)})


@login_required
def all_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE COALESCE(p.is_oj,0) = 0"""
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
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'],
        'tab': 'all',
        'posts_json': _posts_to_json(posts_list),
    })


@login_required
def oj_view(request):
    with connection.cursor() as c:
        topics = _topics(c)
        # Check if is_oj column exists; fall back to empty list if not
        try:
            posts = _q(c, """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                                    p.image, t.name, t.color, p.topic_id, COALESCE(p.comment,'') as comment
                             FROM planner_posts p
                             LEFT JOIN planner_topics t ON p.topic_id = t.id
                             WHERE p.is_oj = 1
                             ORDER BY FIELD(p.status,'Draft','Review','Ready','Scheduled','Posted'),
                                      COALESCE(p.planned_date,'9999-12-31'), p.created_at""", [])
        except Exception:
            posts = []

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
        })

    return render(request, 'planner/oj.html', {
        'posts': posts_list,
        'topics': topics,
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'],
        'tab': 'oj',
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


def api_post(request):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'session_expired'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=400)
    data = json.loads(request.body)
    action = data.get('action')
    with connection.cursor() as c:
        if action == 'create':
            is_oj = 1 if data.get('is_oj') else 0
            base_params = [
                data.get('topic_id') or None, data.get('title'),
                data.get('content'), data.get('status', 'Draft'),
                data.get('planned_date') or None,
                data.get('series_id') or None,
                data.get('series_order', 0),
                data.get('comment') or None,
            ]
            try:
                c.execute("""INSERT INTO planner_posts
                            (topic_id, title, content, status, planned_date, series_id, series_order, comment, is_oj)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    base_params + [is_oj])
            except Exception:
                c.execute("""INSERT INTO planner_posts
                            (topic_id, title, content, status, planned_date, series_id, series_order, comment)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    base_params)
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


# ─────────────────────────────────────────────
#  LinkedIn API Connect
# ─────────────────────────────────────────────

LINKEDIN_AUTH_URL  = 'https://www.linkedin.com/oauth/v2/authorization'
LINKEDIN_TOKEN_URL = 'https://www.linkedin.com/oauth/v2/accessToken'
LINKEDIN_API_BASE  = 'https://api.linkedin.com/v2'
LINKEDIN_SCOPES    = 'openid profile w_member_social'


def _li_credentials_ok():
    return bool(getattr(settings, 'LINKEDIN_CLIENT_ID', None) and
                getattr(settings, 'LINKEDIN_CLIENT_SECRET', None))


def _li_get_token(request):
    with connection.cursor() as c:
        try:
            c.execute("""SELECT access_token, token_type, expires_at,
                                linkedin_person_id, linkedin_name, linkedin_picture,
                                org_id, org_name
                         FROM planner_linkedin_tokens WHERE user_id=%s""",
                      [request.user.id])
            row = c.fetchone()
        except Exception:
            return None
    if not row:
        return None
    return {'access_token': row[0], 'token_type': row[1], 'expires_at': row[2],
            'person_id': row[3], 'name': row[4], 'picture': row[5],
            'org_id': row[6], 'org_name': row[7]}


def _li_ensure_table():
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS planner_linkedin_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL UNIQUE,
            access_token TEXT,
            token_type VARCHAR(50) DEFAULT 'Bearer',
            expires_at BIGINT DEFAULT 0,
            linkedin_person_id VARCHAR(100),
            linkedin_name VARCHAR(200),
            linkedin_picture TEXT,
            org_id VARCHAR(100),
            org_name VARCHAR(200)
        )""")


def _li_fetch(url, token, method='GET', body=None):
    req = urllib.request.Request(url)
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Restli-Protocol-Version', '2.0.0')
    if body:
        req.method = 'POST'
        req.data = json.dumps(body).encode('utf-8')
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _superuser_only(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404
        return view_func(request, *args, **kwargs)
    return wrapped


@_superuser_only
def api_connect_view(request):
    _li_ensure_table()
    token    = _li_get_token(request)
    creds_ok = _li_credentials_ok()
    ready_posts = []
    with connection.cursor() as c:
        rows = _q(c, """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                               p.image, t.name, t.color
                        FROM planner_posts p
                        LEFT JOIN planner_topics t ON p.topic_id = t.id
                        WHERE p.status IN ('Ready','Scheduled')
                        AND COALESCE(p.is_oj,0) = 0
                        ORDER BY COALESCE(p.planned_date,'9999-12-31'), p.created_at""", [])
    for r in rows:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        ready_posts.append({'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
                            'status': r[3], 'planned_date': r[4], 'has_image': bool(r[5]),
                            'topic_name': r[6] or '', 'bg': bg, 'fg': fg})
    return render(request, 'planner/api_connect.html', {
        'tab': 'api_connect', 'token': token, 'creds_ok': creds_ok,
        'ready_posts': ready_posts,
        'posts_json': _posts_to_json(ready_posts),
    })


@_superuser_only
def linkedin_auth_start(request):
    if not _li_credentials_ok():
        return redirect('/planner/api-connect/')
    state = secrets.token_urlsafe(16)
    request.session['li_oauth_state'] = state
    redirect_uri = request.build_absolute_uri('/planner/linkedin/callback/')
    params = urllib.parse.urlencode({
        'response_type': 'code',
        'client_id': settings.LINKEDIN_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'state': state,
        'scope': LINKEDIN_SCOPES,
    })
    return redirect(f'{LINKEDIN_AUTH_URL}?{params}')


@_superuser_only
def linkedin_auth_callback(request):
    error = request.GET.get('error')
    if error:
        return redirect('/planner/api-connect/?error=' + urllib.parse.quote(error))
    code  = request.GET.get('code', '')
    state = request.GET.get('state', '')
    if state != request.session.get('li_oauth_state', ''):
        return redirect('/planner/api-connect/?error=state_mismatch')
    redirect_uri = request.build_absolute_uri('/planner/linkedin/callback/')
    try:
        data = urllib.parse.urlencode({
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': settings.LINKEDIN_CLIENT_ID,
            'client_secret': settings.LINKEDIN_CLIENT_SECRET,
        }).encode('utf-8')
        req = urllib.request.Request(LINKEDIN_TOKEN_URL, data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return redirect(f'/planner/api-connect/?error={urllib.parse.quote(str(e))}')
    import time
    access_token = token_data.get('access_token', '')
    expires_at   = int(time.time()) + token_data.get('expires_in', 3600)
    try:
        profile   = _li_fetch('https://api.linkedin.com/v2/userinfo', access_token)
        person_id = profile.get('sub', '')
        name      = profile.get('name', '')
        picture   = profile.get('picture', '')
    except Exception:
        person_id, name, picture = '', '', ''
    org_id, org_name = '', ''
    try:
        orgs = _li_fetch(
            'https://api.linkedin.com/v2/organizationAcls?q=roleAssignee&role=ADMINISTRATOR'
            '&projection=(elements*(organization~(id,localizedName)))', access_token)
        elems = orgs.get('elements', [])
        if elems:
            org = elems[0].get('organization~', {})
            org_id   = str(org.get('id', ''))
            org_name = org.get('localizedName', '')
    except Exception:
        pass
    _li_ensure_table()
    with connection.cursor() as c:
        c.execute("""INSERT INTO planner_linkedin_tokens
                        (user_id, access_token, expires_at, linkedin_person_id,
                         linkedin_name, linkedin_picture, org_id, org_name)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE
                        access_token=VALUES(access_token), expires_at=VALUES(expires_at),
                        linkedin_person_id=VALUES(linkedin_person_id),
                        linkedin_name=VALUES(linkedin_name),
                        linkedin_picture=VALUES(linkedin_picture),
                        org_id=VALUES(org_id), org_name=VALUES(org_name)""",
                  [request.user.id, access_token, expires_at,
                   person_id, name, picture, org_id, org_name])
    return redirect('/planner/api-connect/?connected=1')


@_superuser_only
def linkedin_disconnect(request):
    with connection.cursor() as c:
        try:
            c.execute("DELETE FROM planner_linkedin_tokens WHERE user_id=%s",
                      [request.user.id])
        except Exception:
            pass
    return redirect('/planner/api-connect/')


@_superuser_only
def linkedin_do_post(request, post_id):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'session_expired'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    token = _li_get_token(request)
    if not token or not token.get('access_token'):
        return JsonResponse({'ok': False, 'error': 'not_connected'}, status=401)
    data         = json.loads(request.body)
    target       = data.get('target', 'person')
    text         = data.get('text', '')
    include_img  = data.get('include_image', False)
    if target == 'org' and token.get('org_id'):
        author     = f"urn:li:organization:{token['org_id']}"
        post_token = token['access_token']
    else:
        author     = f"urn:li:person:{token['person_id']}"
        post_token = token['access_token']
    media = []
    if include_img:
        with connection.cursor() as c:
            rows = _q(c, "SELECT image FROM planner_posts WHERE id=%s", [post_id])
        if rows and rows[0][0]:
            try:
                reg = _li_fetch(f'{LINKEDIN_API_BASE}/assets?action=registerUpload',
                    post_token, method='POST', body={
                        'registerUploadRequest': {
                            'recipes': ['urn:li:digitalmediaRecipe:feedshare-image'],
                            'owner': author,
                            'serviceRelationships': [{'relationshipType': 'OWNER',
                                'identifier': 'urn:li:userGeneratedContent'}],
                        }})
                upload_url = (reg['value']['uploadMechanism']
                              ['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']
                              ['uploadUrl'])
                asset = reg['value']['asset']
                with connection.cursor() as c:
                    img_rows = _q(c, "SELECT image FROM planner_posts WHERE id=%s", [post_id])
                image_path = img_rows[0][0] if img_rows else None
                if image_path:
                    full_path = os.path.join(settings.MEDIA_ROOT, image_path)
                    with open(full_path, 'rb') as f:
                        img_bytes = f.read()
                    img_req = urllib.request.Request(upload_url, data=img_bytes, method='PUT')
                    img_req.add_header('Authorization', f'Bearer {post_token}')
                    img_req.add_header('Content-Type', 'image/jpeg')
                    urllib.request.urlopen(img_req)
                    media.append({'status': 'READY', 'media': asset})
            except Exception as e:
                print(f'LI image upload error: {e}')
    post_body = {
        'author': author,
        'lifecycleState': 'PUBLISHED',
        'specificContent': {
            'com.linkedin.ugc.ShareContent': {
                'shareCommentary': {'text': text},
                'shareMediaCategory': 'IMAGE' if media else 'NONE',
                'media': media,
            }
        },
        'visibility': {'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'},
    }
    try:
        result   = _li_fetch(f'{LINKEDIN_API_BASE}/ugcPosts', post_token,
                             method='POST', body=post_body)
        post_urn = result.get('id', '')
        with connection.cursor() as c:
            c.execute("UPDATE planner_posts SET status='Posted', in_pipeline=1 WHERE id=%s",
                      [post_id])
        return JsonResponse({'ok': True, 'post_urn': post_urn})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)
