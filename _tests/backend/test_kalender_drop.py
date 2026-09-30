"""Drag and drop in the calendar (30.09.2026): drop_post and undo_drop.

Ortrud: "I drag the post I want there onto the day, and the one already on it
disappears into Review without a date." And: if it is at Buffer, it goes from
Buffer too.

Checked against a real database, with Buffer itself stood in for - these tests
must never delete anything at the real Buffer.
"""
import json
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from .basis import schema_aufbauen

WEITERE_SPALTEN = [
    "topic_id INT NULL", "planned_date DATE NULL", "planned_time TIME NULL",
    "in_pipeline TINYINT NOT NULL DEFAULT 0", "series_id INT NULL",
    "series_order INT NOT NULL DEFAULT 0", "is_oj TINYINT NOT NULL DEFAULT 0",
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
]

BUFFER_ZEILEN = """
CREATE TABLE IF NOT EXISTS buffer_posts_posted (
    id INT AUTO_INCREMENT PRIMARY KEY,
    buffer_post_id VARCHAR(100) NOT NULL UNIQUE,
    sent_at VARCHAR(64), due_at VARCHAR(64),
    planner_post_id INT DEFAULT NULL, has_image TINYINT DEFAULT 0
)"""

TOKEN = 'planner.views._li_get_superuser_token'
LOESCHEN = 'planner.views._buffer_delete_post'


def zeile(pid):
    with connection.cursor() as c:
        c.execute("""SELECT planned_date, status, in_pipeline, post_scheduled_at,
                            buffer_update_id FROM planner_posts WHERE id=%s""", [pid])
        d, s, p, a, b = c.fetchone()
    return {'datum': d.isoformat() if d else '', 'status': s, 'pipeline': p,
            'angesetzt': a, 'buffer_id': b}


