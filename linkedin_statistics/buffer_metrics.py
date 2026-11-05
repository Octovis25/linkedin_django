"""Post numbers from Buffer, one snapshot per post and day.

Buffer hands out the numbers of a post (impressions, reach, reactions, video
views, ...) for about 30 days after it went out - in the free plan as well,
as long as the key has the scope insights:read (checked 01.11.2026 with
``check_buffer_scopes --insights --posting``). Buffer itself keeps no history:
it always answers with today's totals. The history comes from us storing those
totals once a day; that is what the per-post timelines are drawn from.

Storage is the table ``buffer_post_metrics`` from June 2026: one row per day,
post and metric (unique key ``uniq_day_post_metric``). Running the fetch twice
on one day overwrites that day's row, it never adds a second one.

The snapshot is taken by ``fetch_buffer_posts``. There is no cron job on
Render (render.yaml describes one, it was never set up - see
posts_posted/buffer_sync.py). So the fetch runs in the background when OJ
profile or the planner's Scheduled tab is opened and today's snapshot is
still missing, and by hand with "Fetch now" (05.11.2026: 04.11. was missing).
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db import connection

BERLIN = ZoneInfo('Europe/Berlin')

# Buffer also lists LinkedIn activity from long before Buffer was used (a
# message from 2013, a shared link from 2011). Ortrud: only posts from 2023
# on, nowhere older ones (01.11.2026). They are not stored and not shown.
OLDEST = date(2023, 1, 1)

# Buffer's metric types, in the order the pages show them, with our labels.
METRICS = [
    ('impressions', 'Impressions'),
    ('reach', 'Reach'),
    ('reactions', 'Reactions'),
    ('comments', 'Comments'),
    ('shares', 'Shares'),
    ('engagementRate', 'Eng. rate %'),
    ('views', 'Video views'),
    ('viewers', 'Unique viewers'),
    ('totalTimeWatched', 'Watch time (min)'),
]
METRIC_LABEL = dict(METRICS)


def today_berlin():
    return datetime.now(BERLIN).date()


UTC = ZoneInfo('UTC')
# Every refresh is kept for posts up to this age; older posts only get the
# daily row (their numbers hardly move, and the table stays small).
MEASURE_MAX_AGE_DAYS = 90


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _ts(text):
    """Buffer's ISO time ('2026-11-04T16:28:40.946Z') -> naive UTC datetime."""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def ensure_table():
    """The table exists in production since June 2026; this is for a fresh database."""
    with connection.cursor() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS buffer_post_metrics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                fetched_date DATE NOT NULL,
                buffer_post_id VARCHAR(100) NOT NULL,
                channel_id VARCHAR(100),
                sent_at VARCHAR(64),
                status VARCHAR(50),
                metric_type VARCHAR(100),
                metric_name VARCHAR(200),
                metric_value DOUBLE DEFAULT 0,
                metric_unit VARCHAR(50),
                metrics_updated_at VARCHAR(64),
                planner_post_id INT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                post_text TEXT,
                thumbnail_url TEXT,
                UNIQUE KEY uniq_day_post_metric (fetched_date, buffer_post_id, metric_type),
                KEY idx_fetched_date (fetched_date)
            )
        """)
        # Every refresh of Buffer's numbers with its time (05.11.2026). The
        # day table above keeps one row per day, so a second refresh on the
        # same day overwrote the first. measured_at is Buffer's
        # metrics_updated_at: when Buffer got the numbers from LinkedIn - the
        # same numbers fetched again add no row.
        c.execute("""
            CREATE TABLE IF NOT EXISTS buffer_post_measurements (
                buffer_post_id VARCHAR(100) NOT NULL,
                channel_id VARCHAR(100),
                metric_type VARCHAR(100) NOT NULL,
                measured_at DATETIME NOT NULL,
                metric_value DOUBLE DEFAULT 0,
                fetched_at DATETIME,
                PRIMARY KEY (buffer_post_id, metric_type, measured_at),
                KEY idx_meas_channel (channel_id)
            )
        """)
        # One fetch per hour at most, whoever asks (Make's call, a page load).
        c.execute("""
            CREATE TABLE IF NOT EXISTS buffer_metrics_runs (
                slot DATETIME PRIMARY KEY, started_at DATETIME, finished_at DATETIME NULL,
                ok TINYINT DEFAULT 0, note VARCHAR(255) DEFAULT ''
            )
        """)


def _planner_post_id(c, buffer_post_id):
    try:
        c.execute("SELECT id FROM planner_posts WHERE buffer_update_id=%s LIMIT 1", [buffer_post_id])
        row = c.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def store_snapshot(posts, day=None):
    """Write today's numbers of every post that has any. Returns (posts, rows)."""
    day = day or today_berlin()
    ensure_table()
    now = _utcnow()
    n_posts = n_rows = 0
    with connection.cursor() as c:
        for p in posts:
            bpid = p.get('buffer_post_id')
            metrics = [m for m in (p.get('metrics') or []) if m.get('type')]
            # Only posts that went out. A queued post has no numbers anyway.
            if not bpid or not metrics or not p.get('sent_at'):
                continue
            if (_as_date(p['sent_at']) or OLDEST) < OLDEST:
                continue
            pid = _planner_post_id(c, bpid)
            # Without Buffer's time of the numbers the day row is all there is.
            measured = _ts(p.get('metrics_updated_at'))
            young = bool(measured) and (now - (_ts(p['sent_at']) or now)).days <= MEASURE_MAX_AGE_DAYS
            for m in metrics:
                try:
                    value = float(m.get('value') or 0)
                except (TypeError, ValueError):
                    value = 0.0
                c.execute("""
                    INSERT INTO buffer_post_metrics
                        (fetched_date, buffer_post_id, channel_id, sent_at, status,
                         metric_type, metric_name, metric_value, metric_unit,
                         metrics_updated_at, planner_post_id, post_text, thumbnail_url)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                        channel_id=VALUES(channel_id), sent_at=VALUES(sent_at),
                        status=VALUES(status), metric_name=VALUES(metric_name),
                        metric_value=VALUES(metric_value), metric_unit=VALUES(metric_unit),
                        metrics_updated_at=VALUES(metrics_updated_at),
                        planner_post_id=VALUES(planner_post_id),
                        post_text=VALUES(post_text), thumbnail_url=VALUES(thumbnail_url)
                """, [day, bpid, p.get('channel_id'), p.get('sent_at'), p.get('status'),
                      m.get('type'), m.get('name'), value, m.get('unit'),
                      p.get('metrics_updated_at'), pid,
                      (p.get('text') or '')[:5000], p.get('thumbnail_url')])
                if young:
                    c.execute("""INSERT IGNORE INTO buffer_post_measurements
                                 (buffer_post_id, channel_id, metric_type, measured_at, metric_value, fetched_at)
                                 VALUES (%s,%s,%s,%s,%s,%s)""",
                              [bpid, p.get('channel_id'), m.get('type'), measured, value, now])
                n_rows += 1
            n_posts += 1
    return n_posts, n_rows


