"""OJ profile, 05.11.2026: no day without numbers, pictures that load.

There is no cron job on Render, so 04.11. had no snapshot at all. Opening
OJ profile or Scheduled now fetches in the background when today's numbers
are missing. Buffer's thumbnail links often do not load; the planner's
preview of the post stands in.

No thread is started for real and Buffer is never called.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from linkedin_statistics import buffer_metrics as bm
from planner import views as pv
from posts_posted import buffer_sync

from .basis import schema_aufbauen
from .test_oj_statistik import KEY, ORG, PERSON, OjStatistik, buffer_post, page_data


class Tagesstand(TransactionTestCase):
    rows = OjStatistik.rows

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        pv._li_tabelle_geprueft = False
        with connection.cursor() as c:
            for t in ('buffer_post_metrics', 'buffer_posts_posted', 'planner_linkedin_tokens', 'buffer_sync_log'):
                c.execute(f"DROP TABLE IF EXISTS {t}")
        buffer_sync._tabelle_geprueft = False
        pv._li_ensure_table()
        self.chefin = User.objects.create_superuser('ortrud', password='x')
        with connection.cursor() as c:
            c.execute("""INSERT INTO planner_linkedin_tokens
                         (user_id, buffer_token, buffer_profile_id, buffer_profile_name,
                          buffer_profile_id_person, buffer_profile_name_person)
                         VALUES (%s,%s,%s,'Octovis',%s,'Ortrud')""", [self.chefin.id, KEY, ORG, PERSON])
        self.client.force_login(self.chefin)

    def tearDown(self):
        pv._li_tabelle_geprueft = False
        buffer_sync._tabelle_geprueft = False
        super().tearDown()

    def sync_log(self, hours_ago):
        buffer_sync._tabelle_sicherstellen()
        with connection.cursor() as c:
            c.execute("DELETE FROM buffer_sync_log")
            t = timezone.now().replace(tzinfo=None) - timedelta(hours=hours_ago)   # as buffer_sync counts
            c.execute("INSERT INTO buffer_sync_log (started_at, finished_at, ok, ausloeser) VALUES (%s,%s,1,'auto')", [t, t])

    def test_fehlt_heute(self):
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=5)],
                          day=bm.today_berlin() - timedelta(days=2))
        self.assertTrue(buffer_sync.snapshot_missing_today())
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=9)], day=bm.today_berlin())
        self.assertFalse(buffer_sync.snapshot_missing_today())

    @override_settings(BUFFER_BACKGROUND_SYNC=True)
    def test_fehlender_tag_wird_trotz_20_stunden_geholt(self):
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=5)],
                          day=bm.today_berlin() - timedelta(days=1))
        self.sync_log(hours_ago=3)              # 14:00 yesterday, 09:00 today: used to skip the day
        with mock.patch('threading.Thread') as th:
            self.assertTrue(buffer_sync.sync_for_today_in_background())
        th.return_value.start.assert_called_once()

    @override_settings(BUFFER_BACKGROUND_SYNC=True)
    def test_mit_heutigem_stand_bleibt_es_bei_einmal_am_tag(self):
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=5)], day=bm.today_berlin())
        self.sync_log(hours_ago=3)
        with mock.patch('threading.Thread') as th:
            self.assertFalse(buffer_sync.sync_for_today_in_background())
        th.assert_not_called()

    @override_settings(BUFFER_BACKGROUND_SYNC=True)
    def test_hoechstens_einmal_pro_stunde(self):
        self.sync_log(hours_ago=0.2)            # a failing Buffer is not asked on every page load
        with mock.patch('threading.Thread') as th:
            self.assertFalse(buffer_sync.sync_for_today_in_background())
        th.assert_not_called()

    def test_in_tests_startet_kein_faden(self):
        with mock.patch('threading.Thread') as th:
            self.assertFalse(buffer_sync.sync_for_today_in_background())
        th.assert_not_called()

    def test_oj_seite_holt_den_fehlenden_tag(self):
        with mock.patch.object(buffer_sync, 'sync_for_today_in_background', return_value=True) as s:
            html = self.client.get('/statistics/oj/').content.decode()
        s.assert_called_once()
        self.assertIn('being fetched', html)
        self.assertNotIn('daily at 14:00', html)
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=9)], day=bm.today_berlin())
        with mock.patch.object(buffer_sync, 'sync_for_today_in_background', return_value=True) as s:
            html = self.client.get('/statistics/oj/').content.decode()
        s.assert_not_called()
        self.assertNotIn('being fetched', html)

    def test_scheduled_holt_den_fehlenden_tag(self):
        with mock.patch.object(buffer_sync, 'sync_for_today_in_background', return_value=False) as s:
            self.assertEqual(200, self.client.get('/planner/scheduled/').status_code)
        s.assert_called_once()

    def test_vorschaubild_aus_dem_planner(self):
        bm.store_snapshot([buffer_post('b155', PERSON, '2026-10-30T08:00:00Z', impressions=73),
                           buffer_post('b157', PERSON, '2026-10-22T08:00:00Z', impressions=106),
                           buffer_post('b0', PERSON, '2026-05-19T08:00:00Z', impressions=104)], day=bm.today_berlin())
        with connection.cursor() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS buffer_posts_posted (
                id INT AUTO_INCREMENT PRIMARY KEY, buffer_post_id VARCHAR(100) UNIQUE,
                post_text TEXT, thumbnail_url TEXT, planner_post_id INT NULL)""")
            c.execute("""INSERT INTO buffer_posts_posted (buffer_post_id, post_text, thumbnail_url, planner_post_id) VALUES
                         ('b155', 'Halloween', 'https://images.buffer.com/thumbnail/abc', 155),
                         ('b157', 'AI', '', 157), ('b0', 'PHUSE', '', NULL)""")
        posts = {p['id']: p for p in page_data(self.client.get('/statistics/oj/').content.decode())['posts']}
        self.assertEqual(('https://images.buffer.com/thumbnail/abc', '/planner/thumb/155/'),
                         (posts['b155']['img'], posts['b155']['img2']))
        self.assertEqual(('/planner/thumb/157/', ''), (posts['b157']['img'], posts['b157']['img2']))
        self.assertEqual(('', ''), (posts['b0']['img'], posts['b0']['img2']))
