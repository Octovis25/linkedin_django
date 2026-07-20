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
import urllib.error
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


def _ensure_media_columns():
    """Ensure image/video media columns used by the planner exist."""
    with connection.cursor() as c:
        try:
            c.execute("ALTER TABLE planner_posts ADD COLUMN video_nc_path VARCHAR(512) DEFAULT NULL")
        except Exception:
            pass


def _attach_video_paths(posts_list):
    """Attach video_nc_path to already built post dictionaries without changing legacy SELECTs."""
    if not posts_list:
        return posts_list
    _ensure_media_columns()
    ids = [p.get('id') for p in posts_list if p.get('id')]
    if not ids:
        return posts_list
    placeholders = ','.join(['%s'] * len(ids))
    with connection.cursor() as c:
        try:
            c.execute(f"SELECT id, COALESCE(video_nc_path,'') FROM planner_posts WHERE id IN ({placeholders})", ids)
            rows = c.fetchall()
        except Exception:
            rows = []
    vid_map = {r[0]: (r[1] or '') for r in rows}
    for p in posts_list:
        p['video_nc_path'] = vid_map.get(p.get('id'), '')
    return posts_list


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
            'video_nc_path': p.get('video_nc_path') or '',
            'video': p.get('video_nc_path') or '',
            'topic_id': p.get('topic_id') or 0,
            'is_oj': bool(p.get('is_oj', False)),
            'link': p.get('link') or '',
            'linkedin_posted': bool(p.get('linkedin_posted', False)),
            'post_scheduled_at': p.get('post_scheduled_at_fmt') or '',
            'time': str(p.get('planned_time') or ''),
            'updated_at': (p.get('updated_at').strftime('%d.%m.%Y %H:%M')
                           if p.get('updated_at') and hasattr(p.get('updated_at'), 'strftime')
                           else (str(p.get('updated_at')) if p.get('updated_at') else '')),
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


def _ensure_aufgaben_table():
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS claude_aufgaben (
            id INT AUTO_INCREMENT PRIMARY KEY,
            aufgabe TEXT NOT NULL,
            typ VARCHAR(50) DEFAULT 'text',
            status VARCHAR(20) DEFAULT 'offen',
            ergebnis LONGTEXT,
            post_id INT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            done_at DATETIME
        )""")


@login_required
def aufgaben_view(request):
    _ensure_aufgaben_table()
    return render(request, 'planner/aufgaben.html')


@csrf_exempt
@login_required
def aufgaben_api(request):
    _ensure_aufgaben_table()
    if request.method == 'GET':
        status = request.GET.get('status', '')
        sql = "SELECT id, aufgabe, typ, status, ergebnis, post_id, created_at, done_at FROM claude_aufgaben"
        params = []
        if status:
            sql += " WHERE status=%s"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT 50"
        with connection.cursor() as c:
            c.execute(sql, params)
            rows = c.fetchall()
        return JsonResponse({'aufgaben': [
            {'id': r[0], 'aufgabe': r[1], 'typ': r[2], 'status': r[3],
             'ergebnis': r[4] or '', 'post_id': r[5], 'created_at': str(r[6] or ''), 'done_at': str(r[7] or '')}
            for r in rows
        ]})
    elif request.method == 'POST':
        data = json.loads(request.body)
        action = data.get('action', 'create')
        if action == 'create':
            aufgabe = data.get('aufgabe', '').strip()
            typ = data.get('typ', 'text')
            post_id = data.get('post_id')
            if not aufgabe:
                return JsonResponse({'error': 'Aufgabe darf nicht leer sein'}, status=400)
            with connection.cursor() as c:
                c.execute("INSERT INTO claude_aufgaben (aufgabe, typ, post_id) VALUES (%s, %s, %s)",
                          [aufgabe, typ, post_id])
                return JsonResponse({'ok': True, 'id': c.lastrowid})
        elif action == 'delete':
            with connection.cursor() as c:
                c.execute("DELETE FROM claude_aufgaben WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'update_status':
            with connection.cursor() as c:
                c.execute("UPDATE claude_aufgaben SET status=%s WHERE id=%s",
                          [data.get('status', 'offen'), data.get('id')])
            return JsonResponse({'ok': True})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def planner_view(request):
    with connection.cursor() as c:
        topics = _topics(c)
        topics_data = []
        for t in topics:
            bg, fg = COLOR_MAP.get(t['color'], ('#f5f5f5', '#6c757d'))
            accent = ACCENT_MAP.get(t['color'], '#888780')
            posts = _q(c, """SELECT id, title, content, status, planned_date, image, COALESCE(comment,'') as comment,
                                    COALESCE(link,'') as link, planned_time
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
                           'image': r[5] or '', 'comment': r[6] or '',
                           'link': r[7] or '', 'planned_time': r[8]} for r in posts],
                'ideas': [{'id': r[0], 'text': r[1]} for r in ideas],
            })

    return render(request, 'planner/planner.html', {
        'topics_data': topics_data,
        'topics': topics,
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'],
        'tab': 'planner',
    })


@login_required
def draft_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, COALESCE(p.comment,'') as comment,
                        COALESCE(p.link,'') as link, p.planned_time, p.updated_at, p.created_at
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Draft' AND COALESCE(p.is_oj,0) = 0"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += " ORDER BY p.updated_at DESC, p.created_at DESC"
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
            'link': r[10] or '', 'planned_time': r[11], 'updated_at': r[12],
            'created_at': r[13],
        })

    _attach_video_paths(posts_list)
    li_token = _li_get_superuser_token()
    return render(request, 'planner/draft.html', {
        'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter,
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'],
        'tab': 'draft', 'page_title': '✏️ Draft',
        'posts_json': _posts_to_json(posts_list),
        'li_connected': bool(li_token),
        'li_org': li_token.get('org_name', '') if li_token else '',
    })