class KalenderDrop(TransactionTestCase):
    URL = '/planner/kalender/api/'

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            for s in WEITERE_SPALTEN:
                c.execute("ALTER TABLE planner_posts ADD COLUMN " + s)
            c.execute("DROP TABLE IF EXISTS buffer_posts_posted")
            c.execute(BUFFER_ZEILEN)
        self.nutzer = User.objects.create_user('kd', password='kd')
        self.client.force_login(self.nutzer)

    # ---------------------------------------------------------------- helpers
    def post(self, datum='', status='Draft', pipeline=0, oj=0, gepostet=0,
             angesetzt=None, buffer_id=None):
        with connection.cursor() as c:
            c.execute("""INSERT INTO planner_posts (title, content, status, planned_date,
                             in_pipeline, is_oj, linkedin_posted, post_scheduled_at, buffer_update_id)
                         VALUES ('T', 'C', %s, %s, %s, %s, %s, %s, %s)""",
                      [status, datum or None, pipeline, oj, gepostet, angesetzt, buffer_id])
            return c.lastrowid

    def buffer_zeile(self, pid, gesendet=''):
        with connection.cursor() as c:
            c.execute("""INSERT INTO buffer_posts_posted (buffer_post_id, sent_at, due_at, planner_post_id)
                         VALUES (%s, %s, '2026-10-10T08:00:00.000Z', %s)""",
                      ['b%s' % pid, gesendet, pid])

    def verknuepft(self, pid):
        with connection.cursor() as c:
            c.execute('SELECT COUNT(*) FROM buffer_posts_posted WHERE planner_post_id=%s', [pid])
            return c.fetchone()[0]

    def api(self, **daten):
        a = self.client.post(self.URL, json.dumps(daten), content_type='application/json')
        return a.status_code, a.json()

    # ------------------------------------------------------------ the basics
    def test_der_neue_verdraengt_den_alten(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-16', 'Draft', 0)
        code, antwort = self.api(action='drop_post', id=a, datum='2026-10-16', weichen=[b])
        self.assertEqual(200, code, antwort)
        self.assertEqual({'datum': '2026-10-16', 'status': 'Review', 'pipeline': 1},
                         {k: zeile(a)[k] for k in ('datum', 'status', 'pipeline')})
        self.assertEqual({'datum': '', 'status': 'Review', 'pipeline': 1},
                         {k: zeile(b)[k] for k in ('datum', 'status', 'pipeline')})
        self.assertEqual([{'id': a, 'planned_date': '2026-10-09', 'status': 'Review', 'in_pipeline': 1},
                          {'id': b, 'planned_date': '2026-10-16', 'status': 'Draft', 'in_pipeline': 0}],
                         antwort['vorher'])

    def test_auf_einen_leeren_tag_bleibt_der_status(self):
        a = self.post('2026-10-09', 'Draft', 0)
        self.assertEqual(200, self.api(action='drop_post', id=a, datum='2026-10-20', weichen=[])[0])
        self.assertEqual(('2026-10-20', 'Draft'), (zeile(a)['datum'], zeile(a)['status']))

    def test_raus_aus_dem_kalender(self):
        a = self.post('2026-10-09', 'Ready', 1)
        self.assertEqual(200, self.api(action='drop_post', id=a, datum='')[0])
        self.assertEqual(('', 'Review'), (zeile(a)['datum'], zeile(a)['status']))

    def test_sich_selbst_verdraengt_er_nicht(self):
        a = self.post('2026-10-09', 'Review', 1)
        self.api(action='drop_post', id=a, datum='2026-10-12', weichen=[a])
        self.assertEqual('2026-10-12', zeile(a)['datum'])

    # ---------------------------------------------------------------- Buffer
    def test_buffer_wird_erst_gefragt(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-10', 'Scheduled', 1, angesetzt='2026-10-10 08:00:00', buffer_id='buf-b')
        with mock.patch(LOESCHEN) as loeschen:
            code, antwort = self.api(action='drop_post', id=a, datum='2026-10-10', weichen=[b])
        self.assertEqual(409, code)
        self.assertEqual({'frage': 'buffer', 'bei_buffer': [b]}, antwort)
        loeschen.assert_not_called()
        self.assertEqual('2026-10-09', zeile(a)['datum'])
        self.assertEqual('2026-10-10', zeile(b)['datum'])

    def test_verdraengter_buffer_post_wird_dort_geloescht(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-10', 'Scheduled', 1, angesetzt='2026-10-10 08:00:00', buffer_id='buf-b')
        self.buffer_zeile(b)
        with mock.patch(TOKEN, return_value={'buffer_token': 'tok'}), \
             mock.patch(LOESCHEN) as loeschen:
            code, antwort = self.api(action='drop_post', id=a, datum='2026-10-10',
                                     weichen=[b], buffer_ok=True)
        self.assertEqual(200, code, antwort)
        loeschen.assert_called_once_with('tok', 'buf-b')
        self.assertEqual([b], antwort['buffer_geloescht'])
        self.assertEqual({'datum': '', 'status': 'Review', 'angesetzt': None, 'buffer_id': None},
                         {k: zeile(b)[k] for k in ('datum', 'status', 'angesetzt', 'buffer_id')})
        # Buffer's unsent row would keep it on its old day - it is unlinked.
        self.assertEqual(0, self.verknuepft(b))
        self.assertEqual('2026-10-10', zeile(a)['datum'])

    def test_gezogener_buffer_post_wird_ready(self):
        b = self.post('2026-10-10', 'Scheduled', 1, angesetzt='2026-10-10 08:00:00', buffer_id='buf-b')
        with mock.patch(TOKEN, return_value={'buffer_token': 'tok'}), mock.patch(LOESCHEN):
            code, _ = self.api(action='drop_post', id=b, datum='2026-10-15', buffer_ok=True)
        self.assertEqual(200, code)
        self.assertEqual({'datum': '2026-10-15', 'status': 'Ready', 'angesetzt': None},
                         {k: zeile(b)[k] for k in ('datum', 'status', 'angesetzt')})

    def test_ohne_token_passiert_gar_nichts(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-10', 'Scheduled', 1, angesetzt='2026-10-10 08:00:00', buffer_id='buf-b')
        with mock.patch(TOKEN, return_value={}), mock.patch(LOESCHEN) as loeschen:
            code, antwort = self.api(action='drop_post', id=a, datum='2026-10-10',
                                     weichen=[b], buffer_ok=True)
        self.assertEqual(400, code)
        self.assertIn('No Buffer token', antwort['error'])
        loeschen.assert_not_called()
        self.assertEqual(('2026-10-09', '2026-10-10'), (zeile(a)['datum'], zeile(b)['datum']))

    def test_buffer_zeile_ohne_buffer_id_wird_abgelehnt(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-10', 'Scheduled', 1)
        self.buffer_zeile(b)                       # Buffer holds it, we do not know its id
        with mock.patch(TOKEN, return_value={'buffer_token': 'tok'}), \
             mock.patch(LOESCHEN) as loeschen:
            code, antwort = self.api(action='drop_post', id=a, datum='2026-10-10',
                                     weichen=[b], buffer_ok=True)
        self.assertEqual(400, code)
        self.assertIn('Buffer id is not known', antwort['error'])
        loeschen.assert_not_called()
        self.assertEqual('2026-10-10', zeile(b)['datum'])

    def test_buffer_lehnt_ab_plan_bleibt(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-10', 'Scheduled', 1, angesetzt='2026-10-10 08:00:00', buffer_id='buf-b')
        with mock.patch(TOKEN, return_value={'buffer_token': 'tok'}), \
             mock.patch(LOESCHEN, side_effect=RuntimeError('rate limited')):
            code, antwort = self.api(action='drop_post', id=a, datum='2026-10-10',
                                     weichen=[b], buffer_ok=True)
        self.assertEqual(502, code)
        self.assertIn('rate limited', antwort['error'])
        self.assertEqual(('2026-10-09', '2026-10-10', 'buf-b'),
                         (zeile(a)['datum'], zeile(b)['datum'], zeile(b)['buffer_id']))

    def test_bei_buffer_schon_weg_zaehlt_als_geloescht(self):
        b = self.post('2026-10-10', 'Scheduled', 1, angesetzt='2026-10-10 08:00:00', buffer_id='buf-b')
        with mock.patch(TOKEN, return_value={'buffer_token': 'tok'}), \
             mock.patch(LOESCHEN, side_effect=RuntimeError('Post not found')):
            code, _ = self.api(action='drop_post', id=b, datum='', buffer_ok=True)
        self.assertEqual(200, code)
        self.assertEqual(('', 'Review', None), (zeile(b)['datum'], zeile(b)['status'], zeile(b)['buffer_id']))

    # ----------------------------------------------------------- what is safe
    def test_veroeffentlichter_post_blockiert(self):
        a = self.post('2026-10-09', 'Review', 1)
        for b in (self.post('2026-10-14', 'Posted', 1),
                  self.post('2026-10-14', 'Scheduled', 1, gepostet=1)):
            with mock.patch(LOESCHEN) as loeschen:
                code, antwort = self.api(action='drop_post', id=a, datum='2026-10-14',
                                         weichen=[b], buffer_ok=True)
            self.assertEqual(400, code, antwort)
            loeschen.assert_not_called()
            self.assertEqual('2026-10-14', zeile(b)['datum'])
        self.assertEqual('2026-10-09', zeile(a)['datum'])

    def test_von_buffer_gesendet_blockiert_auch(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-14', 'Scheduled', 1)
        self.buffer_zeile(b, gesendet='2026-09-14T08:00:00.000Z')
        code, _ = self.api(action='drop_post', id=a, datum='2026-10-14', weichen=[b])
        self.assertEqual(400, code)
        self.assertEqual('2026-10-14', zeile(b)['datum'])

    def test_oj_nur_fuer_admins_und_nie_gemischt(self):
        oj = self.post('2026-10-09', 'Draft', 0, oj=1)
        code, _ = self.api(action='drop_post', id=oj, datum='2026-10-12')
        self.assertEqual(404, code)
        self.assertEqual('2026-10-09', zeile(oj)['datum'])
        self.client.force_login(User.objects.create_superuser('kdadmin', password='x'))
        planner = self.post('2026-10-12', 'Draft', 0)
        code, _ = self.api(action='drop_post', id=oj, datum='2026-10-12', weichen=[planner])
        self.assertEqual(400, code)
        self.assertEqual('2026-10-12', zeile(planner)['datum'])

    def test_unsinn_wird_abgelehnt(self):
        a = self.post('2026-10-09')
        self.assertEqual(400, self.api(action='drop_post', id=a, datum='16.10.2026')[0])
        self.assertEqual(400, self.api(action='drop_post', id='x', datum='2026-10-16')[0])
        self.assertEqual(404, self.api(action='drop_post', id=a + 999, datum='2026-10-16')[0])

    # ------------------------------------------------------------------ Undo
    def test_undo_stellt_alles_zurueck(self):
        a = self.post('2026-10-09', 'Review', 1)
        b = self.post('2026-10-16', 'Draft', 0)
        _, antwort = self.api(action='drop_post', id=a, datum='2026-10-16', weichen=[b])
        code, _ = self.api(action='undo_drop', vorher=antwort['vorher'])
        self.assertEqual(200, code)
        self.assertEqual(('2026-10-09', 'Review', 1), tuple(zeile(a)[k] for k in ('datum', 'status', 'pipeline')))
        self.assertEqual(('2026-10-16', 'Draft', 0), tuple(zeile(b)[k] for k in ('datum', 'status', 'pipeline')))

    def test_undo_macht_nie_scheduled(self):
        b = self.post('2026-10-10', 'Scheduled', 1, angesetzt='2026-10-10 08:00:00', buffer_id='buf-b')
        with mock.patch(TOKEN, return_value={'buffer_token': 'tok'}), mock.patch(LOESCHEN):
            _, antwort = self.api(action='drop_post', id=b, datum='2026-10-15', buffer_ok=True)
        self.api(action='undo_drop', vorher=antwort['vorher'])
        self.assertEqual(('2026-10-10', 'Ready', None), (zeile(b)['datum'], zeile(b)['status'], zeile(b)['angesetzt']))

    def test_undo_prueft_alles_bevor_es_etwas_aendert(self):
        a = self.post('2026-10-09', 'Review', 1)
        code, _ = self.api(action='undo_drop', vorher=[
            {'id': a, 'planned_date': '2026-10-01', 'status': 'Draft', 'in_pipeline': 0},
            {'id': a, 'planned_date': '2026-10-02', 'status': 'Hacked', 'in_pipeline': 0}])
        self.assertEqual(400, code)
        self.assertEqual(('2026-10-09', 'Review'), (zeile(a)['datum'], zeile(a)['status']))
        self.assertEqual(400, self.api(action='undo_drop', vorher=[])[0])
