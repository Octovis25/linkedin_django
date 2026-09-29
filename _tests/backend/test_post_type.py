"""Post type: short post / company post, a second label next to the topic (29.09.2026).

Checks the planner API against a real database: the value is stored, only the
two known values count, an edit that does not send it leaves it alone - and the
same now for the topic, which the Planner's edit dialog used to wipe.
"""
import json

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from .basis import schema_aufbauen

# basis.py builds planner_posts deliberately bare; the API needs these as well.
WEITERE_SPALTEN = [
    "topic_id INT NULL", "planned_date DATE NULL", "planned_time TIME NULL",
    "in_pipeline TINYINT NOT NULL DEFAULT 0", "series_id INT NULL",
    "series_order INT NOT NULL DEFAULT 0", "is_oj TINYINT NOT NULL DEFAULT 0",
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
]


def wert(sql, *args):
    with connection.cursor() as c:
        c.execute(sql, list(args))
        return c.fetchone()[0]


class PostType(TransactionTestCase):
    URL = '/planner/api/post/'

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            for s in WEITERE_SPALTEN:
                c.execute("ALTER TABLE planner_posts ADD COLUMN " + s)
        self.client.force_login(User.objects.create_user('pt', password='pt'))

    def api(self, **daten):
        antwort = self.client.post(self.URL, json.dumps(daten), content_type='application/json')
        self.assertEqual(antwort.status_code, 200, antwort.content[:300])
        return antwort.json()

    def neu(self, **extra):
        daten = dict(action='create', title='T', content='C', status='Draft', topic_id=16)
        daten.update(extra)
        return self.api(**daten)['id']

    def test_die_spalte_wird_nachgeruestet(self):
        with connection.cursor() as c:
            c.execute("SHOW COLUMNS FROM planner_posts LIKE 'post_type'")
            self.assertTrue(c.fetchone())

    def test_anlegen_mit_typ(self):
        pid = self.neu(post_type='company')
        self.assertEqual('company', wert("SELECT post_type FROM planner_posts WHERE id=%s", pid))

    def test_nur_die_zwei_werte_zaehlen(self):
        pid = self.neu(post_type='longread')
        self.assertIsNone(wert("SELECT post_type FROM planner_posts WHERE id=%s", pid))
        pid2 = self.neu(post_type=' Short ')
        self.assertEqual('short', wert("SELECT post_type FROM planner_posts WHERE id=%s", pid2))

    def test_bearbeiten_ohne_typ_und_thema_laesst_beides_stehen(self):
        # The Planner's edit dialog sends neither field.
        pid = self.neu(post_type='short')
        self.api(action='update', id=pid, title='Neu', content='C', status='Review')
        self.assertEqual('short', wert("SELECT post_type FROM planner_posts WHERE id=%s", pid))
        self.assertEqual(16, wert("SELECT topic_id FROM planner_posts WHERE id=%s", pid))
        self.assertEqual('Neu', wert("SELECT title FROM planner_posts WHERE id=%s", pid))

    def test_bearbeiten_mit_typ_und_thema_aendert_beides(self):
        pid = self.neu(post_type='short')
        self.api(action='update', id=pid, title='T', content='C', status='Draft', topic_id=3, post_type='company')
        self.assertEqual('company', wert("SELECT post_type FROM planner_posts WHERE id=%s", pid))
        self.assertEqual(3, wert("SELECT topic_id FROM planner_posts WHERE id=%s", pid))
        self.api(action='update', id=pid, title='T', content='C', status='Draft', post_type='')
        self.assertIsNone(wert("SELECT post_type FROM planner_posts WHERE id=%s", pid))

    def test_mehrere_auf_einmal_markieren(self):
        a, b, c = self.neu(), self.neu(), self.neu()
        r = self.api(action='set_type', ids=[a, b], post_type='short')
        self.assertEqual(2, r['count'])
        self.assertEqual('short', wert("SELECT post_type FROM planner_posts WHERE id=%s", a))
        self.assertIsNone(wert("SELECT post_type FROM planner_posts WHERE id=%s", c))

    def test_listen_bekommen_den_typ_mit(self):
        from planner import views as pv
        a, b = self.neu(post_type='company'), self.neu()
        liste = [{'id': a, 'planned_date': None}, {'id': b, 'planned_date': None}]
        pv._attach_video_paths(liste)
        self.assertEqual(['company', ''], [p['post_type'] for p in liste])
        self.assertEqual('company', json.loads(pv._posts_to_json(liste))[0]['post_type'])
