"""The app's Nextcloud folder, and its move to a name without spaces (26.10.2026).

All the app's media live in one brand folder in Nextcloud. It was called
"Marketing & Design" - a space and an ampersand that every URL has to encode
("Marketing%20%26%20Design"), and that went missing on 23.10.2026. Ortrud got
it back as a transfer and had it copied to "Marketing_and_Design", together
with the files made since.

Three things make the move complete:

  * The code names the new folder everywhere (NC_ROOT).
  * The database still holds the old paths: posts, Studio designs (their JSON
    carries image addresses, URL-encoded too), templates, library items,
    tutorials. pfade_umstellen() rewrites them once, from the first request
    after the deploy - Render runs no migrations, so the app does it itself.
    A marker row makes sure it runs only once.
  * An address from before the move (an open browser tab, a cached design)
    still asks for "Marketing & Design/...". nc_pfad() turns it into the new
    path wherever a path comes in from outside.

The audit log is left as it is: it records what happened, under the names
that were valid then. Post titles, texts and comments are words, not paths.
"""
import threading

NC_ROOT = 'Marketing_and_Design'
OLD_ROOT = 'Marketing & Design'

# The old name as it can appear in stored text: plain, URL-encoded (quote and
# quote_plus, with and without the ampersand encoded), and JSON-escaped.
OLD_FORMS = (
    'Marketing & Design',
    'Marketing%20%26%20Design',
    'Marketing+%26+Design',
    'Marketing%20&%20Design',
    'Marketing \\u0026 Design',
)

MARKER = 'nc_root_marketing_and_design'

# Columns that hold words, not paths.
NOT_PATHS = {
    ('planner_posts', 'title'),
    ('planner_posts', 'content'),
    ('planner_posts', 'comment'),
}
TABLES_LEFT_ALONE = {'audit_log'}

TEXT_TYPES = ('char', 'varchar', 'tinytext', 'text', 'mediumtext', 'longtext')


def nc_pfad(pfad):
    """A path from before the move, turned into the new one. Others unchanged."""
    if not pfad:
        return pfad
    vorne = '/' if pfad.startswith('/') else ''
    rest = pfad[len(vorne):]
    if rest == OLD_ROOT or rest.startswith(OLD_ROOT + '/'):
        return vorne + NC_ROOT + rest[len(OLD_ROOT):]
    return pfad


def text_umstellen(text):
    """Every form of the old name in a piece of text, replaced by the new one."""
    if not text:
        return text
    for alt in OLD_FORMS:
        text = text.replace(alt, NC_ROOT)
    return text


def _marker_gesetzt(c):
    c.execute("""CREATE TABLE IF NOT EXISTS app_once (
                     name    VARCHAR(100) PRIMARY KEY,
                     done_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("SELECT 1 FROM app_once WHERE name=%s", [MARKER])
    return c.fetchone() is not None


def _textspalten(c):
    c.execute("""SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND DATA_TYPE IN (%s)""" %
              ','.join(['%s'] * len(TEXT_TYPES)), list(TEXT_TYPES))
    return [(t, s) for t, s in c.fetchall()
            if t not in TABLES_LEFT_ALONE and (t, s) not in NOT_PATHS
            and t != 'app_once']


def pfade_umstellen(c):
    """Rewrite every stored path to the new folder name. Returns the number of
    changed rows, or None if it had already run."""
    if _marker_gesetzt(c):
        return None
    geaendert = 0
    for tabelle, spalte in _textspalten(c):
        ausdruck = '`%s`' % spalte
        for alt in OLD_FORMS:
            ausdruck = 'REPLACE(%s, %%s, %%s)' % ausdruck
        # The innermost REPLACE comes first in the text, so the values go in
        # the same order as OLD_FORMS. A cheap filter keeps untouched rows out.
        werte = [w for alt in OLD_FORMS for w in (alt, NC_ROOT)]
        bedingung = ' OR '.join(['`%s` LIKE %%s' % spalte] * len(OLD_FORMS))
        filter_werte = ['%' + alt.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                        for alt in OLD_FORMS]
        c.execute('UPDATE `%s` SET `%s` = %s WHERE %s' % (tabelle, spalte, ausdruck, bedingung),
                  werte + filter_werte)
        geaendert += c.rowcount or 0
    c.execute("INSERT INTO app_once (name) VALUES (%s)", [MARKER])
    return geaendert


_erledigt = False
_sperre = threading.Lock()


class NcRootMiddleware:
    """Runs pfade_umstellen() once per process, on the first request.

    A failure is logged and never stops the request; the next process tries
    again, because the marker is only written after a complete run.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _erledigt
        if not _erledigt:
            with _sperre:
                if not _erledigt:
                    try:
                        from django.db import connection
                        with connection.cursor() as c:
                            n = pfade_umstellen(c)
                        if n is not None:
                            print('Nextcloud folder move: %d stored paths now point to %s/' % (n, NC_ROOT))
                    except Exception as fehler:
                        print('Nextcloud folder move failed, will retry:', fehler)
                    else:
                        _erledigt = True
        return self.get_response(request)
