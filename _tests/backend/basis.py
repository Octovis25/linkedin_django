"""Gemeinsames Gerüst für die Backend-Tests.

Zwei Dinge nimmt es jedem einzelnen Test ab:

  * eine angemeldete Sitzung (fast alle Ansichten haben @login_required, ohne
    Anmeldung prüft man nur die Weiterleitung zur Anmeldeseite),
  * eine Nextcloud-Attrappe (`WolkeAttrappe`) statt der echten Wolke. Sie ist
    kein Beiwerk, sondern der Kern: Die Fehler, die in dieser App auftreten,
    entstehen fast alle daran, wie die Ansichten auf eine *nicht* gelingende
    Nextcloud-Antwort reagieren. Genau das lässt sich mit der echten Wolke nicht
    zuverlässig herstellen - mit der Attrappe schon.
"""
import os
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase


class WolkeAttrappe:
    """Ein Nextcloud, das im Arbeitsspeicher liegt und sich auf Kommando weigert.

    Benutzung im Test::

        with self.wolke() as w:
            w.dateien['Marketing & Design/x/bild.png'] = b'...'
            w.loeschen_scheitert_mit = 'Datei gesperrt (423)'
            antwort = self.client.post(...)

        w.geloescht   -> was tatsächlich zum Löschen kam
    """

    def __init__(self):
        self.dateien = {}                  # nc_path -> bytes
        self.typen = {}                    # nc_path -> Content-Type von "Nextcloud"
        self.geloescht = []                # jeder Löschauftrag, auch gescheiterte
        self.loeschen_scheitert_mit = None  # Grund, oder None für "gelingt"
        self.holen_scheitert = False

    # -- was die Ansichten aufrufen ------------------------------------------
    def loeschen(self, nc_path):
        self.geloescht.append(nc_path)
        if self.loeschen_scheitert_mit:
            return False, self.loeschen_scheitert_mit
        self.dateien.pop(nc_path, None)
        return True, ''

    def herunterladen(self, nc_path):
        if self.holen_scheitert or nc_path not in self.dateien:
            return None, None
        return self.dateien[nc_path], self.typen.get(nc_path, 'application/octet-stream')

    def stroemen(self, nc_path, range_header=None, timeout=60):
        """Stellt nach, was requests mit stream=True liefert - inklusive der
        206-Antwort auf eine Range-Anfrage, denn genau die braucht Video."""
        if self.holen_scheitert or nc_path not in self.dateien:
            return None, 'Nextcloud answered 404'
        inhalt = self.dateien[nc_path]
        kopfzeilen = {'Content-Type': self.typen.get(nc_path, 'application/octet-stream')}
        status = 200
        if range_header and range_header.startswith('bytes='):
            spanne = range_header[6:].strip()
            von, _, bis = spanne.partition('-')
            anfang = int(von) if von else 0
            ende = int(bis) if bis else len(inhalt) - 1
            ende = min(ende, len(inhalt) - 1)
            inhalt = inhalt[anfang:ende + 1]
            status = 206
            kopfzeilen['Content-Range'] = 'bytes %d-%d/%d' % (
                anfang, ende, len(self.dateien[nc_path]))
        kopfzeilen['Content-Length'] = str(len(inhalt))
        return _Antwort(status, kopfzeilen, inhalt), ''


class _Antwort:
    """So viel von einer requests-Antwort, wie der Proxy anfasst."""

    def __init__(self, status_code, headers, inhalt):
        self.status_code = status_code
        self.headers = headers
        self._inhalt = inhalt

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._inhalt), chunk_size):
            yield self._inhalt[i:i + chunk_size]

    def close(self):
        pass


# Die Tabellen, die die App sich selbst anlegt, entstehen über ihre eigenen
# _ensure_-Funktionen. planner_posts gehört nicht dazu - das legen wir hier an,
# und zwar ABSICHTLICH ohne die nachrüstbaren Spalten: So hat
# schema_sicherstellen() im Test wirklich etwas zu tun, statt auf einer schon
# fertigen Tabelle nichts zu finden.
PLANNER_POSTS = """
CREATE TABLE IF NOT EXISTS planner_posts (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    title    VARCHAR(255) DEFAULT '',
    content  LONGTEXT,
    status   VARCHAR(50) DEFAULT '',
    image    VARCHAR(512) DEFAULT NULL,
    link     VARCHAR(512) DEFAULT NULL,
    comment  LONGTEXT,
    category VARCHAR(100) DEFAULT NULL,
    post_date DATETIME NULL DEFAULT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
"""


def vorschau_cache_leeren():
    """Der Vorschau-Cache liegt auf der Platte und ueberlebt darum den
    Testlauf. Bliebe er stehen, bekaeme ein Test das Vorschaubild eines
    anderen - dieselbe Datei, derselbe Zeitstempel, derselbe Schluessel. Das
    ist kein theoretischer Fall: Genau daran ist der erste Lauf gescheitert.
    """
    import shutil
    from django.conf import settings as _s
    shutil.rmtree(os.path.join(_s.BASE_DIR, 'media', '_thumbs'), ignore_errors=True)


def schema_aufbauen(mit_nachgeruesteten=True):
    """Die Tabellen herstellen, die die Tests brauchen.

    Die App legt ihre eigenen Tabellen selbst an - wir rufen dafür ihre eigenen
    Funktionen auf, nicht eine abgeschriebene Fassung. So kann das Testschema
    gar nicht vom echten abweichen.

    `mit_nachgeruesteten=False` lässt planner_posts ohne die nachrüstbaren
    Spalten - dann hat schema_sicherstellen() im Test wirklich etwas zu tun.
    """
    from media_library import views
    from planner import views as pv
    views._SCHEMA_GEPRUEFT.clear()
    pv._schema_geprueft = False
    with connection.cursor() as c:
        c.execute("DROP TABLE IF EXISTS planner_posts")
        c.execute(PLANNER_POSTS)
    for name in ('_ensure_table', '_ensure_brand_colors_table',
                 '_ensure_studio_tables', '_ensure_video_template_table'):
        getattr(views, name).ungepuffert()
    if mit_nachgeruesteten:
        pv.schema_sicherstellen(erzwingen=True)


class BackendTest(TestCase):
    """Basis für alle Backend-Tests: Anmeldung, Schema, Wolken-Attrappe."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        schema_aufbauen()

    def setUp(self):
        super().setUp()
        vorschau_cache_leeren()
        self.benutzer = User.objects.create_user('pruefer', password='pruefwort')
        self.admin = User.objects.create_superuser('chefin', password='pruefwort')
        self.client.force_login(self.benutzer)

    # -- Werkzeuge -----------------------------------------------------------
    def wolke(self):
        """Kontextmanager: schaltet Nextcloud auf die Attrappe um."""
        return _WolkenSchalter()

    def zeile(self, sql, *werte):
        with connection.cursor() as c:
            c.execute(sql, list(werte))
            return c.fetchone()

    def zahl(self, sql, *werte):
        return (self.zeile(sql, *werte) or [0])[0]


class _WolkenSchalter:
    def __enter__(self):
        self.wolke = WolkeAttrappe()
        ziel = 'posts_posted.nc_storage.'
        self._flicken = [
            mock.patch(ziel + 'delete_from_nextcloud_detail', self.wolke.loeschen),
            mock.patch(ziel + 'download_image_from_nextcloud', self.wolke.herunterladen),
            mock.patch(ziel + 'stream_from_nextcloud', self.wolke.stroemen),
        ]
        for f in self._flicken:
            f.start()
        return self.wolke

    def __exit__(self, *_):
        for f in self._flicken:
            f.stop()
        return False
