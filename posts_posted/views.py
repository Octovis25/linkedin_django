import json
import re
import io
import urllib.request
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.contrib import messages
from django.http import HttpResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST
from .models import LinkedinPostPosted
from .forms import PostPostedForm
from .nc_storage import download_image_from_nextcloud


def _norm_text(s):
    """Normalise text for matching: lower case, a-z0-9 only, first 25 characters."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())[:25]


def zusammenfuehren(linkedin, buffer, schluessel):
    """One row per post, out of the two lists Data used to show separately.

    linkedin: what LinkedIn reports (the Excel upload) - dicts with 'text'
              and 'datum' (a date or None).
    buffer:   what Buffer sent or still holds - dicts with 'text', 'datum'
              and 'status'.
    schluessel: the content key, the one in linkedin_statistics/post_text.py.

    There is no shared ID: LinkedIn and Buffer number the same post
    differently (activity against share/ugcPost). So the text decides, and
    within one text the dates do: a text posted twice is two posts, and each
    LinkedIn entry takes the Buffer entry closest to its own day. What Buffer
    has left over for a text is a repeat, and is hung on the row nearest in
    time instead of becoming a row of its own.

    Returns dicts: li, bu (either may be None), bu_mehr (Buffer repeats),
    li_gleich (how often the text is in the Excel data), datum, art
    ('both' | 'li' | 'bu') and hinweise (what does not add up).
    """
    gruppen = {}
    for i, p in enumerate(linkedin):
        k = schluessel(p.get('text')) or ('li', i)
        gruppen.setdefault(k, ([], []))[0].append(p)
    for i, b in enumerate(buffer):
        k = schluessel(b.get('text')) or ('bu', i)
        gruppen.setdefault(k, ([], []))[1].append(b)

    def abstand(a, b):
        if a is None or b is None:
            return 10 ** 6
        return abs((a - b).days)

    zeilen = []
    for lis, bus in gruppen.values():
        paare = sorted((abstand(l.get('datum'), b.get('datum')), i, j)
                       for i, l in enumerate(lis) for j, b in enumerate(bus))
        zu_li, zu_bu = {}, {}
        for _d, i, j in paare:
            if i in zu_li or j in zu_bu:
                continue
            zu_li[i], zu_bu[j] = j, i

        if lis:
            neu = [{'li': l, 'bu': bus[zu_li[i]] if i in zu_li else None, 'bu_mehr': []}
                   for i, l in enumerate(lis)]
            for j, b in enumerate(bus):
                if j in zu_bu:
                    continue
                ziel = min(neu, key=lambda z: abstand(
                    (z['bu'] or z['li']).get('datum'), b.get('datum')))
                ziel['bu_mehr'].append(b)
        else:
            # Only Buffer knows this text: one row, the latest copy leads.
            reihe = sorted(bus, key=lambda b: (b.get('datum') is not None, b.get('datum')),
                           reverse=True)
            neu = [{'li': None, 'bu': reihe[0], 'bu_mehr': reihe[1:]}]

        for z in neu:
            z['li_gleich'] = len(lis)
            li, bu = z['li'], z['bu']
            # Buffer's send date wins: it is when the post went out. The
            # LinkedIn date comes from the export and has been wrong before.
            z['datum'] = (bu or {}).get('datum') or (li or {}).get('datum')
            z['art'] = 'both' if (li and bu) else ('li' if li else 'bu')
            hinweise = []
            if li and bu and abstand(li.get('datum'), bu.get('datum')) > 1 \
                    and li.get('datum') and bu.get('datum'):
                hinweise.append('Excel says %s' % li['datum'].strftime('%d.%m.'))
            if z['bu_mehr']:
                tage = sorted(x['datum'].strftime('%d.%m.') for x in [bu] + z['bu_mehr']
                              if x and x.get('datum'))
                hinweise.append('%d\u00d7 in Buffer%s' % (
                    1 + len(z['bu_mehr']), (' (' + ', '.join(tage) + ')') if tage else ''))
            if len(lis) > 1:
                hinweise.append('%d\u00d7 in the Excel data' % len(lis))
            z['hinweise'] = hinweise
            zeilen.append(z)

    zeilen.sort(key=lambda z: (z['datum'] is not None, z['datum']), reverse=True)
    return zeilen


def fill_missing_post_images():
    """Fill in missing overview images (linkedin_posts_posted.post_image)
    from the matching Buffer thumbnail, matched on text. Only EMPTY images are set.
    Returns (filled, checked, errors)."""
    from .nc_storage import upload_image_to_nextcloud

    filled, checked, errors, dates_filled = 0, 0, 0, 0

    # --- Load everything we need ONCE ---
    with connection.cursor() as c:
        c.execute("""
            SELECT post_text, thumbnail_url,
                   LEFT(COALESCE(sent_at, due_at),10) AS sd
            FROM buffer_posts_posted
            WHERE post_text IS NOT NULL AND post_text<>''
        """)
        buf, buf_dates = [], []
        for t, th, sd in c.fetchall():
            k = _norm_text(t)
            if not k:
                continue
            if th:
                buf.append((k, th))
            if sd:
                buf_dates.append((k, sd))

        # EVERY post (title + current date + whether it has an image).
        c.execute("""
            SELECT lp.post_id, lp.post_title, pp.id,
                   CAST(pp.post_date AS CHAR), pp.post_image
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE lp.post_title IS NOT NULL
        """)
        rows = c.fetchall()

    # --- 1) DATE: the Buffer date wins, and overwrites a wrong one too ---
    for post_id, title, pp_id, cur_date, _img in rows:
        key = _norm_text(title)
        if not key:
            continue
        bd = next((d for bk, d in buf_dates if bk and (bk.startswith(key) or key.startswith(bk))), None)
        if not bd:
            continue
        if cur_date and str(cur_date)[:10] == str(bd)[:10]:
            continue  # schon korrekt
        try:
            with connection.cursor() as c3:
                if pp_id:
                    c3.execute("UPDATE linkedin_posts_posted SET post_date=%s WHERE id=%s", [bd, pp_id])
                else:
                    c3.execute("INSERT INTO linkedin_posts_posted (post_id, post_date) VALUES (%s,%s)",
                               [post_id, bd])
            dates_filled += 1
        except Exception:
            pass

    # --- 2) IMAGE: only fill EMPTY images from the Buffer thumbnail ---
    for post_id, title, pp_id, _cur_date, post_image in rows:
        if post_image:
            continue  # already has an image - leave it alone
        checked += 1
        key = _norm_text(title)
        if not key:
            continue
        thumb = next((th for bk, th in buf if bk and (bk.startswith(key) or key.startswith(bk))), None)
        if not thumb:
            continue
        try:
            req = urllib.request.Request(thumb, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if not data:
                continue
            bio = io.BytesIO(data)
            bio.content_type = 'image/jpeg'
            filename = f"buffer_auto_{post_id}.jpg"
            nc_path = upload_image_to_nextcloud(bio, filename)
            if not nc_path:
                errors += 1
                continue
            with connection.cursor() as c2:
                if pp_id:
                    c2.execute("UPDATE linkedin_posts_posted SET post_image=%s WHERE id=%s", [nc_path, pp_id])
                else:
                    c2.execute("INSERT INTO linkedin_posts_posted (post_id, post_image) VALUES (%s,%s)",
                               [post_id, nc_path])
            filled += 1
        except Exception:
            errors += 1

    return filled, checked, errors, dates_filled


def promote_scheduled_to_posted():
    """Move planner posts that Buffer reports as sent from 'Scheduled' to
    'Posted'.

    The link between the two worlds is buffer_posts_posted.planner_post_id.
    Only posts sitting in 'Scheduled' are touched, so a status set by hand
    stays untouched. Returns how many posts were moved.

    A post counts as sent when Buffer says status='sent', or when a sent_at is
    on record. That second half was a trap until September 2026: the sync wrote
    Buffer's dueAt - the PLANNED time - into sent_at whenever no sentAt existed
    yet. Every queued post therefore carried a timestamp, the condition below
    read it as proof of publication, and a post planned for next Tuesday was
    archived at the next sync - days before it went out. The two timestamps now
    live in two columns, so sent_at means what its name says.
    """
    with connection.cursor() as c:
        try:
            c.execute("""
                UPDATE planner_posts p
                JOIN buffer_posts_posted b ON b.planner_post_id = p.id
                SET p.status='Posted', p.in_pipeline=1, p.linkedin_posted=1,
                    p.post_scheduled_at=NULL
                WHERE p.status='Scheduled'
                  AND (
                        LOWER(COALESCE(b.status,'')) = 'sent'
                        -- A date alone is not proof. It has to lie in the past:
                        -- nothing is ever sent tomorrow. Twice now a planned
                        -- time ended up in sent_at and posts were archived days
                        -- early; this makes that impossible rather than fixed.
                        OR (b.sent_at IS NOT NULL
                            AND STR_TO_DATE(REPLACE(LEFT(b.sent_at, 19), 'T', ' '),
                                            '%Y-%m-%d %H:%i:%s') <= UTC_TIMESTAMP())
                      )
            """)
            return c.rowcount or 0
        except Exception as e:
            print("promote_scheduled_to_posted:", e)
            return 0


@login_required
@require_POST
def buffer_fill_images(request):
    """Button action: fill missing overview images and dates from Buffer.
    Setzt zusaetzlich gesendete Scheduled-Posts auf 'Posted'."""
    try:
        filled, checked, errors, dates_filled = fill_missing_post_images()
        promoted = promote_scheduled_to_posted()
        return JsonResponse({'ok': True, 'filled': filled, 'checked': checked,
                             'errors': errors, 'dates_filled': dates_filled,
                             'promoted': promoted})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


def _ensure_repost_column():
    """Make sure buffer_posts_posted has an is_repost column."""
    with connection.cursor() as c:
        try:
            c.execute("ALTER TABLE buffer_posts_posted ADD COLUMN is_repost TINYINT DEFAULT 0")
        except Exception:
            pass  # Spalte existiert bereits


@login_required
@require_POST
def buffer_toggle_repost(request):
    """Toggle the repost flag of a Buffer post. Called from the OJ tab."""
    _ensure_repost_column()
    try:
        data = json.loads(request.body or '{}')
    except Exception:
        data = {}
    bpid = data.get('buffer_post_id')
    if not bpid:
        return JsonResponse({'ok': False, 'error': 'buffer_post_id fehlt'}, status=400)
    with connection.cursor() as c:
        c.execute("SELECT COALESCE(is_repost,0) FROM buffer_posts_posted WHERE buffer_post_id=%s", [bpid])
        row = c.fetchone()
        if not row:
            return JsonResponse({'ok': False, 'error': 'Post nicht gefunden'}, status=404)
        new_val = 0 if row[0] else 1
        c.execute("UPDATE buffer_posts_posted SET is_repost=%s WHERE buffer_post_id=%s", [new_val, bpid])
    return JsonResponse({'ok': True, 'is_repost': bool(new_val)})


@login_required
def post_list(request):
    # Auto-Sync: fehlende Posts + post_title aktualisieren
    from django.db import connection as _c
    with _c.cursor() as cur:
        cur.execute("""
            INSERT IGNORE INTO linkedin_posts_posted (post_id, post_url, post_date, post_title)
            SELECT lp.post_id, lp.post_url, lp.post_date, lp.post_title
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE pp.post_id IS NULL
              AND lp.post_id IS NOT NULL
              AND lp.post_url IS NOT NULL
        """)
        cur.execute("""
            UPDATE linkedin_posts_posted pp
            JOIN linkedin_posts lp ON pp.post_id = lp.post_id
            SET pp.post_title = lp.post_title
            WHERE pp.post_title IS NULL OR pp.post_title = ''
        """)
    # Keep in step: add posts that are in linkedin_posts but missing here
    from django.db import connection as _c
    with _c.cursor() as cur:
        cur.execute("""
            INSERT IGNORE INTO linkedin_posts_posted (post_id, post_url, post_date)
            SELECT lp.post_id, lp.post_url, lp.post_date
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE pp.post_id IS NULL
              AND lp.post_id IS NOT NULL
              AND lp.post_url IS NOT NULL
        """)
    """One view of what went out: what LinkedIn reports (the Excel upload)
    and what Buffer sent, side by side - Ortrud, 25.09.2026: "one view is
    enough". Both tables stay; the calendar, the overview and the statistics
    read from them."""
    from linkedin_statistics.post_text import TITEL, _inhalts_schluessel
    query = request.GET.get("q", "").strip()

    with connection.cursor() as cur:
        cur.execute("""
            SELECT lp.post_id, """ + TITEL + """ AS text, lp.post_url,
                   COALESCE(pp.post_date, lp.post_date) AS datum,
                   pp.post_image, pp.id AS pp_id
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        """)
        spalten = [col[0] for col in cur.description]
        linkedin = [dict(zip(spalten, r)) for r in cur.fetchall()]
    for p in linkedin:
        d = p.get('datum')
        p['datum'] = d.date() if hasattr(d, 'date') and callable(d.date) else d
        p['text'] = p.get('text') or ''

    buffer, last_fetch, error = _buffer_posts_lesen()
    from datetime import date as _date
    for b in buffer:
        try:
            b['datum'] = _date.fromisoformat(b['sent_at'][:10]) if b['sent_at'] else None
        except ValueError:
            b['datum'] = None

    zeilen = zusammenfuehren(linkedin, buffer, _inhalts_schluessel)
    zaehler = {
        'all': len(zeilen),
        'both': sum(1 for z in zeilen if z['art'] == 'both'),
        'li': sum(1 for z in zeilen if z['art'] == 'li'),
        'bu': sum(1 for z in zeilen if z['art'] == 'bu'),
        'check': sum(1 for z in zeilen if z['hinweise']),
    }

    return render(request, "posts_posted/list.html", {
        "zeilen": zeilen,
        "zaehler": zaehler,
        "query": query,
        "last_fetch": last_fetch,
        "error": error,
        "zuerst": 10,
    })


def _buffer_posts_lesen():
    """The Octovis company posts in buffer_posts_posted, from 2023 on.

    Returns (posts, last_fetch, error). This used to be the whole of the tab
    'Buffer Posts Posted'; since 25.09.2026 that tab is part of Posts Posted.
    """
    error = None
    posts = []
    last_fetch = None

    # The Octovis company channel comes from the token (buffer_profile_id = company).
    octovis_channel = None
    with connection.cursor() as c:
        try:
            c.execute("""
                SELECT t.buffer_profile_id
                FROM planner_linkedin_tokens t
                JOIN auth_user u ON t.user_id = u.id
                WHERE u.is_superuser = 1 AND t.buffer_profile_id IS NOT NULL
                LIMIT 1
            """)
            row = c.fetchone()
            octovis_channel = row[0] if row else None
        except Exception:
            octovis_channel = None

    with connection.cursor() as c:
        try:
            # Company posts on that channel only, and only from 2023 onwards.
            sql = """
                -- COALESCE, so a post still in the queue keeps showing its
                -- planned date: sent_at stays empty until Buffer sent it.
                SELECT buffer_post_id, post_text, status,
                       COALESCE(sent_at, due_at),
                       planner_post_id, has_image, linkedin_url, thumbnail_url, updated_at
                FROM buffer_posts_posted
                WHERE (COALESCE(sent_at, due_at) IS NULL
                       OR COALESCE(sent_at, due_at) >= '2023-01-01')
            """
            params = []
            if octovis_channel:
                sql += " AND channel_id = %s"
                params.append(octovis_channel)
            sql += " ORDER BY COALESCE(sent_at, due_at) DESC, id DESC"
            c.execute(sql, params)
            for bpid, text, status, sent_at, pid, has_image, link, thumb, updated in c.fetchall():
                if updated and (last_fetch is None or updated > last_fetch):
                    last_fetch = updated
                s = sent_at or ''
                posts.append({
                    "buffer_post_id": bpid,
                    "text": text or '',
                    "status": status or '',
                    "sent_at": s[:10] if s else '',
                    "planner_id": pid,
                    "has_image": bool(has_image),
                    "thumbnail_url": thumb or '',
                    "link": link or '',
                })
        except Exception as e:
            # The table is not there yet - say what to run, not just "error".
            if 'buffer_posts_posted' in str(e):
                error = ("No Buffer posts in the database yet. Run "
                         "'python manage.py fetch_buffer_posts' once.")
            else:
                error = "Could not read the data: {}".format(e)

    if not posts and not error:
        error = ("No Buffer posts in the database yet. Run "
                 "'python manage.py fetch_buffer_posts' once.")

    return posts, last_fetch, error


@login_required
def buffer_post_list(request):
    """The old tab 'Buffer Posts Posted' is part of Posts Posted now.
    Kept as an address, so a bookmark still lands somewhere sensible."""
    return redirect('posts_posted:list')


@login_required
def post_add(request):
    if request.method == "POST":
        form = PostPostedForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, "Post date saved!")
            except Exception as e:
                messages.error(request, str(e))
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
    return redirect("posts_posted:list")


@login_required
def post_edit(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        form = PostPostedForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            try:
                # Save the date with plain SQL - this skips full_clean and the
                new_date = form.cleaned_data.get('post_date')
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE linkedin_posts_posted SET post_date=%s WHERE id=%s',
                        [new_date, post.pk]
                    )
                # Upload the image, if one was given
                upload_file = request.FILES.get("upload_image")
                if upload_file:
                    from .nc_storage import upload_image_to_nextcloud
                    import os, tempfile
                    suffix = os.path.splitext(upload_file.name)[1]
                    filename = "post_{}{}".format(post.post_id, suffix)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        for chunk in upload_file.chunks():
                            tmp.write(chunk)
                        tmp_path = tmp.name
                    try:
                        with open(tmp_path, 'rb') as img_f:
                            nc_path = upload_image_to_nextcloud(img_f, filename)
                        if nc_path:
                            with connection.cursor() as cur:
                                cur.execute(
                                    "UPDATE linkedin_posts_posted SET post_image=%s WHERE id=%s",
                                    [nc_path, post.pk]
                                )
                            messages.success(request, "Image saved!")
                        else:
                            messages.error(request, "Nextcloud upload failed!")
                    finally:
                        os.unlink(tmp_path)
                messages.success(request, "Updated!")
            except Exception as e:
                messages.error(request, str(e))
            return redirect("posts_posted:list")
    else:
        form = PostPostedForm(instance=post)
    return render(request, "posts_posted/edit.html", {"form": form, "post": post})


@login_required
def post_delete(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        post.delete()
        messages.success(request, "Post {} deleted.".format(post.post_id))
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})


@login_required
def post_image_proxy(request, pk):
    """Proxy: fetch the image from Nextcloud and serve it."""
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if not post.post_image:
        raise Http404("No image on this post")
    nc_path = str(post.post_image)
    content, content_type = download_image_from_nextcloud(nc_path)
    if content is None:
        raise Http404("The image could not be loaded from Nextcloud")
    response = HttpResponse(content, content_type=content_type)
    response['Cache-Control'] = 'public, max-age=86400'
    return response


@login_required
def post_delete_image(request, pk):
    """Delete a post's image, both in Nextcloud and in the database."""
    from django.db import connection as _conn
    from .nc_storage import delete_image_from_nextcloud
    with _conn.cursor() as cur:
        cur.execute("SELECT post_url, post_image FROM linkedin_posts_posted WHERE id = %s", [pk])
        row = cur.fetchone()
    if not row:
        messages.error(request, "Post not found.")
        return redirect("posts_posted:list")
    post_url, nc_path = row
    if nc_path:
        delete_image_from_nextcloud(nc_path)
        with _conn.cursor() as cur:
            cur.execute("UPDATE linkedin_posts_posted SET post_image = NULL WHERE id = %s", [pk])
        messages.success(request, "Image deleted.")
    else:
        messages.info(request, "No image present.")
    return redirect("posts_posted:list")
