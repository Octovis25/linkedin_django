"""Website log of octotrial.com: what changed, when, by whom.

WordPress keeps the revisions of pages and posts; the app copies them into
its own tables (read only on the WordPress side), so the history stays even
when WordPress drops old revisions. Media uploads are kept too.

Tables are made here (CREATE TABLE IF NOT EXISTS), like the OJ statistics -
no migration to run on production. Times are stored in UTC and shown in
Berlin time.

One "change" in the list = one save: all revisions of one page by one
WordPress user in the same minute. Elementor writes up to three revisions
per save.

No working-time evaluation on purpose (Ortrud, 04.11.2026): the log shows
what was changed, not how long anybody worked.
"""
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import connection

from . import diff, wp

BERLIN = ZoneInfo('Europe/Berlin')
UTC = ZoneInfo('UTC')
KIND_FILTERS = ('Text', 'Title', 'Image', 'No text change', 'New', 'Upload')

# WordPress user id -> name. Editors may not read the full user list, so the
# names are kept here; unknown ids show as "User <id>".
DEFAULT_AUTHORS = [
    (6, 'Ekaterina', None, 0),
    (7, 'Ortrud Junker-Wolf', None, 0),
    (8, 'octovis-log', None, 0),
    (4, 'Jan', None, 0),
    (1, 'Hosting admin', None, 0),
]


