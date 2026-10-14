"""The audit trail table: one row per change somebody made in the app.

Who, when, what, on which object, and whether it worked. Written by the
middleware (every POST/PUT/PATCH/DELETE of a signed-in user or of the Claude
API) and by the sign-in signals. Read only by the audit page, which only the
owner can open.

Like the other tables of this app it creates itself (CREATE TABLE IF NOT
EXISTS) instead of going through a migration.

Repeats are folded: the Studio and the flowchart editor save every few
seconds while somebody works. The same person doing the same thing to the same
object within FOLD_SECONDS updates the last row (count + 1, new end time)
instead of adding one - otherwise one afternoon in the Studio would be a
thousand lines.
"""
import json
from datetime import datetime, timedelta, timezone

from django.db import connection

TABLE = 'audit_log'
FOLD_SECONDS = 120
KEEP_DAYS = 400

_checked = False
_last_prune = None

CREATE = """
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    at         DATETIME NOT NULL,
    last_at    DATETIME NOT NULL,
    times      INT NOT NULL DEFAULT 1,
    user_id    INT NULL,
    username   VARCHAR(150) NOT NULL DEFAULT '',
    method     VARCHAR(10) NOT NULL DEFAULT '',
    path       VARCHAR(500) NOT NULL DEFAULT '',
    view       VARCHAR(150) NOT NULL DEFAULT '',
    action     VARCHAR(100) NOT NULL DEFAULT '',
    object_id  VARCHAR(64) NOT NULL DEFAULT '',
    status     SMALLINT NOT NULL DEFAULT 0,
    details    TEXT,
    KEY ix_at (at),
    KEY ix_user_at (username, at),
    KEY ix_object (object_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
"""


def utcnow():
    """Naive UTC - the same convention as post_scheduled_at."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_table(force=False):
    global _checked
    if _checked and not force:
        return
    with connection.cursor() as c:
        c.execute(CREATE)
    _checked = True


def write(username, method, path, view='', action='', object_id='', status=0,
          details=None, user_id=None, now=None):
    """Record one change. Never raises: the trail must not break the app."""
    try:
        ensure_table()
        now = now or utcnow()
        text = json.dumps(details or {}, ensure_ascii=False, default=str)[:4000]
        values = [(username or '')[:150], (method or '')[:10], (path or '')[:500],
                  (view or '')[:150], (action or '')[:100], str(object_id or '')[:64]]
        with connection.cursor() as c:
            c.execute(
                """SELECT id, details FROM audit_log
                   WHERE username=%s AND method=%s AND path=%s AND view=%s
                     AND action=%s AND object_id=%s AND status=%s AND last_at >= %s
                   ORDER BY id DESC LIMIT 1""",
                values + [int(status or 0), now - timedelta(seconds=FOLD_SECONDS)])
            row = c.fetchone()
            if row:
                c.execute("UPDATE audit_log SET times=times+1, last_at=%s, details=%s "
                          "WHERE id=%s", [now, text, row[0]])
            else:
                c.execute(
                    """INSERT INTO audit_log
                       (at, last_at, username, method, path, view, action, object_id,
                        status, details, user_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [now, now] + values + [int(status or 0), text, user_id])
        _prune(now)
    except Exception as error:
        print('audit trail: could not write (%s)' % error)


def _prune(now):
    """Once a day per process: drop rows older than KEEP_DAYS."""
    global _last_prune
    if _last_prune and now - _last_prune < timedelta(days=1):
        return
    _last_prune = now
    with connection.cursor() as c:
        c.execute("DELETE FROM audit_log WHERE at < %s", [now - timedelta(days=KEEP_DAYS)])


def read(since, until, username='', text='', object_id='', limit=300):
    """Rows newest first, as dicts. since/until are naive UTC."""
    ensure_table()
    sql = ["SELECT id, at, last_at, times, username, method, path, view, action, "
           "object_id, status, details FROM audit_log WHERE at >= %s AND at < %s"]
    args = [since, until]
    if username:
        sql.append("AND username = %s")
        args.append(username)
    if object_id:
        sql.append("AND object_id = %s")
        args.append(object_id)
    if text:
        sql.append("AND (path LIKE %s OR view LIKE %s OR action LIKE %s OR details LIKE %s)")
        args += ['%' + text + '%'] * 4
    sql.append("ORDER BY at DESC, id DESC LIMIT %s")
    args.append(int(limit))
    with connection.cursor() as c:
        c.execute(' '.join(sql), args)
        names = [d[0] for d in c.description]
        rows = [dict(zip(names, r)) for r in c.fetchall()]
    for r in rows:
        try:
            r['details'] = json.loads(r['details'] or '{}')
        except ValueError:
            r['details'] = {'raw': r['details']}
    return rows


def summary(since, until):
    """Per person: number of changes, sign-ins, first and last activity."""
    ensure_table()
    with connection.cursor() as c:
        c.execute(
            """SELECT username,
                      SUM(CASE WHEN view NOT LIKE 'auth:%%' THEN times ELSE 0 END),
                      SUM(CASE WHEN action = 'login' THEN 1 ELSE 0 END),
                      MIN(at), MAX(last_at)
               FROM audit_log WHERE at >= %s AND at < %s
               GROUP BY username ORDER BY MAX(last_at) DESC""", [since, until])
        return [{'username': r[0], 'changes': int(r[1] or 0), 'logins': int(r[2] or 0),
                 'first': r[3], 'last': r[4]} for r in c.fetchall()]


def usernames():
    ensure_table()
    with connection.cursor() as c:
        c.execute("SELECT DISTINCT username FROM audit_log ORDER BY username")
        return [r[0] for r in c.fetchall()]
