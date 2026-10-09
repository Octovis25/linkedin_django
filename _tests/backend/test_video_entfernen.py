"""The ✕ next to a post's video (09.10.2026, post #127): only the video comes
off, an image on the same post stays, the file goes back to the outputs."""
import json
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from planner import views as pv

from .basis import schema_aufbauen


class VideoEntfernen(TransactionTestCase):

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            c.execute("""INSERT INTO planner_posts (title, content, status, image, video_nc_path)
                         VALUES ('T', 'C', 'Review', 'Marketing & Design/LinkedIn/Planner/Images/a.png',
                                 'Marketing & Design/LinkedIn/Planner/Videos/old.mp4')""")
            self.pid = c.lastrowid
        self.client.force_login(User.objects.create_user('ve', password='ve'))

    def zeile(self):
        with connection.cursor() as c:
            c.execute("SELECT image, video_nc_path FROM planner_posts WHERE id=%s", [self.pid])
            return c.fetchone()

    def entfernen(self):
        with mock.patch.object(pv, '_move_replaced_media_to_outputs') as zurueck:
            antwort = self.client.post('/planner/api/post/', json.dumps({'action': 'remove_video', 'id': self.pid}),
                                       content_type='application/json')
        return antwort, zurueck

    def test_nur_das_video_geht(self):
        antwort, zurueck = self.entfernen()
        self.assertTrue(antwort.json()['ok'])
        self.assertEqual(('Marketing & Design/LinkedIn/Planner/Images/a.png', None), self.zeile())
        self.assertEqual('Marketing & Design/LinkedIn/Planner/Videos/old.mp4', zurueck.call_args.args[0])

    def test_veroeffentlichter_post_behaelt_die_datei(self):
        with connection.cursor() as c:
            c.execute("UPDATE planner_posts SET status='Posted' WHERE id=%s", [self.pid])
        antwort, zurueck = self.entfernen()
        self.assertTrue(antwort.json()['ok'])
        zurueck.assert_not_called()
        self.assertIsNone(self.zeile()[1])
