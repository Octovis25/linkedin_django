"""Schema-Pflege gegen eine echte Datenbank.

schema_test.py im Ordner darüber prüft die Auswahl-Logik ohne Datenbank. Hier
geht es um das, was nur mit einer echten MySQL herauskommt: dass das erzeugte
ALTER auch wirklich durchgeht, und dass eine fehlende Spalte danach da ist.

Absichtlich legt basis.py die Tabelle planner_posts OHNE die nachrüstbaren
Spalten an - sonst hätte die Pflege hier nichts zu tun und der Test bewiese
nichts.
"""
from django.db import connection
from django.test import TransactionTestCase

from .basis import BackendTest, schema_aufbauen


def spalten(tabelle):
    with connection.cursor() as c:
        c.execute("SHOW COLUMNS FROM `%s`" % tabelle)
        return {r[0] for r in c.fetchall()}


# TransactionTestCase statt TestCase: ALTER TABLE ist in MySQL keine Sache, die
# sich zurueckrollen laesst - jede Schema-Aenderung schliesst die laufende
# Transaktion implizit ab. In einem TestCase-Block laeuft danach nichts mehr.
class SchemaPflege(TransactionTestCase):

    def setUp(self):
        super().setUp()
        schema_aufbauen(mit_nachgeruesteten=False)
        from planner import views as pv
        self.pv = pv
        pv._schema_geprueft = False

    def test_fehlende_spalten_werden_angelegt(self):
        vorher = spalten('planner_posts')
        self.assertNotIn('linkedin_posted', vorher)
        self.assertNotIn('post_scheduled_at', vorher)

        self.pv.schema_sicherstellen()

        nachher = spalten('planner_posts')
        for spalte in ('video_nc_path', 'gif_nc_path', 'linkedin_posted',
                       'post_scheduled_at', 'buffer_update_id'):
            self.assertIn(spalte, nachher, spalte)

    def test_ein_zweiter_lauf_aendert_nichts_mehr(self):
        self.pv.schema_sicherstellen()
        vorher = spalten('planner_posts')
        self.pv._schema_geprueft = False        # Zwischenspeicher aus
        self.pv.schema_sicherstellen()          # darf nicht stolpern
        self.assertEqual(vorher, spalten('planner_posts'))

    def test_die_angelegte_spalte_ist_auch_benutzbar(self):
        # Eine Spalte anzulegen nuetzt nichts, wenn der Typ nicht passt.
        self.pv.schema_sicherstellen()
        with connection.cursor() as c:
            c.execute("INSERT INTO planner_posts (title, content) VALUES ('T', 'I')")
            c.execute("SELECT LAST_INSERT_ID()")
            nr = c.fetchone()[0]
            c.execute("UPDATE planner_posts SET linkedin_posted=1, "
                      "post_scheduled_at='2026-09-12 14:00:00', "
                      "video_nc_path='Marketing & Design/x/clip.webm' WHERE id=%s", [nr])
            c.execute("SELECT linkedin_posted, post_scheduled_at, video_nc_path "
                      "FROM planner_posts WHERE id=%s", [nr])
            zeile = c.fetchone()
        self.assertEqual(1, zeile[0])
        self.assertIsNotNone(zeile[1])
        self.assertEqual('Marketing & Design/x/clip.webm', zeile[2])

    def test_nur_einmal_pro_prozess(self):
        # Der eigentliche Zweck: Nach dem ersten Lauf darf die Datenbank nicht
        # noch einmal befragt werden. Gemessen an der Anzahl Abfragen.
        from django.test.utils import CaptureQueriesContext
        self.pv.schema_sicherstellen()
        with CaptureQueriesContext(connection) as abfragen:
            self.pv.schema_sicherstellen()
            self.pv.schema_sicherstellen()
            self.pv.schema_sicherstellen()
        self.assertEqual(0, len(abfragen), [a['sql'][:60] for a in abfragen])

    def test_der_erste_lauf_fragt_sehr_wohl(self):
        # Gegenprobe zum vorigen - sonst bewiese der nur, dass nichts passiert.
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as abfragen:
            self.pv.schema_sicherstellen()
        self.assertGreater(len(abfragen), 0)

    def test_eine_unbekannte_tabelle_wird_nicht_angefasst(self):
        # Steht in der Liste eine Tabelle, die es nicht gibt, darf das den Rest
        # nicht aufhalten - und es darf kein ALTER darauf abgesetzt werden.
        echte = self.pv.NACHGERUESTETE_SPALTEN
        try:
            self.pv.NACHGERUESTETE_SPALTEN = echte + (
                ('gibt_es_nicht', 'spalte', 'INT'),)
            self.pv._schema_geprueft = False
            self.pv.schema_sicherstellen()
        finally:
            self.pv.NACHGERUESTETE_SPALTEN = echte
        self.assertIn('linkedin_posted', spalten('planner_posts'))