@login_required
def pipeline_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, COALESCE(p.comment,'') as comment,
                        p.created_at, p.updated_at, COALESCE(p.link,'') as link,
                        p.planned_time
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Review' AND COALESCE(p.is_oj,0) = 0"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += " ORDER BY p.updated_at DESC"
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
            'created_at': r[10], 'updated_at': r[11], 'link': r[12] or '',
            'planned_time': r[13],
        })

    _attach_video_paths(posts_list)
    return render(request, 'planner/pipeline.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'pipeline', 'page_title': '→ Pipeline', 'posts_json': _posts_to_json(posts_list), 'allow_create': True})


@login_required
def ready_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment,
                        p.created_at, p.updated_at
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Ready' AND p.in_pipeline = 1 AND COALESCE(p.is_oj,0) = 0"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += " ORDER BY p.updated_at DESC, p.created_at DESC"
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
            'created_at': r[10], 'updated_at': r[11],
        })

    _attach_video_paths(posts_list)
    return render(request, 'planner/ready.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'ready', 'page_title': '🚀 Ready to post', 'posts_json': _posts_to_json(posts_list)})


@login_required
def scheduled_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        # Ensure linkedin_posted column exists
        try:
            c.execute("ALTER TABLE planner_posts ADD COLUMN linkedin_posted TINYINT(1) NOT NULL DEFAULT 0")
        except Exception:
            pass
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment,
                        COALESCE(p.linkedin_posted,0), COALESCE(p.link,'') as link,
                        p.post_scheduled_at, p.planned_time,
                        p.created_at, p.updated_at
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status = 'Scheduled' AND p.in_pipeline = 1 AND COALESCE(p.is_oj,0) = 0"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += """
                 ORDER BY
                   CASE
                     WHEN p.post_scheduled_at IS NOT NULL THEN p.post_scheduled_at
                     WHEN p.planned_date IS NOT NULL THEN TIMESTAMP(p.planned_date, COALESCE(p.planned_time, '00:00:00'))
                     ELSE '9999-12-31 23:59:59'
                   END ASC,
                   p.created_at ASC
              """
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        sched_at = r[12]
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
            'linkedin_posted': bool(r[10]), 'is_oj': False, 'link': r[11] or '',
            'post_scheduled_at': sched_at,
            'post_scheduled_at_fmt': sched_at.strftime('%d.%m.%Y %H:%M') if sched_at else '',
            'planned_time': r[13],
            'created_at': r[14], 'updated_at': r[15],
        })
    li_token = _li_get_superuser_token()
    _attach_video_paths(posts_list)
    return render(request, 'planner/scheduled.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'scheduled', 'page_title': '📅 Scheduled', 'posts_json': _posts_to_json(posts_list), 'li_connected': bool(li_token), 'li_org': li_token.get('org_name','') if li_token else ''})


@login_required
def archive_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment,
                        p.updated_at, p.created_at
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE p.status IN ('Posted', 'Archive')"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += " ORDER BY p.updated_at DESC, p.created_at DESC"
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
            'updated_at': r[10], 'created_at': r[11],
        })

    _attach_video_paths(posts_list)
    return render(request, 'planner/archive.html', {'posts': posts_list, 'topics': topics, 'topic_filter': topic_filter, 'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'], 'tab': 'archive', 'page_title': '📦 Archive', 'posts_json': _posts_to_json(posts_list)})


@login_required
def all_view(request):
    topic_filter = request.GET.get('topic', '')
    with connection.cursor() as c:
        topics = _topics(c)
        sql = """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                        p.image, t.name, t.color, p.topic_id, p.comment,
                        p.created_at, p.updated_at
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 WHERE COALESCE(p.is_oj,0) = 0"""
        params = []
        if topic_filter:
            sql += " AND p.topic_id=%s"
            params.append(topic_filter)
        sql += " ORDER BY p.updated_at DESC, p.created_at DESC"
        posts = _q(c, sql, params)

    posts_list = []
    for r in posts:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts_list.append({
            'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
            'status': r[3], 'planned_date': r[4], 'image': r[5] or '',
            'topic_name': r[6] or '', 'topic_color': r[7] or 'gray',
            'topic_id': r[8], 'comment': r[9] or '', 'bg': bg, 'fg': fg,
            'created_at': r[10], 'updated_at': r[11],
        })

    _attach_video_paths(posts_list)
    return render(request, 'planner/all_posts.html', {
        'posts': posts_list,
        'topics': topics,
        'topic_filter': topic_filter,
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'],
        'tab': 'all',
        'posts_json': _posts_to_json(posts_list),
    })


@login_required
def uebersicht_view(request):
    """Gesamtübersicht: alle Posts (vergangen, aktuell, zukünftig) in einer
    durchsuchbaren, sortierbaren Liste. Reine Lese-Anzeige; Anlegen und
    Status-Wechsel laufen über den bestehenden Endpunkt /planner/api/post/.
    """
    # 'Planned' ist die Planungsstufe (Redaktionsplan): Slot eingeplant, Inhalt
    # noch nicht erstellt. Steht bewusst vor 'Draft'.
    STATUSES = ['Planned', 'Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive']
    STATUS_LABEL = {s: s for s in STATUSES}
    STATUS_STYLE = {
        'Planned': ('#E4F3F1', '#0E7C86'), 'Draft': ('#f5f5f5', '#6c757d'),
        'Review': ('#EEEDFE', '#3C3489'), 'Ready': ('#E1F5EE', '#0F6E56'),
        'Scheduled': ('#FAEEDA', '#854F0B'), 'Posted': ('#E6F1FB', '#185FA5'),
        'Archive': ('#f5f5f5', '#6c757d'),
    }
    with connection.cursor() as c:
        topics = _topics(c)
        _ensure_media_columns()
        rows = _q(c, """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                               p.image, t.name, t.color, p.topic_id, COALESCE(p.comment,''),
                               p.planned_time, COALESCE(p.video_nc_path,''), COALESCE(p.link,'')
                        FROM planner_posts p
                        LEFT JOIN planner_topics t ON p.topic_id = t.id
                        WHERE COALESCE(p.is_oj,0) = 0
                        ORDER BY COALESCE(p.planned_date,'9999-12-31') DESC, p.created_at DESC""")

        # Fallback-Bild + -Link aus den Buffer-Daten (über planner_post_id),
        # falls der Post im Planner selbst kein Bild/keinen Link gespeichert hat.
        buf = {}
        try:
            c.execute("""SELECT planner_post_id,
                                MAX(NULLIF(thumbnail_url,'')),
                                MAX(NULLIF(linkedin_url,''))
                         FROM buffer_posts_posted
                         WHERE planner_post_id IS NOT NULL
                         GROUP BY planner_post_id""")
            for pid, th, lu in c.fetchall():
                buf[pid] = (th or '', lu or '')
        except Exception:
            buf = {}

    posts = []
    edit_map = {}
    for r in rows:
        tbg, tfg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        st = r[3] or 'Draft'
        sbg, sfg = STATUS_STYLE.get(st, ('#f5f5f5', '#6c757d'))
        pdate = r[4].strftime('%Y-%m-%d') if r[4] else ''
        ptime = r[10].strftime('%H:%M') if r[10] else ''
        bthumb, blink = buf.get(r[0], ('', ''))
        # Bildquelle: Planner-Bild bevorzugt, sonst Buffer-Thumbnail.
        img_url = ('/planner/image/%d/' % r[0]) if r[5] else (bthumb or '')
        link = (r[12] or '') or blink
        posts.append({
            'id': r[0], 'title': r[1] or '(untitled)', 'content': r[2] or '',
            'status': st, 'status_label': STATUS_LABEL.get(st, st),
            'status_bg': sbg, 'status_fg': sfg,
            'planned_date': r[4], 'img_url': img_url,
            'topic_name': r[6] or '', 'topic_bg': tbg, 'topic_fg': tfg,
            'topic_id': r[8] or '', 'planned_time': r[10],
            'has_video': bool(r[11]), 'link': link,
        })
        # Vollstaendige Werte fuer die Inline-Bearbeitung (verhindert das
        # Ueberschreiben nicht editierter Felder beim update).
        edit_map[r[0]] = {
            'title': r[1] or '', 'content': r[2] or '', 'status': st,
            'planned_date': pdate, 'planned_time': ptime,
            'topic_id': r[8] or '', 'comment': r[9] or '', 'link': r[12] or '',
        }

    status_choices = [(s, STATUS_LABEL.get(s, s)) for s in STATUSES]
    return render(request, 'planner/uebersicht.html', {
        'posts': posts,
        'topics': topics,
        'status_choices': status_choices,
        'edit_map': edit_map,
        'tab': 'uebersicht',
        'page_title': '📋 Overview',
    })


@login_required
def oj_view(request):
    with connection.cursor() as c:
        topics = _topics(c)
        # Check if is_oj column exists; fall back to empty list if not
        try:
            c.execute("ALTER TABLE planner_posts ADD COLUMN linkedin_posted TINYINT(1) NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            posts = _q(c, """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                                    p.image, t.name, t.color, p.topic_id, COALESCE(p.comment,'') as comment,
                                    COALESCE(p.linkedin_posted,0)
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
            'linkedin_posted': bool(r[10]), 'is_oj': True,
        })

    _attach_video_paths(posts_list)
    li_token = _li_get_superuser_token()
    return render(request, 'planner/oj.html', {
        'posts': posts_list,
        'topics': topics,
        'statuses': ['Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive'],
        'tab': 'oj',
        'posts_json': _posts_to_json(posts_list),
        'li_connected': bool(li_token),
        'li_org': li_token.get('org_name', '') if li_token else '',
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
        nc_path = f"Marketing & Design/LinkedIn/Planner/Images/{filename}"
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
            try:
                link_sent = data.get('link')  # None = leer (JS sendet null wenn leer)
                link_val = (link_sent or '').strip() or None  # '' → None, URL → URL
                pt = data.get('planned_time') or None
                c.execute("""UPDATE planner_posts SET topic_id=%s, title=%s, content=%s,
                            status=%s, planned_date=%s, planned_time=%s, comment=%s, link=%s, in_pipeline=%s WHERE id=%s""",
                    [data.get('topic_id') or None, data.get('title'),
                     data.get('content'), status,
                     data.get('planned_date') or None, pt,
                     data.get('comment') or None,
                     link_val, in_pipeline, data.get('id')])
            except Exception as e:
                return JsonResponse({'ok': False, 'error': str(e)})
            return JsonResponse({'ok': True})
        elif action == 'delete':
            pid = data.get('id')
            # Falls der Post über Buffer geplant wurde: zuerst in Buffer löschen.
            buffer_deleted = None
            buffer_error = None
            buf_post_id = None
            try:
                c.execute("SELECT buffer_update_id FROM planner_posts WHERE id=%s", [pid])
                brow = c.fetchone()
                buf_post_id = brow[0] if brow else None
                if buf_post_id:
                    tok = _li_get_superuser_token()
                    if tok and tok.get('buffer_token'):
                        _buffer_delete_post(tok['buffer_token'], buf_post_id)
                        buffer_deleted = True
                    else:
                        buffer_error = 'kein Buffer-Token konfiguriert'
            except Exception as _be:
                print("Buffer delete on post-delete error:", _be)
                buffer_deleted = False
                buffer_error = str(_be)
            # Zugehörige Mediendateien mitlöschen (Posted-Beiträge werden geschont).
            try: _delete_post_media(c, pid, keep=None)
            except Exception as _me: print("media delete on post-delete:", _me)
            c.execute("DELETE FROM planner_posts WHERE id=%s", [pid])
            return JsonResponse({'ok': True, 'buffer_deleted': buffer_deleted,
                                 'buffer_error': buffer_error, 'had_buffer_id': bool(buf_post_id)})
        elif action == 'to_pipeline':
            c.execute("UPDATE planner_posts SET in_pipeline=1 WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'update_topic':
            c.execute("UPDATE planner_posts SET topic_id=%s WHERE id=%s",
                      [data.get('topic_id'), data.get('id')])
            return JsonResponse({'ok': True})
        elif action in ('delete_image', 'delete_video', 'delete_media'):
            # Ein Medium pro Post: Datei(en) in Nextcloud löschen (Posted geschont)
            # und alle drei Medien-Spalten leeren.
            _ensure_media_columns()
            _delete_post_media(c, data.get('id'), keep=None)
            try:
                c.execute("UPDATE planner_posts SET image=NULL, gif_nc_path=NULL, video_nc_path=NULL WHERE id=%s", [data.get('id')])
            except Exception:
                c.execute("UPDATE planner_posts SET image=NULL, video_nc_path=NULL WHERE id=%s", [data.get('id')])
            return JsonResponse({'ok': True})
        elif action == 'set_video':
            # Link an existing Nextcloud video to this post (no upload).
            _ensure_media_columns()
            nc_path = (data.get('video_nc_path') or '').strip()
            if not nc_path:
                return JsonResponse({'ok': False, 'error': 'video_nc_path fehlt'}, status=400)
            # Studio-Ausgabe → in den Planner/Videos-Ordner verschieben (keine Kopie).
            nc_path = _move_studio_output_to_planner(nc_path, PLANNER_VIDEOS_FOLDER)
            # Ein Medium pro Post: bisherige Medien (außer der neuen Datei) löschen.
            _delete_post_media(c, data.get('id'), keep=nc_path)
            c.execute(
                "UPDATE planner_posts SET video_nc_path=%s, image=NULL, gif_nc_path=NULL WHERE id=%s",
                [nc_path, data.get('id')]
            )
            return JsonResponse({'ok': True, 'nc_path': nc_path})
        elif action == 'set_image':
            # Ein bestehendes Nextcloud-/Studio-Bild an den Post hängen (kein Upload).
            _ensure_media_columns()
            nc_path = (data.get('image_nc_path') or '').strip()
            if not nc_path:
                return JsonResponse({'ok': False, 'error': 'image_nc_path fehlt'}, status=400)
            # Studio-Ausgabe → in den Planner/Images-Ordner verschieben (keine Kopie).
            nc_path = _move_studio_output_to_planner(nc_path, PLANNER_IMAGES_FOLDER)
            # Ein Medium pro Post: bisherige Medien (außer der neuen Datei) löschen.
            _delete_post_media(c, data.get('id'), keep=nc_path)
            c.execute(
                "UPDATE planner_posts SET image=%s, video_nc_path=NULL, gif_nc_path=NULL WHERE id=%s",
                [nc_path, data.get('id')]
            )
            return JsonResponse({'ok': True, 'nc_path': nc_path})
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
        elif action == 'cancel_linkedin':
            pid = data.get('id')
            # Geplanten Post auch in Buffer löschen, sonst wird er trotzdem gepostet.
            buffer_deleted = None
            buffer_error = None
            buf_post_id = None
            try:
                c.execute("SELECT buffer_update_id FROM planner_posts WHERE id=%s", [pid])
                brow = c.fetchone()
                buf_post_id = brow[0] if brow else None
                if buf_post_id:
                    tok = _li_get_superuser_token()
                    if tok and tok.get('buffer_token'):
                        _buffer_delete_post(tok['buffer_token'], buf_post_id)
                        buffer_deleted = True
                    else:
                        buffer_error = 'kein Buffer-Token konfiguriert'
            except Exception as _be:
                print("Buffer delete on cancel error:", _be)
                buffer_deleted = False
                buffer_error = str(_be)
            # Planung zurücksetzen + Buffer-ID entfernen (Post bleibt in Django).
            try:
                c.execute("UPDATE planner_posts SET post_scheduled_at=NULL, buffer_update_id=NULL WHERE id=%s", [pid])
            except Exception:
                c.execute("UPDATE planner_posts SET post_scheduled_at=NULL WHERE id=%s", [pid])
            return JsonResponse({'ok': True, 'buffer_deleted': buffer_deleted,
                                 'buffer_error': buffer_error, 'had_buffer_id': bool(buf_post_id)})
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
    _ensure_media_columns()
    if request.method == 'POST':
        image = request.FILES.get('image')
        if image:
            filename = f"post_{post_id}_{image.name}"
            try:
                from posts_posted.nc_storage import upload_image_to_nextcloud
                nc_path = upload_image_to_nextcloud(image, filename)
                if nc_path:
                    with connection.cursor() as c:
                        c.execute("UPDATE planner_posts SET image=%s, video_nc_path=NULL WHERE id=%s", [nc_path, post_id])
                    return JsonResponse({'ok': True, 'image': nc_path})
            except Exception as e:
                print(f"NC image upload error: {e}")
            return JsonResponse({'ok': False, 'error': 'Upload failed'}, status=500)
    return JsonResponse({'ok': False}, status=400)


def _ensure_scheduled_at_column():
    """Add post_scheduled_at DATETIME column if it doesn't exist yet."""
    with connection.cursor() as c:
        try:
            c.execute("ALTER TABLE planner_posts ADD COLUMN post_scheduled_at DATETIME NULL DEFAULT NULL")
        except Exception:
            pass


def _make_image_token(post_id):
    """Generate a signed token for public image access (no auth required)."""
    import hmac as _hmac, hashlib as _hashlib
    secret = (getattr(settings, 'SECRET_KEY', 'fallback'))[:32]
    return _hmac.new(secret.encode(), str(post_id).encode(), _hashlib.sha256).hexdigest()[:24]


def _public_base_url():
    """Public base URL used for media URLs that Buffer must fetch from the internet."""
    return getattr(settings, 'PUBLIC_BASE_URL', 'https://linkedin-django-wd7a.onrender.com').rstrip('/')


def _public_image_url(post_id):
    """Build the public image URL for Buffer."""
    img_token = _make_image_token(post_id)
    return f"{_public_base_url()}/planner/public-image/{post_id}/{img_token}/"


def _make_video_token(post_id):
    """Generate a signed token for public video access via Render streaming proxy."""
    import hmac as _hmac, hashlib as _hashlib
    secret = (getattr(settings, 'SECRET_KEY', 'fallback'))[:32]
    return _hmac.new(secret.encode(), f"video-{post_id}".encode(), _hashlib.sha256).hexdigest()[:24]


def _temp_video_dir():
    """Local temporary folder used to serve videos quickly to Buffer."""
    return getattr(settings, 'BUFFER_VIDEO_TEMP_DIR', '/tmp/buffer_videos')


def _temp_video_url(post_id):
    """Build the temporary local video URL for Buffer."""
    video_token = _make_video_token(post_id)
    return f"{_public_base_url()}/planner/temp-video/{post_id}/{video_token}/"


def _cleanup_temp_videos(max_age_seconds=7200):
    """Delete temporary Buffer video files older than max_age_seconds."""
    import time as _time
    import glob as _glob

    temp_dir = _temp_video_dir()
    os.makedirs(temp_dir, exist_ok=True)
    now = _time.time()

    for path in _glob.glob(os.path.join(temp_dir, "post_*")):
        try:
            if os.path.isfile(path) and now - os.path.getmtime(path) > max_age_seconds:
                os.remove(path)
        except Exception as e:
            print(f"temp video cleanup error: {e}")


def _video_content_type(filename):
    """Return a reasonable video content type from filename."""
    lower_name = str(filename or "").lower()
    if lower_name.endswith(".mov"):
        return "video/quicktime"
    if lower_name.endswith(".webm"):
        return "video/webm"
    if lower_name.endswith(".m4v"):
        return "video/x-m4v"
    return "video/mp4"


def _get_video_nc_path(post_id):
    """Read and normalize the Nextcloud video path for one post."""
    _ensure_media_columns()
    with connection.cursor() as c:
        c.execute("SELECT video_nc_path FROM planner_posts WHERE id=%s", [post_id])
        row = c.fetchone()

    if not row or not row[0]:
        raise Exception("Kein Video für diesen Post gespeichert.")

    nc_path = row[0]
    if not nc_path.startswith("Marketing"):
        filename = nc_path.split("/")[-1]
        nc_path = f"Marketing & Design/LinkedIn/Planner/Videos/{filename}"
    return nc_path


def _prepare_temp_video(post_id):
    """
    Copy the video from Nextcloud into a local temporary file before sending the URL to Buffer.

    Buffer then receives a fast local Render URL instead of a live Nextcloud proxy.
    """
    import requests as _req
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote as _q2
    from requests.auth import HTTPBasicAuth as _BA

    _cleanup_temp_videos()

    nc_path = _get_video_nc_path(post_id)
    original_filename = nc_path.split("/")[-1]
    safe_filename = original_filename.replace(" ", "_").replace("/", "_").replace("\\", "_")
    local_filename = f"post_{post_id}_{safe_filename}"
    temp_dir = _temp_video_dir()
    os.makedirs(temp_dir, exist_ok=True)

    local_path = os.path.join(temp_dir, local_filename)
    part_path = local_path + ".part"

    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        raise Exception("Nextcloud nicht verbunden")

    download_url = f"{nc_url}/remote.php/dav/files/{username}/{_q2(nc_path, safe='/')}"

    try:
        with _req.get(download_url, auth=_BA(username, password), stream=True, timeout=(10, 300)) as r:
            if r.status_code != 200:
                raise Exception(f"Nextcloud Video Download HTTP {r.status_code}: {r.text[:200]}")
            with open(part_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        if not os.path.exists(part_path) or os.path.getsize(part_path) <= 0:
            raise Exception("Temporäre Videodatei ist leer.")

        os.replace(part_path, local_path)
        return local_path
    finally:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except Exception:
            pass


def _upload_video_to_cloudinary(post_id):
    """
    Copy the post's video from Nextcloud to a local temp file, then upload it to
    Cloudinary and return the permanent public URL. Buffer can fetch this URL
    reliably (also for scheduled posts), unlike the Render temp-video URL.

    Requires env vars: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET.
    """
    import requests as _req
    import time as _time, hashlib as _hashlib

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.environ.get("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
    if not all([cloud_name, api_key, api_secret]):
        raise Exception("Cloudinary ist nicht konfiguriert (CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET fehlen).")

    # 1) Video lokal aus Nextcloud holen (vorhandene Logik, WebDAV mit Login).
    local_path = _prepare_temp_video(post_id)

    # 2) Signierten Upload an Cloudinary vorbereiten.
    timestamp = str(int(_time.time()))
    # Eindeutiger Name je Upload → Cloudinary liefert nie eine alte, gecachte Version.
    public_id = f"linkedin_post_{post_id}_{timestamp}"
    # Signatur: alle Parameter (außer file/api_key) alphabetisch, mit api_secret gehasht.
    to_sign = f"public_id={public_id}&timestamp={timestamp}{api_secret}"
    signature = _hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

    # Cloudinary-Video-Upload akzeptiert KEIN GIF. Animierte GIFs daher über den
    # Bild-Endpunkt hochladen und als MP4 ausliefern (Cloudinary konvertiert das
    # animierte GIF on-the-fly), damit LinkedIn ein echtes Video bekommt.
    is_gif = local_path.lower().endswith(".gif")
    endpoint = "image" if is_gif else "video"
    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/{endpoint}/upload"
    with open(local_path, "rb") as f:
        files = {"file": f}
        data = {
            "api_key": api_key,
            "timestamp": timestamp,
            "public_id": public_id,
            "signature": signature,
        }
        r = _req.post(upload_url, data=data, files=files, timeout=300)

    if r.status_code not in (200, 201):
        raise Exception(f"Cloudinary Upload HTTP {r.status_code}: {r.text[:300]}")

    result = r.json()
    secure_url = result.get("secure_url")
    if not secure_url:
        raise Exception("Cloudinary lieferte keine URL: " + json.dumps(result)[:300])
    # Animiertes GIF → als MP4 ausliefern (Dateiendung tauschen).
    if is_gif and secure_url.lower().endswith(".gif"):
        secure_url = secure_url[:-4] + ".mp4"
    return secure_url


def _upload_image_to_cloudinary(post_id):
    """
    Download the post's image from Nextcloud and upload it to Cloudinary,
    returning the permanent public URL. Same reasoning as the video variant:
    Buffer can fetch this reliably, unlike the Render public-image URL.
    """
    import requests as _req
    import time as _time, hashlib as _hashlib
    from posts_posted.nc_storage import download_image_from_nextcloud

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.environ.get("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
    if not all([cloud_name, api_key, api_secret]):
        raise Exception("Cloudinary ist nicht konfiguriert (CLOUDINARY_* fehlen).")

    # Bildpfad holen + von Nextcloud laden.
    with connection.cursor() as c:
        c.execute("SELECT image FROM planner_posts WHERE id=%s", [post_id])
        row = c.fetchone()
    if not row or not row[0]:
        raise Exception("Kein Bild für diesen Post gespeichert.")
    nc_path = row[0]
    if not nc_path.startswith("Marketing"):
        filename = nc_path.split("/")[-1]
        nc_path = f"Marketing & Design/LinkedIn/Planner/Images/{filename}"

    img_content, img_content_type = download_image_from_nextcloud(nc_path)
    if not img_content:
        raise Exception("Bild konnte nicht von Nextcloud geladen werden.")

    timestamp = str(int(_time.time()))
    # Eindeutiger Name je Upload → Cloudinary liefert nie eine alte, gecachte Version.
    public_id = f"linkedin_post_img_{post_id}_{timestamp}"
    to_sign = f"public_id={public_id}&timestamp={timestamp}{api_secret}"
    signature = _hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    files = {"file": ("image", img_content, img_content_type or "image/jpeg")}
    data = {
        "api_key": api_key,
        "timestamp": timestamp,
        "public_id": public_id,
        "signature": signature,
    }
    r = _req.post(upload_url, data=data, files=files, timeout=120)
    if r.status_code not in (200, 201):
        raise Exception(f"Cloudinary Image Upload HTTP {r.status_code}: {r.text[:300]}")

    result = r.json()
    secure_url = result.get("secure_url")
    if not secure_url:
        raise Exception("Cloudinary lieferte keine Bild-URL: " + json.dumps(result)[:300])
    return secure_url


def _upload_video_to_nextcloud(video_file, post_id):
    """Upload one video file into the Planner/Videos folder and return its Nextcloud path."""
    import requests as _req, time as _time
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote as _q2
    from requests.auth import HTTPBasicAuth as _BA

    suffix = os.path.splitext(video_file.name)[1] or '.mp4'
    filename = f"video_{post_id}_{int(_time.time())}{suffix}"
    nc_folder = "Marketing & Design/LinkedIn/Planner/Videos"
    nc_path = f"{nc_folder}/{filename}"

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        raise Exception('Nextcloud nicht verbunden')

    video_bytes = video_file.read()
    upload_url = f"{nc_url}/remote.php/dav/files/{username}/{_q2(nc_path, safe='/')}"
    r = _req.put(
        upload_url,
        data=video_bytes,
        auth=_BA(username, password),
        headers={'Content-Type': video_file.content_type or 'video/mp4'},
        timeout=120
    )
    if r.status_code not in [200, 201, 204]:
        raise Exception(f'NC HTTP {r.status_code}: {r.text[:200]}')

    return nc_path


def _list_nc_folder_media(nc_folder, exts):
    """
    List files with the given extensions in a Nextcloud folder via WebDAV PROPFIND.
    Returns a list of dicts: {'filename', 'nc_path'}. Newest first by name.
    """
    import requests as _req
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote as _q2, unquote as _unq
    from requests.auth import HTTPBasicAuth as _BA
    import xml.etree.ElementTree as _ET

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        raise Exception('Nextcloud nicht verbunden')

    dav_url = f"{nc_url}/remote.php/dav/files/{username}/{_q2(nc_folder, safe='/')}/"
    body = (
        '<?xml version="1.0"?>'
        '<d:propfind xmlns:d="DAV:"><d:prop>'
        '<d:displayname/><d:getcontenttype/><d:getlastmodified/>'
        '</d:prop></d:propfind>'
    )
    r = _req.request(
        'PROPFIND', dav_url,
        data=body,
        auth=_BA(username, password),
        headers={'Depth': '1', 'Content-Type': 'application/xml'},
        timeout=30,
    )
    if r.status_code not in (207, 200):
        raise Exception(f'NC PROPFIND HTTP {r.status_code}: {r.text[:200]}')

    results = []
    root = _ET.fromstring(r.content)
    ns = {'d': 'DAV:'}
    for resp in root.findall('d:response', ns):
        href_el = resp.find('d:href', ns)
        if href_el is None or not href_el.text:
            continue
        href = _unq(href_el.text)
        filename = href.rstrip('/').split('/')[-1]
        if not filename or not filename.lower().endswith(tuple(exts)):
            continue
        results.append({'filename': filename, 'nc_path': f"{nc_folder}/{filename}"})

    results.sort(key=lambda x: x['filename'], reverse=True)
    return results


def _list_nextcloud_videos():
    """List video files in the Nextcloud Planner/Videos folder."""
    return _list_nc_folder_media(
        "Marketing & Design/LinkedIn/Planner/Videos",
        ('.mp4', '.mov', '.webm', '.m4v', '.avi'))


# Studio-Ausgaben (bewegte Medien) aus Studio_Work/Output.
STUDIO_OUTPUT_VIDEOS = "Marketing & Design/Octotrial_Assets/Studio_Work/Output/Videos"
STUDIO_OUTPUT_GIFS   = "Marketing & Design/Octotrial_Assets/Studio_Work/Output/GIFs"


def _list_studio_outputs():
    """List moving Studio outputs (Videos + GIFs) from Studio_Work/Output."""
    out = []
    for folder, exts in ((STUDIO_OUTPUT_VIDEOS, ('.mp4', '.mov', '.webm', '.m4v', '.avi')),
                         (STUDIO_OUTPUT_GIFS, ('.gif',))):
        try:
            out.extend(_list_nc_folder_media(folder, exts))
        except Exception as e:
            print("studio outputs list:", folder, e)
    out.sort(key=lambda x: x['filename'], reverse=True)
    return out


@login_required
def api_nc_videos(request):
    """JSON endpoint: list available videos in the Nextcloud Planner/Videos folder."""
    try:
        return JsonResponse({'ok': True, 'videos': _list_nextcloud_videos()})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def api_studio_outputs(request):
    """JSON endpoint: list moving Studio outputs (Videos + GIFs)."""
    try:
        return JsonResponse({'ok': True, 'videos': _list_studio_outputs()})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


# Statische Studio-Bilder aus Studio_Work/Output/Images.
STUDIO_OUTPUT_IMAGES = "Marketing & Design/Octotrial_Assets/Studio_Work/Output/Images"


def _list_studio_images():
    """List static Studio image outputs from Studio_Work/Output/Images."""
    try:
        return _list_nc_folder_media(STUDIO_OUTPUT_IMAGES, ('.png', '.jpg', '.jpeg', '.webp'))
    except Exception as e:
        print("studio images list:", e)
        return []


@login_required
def api_studio_images(request):
    """JSON endpoint: list static Studio image outputs."""
    try:
        return JsonResponse({'ok': True, 'images': _list_studio_images()})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


STUDIO_OUTPUT_PREFIX = "Marketing & Design/Octotrial_Assets/Studio_Work/Output/"
PLANNER_IMAGES_FOLDER = "Marketing & Design/LinkedIn/Planner/Images"
PLANNER_VIDEOS_FOLDER = "Marketing & Design/LinkedIn/Planner/Videos"


def _nc_move(src_nc_path, dst_nc_path):
    """WebDAV MOVE a file within Nextcloud. Returns dst_nc_path on success, else None."""
    import requests as _req
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote as _q2
    from requests.auth import HTTPBasicAuth as _BA
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None
    base = f"{nc_url}/remote.php/dav/files/{username}/"
    src = base + _q2(src_nc_path, safe='/')
    dst = base + _q2(dst_nc_path, safe='/')
    try:
        r = _req.request('MOVE', src, auth=_BA(username, password),
                         headers={'Destination': dst, 'Overwrite': 'T'}, timeout=30)
        if r.status_code in (200, 201, 204):
            return dst_nc_path
        print("nc move failed", r.status_code, r.text[:200])
    except Exception as e:
        print("nc move error", e)
    return None


def _move_studio_output_to_planner(nc_path, dest_folder):
    """Studio-Ausgaben aus Studio_Work/Output in den Planner-Ordner verschieben,
    damit die Datei beim Post liegt (keine Kopie)."""
    if not nc_path or not nc_path.startswith(STUDIO_OUTPUT_PREFIX):
        return nc_path
    fname = nc_path.rsplit('/', 1)[-1]
    moved = _nc_move(nc_path, f"{dest_folder}/{fname}")
    return moved or nc_path


def _nc_delete(nc_path):
    """Eine Datei in Nextcloud löschen (WebDAV DELETE). True bei Erfolg/nicht vorhanden."""
    if not nc_path:
        return False
    import requests as _req
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote as _q2
    from requests.auth import HTTPBasicAuth as _BA
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False
    url = f"{nc_url}/remote.php/dav/files/{username}/{_q2(nc_path, safe='/')}"
    try:
        r = _req.request('DELETE', url, auth=_BA(username, password), timeout=30)
        return r.status_code in (200, 204, 404)
    except Exception as e:
        print("nc delete error:", e)
        return False


def _delete_post_media(c, post_id, keep=None):
    """Alle am Post hängenden Mediendateien (Bild/GIF/Video) aus Nextcloud löschen,
    außer `keep`. Bereits gepostete Beiträge werden geschont (Dateien bleiben)."""
    _ensure_media_columns()
    try:
        c.execute("""SELECT COALESCE(image,''), COALESCE(gif_nc_path,''),
                            COALESCE(video_nc_path,''), COALESCE(status,'')
                     FROM planner_posts WHERE id=%s""", [post_id])
    except Exception:
        c.execute("SELECT COALESCE(image,''), '', COALESCE(video_nc_path,''), COALESCE(status,'') FROM planner_posts WHERE id=%s", [post_id])
    row = c.fetchone()
    if not row:
        return
    img, gif, vid, status = row[0], row[1], row[2], row[3]
    if (status or '').lower() == 'posted':
        return   # veröffentlichte Beiträge schonen
    for p in (img, gif, vid):
        if p and p != keep:
            _nc_delete(p)


@login_required
def nc_video_preview(request, filename):
    """
    Stream a single video from the Nextcloud Planner/Videos folder for in-browser
    preview. Range-aware so the HTML5 player can seek. Only serves files from the
    fixed Planner/Videos folder (filename only — no path traversal).
    """
    from django.http import HttpResponse, StreamingHttpResponse
    import requests as _req
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote as _q2
    from requests.auth import HTTPBasicAuth as _BA

    # Security: strip any path components, allow only a bare filename.
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename or '..' in safe_name:
        return HttpResponse(status=400)
    if not safe_name.lower().endswith(('.mp4', '.mov', '.webm', '.m4v', '.avi')):
        return HttpResponse(status=400)

    nc_path = f"Marketing & Design/LinkedIn/Planner/Videos/{safe_name}"
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return HttpResponse(status=500)

    download_url = f"{nc_url}/remote.php/dav/files/{username}/{_q2(nc_path, safe='/')}"

    headers = {}
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        upstream = _req.get(download_url, auth=_BA(username, password),
                            headers=headers, stream=True, timeout=(10, 120))
    except Exception as e:
        print(f"nc_video_preview upstream error: {e}")
        return HttpResponse(status=504)

    if upstream.status_code not in (200, 206):
        upstream.close()
        return HttpResponse(status=404)

    content_type = _video_content_type(safe_name)

    def stream_chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    response = StreamingHttpResponse(
        stream_chunks(),
        status=206 if upstream.status_code == 206 else 200,
        content_type=content_type,
    )
    cl = upstream.headers.get("Content-Length")
    cr = upstream.headers.get("Content-Range")
    if cl:
        response["Content-Length"] = cl
    if cr:
        response["Content-Range"] = cr
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = f'inline; filename="{safe_name}"'
    return response


def public_image(request, post_id, token):
    """Serve a post image publicly using a signed token — used by Buffer."""
    from django.http import HttpResponse

    if token != _make_image_token(post_id):
        return HttpResponse(status=403)

    with connection.cursor() as c:
        c.execute("SELECT image FROM planner_posts WHERE id=%s", [post_id])
        row = c.fetchone()

    if not row or not row[0]:
        return HttpResponse(status=404)

    try:
        from posts_posted.nc_storage import download_image_from_nextcloud

        nc_path = row[0]

        # If the DB only stores a short/local path like planner/post_2_x.jpg,
        # convert it to the real Nextcloud folder path.
        if not nc_path.startswith("Marketing"):
            filename = nc_path.split("/")[-1]
            nc_path = f"Marketing & Design/LinkedIn/Planner/Images/{filename}"

        img_content, img_content_type = download_image_from_nextcloud(nc_path)

        if img_content:
            return HttpResponse(
                img_content,
                content_type=img_content_type or "image/jpeg"
            )

    except Exception as e:
        print(f"public_image error: {e}")

    return HttpResponse(status=404)



def temp_video(request, post_id, token):
    """
    Serve the locally cached temporary video to Buffer.

    This view deliberately does not fetch from Nextcloud during Buffer validation.
    """
    from django.http import HttpResponse, StreamingHttpResponse
    import glob as _glob

    if token != _make_video_token(post_id):
        return HttpResponse(status=403)

    temp_dir = _temp_video_dir()
    pattern = os.path.join(temp_dir, f"post_{post_id}_*")
    candidates = [p for p in _glob.glob(pattern) if os.path.isfile(p) and not p.endswith(".part")]

    if not candidates:
        return HttpResponse(status=404)

    local_path = max(candidates, key=os.path.getmtime)
    file_size = os.path.getsize(local_path)
    if file_size <= 0:
        return HttpResponse(status=404)

    filename = os.path.basename(local_path)
    content_type = _video_content_type(filename)

    range_header = request.headers.get("Range")
    start = 0
    end = file_size - 1
    status = 200

    if range_header:
        try:
            units, rng = range_header.split("=", 1)
            if units.strip().lower() == "bytes":
                start_s, end_s = rng.split("-", 1)
                if start_s:
                    start = int(start_s)
                if end_s:
                    end = int(end_s)
                end = min(end, file_size - 1)
                if start > end or start >= file_size:
                    resp = HttpResponse(status=416)
                    resp["Content-Range"] = f"bytes */{file_size}"
                    return resp
                status = 206
        except Exception:
            start = 0
            end = file_size - 1
            status = 200

    length = end - start + 1

    def file_iterator(path, start_byte, bytes_to_send, chunk_size=1024 * 1024):
        with open(path, "rb") as f:
            f.seek(start_byte)
            remaining = bytes_to_send
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    response = StreamingHttpResponse(file_iterator(local_path, start, length), status=status, content_type=content_type)
    response["Content-Length"] = str(length)
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "public, max-age=3600"
    if status == 206:
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return response



def public_video(request, post_id, token):
    """
    Legacy live Nextcloud video proxy. Prefer temp_video() for Buffer.

    Important:
    - Do NOT download the full video into Django memory first.
    - Stream from Nextcloud to Buffer so Buffer gets video/mp4 quickly.
    """
    from django.http import HttpResponse, StreamingHttpResponse
    import requests as _req
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote as _q2
    from requests.auth import HTTPBasicAuth as _BA

    if token != _make_video_token(post_id):
        return HttpResponse(status=403)

    _ensure_media_columns()
    with connection.cursor() as c:
        c.execute("SELECT video_nc_path FROM planner_posts WHERE id=%s", [post_id])
        row = c.fetchone()

    if not row or not row[0]:
        return HttpResponse(status=404)

    nc_path = row[0]
    if not nc_path.startswith("Marketing"):
        filename = nc_path.split("/")[-1]
        nc_path = f"Marketing & Design/LinkedIn/Planner/Videos/{filename}"
    else:
        filename = nc_path.split("/")[-1]

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return HttpResponse(status=500)

    download_url = f"{nc_url}/remote.php/dav/files/{username}/{_q2(nc_path, safe='/')}"

    headers = {}
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        upstream = _req.get(
            download_url,
            auth=_BA(username, password),
            headers=headers,
            stream=True,
            timeout=(10, 120)
        )
    except Exception as e:
        print(f"public_video upstream error: {e}")
        return HttpResponse(status=504)

    if upstream.status_code not in (200, 206):
        print(f"public_video upstream status: {upstream.status_code} {upstream.text[:200] if hasattr(upstream, 'text') else ''}")
        upstream.close()
        return HttpResponse(status=404)

    lower_name = filename.lower()
    if lower_name.endswith(".mov"):
        content_type = "video/quicktime"
    elif lower_name.endswith(".webm"):
        content_type = "video/webm"
    else:
        content_type = "video/mp4"

    def stream_chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    response = StreamingHttpResponse(
        stream_chunks(),
        status=206 if upstream.status_code == 206 else 200,
        content_type=content_type
    )

    content_length = upstream.headers.get("Content-Length")
    content_range = upstream.headers.get("Content-Range")
    if content_length:
        response["Content-Length"] = content_length
    if content_range:
        response["Content-Range"] = content_range
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "public, max-age=3600"

    return response

# ─────────────────────────────────────────────
#  LinkedIn API Connect
# ─────────────────────────────────────────────

LINKEDIN_AUTH_URL  = 'https://www.linkedin.com/oauth/v2/authorization'
LINKEDIN_TOKEN_URL = 'https://www.linkedin.com/oauth/v2/accessToken'
LINKEDIN_API_BASE  = 'https://api.linkedin.com/v2'
LINKEDIN_SCOPES    = 'openid profile w_member_social w_organization_social r_organization_social rw_organization_admin'


def _li_credentials_ok():
    return bool(getattr(settings, 'LINKEDIN_CLIENT_ID', None) and
                getattr(settings, 'LINKEDIN_CLIENT_SECRET', None))


def _li_get_superuser_token():
    """Get the LinkedIn token stored by any superuser (shared for all users to post)."""
    _li_ensure_table()
    with connection.cursor() as c:
        try:
            c.execute("""SELECT t.access_token, t.token_type, t.expires_at,
                                t.linkedin_person_id, t.linkedin_name, t.linkedin_picture,
                                t.org_id, t.org_name,
                                t.buffer_token, t.buffer_profile_id, t.buffer_profile_name,
                                t.make_webhook_url,
                                t.buffer_profile_id_person, t.buffer_profile_name_person,
                                t.buffer_insights_token
                         FROM planner_linkedin_tokens t
                         JOIN auth_user u ON t.user_id = u.id
                         WHERE u.is_superuser = 1 LIMIT 1""")
            row = c.fetchone()
        except Exception:
            return None
    if not row:
        return None
    return {'access_token': row[0], 'token_type': row[1], 'expires_at': row[2],
            'person_id': row[3], 'name': row[4], 'picture': row[5],
            'org_id': row[6], 'org_name': row[7],
            'buffer_token': row[8], 'buffer_profile_id': row[9], 'buffer_profile_name': row[10],
            'make_webhook_url': row[11],
            'buffer_profile_id_person': row[12], 'buffer_profile_name_person': row[13],
            'buffer_insights_token': row[14] if len(row) > 14 else None}


def _li_get_token(request):
    with connection.cursor() as c:
        try:
            c.execute("""SELECT access_token, token_type, expires_at,
                                linkedin_person_id, linkedin_name, linkedin_picture,
                                org_id, org_name,
                                buffer_token, buffer_profile_id, buffer_profile_name,
                                make_webhook_url,
                                buffer_profile_id_person, buffer_profile_name_person,
                                buffer_insights_token
                         FROM planner_linkedin_tokens WHERE user_id=%s""",
                      [request.user.id])
            row = c.fetchone()
        except Exception:
            return None
    if not row:
        return None
    return {'access_token': row[0], 'token_type': row[1], 'expires_at': row[2],
            'person_id': row[3], 'name': row[4], 'picture': row[5],
            'org_id': row[6], 'org_name': row[7],
            'buffer_token': row[8], 'buffer_profile_id': row[9], 'buffer_profile_name': row[10],
            'make_webhook_url': row[11],
            'buffer_profile_id_person': row[12], 'buffer_profile_name_person': row[13],
            'buffer_insights_token': row[14] if len(row) > 14 else None}


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
            org_name VARCHAR(200),
            buffer_token TEXT,
            buffer_profile_id VARCHAR(100),
            buffer_profile_name VARCHAR(200),
            buffer_profile_id_person VARCHAR(100),
            buffer_profile_name_person VARCHAR(200)
        )""")
        # Migrate existing tables — silently skip if columns already exist
        # Note: buffer_profile_id / buffer_profile_name = ORG channel (legacy name kept).
        #       buffer_profile_id_person / _name = personal (OJ) channel.
        for col, defn in [('buffer_token', 'TEXT'),
                          ('buffer_insights_token', 'TEXT'),
                          ('buffer_profile_id', 'VARCHAR(100)'),
                          ('buffer_profile_name', 'VARCHAR(200)'),
                          ('buffer_profile_id_person', 'VARCHAR(100)'),
                          ('buffer_profile_name_person', 'VARCHAR(200)'),
                          ('make_webhook_url', 'TEXT')]:
            try:
                c.execute(f"ALTER TABLE planner_linkedin_tokens ADD COLUMN {col} {defn}")
            except Exception:
                pass


def _li_fetch(url, token, method='GET', body=None, version=None):
    req = urllib.request.Request(url)
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Content-Type', 'application/json')
    if version:
        # New versioned REST API — no Restli header
        req.add_header('LinkedIn-Version', version)
    else:
        # Legacy Restli API (/v2/)
        req.add_header('X-Restli-Protocol-Version', '2.0.0')
    if body:
        req.method = method if method != 'GET' else 'POST'
        req.data = json.dumps(body).encode('utf-8')
    else:
        req.method = method
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw.decode('utf-8')) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise Exception(f"HTTP {e.code} {e.reason}: {body}")


def _buffer_graphql(buf_token, query, variables=None):
    """Small helper for Buffer's current GraphQL API."""
    payload = {"query": query}
    if variables is not None:
        payload["variables"] = variables

    req = urllib.request.Request(
        "https://api.buffer.com",
        data=json.dumps(payload).encode("utf-8"),
        method="POST"
    )
    req.add_header("Authorization", f"Bearer {buf_token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"Buffer GraphQL HTTP {e.code}: {body}")
    except Exception as e:
        raise Exception(f"Buffer GraphQL Verbindungsfehler: {type(e).__name__}: {e}")

    if result.get("errors"):
        raise Exception("Buffer GraphQL errors: " + json.dumps(result["errors"], ensure_ascii=False))

    return result


def _buffer_channel_for_target(token, target):
    """
    Pick the correct Buffer channel ID/name for a given post target.

    Rule (per Ortrud): OJ / personal posts → personal Buffer channel,
    everything else (org / company page) → org Buffer channel.
    Falls back to the org channel if no personal channel is configured.
    """
    if target == 'person':
        pid = token.get('buffer_profile_id_person')
        pname = token.get('buffer_profile_name_person')
        if pid:
            return pid, pname
        # No dedicated personal channel — fall back to org channel.
        return token.get('buffer_profile_id'), token.get('buffer_profile_name')
    return token.get('buffer_profile_id'), token.get('buffer_profile_name')


def _buffer_first_org_id(buf_token):
    """Get the first Buffer organization id (needed for the posts metrics query)."""
    query = """
    query GetOrganizations {
      account { organizations { id name } }
    }
    """
    result = _buffer_graphql(buf_token, query)
    orgs = (result.get('data', {}) or {}).get('account', {}).get('organizations', []) or []
    return orgs[0].get('id') if orgs else None


def _buffer_fetch_post_metrics(buf_token, org_id, first=50, all_pages=False, max_posts=1000):
    """
    Fetch posts with their metrics from Buffer.

    all_pages=True paginiert ueber alle verfuegbaren Posts (bis max_posts).
    Liefert pro Post auch Text und Thumbnail (zur Erkennung im Tab).
    """
    query = """
    query PostsMetrics($input: PostsInput!, $first: Int, $after: String) {
      posts(input: $input, first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            channelId
            dueAt
            status
            text
            metricsUpdatedAt
            metrics { type name value unit }
          }
        }
      }
    }
    """

    def _thumb(node):
        for a in (node.get('assets') or []):
            t = a.get('thumbnailUrl') or a.get('url')
            if t:
                return t
        return None

    out = []
    after = None
    while True:
        variables = {"input": {"organizationId": org_id}, "first": first}
        if after:
            variables["after"] = after
        result = _buffer_graphql(buf_token, query, variables)
        posts_node = (result.get('data', {}) or {}).get('posts', {}) or {}
        edges = posts_node.get('edges', []) or []
        for e in edges:
            node = e.get('node') or {}
            out.append({
                'buffer_post_id': node.get('id'),
                'channel_id': node.get('channelId'),
                'sent_at': node.get('dueAt'),
                'status': node.get('status'),
                'text': node.get('text') or '',
                'thumbnail_url': _thumb(node),
                'metrics_updated_at': node.get('metricsUpdatedAt'),
                'metrics': node.get('metrics') or [],
            })
        page = posts_node.get('pageInfo') or {}
        if not all_pages or not page.get('hasNextPage') or len(out) >= max_posts:
            break
        after = page.get('endCursor')
        if not after:
            break
    return out


def _buffer_fetch_posts_basic(buf_token, org_id, first=50, all_pages=True, max_posts=1000):
    """
    Holt Buffer-Posts OHNE Metriken (kommt mit posts:read aus, kein insights:read noetig).
    Liefert pro Post: Buffer-ID, Channel, Text, Status, Sende-Datum.
    Bild + LinkedIn-Link werden spaeter ueber planner_posts (buffer_update_id) ergaenzt.
    """
    query = """
    query PostsBasic($input: PostsInput!, $first: Int, $after: String) {
      posts(input: $input, first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            channelId
            dueAt
            sentAt
            status
            text
            externalLink
            assets {
              __typename
              ... on ImageAsset { source thumbnail }
              ... on VideoAsset { source thumbnail }
            }
          }
        }
      }
    }
    """

    def _asset_thumb(node):
        for a in (node.get('assets') or []):
            t = a.get('thumbnail') or a.get('source')
            if t:
                return t
        return ''

    out = []
    after = None
    while True:
        variables = {"input": {"organizationId": org_id}, "first": first}
        if after:
            variables["after"] = after
        result = _buffer_graphql(buf_token, query, variables)
        posts_node = (result.get('data', {}) or {}).get('posts', {}) or {}
        edges = posts_node.get('edges', []) or []
        for e in edges:
            node = e.get('node') or {}
            out.append({
                'buffer_post_id': node.get('id'),
                'channel_id': node.get('channelId'),
                'sent_at': node.get('sentAt') or node.get('dueAt'),
                'status': node.get('status'),
                'text': node.get('text') or '',
                'external_link': node.get('externalLink') or '',
                'thumbnail_url': _asset_thumb(node),
            })
        page = posts_node.get('pageInfo') or {}
        if not all_pages or not page.get('hasNextPage') or len(out) >= max_posts:
            break
        after = page.get('endCursor')
        if not after:
            break
    return out


def _buffer_delete_post(buf_token, buffer_post_id):
    """Delete a post in Buffer by its Buffer post id (buffer_update_id)."""
    if not buf_token or not buffer_post_id:
        return False
    query = """
    mutation DeletePost($input: DeletePostInput!) {
      deletePost(input: $input) {
        __typename
      }
    }
    """
    result = _buffer_graphql(buf_token, query, {"input": {"id": buffer_post_id}})
    # _buffer_graphql wirft bereits bei GraphQL-Fehlern (errors-Feld) eine Exception.
    return True


def _buffer_post(buf_token, profile_id, text, image_url=None, video_url=None, scheduled_at=None, link_url=None):
    """
    Send a post to Buffer using the current GraphQL API.

    - If scheduled_at is given, Buffer schedules the post for that exact UTC time.
    - If scheduled_at is not given, Buffer adds the post to the next queue slot.
    - image_url/video_url must be publicly reachable by Buffer.
    """
    from datetime import timezone

    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post {
            id
            text
            dueAt
            status
            assets {
              id
              mimeType
            }
          }
        }
        ... on MutationError {
          message
        }
      }
    }
    """

    input_data = {
        "text": text,
        "channelId": profile_id,
        "schedulingType": "automatic",
        "mode": "addToQueue",
        "assets": [],
    }

    if scheduled_at:
        # Buffer expects ISO 8601 UTC for customScheduled posts.
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        else:
            scheduled_at = scheduled_at.astimezone(timezone.utc)
        input_data["mode"] = "customScheduled"
        input_data["dueAt"] = scheduled_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    # Reihenfolge (eure Regel): Link → Video → Bild.
    # Ein Link-Post zeigt auf LinkedIn die Link-Vorschau (z.B. Canva-Video),
    # ohne dass wir Medien hochladen müssen (kein Render-/Timeout-Problem).
    if link_url:
        input_data["assets"] = [{"link": {"url": link_url}}]
    elif video_url:
        input_data["assets"] = [{"video": {"url": video_url}}]
    elif image_url:
        input_data["assets"] = [{"image": {"url": image_url}}]

    result = _buffer_graphql(buf_token, query, {"input": input_data})
    create_result = result.get("data", {}).get("createPost") or {}

    if create_result.get("message"):
        raise Exception(create_result.get("message"))

    post = create_result.get("post") or {}
    if not post.get("id"):
        raise Exception("Buffer did not return a post id: " + json.dumps(result, ensure_ascii=False))

    # Keep a shape similar to the old REST API code.
    return {"updates": [{"id": post.get("id"), "due_at": post.get("dueAt"), "status": post.get("status")}], "raw": result}


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
    # Handle Make.com webhook URL save
    if request.method == 'POST' and 'make_webhook_url' in request.POST:
        wh_url = request.POST.get('make_webhook_url', '').strip()
        with connection.cursor() as c:
            try:
                c.execute("UPDATE planner_linkedin_tokens SET make_webhook_url=%s WHERE user_id=%s",
                          [wh_url or None, request.user.id])
            except Exception as ex:
                print('Make webhook save error:', ex)
        return redirect('/planner/api-connect/?make_saved=1')
    # Handle Buffer token/profile save
    if request.method == 'POST' and 'buffer_token' in request.POST:
        buf_tok  = request.POST.get('buffer_token', '').strip()
        buf_pid  = request.POST.get('buffer_profile_id', '').strip()
        buf_pname = request.POST.get('buffer_profile_name', '').strip()
        # Personal (OJ) channel — optional second channel.
        buf_pid_person  = request.POST.get('buffer_profile_id_person', '').strip()
        buf_pname_person = request.POST.get('buffer_profile_name_person', '').strip()
        with connection.cursor() as c:
            try:
                # Leere Felder NICHT ueberschreiben (COALESCE auf neuen Wert, sonst alt).
                # So loescht das Eintragen des Insights-Tokens nicht den Posting-Token.
                c.execute("""UPDATE planner_linkedin_tokens
                             SET buffer_token=COALESCE(%s, buffer_token),
                                 buffer_profile_id=COALESCE(%s, buffer_profile_id),
                                 buffer_profile_name=COALESCE(%s, buffer_profile_name),
                                 buffer_profile_id_person=COALESCE(%s, buffer_profile_id_person),
                                 buffer_profile_name_person=COALESCE(%s, buffer_profile_name_person)
                             WHERE user_id=%s""",
                          [buf_tok or None,
                           buf_pid or None, buf_pname or None,
                           buf_pid_person or None, buf_pname_person or None, request.user.id])
            except Exception as ex:
                print('Buffer save error:', ex)
        return redirect('/planner/api-connect/?buf_saved=1')
    # Handle manual org save
    if request.method == 'POST' and 'org_id' in request.POST:
        org_id_m   = request.POST.get('org_id',   '').strip()
        org_name_m = request.POST.get('org_name', '').strip()
        # Extract only the numeric part (handle full URLs like linkedin.com/company/12345/admin/)
        import re as _re
        m = _re.search(r'(\d{5,})', org_id_m)
        org_id_m = m.group(1) if m else org_id_m
        if org_id_m:
            with connection.cursor() as c:
                try:
                    c.execute(
                        "UPDATE planner_linkedin_tokens SET org_id=%s, org_name=%s WHERE user_id=%s",
                        [org_id_m, org_name_m or org_id_m, request.user.id])
                except Exception:
                    pass
        return redirect('/planner/api-connect/?org_saved=1')
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
    # Build the trigger URL for Make.com
    import hmac as _hmac2, hashlib as _hashlib2
    _secret = (getattr(settings, 'SECRET_KEY', 'fallback'))[:32]
    _trigger_key = _hmac2.new(_secret.encode(), b'trigger-scheduled', _hashlib2.sha256).hexdigest()[:24]
    trigger_url = f"https://linkedin-django-wd7a.onrender.com/planner/api/trigger-scheduled/?key={_trigger_key}"
    _attach_video_paths(ready_posts)

    return render(request, 'planner/api_connect.html', {
        'tab': 'api_connect', 'token': token, 'creds_ok': creds_ok,
        'ready_posts': ready_posts,
        'posts_json': _posts_to_json(ready_posts),
        'trigger_url': trigger_url,
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


@login_required
def linkedin_diag(request):
    """
    Diagnostic endpoint to verify which LinkedIn scopes / org permissions
    the stored token really has. Hit GET /planner/api/linkedin-diag/.
    """
    import requests as _requests
    import json as _json

    token = _li_get_superuser_token()
    if not token or not token.get('access_token'):
        return JsonResponse({'ok': False, 'error': 'No LinkedIn token stored'}, status=401)

    report = {
        'stored_in_db': {
            'person_id': token.get('person_id'),
            'name':      token.get('name'),
            'org_id':    token.get('org_id'),
            'org_name':  token.get('org_name'),
            'expires_at': str(token.get('expires_at')),
            'token_prefix': (token.get('access_token') or '')[:12] + '…',
        },
        'tests': {},
    }

    headers = {
        'Authorization': f"Bearer {token['access_token']}",
        'Linkedin-Version': '202604',
        'X-Restli-Protocol-Version': '2.0.0',
    }

    # Test 1: /v2/userinfo — does the token still authenticate at all?
    try:
        r = _requests.get('https://api.linkedin.com/v2/userinfo', headers=headers, timeout=15)
        report['tests']['userinfo'] = {'status': r.status_code, 'body': r.text[:400]}
    except Exception as e:
        report['tests']['userinfo'] = {'error': str(e)}

    # Test 2: organizationAcls — does the token have org-posting permission?
    # If empty → no org admin role for this token. If 403 → no scope at all.
    try:
        r = _requests.get(
            'https://api.linkedin.com/rest/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED',
            headers=headers, timeout=15,
        )
        body = r.text[:1200]
        elements = []
        try:
            j = r.json()
            for el in (j.get('elements') or []):
                elements.append({
                    'role': el.get('role'),
                    'state': el.get('state'),
                    'organization': el.get('organization'),
                })
        except Exception:
            pass
        report['tests']['organizationAcls'] = {
            'status': r.status_code,
            'admin_orgs_found': elements,
            'raw_body': body if not elements else '(parsed above)',
        }
    except Exception as e:
        report['tests']['organizationAcls'] = {'error': str(e)}

    # Interpretation hint for the user
    hints = []
    acls = report['tests'].get('organizationAcls', {})
    if acls.get('status') == 403:
        hints.append("403 on organizationAcls → token has NO w_organization_social / r_organization_admin scope. Reconnect LinkedIn.")
    elif acls.get('status') == 200 and not acls.get('admin_orgs_found'):
        hints.append("Scope is granted but the user is NOT an ADMINISTRATOR on any LinkedIn page.")
    elif acls.get('admin_orgs_found'):
        ids = [e.get('organization') for e in acls['admin_orgs_found']]
        hints.append(f"Token CAN post to: {ids}. Make sure token.org_id matches one of these.")
    report['hints'] = hints

    return JsonResponse(report, json_dumps_params={'indent': 2})


def _linkedin_author_urn(token, target='org'):
    """Build the LinkedIn author URN for organization/company or personal posting."""
    import re as _re
    if target == 'org' and token.get('org_id'):
        m = _re.search(r'(\d{5,})', str(token['org_id']))
        return f"urn:li:organization:{m.group(1) if m else token['org_id']}"
    if not token.get('person_id'):
        raise Exception("Kein LinkedIn person_id gefunden.")
    return f"urn:li:person:{token['person_id']}"


def _schedule_linkedin_video_post(post_id, text, scheduled_at):
    """Store a video post for the scheduled trigger path. No Buffer is involved."""
    _ensure_scheduled_at_column()
    with connection.cursor() as c:
        for sql in [
            "ALTER TABLE planner_posts ADD COLUMN linkedin_posted TINYINT(1) NOT NULL DEFAULT 0",
            "ALTER TABLE planner_posts ADD COLUMN post_scheduled_at DATETIME NULL DEFAULT NULL",
        ]:
            try:
                c.execute(sql)
            except Exception:
                pass
        c.execute("""
            UPDATE planner_posts
            SET content=%s,
                status='Scheduled',
                in_pipeline=1,
                linkedin_posted=0,
                post_scheduled_at=%s
            WHERE id=%s
        """, [text, scheduled_at.replace(tzinfo=None), post_id])


def _post_linkedin_video_now(token, post_id, text, target='org'):
    """
    Upload an existing Planner video from Nextcloud directly to LinkedIn and publish it.
    Buffer is intentionally bypassed for videos.
    """
    import requests as _requests
    from posts_posted.nc_storage import download_image_from_nextcloud

    nc_path = _get_video_nc_path(post_id)
    vid_bytes, _ct = download_image_from_nextcloud(nc_path)
    if not vid_bytes:
        raise Exception("Video konnte nicht aus Nextcloud geladen werden.")

    author = _linkedin_author_urn(token, target)

    # ── Diagnostic logging ───────────────────────────────────────────
    print("=" * 60)
    print(f"LINKEDIN VIDEO POST DIAGNOSTIC (post_id={post_id})")
    print(f"  target           : {target}")
    print(f"  token.org_id     : {token.get('org_id')!r}")
    print(f"  token.org_name   : {token.get('org_name')!r}")
    print(f"  token.person_id  : {token.get('person_id')!r}")
    print(f"  author URN sent  : {author}")
    print(f"  video size       : {len(vid_bytes)} bytes")
    _atok = token.get('access_token') or ''
    print(f"  token prefix     : {_atok[:12]}…{_atok[-4:] if len(_atok) > 16 else ''}")
    print("=" * 60)
    # ────────────────────────────────────────────────────────────────

    init_r = _li_fetch(
        'https://api.linkedin.com/rest/videos?action=initializeUpload',
        token['access_token'],
        method='POST',
        version='202604',
        body={'initializeUploadRequest': {
            'owner': author,
            'fileSizeBytes': len(vid_bytes),
            'uploadCaptions': False,
            'uploadThumbnail': False,
        }},
    )

    value = init_r.get('value') or {}
    instrs = value.get('uploadInstructions') or []
    vid_urn = value.get('video')
    up_token = value.get('uploadToken')

    if not instrs or not vid_urn or not up_token:
        raise Exception("LinkedIn initializeUpload lieferte keine vollständigen Upload-Daten.")

    up_ids = []
    for instr in instrs:
        first = instr['firstByte']
        last = instr['lastByte']
        chunk = vid_bytes[first:last + 1]
        rr = _requests.put(
            instr['uploadUrl'],
            data=chunk,
            headers={
                'Authorization': f"Bearer {token['access_token']}",
                'Content-Type': 'application/octet-stream',
            },
            timeout=180,
        )
        if rr.status_code >= 400:
            raise Exception(f"LinkedIn Video Upload HTTP {rr.status_code}: {rr.text[:300]}")
        part_id = instr.get('partId')
        if part_id:
            up_ids.append(part_id)

    _li_fetch(
        'https://api.linkedin.com/rest/videos?action=finalizeUpload',
        token['access_token'],
        method='POST',
        version='202604',
        body={'finalizeUploadRequest': {
            'video': vid_urn,
            'uploadToken': up_token,
            'uploadedPartIds': up_ids,
        }},
    )

    result = _li_fetch(
        'https://api.linkedin.com/rest/posts',
        token['access_token'],
        method='POST',
        version='202604',
        body={
            'author': author,
            'commentary': text,
            'visibility': 'PUBLIC',
            'distribution': {
                'feedDistribution': 'MAIN_FEED',
                'targetEntities': [],
                'thirdPartyDistributionChannels': [],
            },
            'content': {'media': {'id': vid_urn}},
            'lifecycleState': 'PUBLISHED',
        },
    )

    post_urn = result.get('id', '') if isinstance(result, dict) else ''

    with connection.cursor() as c:
        for sql in [
            "ALTER TABLE planner_posts ADD COLUMN linkedin_posted TINYINT(1) NOT NULL DEFAULT 0",
            "ALTER TABLE planner_posts ADD COLUMN post_scheduled_at DATETIME NULL DEFAULT NULL",
        ]:
            try:
                c.execute(sql)
            except Exception:
                pass
        c.execute("""
            UPDATE planner_posts
            SET content=%s,
                status='Posted',
                in_pipeline=1,
                linkedin_posted=1,
                post_scheduled_at=NULL
            WHERE id=%s
        """, [text, post_id])

    return post_urn


def _handle_video_from_json_request(token, post_id, text, target, scheduled_ms):
    """
    JSON endpoint helper for /planner/linkedin/post/<id>/.
    If a video is included, do not call Buffer.
    """
    import time as _time
    from datetime import datetime as _dt, timezone as _timezone

    if not token.get('access_token'):
        return JsonResponse({'ok': False, 'error': 'linkedin_not_connected'}, status=401)

    _ensure_media_columns()
    nc_path = _get_video_nc_path(post_id)

    scheduled_at = None
    if scheduled_ms:
        scheduled_ts = float(scheduled_ms) / 1000.0
        if scheduled_ts > _time.time() + 60:
            scheduled_at = _dt.fromtimestamp(scheduled_ts, tz=_timezone.utc)

    if scheduled_at:
        _schedule_linkedin_video_post(post_id, text, scheduled_at)
        return JsonResponse({
            'ok': True,
            'via': 'linkedin_scheduled',
            'scheduled': True,
            'scheduled_at': scheduled_at.isoformat(),
            'has_video': True,
        })

    post_urn = _post_linkedin_video_now(token, post_id, text, target=target)
    return JsonResponse({
        'ok': True,
        'via': 'linkedin',
        'post_urn': post_urn,
        'scheduled': False,
        'has_video': True,
    })


@login_required
def linkedin_do_post(request, post_id):
    try:
        return _linkedin_do_post_impl(request, post_id)
    except Exception as _e:
        import traceback as _tb
        print("linkedin_do_post CRASH:", _tb.format_exc())
        return JsonResponse({'ok': False, 'error': f'{type(_e).__name__}: {_e}'}, status=500)


def _linkedin_do_post_impl(request, post_id):
    import time as _time
    from datetime import datetime as _dt, timezone as _timezone

    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    token = _li_get_superuser_token()
    if not token:
        return JsonResponse({'ok': False, 'error': 'not_connected'}, status=401)

    data = json.loads(request.body)
    target = data.get('target', 'person')
    text = data.get('text', '').strip()
    include_img = data.get('include_image', False)
    include_video = data.get('include_video', False)
    scheduled_ms = data.get('scheduled_ms')

    if not text:
        return JsonResponse({'ok': False, 'error': 'empty_text'}, status=400)

    # ─────────────────────────────────────────────
    # Routing rule (per Ortrud):
    #   scheduled (scheduled_ms set) → Buffer
    #   immediate                    → direct LinkedIn
    # Applies to text, image AND video alike.
    # ─────────────────────────────────────────────

    # Immediate video → direct LinkedIn (bypass Buffer).
    # Scheduled video falls through to the Buffer route below.
    if include_video and not scheduled_ms:
        try:
            return _handle_video_from_json_request(token, post_id, text, target, scheduled_ms)
        except Exception as e:
            return JsonResponse({'ok': False, 'error': str(e)}, status=500)

    # ─────────────────────────────────────────────
    # Buffer route: used for scheduled posts (and org posts).
    # Channel is chosen by target via _buffer_channel_for_target.
    # ─────────────────────────────────────────────
    _buf_pid, _buf_pname = _buffer_channel_for_target(token, target)
    if scheduled_ms or target == 'org':
        if not token.get('buffer_token') or not _buf_pid:
            return JsonResponse({
                'ok': False,
                'error': 'Buffer ist nicht konfiguriert. Bitte Buffer Access Token speichern und Profil auswählen.'
            }, status=400)

        try:
            image_url = None
            video_url = None
            link_url = None

            # Regel (per Ortrud): Hat der Post einen Link -> Link posten
            # (LinkedIn zeigt die Link-Vorschau, z.B. Canva-Video). Kein Medien-Upload.
            _ensure_media_columns()
            with connection.cursor() as c:
                c.execute("SELECT COALESCE(link,'') FROM planner_posts WHERE id=%s", [post_id])
                lrow = c.fetchone()
            if lrow and lrow[0] and str(lrow[0]).strip().lower().startswith("http"):
                link_url = str(lrow[0]).strip()
                print("BUFFER LINK URL:", link_url)

            if not link_url and include_video:
                with connection.cursor() as c:
                    c.execute("SELECT video_nc_path FROM planner_posts WHERE id=%s", [post_id])
                    vrow = c.fetchone()
                if vrow and vrow[0]:
                    # Cloudinary: dauerhaft öffentliche URL, die Buffer zuverlässig
                    # erreichen kann (auch bei geplanten Posts Stunden später).
                    video_url = _upload_video_to_cloudinary(post_id)
                    print("BUFFER CLOUDINARY VIDEO URL:", video_url)

            if not link_url and include_img and not video_url:
                with connection.cursor() as c:
                    c.execute("SELECT image FROM planner_posts WHERE id=%s", [post_id])
                    row = c.fetchone()
                if row and row[0]:
                    # Bild über Cloudinary (wie Video): Buffer erreicht die
                    # Render-Proxy-URL nicht zuverlässig (403/Timeout).
                    image_url = _upload_image_to_cloudinary(post_id)
                    print("BUFFER CLOUDINARY IMAGE URL:", image_url)

            scheduled_at = None
            if scheduled_ms:
                scheduled_ts = float(scheduled_ms) / 1000.0
                if scheduled_ts > _time.time() + 60:
                    scheduled_at = _dt.fromtimestamp(scheduled_ts, tz=_timezone.utc)

            result = _buffer_post(
                buf_token=token['buffer_token'],
                profile_id=_buf_pid,
                text=text,
                image_url=image_url,
                video_url=video_url,
                scheduled_at=scheduled_at,
                link_url=link_url,
            )

            buffer_update_id = None
            try:
                updates = result.get('updates') or []
                if updates:
                    buffer_update_id = updates[0].get('id')
            except Exception:
                buffer_update_id = None

            with connection.cursor() as c:
                for sql in [
                    "ALTER TABLE planner_posts ADD COLUMN linkedin_posted TINYINT(1) NOT NULL DEFAULT 0",
                    "ALTER TABLE planner_posts ADD COLUMN buffer_update_id VARCHAR(100) DEFAULT NULL",
                    "ALTER TABLE planner_posts ADD COLUMN post_scheduled_at DATETIME NULL DEFAULT NULL",
                ]:
                    try:
                        c.execute(sql)
                    except Exception:
                        pass

                if scheduled_at:
                    c.execute("""
                        UPDATE planner_posts
                        SET content=%s,
                            status='Scheduled',
                            in_pipeline=1,
                            linkedin_posted=0,
                            post_scheduled_at=%s,
                            buffer_update_id=%s
                        WHERE id=%s
                    """, [text, scheduled_at.replace(tzinfo=None), buffer_update_id, post_id])

                    return JsonResponse({
                        'ok': True,
                        'via': 'buffer',
                        'scheduled': True,
                        'scheduled_at': scheduled_at.isoformat(),
                        'buffer_update_id': buffer_update_id,
                        'has_image': bool(image_url),
                        'has_video': bool(video_url),
                    })

                c.execute("""
                    UPDATE planner_posts
                    SET content=%s,
                        status='Scheduled',
                        in_pipeline=1,
                        linkedin_posted=0,
                        buffer_update_id=%s
                    WHERE id=%s
                """, [text, buffer_update_id, post_id])

                return JsonResponse({
                    'ok': True,
                    'via': 'buffer',
                    'scheduled': True,
                    'buffer_update_id': buffer_update_id,
                    'has_image': bool(image_url),
                    'has_video': bool(video_url),
                })

        except Exception as e:
            return JsonResponse({'ok': False, 'error': str(e)}, status=500)

    # ─────────────────────────────────────────────
    # Personal LinkedIn fallback
    # ─────────────────────────────────────────────
    if not token.get('access_token'):
        return JsonResponse({'ok': False, 'error': 'linkedin_not_connected'}, status=401)

    post_token = token['access_token']
    author = f"urn:li:person:{token['person_id']}"
    image_urn = None

    if include_img:
        with connection.cursor() as c:
            rows = _q(c, "SELECT image FROM planner_posts WHERE id=%s", [post_id])

        if rows and rows[0][0]:
            try:
                image_path = rows[0][0]
                full_path = os.path.join(settings.MEDIA_ROOT, image_path)

                init = _li_fetch(
                    'https://api.linkedin.com/rest/images?action=initializeUpload',
                    post_token,
                    method='POST',
                    body={'initializeUploadRequest': {'owner': author}},
                    version='202604'
                )

                upload_url = init['value']['uploadUrl']
                image_urn = init['value']['image']

                with open(full_path, 'rb') as f:
                    img_bytes = f.read()

                img_req = urllib.request.Request(upload_url, data=img_bytes, method='PUT')
                img_req.add_header('Authorization', f'Bearer {post_token}')
                img_req.add_header('Content-Type', 'image/jpeg')
                urllib.request.urlopen(img_req)

            except Exception as e:
                print(f'LI image upload error: {e}')
                image_urn = None

    post_body = {
        'author': author,
        'commentary': text,
        'visibility': 'PUBLIC',
        'distribution': {
            'feedDistribution': 'MAIN_FEED',
            'targetEntities': [],
            'thirdPartyDistributionChannels': [],
        },
        'lifecycleState': 'PUBLISHED',
    }

    if image_urn:
        post_body['content'] = {'media': {'id': image_urn}}

    try:
        result = _li_fetch(
            'https://api.linkedin.com/rest/posts',
            post_token,
            method='POST',
            body=post_body,
            version='202604'
        )

        post_urn = result.get('id', '') if isinstance(result, dict) else ''

        with connection.cursor() as c:
            try:
                c.execute("ALTER TABLE planner_posts ADD COLUMN linkedin_posted TINYINT(1) NOT NULL DEFAULT 0")
            except Exception:
                pass

            c.execute("""
                UPDATE planner_posts
                SET content=%s,
                    status='Posted',
                    in_pipeline=1,
                    linkedin_posted=1
                WHERE id=%s
            """, [text, post_id])

        return JsonResponse({
            'ok': True,
            'via': 'linkedin',
            'post_urn': post_urn,
            'scheduled': False,
        })

    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def linkedin_post_video(request, post_id):
    """
    Post a video to Buffer.

    The uploaded video is stored in Nextcloud Planner/Videos and Buffer receives
    the public Nextcloud download URL instead of the slow Render proxy URL.
    """
    import time as _time
    from datetime import datetime as _dt, timezone as _timezone

    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST only'}, status=405)

    token = _li_get_superuser_token()
    if not token:
        return JsonResponse({'ok': False, 'error': 'not_connected'}, status=401)

    if not token.get('buffer_token') or not token.get('buffer_profile_id'):
        return JsonResponse({
            'ok': False,
            'error': 'Buffer ist nicht konfiguriert. Bitte Buffer Access Token speichern und Profil auswählen.'
        }, status=400)

    target = request.POST.get('target', 'org')
    if target != 'org':
        return JsonResponse({
            'ok': False,
            'error': 'Video-Posting ist aktuell nur über Buffer für die Unternehmensseite aktiviert.'
        }, status=400)

    text = (request.POST.get('text') or '').strip()
    if not text:
        return JsonResponse({'ok': False, 'error': 'empty_text'}, status=400)

    try:
        _ensure_media_columns()

        video_file = request.FILES.get('video')
        nc_path = None

        if video_file:
            nc_path = _upload_video_to_nextcloud(video_file, post_id)
            with connection.cursor() as c:
                c.execute("UPDATE planner_posts SET video_nc_path=%s, image=NULL WHERE id=%s", [nc_path, post_id])
        else:
            with connection.cursor() as c:
                c.execute("SELECT video_nc_path FROM planner_posts WHERE id=%s", [post_id])
                row = c.fetchone()
            if row and row[0]:
                nc_path = row[0]

        if not nc_path:
            return JsonResponse({'ok': False, 'error': 'Kein Video für diesen Post gespeichert.'}, status=400)

        video_url = _upload_video_to_cloudinary(post_id)
        print("BUFFER CLOUDINARY VIDEO URL:", video_url)

        scheduled_at = None
        scheduled_ms = request.POST.get('scheduled_ms')
        if scheduled_ms:
            scheduled_ts = float(scheduled_ms) / 1000.0
            if scheduled_ts > _time.time() + 60:
                scheduled_at = _dt.fromtimestamp(scheduled_ts, tz=_timezone.utc)

        result = _buffer_post(
            buf_token=token['buffer_token'],
            profile_id=token['buffer_profile_id'],
            text=text,
            video_url=video_url,
            scheduled_at=scheduled_at,
        )

        buffer_update_id = None
        try:
            updates = result.get('updates') or []
            if updates:
                buffer_update_id = updates[0].get('id')
        except Exception:
            buffer_update_id = None

        with connection.cursor() as c:
            for sql in [
                "ALTER TABLE planner_posts ADD COLUMN linkedin_posted TINYINT(1) NOT NULL DEFAULT 0",
                "ALTER TABLE planner_posts ADD COLUMN buffer_update_id VARCHAR(100) DEFAULT NULL",
                "ALTER TABLE planner_posts ADD COLUMN post_scheduled_at DATETIME NULL DEFAULT NULL",
            ]:
                try:
                    c.execute(sql)
                except Exception:
                    pass

            if scheduled_at:
                c.execute("""
                    UPDATE planner_posts
                    SET content=%s,
                        status='Scheduled',
                        in_pipeline=1,
                        linkedin_posted=0,
                        post_scheduled_at=%s,
                        buffer_update_id=%s
                    WHERE id=%s
                """, [text, scheduled_at.replace(tzinfo=None), buffer_update_id, post_id])
            else:
                c.execute("""
                    UPDATE planner_posts
                    SET content=%s,
                        status='Scheduled',
                        in_pipeline=1,
                        linkedin_posted=0,
                        buffer_update_id=%s
                    WHERE id=%s
                """, [text, buffer_update_id, post_id])

        return JsonResponse({
            'ok': True,
            'via': 'buffer',
            'scheduled': True,
            'scheduled_at': scheduled_at.isoformat() if scheduled_at else None,
            'buffer_update_id': buffer_update_id,
            'has_video': True,
            'video_url': video_url,
        })

    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def api_video(request, post_id):
    """Upload a video file to Nextcloud and store its path in planner_posts.video_nc_path."""
    _ensure_media_columns()
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    video_file = request.FILES.get('video')
    if not video_file:
        return JsonResponse({'ok': False, 'error': 'Keine Videodatei'}, status=400)

    try:
        nc_path = _upload_video_to_nextcloud(video_file, post_id)
        with connection.cursor() as c:
            c.execute("UPDATE planner_posts SET video_nc_path=%s, image=NULL WHERE id=%s", [nc_path, post_id])
        return JsonResponse({'ok': True, 'nc_path': nc_path})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


def api_trigger_scheduled(request):
    """
    Called by Make.com on a time schedule (e.g. every 15 min).
    Finds all scheduled posts that are due and posts them via Make webhook.
    Protected by a secret key: /planner/api/trigger-scheduled/?key=XXXX
    """
    import time as _time
    import requests as _requests
    from datetime import datetime as _dt
    import hmac as _hmac, hashlib as _hashlib

    # Derive a stable secret key from Django SECRET_KEY
    secret = (getattr(settings, 'SECRET_KEY', 'fallback'))[:32]
    expected = _hmac.new(secret.encode(), b'trigger-scheduled', _hashlib.sha256).hexdigest()[:24]
    provided = request.GET.get('key', '')
    if provided != expected:
        return JsonResponse({'error': 'forbidden'}, status=403)

    token = _li_get_superuser_token()
    if not token:
        return JsonResponse({'ok': False, 'error': 'linkedin_not_connected'})

    _ensure_scheduled_at_column()
    with connection.cursor() as c:
        try:
            c.execute("ALTER TABLE planner_posts ADD COLUMN video_nc_path VARCHAR(512) DEFAULT NULL")
        except Exception:
            pass
        c.execute("""SELECT id, content, image, video_nc_path
                     FROM planner_posts
                     WHERE status = 'Scheduled'
                       AND post_scheduled_at IS NOT NULL
                       AND post_scheduled_at <= UTC_TIMESTAMP()
                       AND COALESCE(linkedin_posted, 0) = 0""")
        due_posts = c.fetchall()

    posted = []
    errors = []
    wh_url = token.get('make_webhook_url', '')

    for (pid, content_txt, image, video_nc_path) in due_posts:
        try:
            # Video posts go directly via LinkedIn API
            if video_nc_path:
                from posts_posted.nc_storage import download_image_from_nextcloud
                vid_bytes, _ = download_image_from_nextcloud(video_nc_path)
                if not vid_bytes:
                    errors.append({'id': pid, 'error': 'Video nicht auf Nextcloud gefunden'})
                    continue
                import re as _re2
                _author = None
                if token.get('org_id'):
                    _m = _re2.search(r'(\d{5,})', str(token['org_id']))
                    _author = f"urn:li:organization:{_m.group(1) if _m else token['org_id']}"
                else:
                    _author = f"urn:li:person:{token['person_id']}"
                init_r = _li_fetch(
                    'https://api.linkedin.com/rest/videos?action=initializeUpload',
                    token['access_token'], method='POST',
                    body={'initializeUploadRequest': {
                        'owner': _author, 'fileSizeBytes': len(vid_bytes),
                        'uploadCaptions': False, 'uploadThumbnail': False,
                    }}, version='202604')
                instrs    = init_r['value']['uploadInstructions']
                vid_urn   = init_r['value']['video']
                up_token  = init_r['value']['uploadToken']
                up_ids    = []
                for instr in instrs:
                    chunk = vid_bytes[instr['firstByte']:instr['lastByte'] + 1]
                    rr = _requests.put(instr['uploadUrl'], data=chunk,
                        headers={'Authorization': f"Bearer {token['access_token']}",
                                 'Content-Type': 'application/octet-stream'}, timeout=120)
                    up_ids.append(instr.get('partId', ''))
                _li_fetch('https://api.linkedin.com/rest/videos?action=finalizeUpload',
                    token['access_token'], method='POST',
                    body={'finalizeUploadRequest': {'video': vid_urn, 'uploadToken': up_token,
                                                    'uploadedPartIds': up_ids}}, version='202604')
                _li_fetch('https://api.linkedin.com/rest/posts',
                    token['access_token'], method='POST', version='202604',
                    body={'author': _author, 'commentary': content_txt or '',
                          'visibility': 'PUBLIC',
                          'distribution': {'feedDistribution': 'MAIN_FEED', 'targetEntities': [],
                                           'thirdPartyDistributionChannels': []},
                          'content': {'media': {'id': vid_urn}},
                          'lifecycleState': 'PUBLISHED'})
                with connection.cursor() as c:
                    c.execute("UPDATE planner_posts SET status='Posted', in_pipeline=1, linkedin_posted=1, post_scheduled_at=NULL WHERE id=%s", [pid])
                posted.append(pid)
                continue
            # Text/image posts via Make.com webhook
            if not wh_url:
                errors.append({'id': pid, 'error': 'Kein Make.com Webhook konfiguriert'})
                continue
            payload = {'text': content_txt or ''}
            if image:
                img_token = _make_image_token(pid)
                base_url = 'https://linkedin-django-wd7a.onrender.com'
                payload['image_url'] = f"{base_url}/planner/public-image/{pid}/{img_token}/"
            resp = _requests.post(wh_url, data=payload, timeout=30)
            if resp.status_code < 400:
                with connection.cursor() as c:
                    c.execute("""UPDATE planner_posts
                                 SET status='Posted', in_pipeline=1, linkedin_posted=1,
                                     post_scheduled_at=NULL
                                 WHERE id=%s""", [pid])
                posted.append(pid)
            else:
                errors.append({'id': pid, 'error': f'HTTP {resp.status_code}'})
        except Exception as e:
            errors.append({'id': pid, 'error': str(e)})

    return JsonResponse({'ok': True, 'posted': posted, 'errors': errors, 'count': len(posted)})


@login_required
def api_buffer_profiles(request):
    """Fetch LinkedIn channels connected to Buffer using the current GraphQL API."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    data = json.loads(request.body)
    buf_token = data.get('token', '').strip()

    if not buf_token:
        return JsonResponse({'error': 'Kein Token angegeben'}, status=400)

    org_query = """
    query GetOrganizations {
      account {
        organizations {
          id
          name
        }
      }
    }
    """

    channels_query = """
    query GetChannels($organizationId: OrganizationId!) {
      channels(input: { organizationId: $organizationId }) {
        id
        name
        displayName
        service
        type
      }
    }
    """

    try:
        org_result = _buffer_graphql(buf_token, org_query)
        organizations = org_result.get('data', {}).get('account', {}).get('organizations', []) or []

        li_profiles = []
        for org in organizations:
            org_id = org.get('id')
            org_name = org.get('name') or org_id
            if not org_id:
                continue

            ch_result = _buffer_graphql(buf_token, channels_query, {'organizationId': org_id})
            channels = ch_result.get('data', {}).get('channels', []) or []

            for ch in channels:
                service = str(ch.get('service') or '').lower()
                if 'linkedin' not in service:
                    continue

                name = ch.get('displayName') or ch.get('name') or ch.get('id')
                li_profiles.append({
                    'id': ch.get('id'),
                    'name': f"{name} — {org_name}",
                    'type': ch.get('service') or 'linkedin',
                })

        return JsonResponse({'profiles': li_profiles})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