def fetch_and_store(buf_token, org_id=None, day=None):
    """Ask Buffer for all posts with numbers and store today's snapshot."""
    from planner.views import _buffer_fetch_post_metrics, _buffer_first_org_id
    org_id = org_id or _buffer_first_org_id(buf_token)
    if not org_id:
        raise Exception('No Buffer organization found.')
    posts = _buffer_fetch_post_metrics(buf_token, org_id, first=50, all_pages=True)
    return store_snapshot(posts, day=day)


def superuser_buffer():
    """Posting key and both channel ids of the superuser (the key never leaves the server)."""
    with connection.cursor() as c:
        try:
            c.execute("""
                SELECT t.buffer_token, t.buffer_profile_id, t.buffer_profile_id_person
                FROM planner_linkedin_tokens t
                JOIN auth_user u ON t.user_id = u.id
                WHERE u.is_superuser = 1 AND t.buffer_token IS NOT NULL
                LIMIT 1
            """)
            row = c.fetchone()
        except Exception:
            row = None
    if not row:
        return {'token': None, 'org_channel': None, 'person_channel': None}
    return {'token': row[0], 'org_channel': row[1], 'person_channel': row[2]}


def _as_date(sent_at):
    """Buffer's ISO time in UTC -> calendar day in Berlin."""
    if not sent_at:
        return None
    try:
        dt = datetime.fromisoformat(str(sent_at).replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(BERLIN).date()


def posts_with_latest(channel_id):
    """Every post of one channel with its newest numbers, newest post first."""
    if not channel_id:
        return []
    ensure_table()
    with connection.cursor() as c:
        c.execute("""
            SELECT m.buffer_post_id, m.sent_at, m.post_text, m.planner_post_id,
                   m.metric_type, m.metric_value, m.fetched_date
            FROM buffer_post_metrics m
            JOIN (SELECT buffer_post_id, MAX(fetched_date) AS last_day
                  FROM buffer_post_metrics WHERE channel_id=%s
                  GROUP BY buffer_post_id) l
              ON l.buffer_post_id = m.buffer_post_id AND l.last_day = m.fetched_date
            WHERE m.channel_id=%s
        """, [channel_id, channel_id])
        rows = c.fetchall()
        c.execute("""SELECT buffer_post_id, COUNT(DISTINCT fetched_date)
                     FROM buffer_post_metrics WHERE channel_id=%s GROUP BY buffer_post_id""",
                  [channel_id])
        days = dict(c.fetchall())
    posts = {}
    for bpid, sent_at, text, pid, mtype, value, last_day in rows:
        p = posts.setdefault(bpid, {
            'id': bpid, 'sent_at': sent_at, 'date': _as_date(sent_at),
            'text': (text or '').strip(), 'planner_post_id': pid,
            'last_day': last_day, 'days': days.get(bpid, 0),
            'thumb': '', 'm': {},
        })
        p['m'][mtype] = value
    # Picture and, for the rows from June 2026 that were stored without it,
    # the text: both come from the sync table (fetch_buffer_posts reads the
    # post's assets; the metrics query does not).
    if posts:
        ids = list(posts)
        with connection.cursor() as c:
            try:
                c.execute("SELECT buffer_post_id, post_text, thumbnail_url FROM buffer_posts_posted "
                          "WHERE buffer_post_id IN (%s)" % ','.join(['%s'] * len(ids)), ids)
                for bpid, text, thumb in c.fetchall():
                    if not posts[bpid]['text']:
                        posts[bpid]['text'] = (text or '').strip()
                    posts[bpid]['thumb'] = thumb or ''
            except Exception:
                pass
        with connection.cursor() as c:
            try:
                c.execute("SELECT buffer_post_id, planner_post_id FROM buffer_posts_posted "
                          "WHERE planner_post_id IS NOT NULL AND buffer_post_id IN (%s)"
                          % ','.join(['%s'] * len(ids)), ids)
                for bpid, pid in c.fetchall():
                    if not posts[bpid]['planner_post_id']:
                        posts[bpid]['planner_post_id'] = pid
            except Exception:
                pass
    # Buffer's thumbnail links (images.buffer.com/thumbnail/...) often do not
    # load any more (05.11.2026: #155, #157 empty). The planner's own preview
    # of the post stands in: as the picture when Buffer has none, otherwise
    # as the fallback the page switches to when Buffer's picture fails.
    for p in posts.values():
        pid = p['planner_post_id']
        p['thumb2'] = f'/planner/thumb/{pid}/' if pid else ''
        if not p['thumb'] and p['thumb2']:
            p['thumb'], p['thumb2'] = p['thumb2'], ''
    out = sorted((p for p in posts.values() if p['date'] and p['date'] >= OLDEST),
                 key=lambda p: (p['date'], p['id']), reverse=True)
    for p in out:
        first_line = p['text'].split('\n', 1)[0].strip()
        p['title'] = (first_line[:90] + '…') if len(first_line) > 90 else first_line
        p['video'] = bool(p['m'].get('views'))
    return out


def post_timeline(buffer_post_id):
    """Day-by-day totals of one post: [{'day', 'date', metric: value, ...}]."""
    ensure_table()
    with connection.cursor() as c:
        c.execute("""SELECT fetched_date, metric_type, metric_value, sent_at
                     FROM buffer_post_metrics WHERE buffer_post_id=%s
                     ORDER BY fetched_date""", [buffer_post_id])
        rows = c.fetchall()
    if not rows:
        return []
    start = _as_date(rows[0][3]) or rows[0][0]
    by_day = {}
    for fetched, mtype, value, _ in rows:
        d = by_day.setdefault(fetched, {'date': fetched.isoformat(), 'day': (fetched - start).days})
        d[mtype] = value
    return [by_day[k] for k in sorted(by_day)]


def first_days_curves(posts, metrics, limit=12, max_day=30):
    """For the overlay chart: per metric, per post the value by day after posting.

    posts: the list from posts_with_latest(); one timeline query per post.
    """
    timelines = [(p, post_timeline(p['id'])) for p in posts[:limit]]
    out = {}
    for metric in metrics:
        curves = []
        for p, days in timelines:
            pts = [(d['day'], d.get(metric)) for d in days
                   if d.get(metric) is not None and 0 <= d['day'] <= max_day]
            if pts:
                label = (f"{p['date']:%d.%m.} " if p['date'] else '') + p['title'][:40]
                curves.append({'id': p['id'], 'label': label, 'points': pts})
        out[metric] = curves
    return out


def last_fetch_day():
    ensure_table()
    with connection.cursor() as c:
        c.execute("SELECT MAX(fetched_date) FROM buffer_post_metrics")
        row = c.fetchone()
    return row[0] if row else None


def channel_timelines(channel_id):
    """All numbers of one channel: {post id: [{'day', 'date', metric: value}]}.

    'day' is the time from posting to the moment Buffer got the numbers
    (metrics_updated_at), in days with decimals: 1.5 = 36 hours after the
    post went out (05.11.2026). Counting calendar days of the fetch made the
    lines crooked - numbers Buffer got on 04.11. at 16:28 and fetched on
    05.11. counted as a day later. Rows without that time (June 2026) count
    calendar days from the Berlin posting day, as before. The same numbers
    fetched twice are one point.
    """
    if not channel_id:
        return {}
    ensure_table()
    with connection.cursor() as c:
        c.execute("""SELECT buffer_post_id, fetched_date, metric_type, metric_value, sent_at, metrics_updated_at
                     FROM buffer_post_metrics WHERE channel_id=%s""", [channel_id])
        rows = list(c.fetchall())
        c.execute("""SELECT m.buffer_post_id, m.metric_type, m.metric_value, m.measured_at, d.sent_at
                     FROM buffer_post_measurements m
                     JOIN (SELECT buffer_post_id, MAX(sent_at) AS sent_at FROM buffer_post_metrics
                           WHERE channel_id=%s GROUP BY buffer_post_id) d ON d.buffer_post_id = m.buffer_post_id""",
                  [channel_id])
        measured = c.fetchall()
    out = {}

    def put(bpid, key, day, label, mtype, value):
        pts = out.setdefault(bpid, {})
        d = pts.setdefault(key, {'date': label, 'day': day})
        d[mtype] = value

    for bpid, fetched, mtype, value, sent_at, updated in rows:
        start = _as_date(sent_at) or fetched
        if start < OLDEST:
            continue
        sent, at = _ts(sent_at), _ts(updated)
        if sent and at:
            put(bpid, at, round(max(0.0, (at - sent).total_seconds() / 86400), 2),
                at.replace(tzinfo=UTC).astimezone(BERLIN).date().isoformat(), mtype, value)
        else:
            put(bpid, fetched, (fetched - start).days, fetched.isoformat(), mtype, value)
    for bpid, mtype, value, at, sent_at in measured:
        sent = _ts(sent_at)
        if not sent or (_as_date(sent_at) or OLDEST) < OLDEST:
            continue
        put(bpid, at, round(max(0.0, (at - sent).total_seconds() / 86400), 2),
            at.replace(tzinfo=UTC).astimezone(BERLIN).date().isoformat(), mtype, value)
    return {bpid: sorted(pts.values(), key=lambda d: d['day']) for bpid, pts in out.items()}


def tick_key():
    """Key of the address a scheduler calls every hour (oj/tick/). Derived
    from SECRET_KEY like the planner's trigger key, so there is no extra
    secret to keep; it only lets the caller start a fetch."""
    import hashlib
    import hmac
    from django.conf import settings
    return hmac.new(settings.SECRET_KEY.encode(), b'statistics-tick', hashlib.sha256).hexdigest()[:32]


def fetch_hourly(background=True):
    """Fetch Buffer's numbers once per hour at most (05.11.2026: "stündlich,
    damit wir sehen, ob sich alle Posts ähnlich entwickeln").

    Called by a scheduler on /statistics/oj/tick/?key=... (Make, GitHub
    Actions - whatever is free), by Make's scheduled call to the planner and
    when OJ profile is opened. The hour is claimed with one INSERT, so two callers in the same
    hour cannot both fetch. Returns True when a fetch was started.
    Buffer itself refreshes the numbers about once a day; a fetch that finds
    the same numbers adds nothing (see buffer_post_measurements).
    """
    from django.conf import settings
    if background and not getattr(settings, 'BUFFER_BACKGROUND_SYNC', True):
        return False
    buf = superuser_buffer()
    if not buf['token']:
        return False
    ensure_table()
    now = _utcnow()
    slot = now.replace(minute=0, second=0)
    with connection.cursor() as c:
        c.execute("INSERT IGNORE INTO buffer_metrics_runs (slot, started_at) VALUES (%s,%s)", [slot, now])
        if c.rowcount != 1:
            return False

    def run():
        ok, note = 0, ''
        try:
            n_posts, _ = fetch_and_store(buf['token'])
            ok, note = 1, f'{n_posts} posts'
        except Exception as e:
            note = str(e)[:250]          # _buffer_graphql never puts the key in its message
        finally:
            with connection.cursor() as c:
                c.execute("UPDATE buffer_metrics_runs SET finished_at=%s, ok=%s, note=%s WHERE slot=%s",
                          [_utcnow(), ok, note, slot])
            if background:
                connection.close()

    if background:
        import threading
        threading.Thread(target=run, daemon=True).start()
    else:
        run()
    return True
