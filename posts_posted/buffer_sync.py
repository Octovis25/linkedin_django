"""Running the Buffer sync from the app itself.

There is no cron job. `render.yaml` describes one - service
`buffer-posts-daily`, 12:00 UTC - but the services on Render were created by
hand and that file was never applied. So the "daily sync at 14:00" the
Scheduled page used to promise never existed at all. Posts left Scheduled only
as a side effect of an Excel import, because that path happens to call
fetch_buffer_posts too.

Two ways in, both from here:

  * `sync_in_background()` - at most once a day, when someone opens the
    Scheduled page. It returns immediately and does the work in a thread; a
    page load must not wait on Buffer's API.
  * `sync_now()` - the button on that page. Runs to completion and reports
    what it did, because the user is waiting for exactly that answer.

Every run is written to `buffer_sync_log`, so the page can say when it last
happened instead of claiming a schedule that does not exist.
"""
import io
import threading
from datetime import timedelta

from django.core.management import call_command
from django.db import connection
from django.utils import timezone

TABELLE = """
CREATE TABLE IF NOT EXISTS buffer_sync_log (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    started_at  DATETIME NOT NULL,
    finished_at DATETIME NULL DEFAULT NULL,
    ok          TINYINT DEFAULT 0,
    promoted    INT DEFAULT 0,
    ausloeser   VARCHAR(20) DEFAULT 'auto',
    note        VARCHAR(255) DEFAULT ''
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
"""

_tabelle_geprueft = False


def _tabelle_sicherstellen():
    global _tabelle_geprueft
    if _tabelle_geprueft:
        return
    with connection.cursor() as c:
        c.execute(TABELLE)
    _tabelle_geprueft = True


def letzter_lauf():
    """The most recent finished run, or None. (started_at, ok, promoted, trigger)"""
    _tabelle_sicherstellen()
    with connection.cursor() as c:
        c.execute("""SELECT started_at, ok, promoted, ausloeser
                     FROM buffer_sync_log
                     WHERE finished_at IS NOT NULL
                     ORDER BY started_at DESC LIMIT 1""")
        return c.fetchone()


def _belegen(min_stunden, ausloeser):
    """Claim a run, or return None if there is no point starting one.

    Two things block a claim: a run that is still going (nobody needs two at
    once), and - for the automatic path - a finished run young enough that
    another would be pointless. The claim IS the insert, so two page loads
    arriving in the same second cannot both start a sync: the second inserts
    no row and gets None back. MySQL refuses to read the target table of an
    INSERT directly, hence the derived table.
    """
    _tabelle_sicherstellen()
    jetzt = timezone.now().replace(tzinfo=None)
    grenze = jetzt - timedelta(hours=min_stunden)
    # A run that never reported back is treated as dead after ten minutes,
    # otherwise one crashed worker would block the sync forever.
    haengt = jetzt - timedelta(minutes=10)
    with connection.cursor() as c:
        c.execute("""
            INSERT INTO buffer_sync_log (started_at, ausloeser)
            SELECT %s, %s FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM (SELECT started_at, finished_at FROM buffer_sync_log) AS a
                WHERE a.finished_at IS NULL AND a.started_at > %s
            )
            AND NOT EXISTS (
                SELECT 1 FROM (SELECT started_at, finished_at FROM buffer_sync_log) AS b
                WHERE b.finished_at IS NOT NULL AND b.started_at > %s
            )
        """, [jetzt, ausloeser, haengt, grenze])
        if not c.rowcount:
            return None
        c.execute("SELECT LAST_INSERT_ID()")
        return c.fetchone()[0]


def _offen():
    """How many posts are waiting in Scheduled right now."""
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM planner_posts WHERE status='Scheduled'")
        return (c.fetchone() or [0])[0]


def _abschliessen(lauf_id, ok, promoted, note=''):
    with connection.cursor() as c:
        c.execute("""UPDATE buffer_sync_log
                     SET finished_at=%s, ok=%s, promoted=%s, note=%s
                     WHERE id=%s""",
                  [timezone.now().replace(tzinfo=None), 1 if ok else 0,
                   promoted, (note or '')[:255], lauf_id])


def _durchfuehren(lauf_id):
    """The work itself. Counts before and after instead of parsing the
    command's output - the number that matters is how many posts left
    Scheduled, and that is exactly what the difference says."""
    vorher = _offen()
    try:
        call_command('fetch_buffer_posts', stdout=io.StringIO(), stderr=io.StringIO())
        promoted = max(0, vorher - _offen())
        _abschliessen(lauf_id, True, promoted)
        return {'ok': True, 'promoted': promoted}
    except Exception as fehler:
        _abschliessen(lauf_id, False, 0, str(fehler))
        return {'ok': False, 'error': str(fehler)}


def sync_in_background(min_stunden=20):
    """Start a sync unless one ran within the last `min_stunden`.

    Returns True if a run was started. The page does not wait for it: Buffer's
    API takes seconds, and nobody should stare at a blank Scheduled page for
    that. The result shows up on the next visit.
    """
    try:
        lauf_id = _belegen(min_stunden, 'auto')
    except Exception:
        return False           # the page must render even if this fails
    if not lauf_id:
        return False

    def arbeiten():
        try:
            _durchfuehren(lauf_id)
        finally:
            # A thread of our own gets a connection of its own, and it has to
            # give it back - otherwise they pile up until the database refuses.
            connection.close()

    threading.Thread(target=arbeiten, daemon=True).start()
    return True


def sync_now():
    """Run a sync to completion, whatever the last one's age. For the button."""
    lauf_id = _belegen(0, 'button')
    if not lauf_id:
        return {'ok': False, 'error': 'A sync is already running.'}
    return _durchfuehren(lauf_id)
