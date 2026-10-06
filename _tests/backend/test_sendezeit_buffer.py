"""Date and time of a post on its way to Buffer (06.10.2026).

Two faults Ortrud found: in Ready, Archive, All and OJ the post editor opened
with an empty time (and link), so saving wiped them. And sending to Buffer
took a made-up time - no date or a date in the past ended up in Buffer's
queue. Now: the lists carry time and link, Buffer only gets a fixed future
time, and the post keeps the date and time Buffer got.
"""
import json
import time
from datetime import date, time as dtime
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from planner import views as pv

from .basis import schema_aufbauen

WEITERE_SPALTEN = [
    "topic_id INT NULL", "planned_date DATE NULL", "planned_time TIME NULL",
    "in_pipeline TINYINT NOT NULL DEFAULT 0", "series_id INT NULL",
    "series_order INT NOT NULL DEFAULT 0", "is_oj TINYINT NOT NULL DEFAULT 0",
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
]

TOKEN = {'access_token': 'x', 'buffer_token': 'b', 'buffer_profile_id': 'p'}


def zeile(sql, *args):
    with connection.cursor() as c:
        c.execute(sql, list(args))
        return c.fetchone()


class Sendezeit(TransactionTestCase):

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            for s in WEITERE_SPALTEN:
                try:
                    c.execute("ALTER TABLE planner_posts ADD COLUMN " + s)
                except Exception:
                    pass
            c.execute("""CREATE TABLE IF NOT EXISTS planner_topics (
                             id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100),
                             color VARCHAR(20))""")
            c.execute("""INSERT INTO planner_posts (title, content, status, in_pipeline,
                                                    planned_date, planned_time, link)
                         VALUES ('R', 'Text', 'Ready', 1, '2026-10-12', '08:45:00',
                                 'https://octotrial.com/services/')""")
            self.pid = c.lastrowid
        self.client.force_login(User.objects.create_superuser('sz', password='sz'))

    # ── the lists ──────────────────────────────────────────────────────────
    def test_ready_traegt_zeit_und_link(self):
        antwort = self.client.get('/planner/ready/')
        self.assertEqual(antwort.status_code, 200)
        posts = json.loads(antwort.context['posts_json'])
        p = next(x for x in posts if x['id'] == self.pid)
        self.assertEqual('08:45', p['time'][:5])
        self.assertEqual('https://octotrial.com/services/', p['link'])

    def test_speichern_ohne_zeitfeld_laesst_zeit_und_link(self):
        # The OJ editor sends neither time nor link.
        antwort = self.client.post('/planner/api/post/', json.dumps(dict(
            action='update', id=self.pid, title='R2', content='Text', status='Ready',
            planned_date='2026-10-13')), content_type='application/json')
        self.assertTrue(antwort.json()['ok'])
        tag, uhr, link = zeile("SELECT planned_date, planned_time, link FROM planner_posts WHERE id=%s", self.pid)
        self.assertEqual(date(2026, 10, 13), tag)
        self.assertEqual('08:45', str(uhr)[:5].zfill(5))
        self.assertEqual('https://octotrial.com/services/', link)

    def test_speichern_mit_leerer_zeit_loescht_sie(self):
        self.client.post('/planner/api/post/', json.dumps(dict(
            action='update', id=self.pid, title='R', content='Text', status='Ready',
            planned_date='2026-10-12', planned_time=None, link=None)),
            content_type='application/json')
        self.assertEqual((None, None), zeile("SELECT planned_time, link FROM planner_posts WHERE id=%s", self.pid))

    def test_oj_seite_kennt_die_uhrzeit(self):
        with connection.cursor() as c:
            c.execute("UPDATE planner_posts SET is_oj=1 WHERE id=%s", [self.pid])
        antwort = self.client.get('/planner/oj/')
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('"time":"08:45"', antwort.content.decode())

    # ── shown in German time ───────────────────────────────────────────────
    def test_anzeige_in_deutscher_zeit(self):
        from datetime import datetime
        from planner.zeit import berlin_fmt
        self.assertEqual('14.10.2030 09:30', berlin_fmt(datetime(2030, 10, 14, 7, 30)))
        self.assertEqual('14.01.2031 08:30', berlin_fmt('2031-01-14T07:30:00.000Z'))
        self.assertEqual('', berlin_fmt(None))

    def test_scheduled_zeigt_deutsche_zeit(self):
        with connection.cursor() as c:
            c.execute("""UPDATE planner_posts SET status='Scheduled',
                         post_scheduled_at='2030-10-14 07:30:00' WHERE id=%s""", [self.pid])
        with mock.patch.object(pv, '_li_get_superuser_token', return_value=None):
            antwort = self.client.get('/planner/scheduled/')
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('14.10.2030 09:30', antwort.content.decode())

    def test_anhaengen_ueberschreibt_nichts(self):
        posts = [{'id': self.pid, 'planned_time': dtime(10, 0), 'link': 'eigen'}]
        pv._attach_time_and_link(posts)
        self.assertEqual(dtime(10, 0), posts[0]['planned_time'])
        self.assertEqual('eigen', posts[0]['link'])

    # ── the time for Buffer ────────────────────────────────────────────────
    def test_ohne_zeit_kein_versand(self):
        wann, fehler = pv._buffer_send_time(None)
        self.assertIsNone(wann)
        self.assertIn('no date', fehler)

    def test_vergangene_zeit_kein_versand(self):
        wann, fehler = pv._buffer_send_time((time.time() - 3600) * 1000)
        self.assertIsNone(wann)
        self.assertIn('past', fehler)

    def test_kuenftige_zeit_geht(self):
        wann, fehler = pv._buffer_send_time((time.time() + 86400) * 1000)
        self.assertIsNone(fehler)
        self.assertEqual('UTC', wann.tzname())

    # ── the endpoint ───────────────────────────────────────────────────────
    def senden(self, **daten):
        daten.setdefault('text', 'Hello')
        daten.setdefault('target', 'org')
        with mock.patch.object(pv, '_li_get_superuser_token', return_value=TOKEN), \
             mock.patch.object(pv, '_buffer_channel_for_target', return_value=('p', 'Octotrial')), \
             mock.patch.object(pv, '_buffer_post', return_value={'updates': [{'id': 'B1'}]}) as bp:
            antwort = self.client.post(f'/planner/linkedin/post/{self.pid}/',
                                       json.dumps(daten), content_type='application/json')
        return antwort, bp

    def test_endpunkt_ohne_datum_schickt_nichts(self):
        antwort, bp = self.senden(scheduled_ms=None)
        self.assertEqual(400, antwort.status_code)
        self.assertIn('no date', antwort.json()['error'])
        bp.assert_not_called()
        self.assertEqual('Ready', zeile("SELECT status FROM planner_posts WHERE id=%s", self.pid)[0])

    def test_endpunkt_vergangenes_datum_schickt_nichts(self):
        antwort, bp = self.senden(scheduled_ms=(time.time() - 600) * 1000)
        self.assertEqual(400, antwort.status_code)
        self.assertIn('past', antwort.json()['error'])
        bp.assert_not_called()

    def test_endpunkt_plant_und_merkt_sich_datum(self):
        # 14.10.2030 07:30 UTC = 09:30 in Berlin (summer time).
        from datetime import datetime, timezone
        ms = datetime(2030, 10, 14, 7, 30, tzinfo=timezone.utc).timestamp() * 1000
        antwort, bp = self.senden(scheduled_ms=ms)
        self.assertEqual(200, antwort.status_code, antwort.content[:300])
        self.assertTrue(antwort.json()['scheduled'])
        self.assertEqual(datetime(2030, 10, 14, 7, 30, tzinfo=timezone.utc),
                         bp.call_args.kwargs['scheduled_at'])
        status, tag, uhr = zeile("""SELECT status, planned_date, planned_time
                                    FROM planner_posts WHERE id=%s""", self.pid)
        self.assertEqual('Scheduled', status)
        self.assertEqual(date(2030, 10, 14), tag)
        self.assertEqual('09:30', str(uhr)[:5].zfill(5))