def ensure_tables():
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS wp_log_objects (
            wp_id INT PRIMARY KEY, kind VARCHAR(10), title VARCHAR(500), link VARCHAR(500),
            modified_gmt DATETIME NULL, checked_modified DATETIME NULL, last_seen DATETIME NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS wp_log_revisions (
            wp_revision_id INT PRIMARY KEY, wp_id INT, author_id INT NULL, saved_utc DATETIME,
            title VARCHAR(500), text_plain MEDIUMTEXT, kinds VARCHAR(40) NULL, changed INT NULL,
            INDEX wp_log_rev_obj (wp_id, saved_utc), INDEX wp_log_rev_time (saved_utc))""")
        c.execute("""CREATE TABLE IF NOT EXISTS wp_log_media (
            wp_id INT PRIMARY KEY, author_id INT NULL, uploaded_utc DATETIME, title VARCHAR(500),
            url VARCHAR(700))""")
        c.execute("""CREATE TABLE IF NOT EXISTS wp_log_notes (
            id INT AUTO_INCREMENT PRIMARY KEY, created_utc DATETIME, wp_id INT NULL,
            entry_key VARCHAR(80) NULL, text TEXT, author VARCHAR(150))""")
        c.execute("""CREATE TABLE IF NOT EXISTS wp_log_authors (
            wp_user_id INT PRIMARY KEY, name VARCHAR(150), person VARCHAR(150) NULL,
            with_claude TINYINT DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS wp_log_sync (
            id INT AUTO_INCREMENT PRIMARY KEY, started_utc DATETIME, finished_utc DATETIME NULL,
            ok TINYINT DEFAULT 0, complete TINYINT DEFAULT 0, message TEXT,
            new_revisions INT DEFAULT 0, new_media INT DEFAULT 0)""")
        c.execute("SELECT COUNT(*) FROM wp_log_authors")
        if not c.fetchone()[0]:
            c.executemany("INSERT INTO wp_log_authors (wp_user_id, name, person, with_claude) VALUES (%s,%s,%s,%s)",
                          DEFAULT_AUTHORS)


def _utc(text):
    """'2026-10-06T09:12:30' (WordPress *_gmt) -> naive UTC datetime."""
    if not text:
        return None
    return datetime.fromisoformat(str(text)[:19])


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def berlin(dt):
    return dt.replace(tzinfo=UTC).astimezone(BERLIN) if dt else None


# ---------------------------------------------------------------- sync

def sync(budget_seconds=240):
    """Copies new revisions and uploads from WordPress. Returns a dict with
    ok, complete, new_revisions, new_media, message.

    Only pages whose modified time changed since the last look are asked for
    their revisions. When the time budget runs out (a web request must stay
    under gunicorn's 300 s), the rest is done by the next sync.
    """
    ensure_tables()
    start = time.monotonic()
    with connection.cursor() as c:
        c.execute("INSERT INTO wp_log_sync (started_utc, message) VALUES (%s, '')", [_now()])
        sync_id = c.lastrowid
    res = {'ok': False, 'complete': False, 'new_revisions': 0, 'new_media': 0, 'message': ''}
    try:
        objs = wp.objects()
        with connection.cursor() as c:
            c.execute("SELECT wp_id, checked_modified FROM wp_log_objects")
            checked = dict(c.fetchall())
        todo = []
        now = _now()
        with connection.cursor() as c:
            for o in objs:
                mod = _utc(o['modified_gmt'])
                c.execute("""INSERT INTO wp_log_objects (wp_id, kind, title, link, modified_gmt, last_seen)
                             VALUES (%s,%s,%s,%s,%s,%s)
                             ON DUPLICATE KEY UPDATE kind=VALUES(kind), title=VALUES(title), link=VALUES(link),
                               modified_gmt=VALUES(modified_gmt), last_seen=VALUES(last_seen)""",
                          [o['id'], 'page' if o['kind'] == 'pages' else 'post', o['title'][:500],
                           o['link'][:500], mod, now])
                if mod is None or checked.get(o['id']) != mod:
                    todo.append((o, mod))
        todo.sort(key=lambda t: t[1] or datetime.min, reverse=True)     # newest changes first
        done = 0
        for o, mod in todo:
            if time.monotonic() - start > budget_seconds:
                break
            res['new_revisions'] += _store_revisions(o, wp.revisions(o['kind'], o['id']))
            with connection.cursor() as c:
                c.execute("UPDATE wp_log_objects SET checked_modified=%s WHERE wp_id=%s", [mod, o['id']])
            done += 1
        if done == len(todo) and time.monotonic() - start <= budget_seconds:
            res['new_media'] = _store_media(wp.media())
            res['complete'] = True
        res['ok'] = True
        rest = len(todo) - done
        res['message'] = (f"{res['new_revisions']} new revisions, {res['new_media']} new uploads."
                          + ('' if res['complete'] else f' {rest} pages left - press "Sync now" again.'))
    except wp.WordPressError as fehler:
        res['message'] = str(fehler)
    with connection.cursor() as c:
        c.execute("""UPDATE wp_log_sync SET finished_utc=%s, ok=%s, complete=%s, message=%s,
                     new_revisions=%s, new_media=%s WHERE id=%s""",
                  [_now(), int(res['ok']), int(res['complete']), res['message'][:2000],
                   res['new_revisions'], res['new_media'], sync_id])
    return res


def _store_revisions(obj, revs):
    """Saves the revisions not yet known and fills in what changed against
    the revision before (whoever made it). Returns how many were new."""
    neu = 0
    with connection.cursor() as c:
        for r in revs:
            c.execute("""INSERT IGNORE INTO wp_log_revisions
                         (wp_revision_id, wp_id, author_id, saved_utc, title, text_plain)
                         VALUES (%s,%s,%s,%s,%s,%s)""",
                      [r['id'], obj['id'], r['author_id'], _utc(r['modified_gmt']),
                       (r['title'] or '')[:500], diff.text_plain(r['content'])])
            neu += c.rowcount
        if neu:
            _classify(c, obj['id'])
    return neu


def _classify(c, wp_id):
    c.execute("""SELECT wp_revision_id, title, text_plain, kinds FROM wp_log_revisions
                 WHERE wp_id=%s ORDER BY saved_utc, wp_revision_id""", [wp_id])
    prev = None
    for rid, title, text, kinds in c.fetchall():
        if kinds is None:
            if prev is None:
                k, n = ['New'], 0
            else:
                k, n = diff.compare(prev[1], text, prev[0], title)
            c.execute("UPDATE wp_log_revisions SET kinds=%s, changed=%s WHERE wp_revision_id=%s",
                      [','.join(k), n, rid])
        prev = (title, text)


def _store_media(items):
    neu = 0
    with connection.cursor() as c:
        for m in items:
            c.execute("""INSERT INTO wp_log_media (wp_id, author_id, uploaded_utc, title, url)
                         VALUES (%s,%s,%s,%s,%s)
                         ON DUPLICATE KEY UPDATE title=VALUES(title), url=VALUES(url)""",
                      [m['id'], m['author_id'], _utc(m['date_gmt']), (m['title'] or '')[:500], m['url'][:700]])
            neu += 1 if c.rowcount == 1 else 0
    return neu


def last_sync():
    ensure_tables()
    with connection.cursor() as c:
        c.execute("""SELECT finished_utc, ok, complete, message FROM wp_log_sync
                     WHERE finished_utc IS NOT NULL ORDER BY id DESC LIMIT 1""")
        r = c.fetchone()
        c.execute("SELECT COUNT(*) FROM wp_log_revisions")
        revs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM wp_log_media")
        med = c.fetchone()[0]
    return {'at': berlin(r[0]) if r else None, 'ok': bool(r[1]) if r else None,
            'complete': bool(r[2]) if r else None, 'message': r[3] if r else '',
            'revisions': revs, 'media': med}


# ---------------------------------------------------------------- authors

def authors():
    ensure_tables()
    with connection.cursor() as c:
        c.execute("SELECT wp_user_id, name, person, with_claude FROM wp_log_authors ORDER BY wp_user_id")
        return [{'id': r[0], 'name': r[1], 'person': r[2] or '', 'with_claude': bool(r[3])} for r in c.fetchall()]


def save_author(user_id, name, person='', with_claude=False):
    ensure_tables()
    with connection.cursor() as c:
        c.execute("""INSERT INTO wp_log_authors (wp_user_id, name, person, with_claude) VALUES (%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE name=VALUES(name), person=VALUES(person),
                       with_claude=VALUES(with_claude)""",
                  [int(user_id), name.strip()[:150], (person or '').strip()[:150] or None, int(bool(with_claude))])


def _who(amap, author_id):
    """(person shown, with Claude?) for a WordPress user id."""
    a = amap.get(author_id)
    if not a:
        return (f'User {author_id}' if author_id else 'Unknown'), False
    return (a['person'] or a['name']), a['with_claude']


# ---------------------------------------------------------------- the list

def entry_key(wp_id, author_id, minute):
    return f"{wp_id}:{author_id or 0}:{minute:%Y%m%d%H%M}"


def _range_utc(day_from, day_to):
    """Berlin days (inclusive) -> UTC datetimes [start, end)."""
    start = datetime.combine(day_from, datetime.min.time(), BERLIN).astimezone(UTC).replace(tzinfo=None)
    end = datetime.combine(day_to + timedelta(days=1), datetime.min.time(), BERLIN).astimezone(UTC).replace(tzinfo=None)
    return start, end


def changes(day_from, day_to, person='', wp_id=None, kind='', limit=500):
    """The changes in a period, newest first. Each: key, time (Berlin), person,
    with_claude, wp_id, title, link, type, kinds, changed, revisions, notes."""
    ensure_tables()
    start, end = _range_utc(day_from, day_to)
    amap = {a['id']: a for a in authors()}
    with connection.cursor() as c:
        sql = """SELECT r.wp_id, r.author_id, r.saved_utc, r.kinds, r.changed,
                        o.title, o.link, o.kind
                 FROM wp_log_revisions r LEFT JOIN wp_log_objects o ON o.wp_id = r.wp_id
                 WHERE r.saved_utc >= %s AND r.saved_utc < %s"""
        args = [start, end]
        if wp_id:
            sql += " AND r.wp_id=%s"
            args.append(int(wp_id))
        c.execute(sql + " ORDER BY r.wp_id, r.author_id, r.saved_utc, r.wp_revision_id", args)
        rows = c.fetchall()
        groups = {}
        for wid, aid, saved, kinds, changed, title, link, otype in rows:
            minute = saved.replace(second=0, microsecond=0)
            key = entry_key(wid, aid, minute)
            g = groups.get(key)
            if not g:
                who, claude = _who(amap, aid)
                g = groups[key] = {'key': key, 'utc': saved, 'person': who, 'with_claude': claude,
                                   'author_id': aid, 'wp_id': wid, 'title': title or f'#{wid}', 'link': link or '',
                                   'type': otype or '', 'kinds': [], 'changed': 0, 'revisions': 0}
            g['utc'] = max(g['utc'], saved)
            g['revisions'] += 1
            g['changed'] += changed or 0
            for k in (kinds or '').split(','):
                if k and k not in g['kinds']:
                    g['kinds'].append(k)
        if not wp_id:
            c.execute("""SELECT wp_id, author_id, uploaded_utc, title, url FROM wp_log_media
                         WHERE uploaded_utc >= %s AND uploaded_utc < %s""", [start, end])
            for mid, aid, up, title, url in c.fetchall():
                who, claude = _who(amap, aid)
                key = f"m{mid}"
                groups[key] = {'key': key, 'utc': up, 'person': who, 'with_claude': claude, 'author_id': aid,
                               'wp_id': mid, 'title': title or url.rsplit('/', 1)[-1], 'link': url,
                               'type': 'upload', 'kinds': ['Upload'], 'changed': 0, 'revisions': 0}
        c.execute("""SELECT id, created_utc, wp_id, entry_key, text, author FROM wp_log_notes
                     ORDER BY created_utc""")
        notes = c.fetchall()
    out = []
    for g in groups.values():
        if not g['kinds']:
            g['kinds'] = ['No text change']
        if person and g['person'] != person:
            continue
        if kind and kind not in g['kinds']:
            continue
        g['berlin'] = berlin(g['utc'])
        day = g['berlin'].date()
        g['notes'] = [n[4] for n in notes
                      if n[3] == g['key'] or (not n[3] and n[2] == g['wp_id'] and g['type'] != 'upload'
                                              and berlin(n[1]).date() == day)]
        out.append(g)
    out.sort(key=lambda g: g['utc'], reverse=True)
    return out[:limit], len(out)


def people():
    """Everybody who appears in the log, for the person filter."""
    ensure_tables()
    amap = {a['id']: a for a in authors()}
    with connection.cursor() as c:
        c.execute("SELECT DISTINCT author_id FROM wp_log_revisions UNION SELECT DISTINCT author_id FROM wp_log_media")
        ids = [r[0] for r in c.fetchall()]
    return sorted({_who(amap, i)[0] for i in ids})


def pages():
    ensure_tables()
    with connection.cursor() as c:
        c.execute("SELECT wp_id, title, kind FROM wp_log_objects ORDER BY title")
        return [{'id': r[0], 'title': r[1] or f'#{r[0]}', 'kind': r[2]} for r in c.fetchall()]


def detail(key):
    """Before/after of one change: the revision before the save (whoever made
    it) against the last revision of the save."""
    ensure_tables()
    try:
        wid, aid, stamp = key.split(':')
        wid, aid = int(wid), int(aid)
        minute = datetime.strptime(stamp, '%Y%m%d%H%M')
    except ValueError:
        return None
    amap = {a['id']: a for a in authors()}
    with connection.cursor() as c:
        c.execute("""SELECT wp_revision_id, saved_utc, title, text_plain FROM wp_log_revisions
                     WHERE wp_id=%s AND COALESCE(author_id,0)=%s AND saved_utc >= %s AND saved_utc < %s
                     ORDER BY saved_utc, wp_revision_id""", [wid, aid, minute, minute + timedelta(minutes=1)])
        mine = c.fetchall()
        if not mine:
            return None
        first, last = mine[0], mine[-1]
        c.execute("""SELECT wp_revision_id, saved_utc, title, text_plain, author_id FROM wp_log_revisions
                     WHERE wp_id=%s AND (saved_utc < %s OR (saved_utc = %s AND wp_revision_id < %s))
                     ORDER BY saved_utc DESC, wp_revision_id DESC LIMIT 1""", [wid, first[1], first[1], first[0]])
        prev = c.fetchone()
    before_html, after_html = diff.side_by_side(prev[3] if prev else '', last[3])
    title_before = prev[2] if prev else ''
    return {'before': before_html, 'after': after_html,
            'before_when': berlin(prev[1]) if prev else None,
            'before_who': _who(amap, prev[4])[0] if prev else '',
            'title_before': title_before, 'title_after': last[2],
            'title_changed': bool(prev) and (title_before or '').strip() != (last[2] or '').strip()}


# ---------------------------------------------------------------- notes

def add_note(text, author, wp_id=None, key=None):
    ensure_tables()
    text = (text or '').strip()
    if not text:
        return False
    with connection.cursor() as c:
        c.execute("INSERT INTO wp_log_notes (created_utc, wp_id, entry_key, text, author) VALUES (%s,%s,%s,%s,%s)",
                  [_now(), int(wp_id) if wp_id else None, (key or '')[:80] or None, text[:5000], author[:150]])
    return True


def notes():
    ensure_tables()
    with connection.cursor() as c:
        c.execute("""SELECT n.created_utc, n.wp_id, n.entry_key, n.text, n.author, o.title
                     FROM wp_log_notes n LEFT JOIN wp_log_objects o ON o.wp_id = n.wp_id
                     ORDER BY n.created_utc DESC""")
        return [{'berlin': berlin(r[0]), 'wp_id': r[1], 'key': r[2] or '', 'text': r[3], 'author': r[4],
                 'title': r[5] or ''} for r in c.fetchall()]
