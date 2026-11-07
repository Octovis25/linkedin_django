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
from . import test_oj_statistik as base
from .test_oj_statistik import KEY, ORG, PERSON, buffer_post, page_data


class _Basis(TransactionTestCase):
    rows = base.OjStatistik.rows

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        pv._li_tabelle_geprueft = False
        with connection.cursor() as c:
            for t in ('buffer_post_metrics', 'buffer_posts_posted', 'planner_linkedin_tokens', 'buffer_sync_log',
                      'buffer_post_measurements', 'buffer_metrics_runs', 'buffer_metrics_state', 'buffer_metrics_ticks'):
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


class Tagesstand(_Basis):
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


def refreshed(post, at):
    post['metrics_updated_at'] = at
    return post


class Stuendlich(_Basis):
    """Every refresh of Buffer's numbers with its time; a fetch once an hour."""

    def test_jede_aktualisierung_mit_uhrzeit(self):
        now = bm._utcnow()
        sent = (now - timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
        a = (now - timedelta(days=1, hours=12)).strftime('%Y-%m-%dT%H:%M:%S.123Z')
        b = (now - timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%S.456Z')
        bm.store_snapshot([refreshed(buffer_post('p1', PERSON, sent, impressions=40), a)])
        bm.store_snapshot([refreshed(buffer_post('p1', PERSON, sent, impressions=40), a)])   # same numbers again
        bm.store_snapshot([refreshed(buffer_post('p1', PERSON, sent, impressions=58), b)])   # same day, later refresh
        self.assertEqual(2, self.rows("SELECT COUNT(*) FROM buffer_post_measurements WHERE metric_type='impressions'")[0][0])
        tl = bm.channel_timelines(PERSON)['p1']
        self.assertEqual([(1.5, 40), (2.75, 58)], [(d['day'], d['impressions']) for d in tl])

    def test_alte_posts_nur_im_tagesstand(self):
        now = bm._utcnow()
        bm.store_snapshot([refreshed(buffer_post('alt', PERSON, '2026-05-19T14:00:00Z', impressions=104),
                                     now.strftime('%Y-%m-%dT%H:%M:%SZ'))])
        self.assertEqual(0, self.rows("SELECT COUNT(*) FROM buffer_post_measurements")[0][0])
        self.assertEqual(1, len(bm.channel_timelines(PERSON)['alt']))

    @override_settings(BUFFER_BACKGROUND_SYNC=True)
    def test_hoechstens_einmal_pro_stunde_geholt(self):
        with mock.patch('threading.Thread') as th:
            self.assertTrue(bm.fetch_hourly())
            self.assertFalse(bm.fetch_hourly())          # same hour: claimed already
        th.return_value.start.assert_called_once()

    def test_ohne_faden_in_tests_und_ohne_schluessel(self):
        with mock.patch('threading.Thread') as th:
            self.assertFalse(bm.fetch_hourly())
        th.assert_not_called()
        with connection.cursor() as c:
            c.execute("UPDATE planner_linkedin_tokens SET buffer_token=NULL")
        with mock.patch.object(bm, 'fetch_and_store') as f:
            self.assertFalse(bm.fetch_hourly(background=False))
        f.assert_not_called()

    def test_lauf_wird_protokolliert(self):
        with mock.patch.object(bm, 'fetch_and_store', return_value=(132, 900)):
            self.assertTrue(bm.fetch_hourly(background=False))
        self.assertEqual((1, '132 posts'), self.rows("SELECT ok, note FROM buffer_metrics_runs")[0])

    def test_makes_zeitplan_stoesst_an(self):
        import hashlib
        import hmac
        from django.conf import settings
        key = hmac.new(settings.SECRET_KEY[:32].encode(), b'trigger-scheduled', hashlib.sha256).hexdigest()[:24]
        with mock.patch.object(bm, 'fetch_hourly', return_value=True) as f:
            self.client.logout()
            self.assertEqual(403, self.client.get('/planner/api/trigger-scheduled/?key=wrong').status_code)
            f.assert_not_called()
            self.client.get('/planner/api/trigger-scheduled/', {'key': key})
        f.assert_called_once()

    def test_oj_seite_stoesst_an(self):
        with mock.patch.object(bm, 'fetch_hourly', return_value=False) as f, \
             mock.patch.object(buffer_sync, 'sync_for_today_in_background', return_value=False):
            self.client.get('/statistics/oj/')
        f.assert_called_once()

    def test_adresse_fuer_den_zeitplan(self):
        # No key (07.11.2026): Make switched the scenario off after a 403.
        with mock.patch.object(bm, 'fetch_hourly', return_value=True) as f:
            self.client.logout()
            for url in ('/statistics/oj/tick/', '/statistics/oj/tick/?key=old'):
                r = self.client.get(url)
                self.assertEqual((200, {'ok': True, 'started': True}), (r.status_code, r.json()))
        self.assertEqual(2, f.call_count)
        self.client.force_login(self.chefin)
        with mock.patch.object(bm, 'fetch_hourly', return_value=False), \
             mock.patch.object(buffer_sync, 'sync_for_today_in_background', return_value=False):
            html = self.client.get('/statistics/oj/').content.decode()
        self.assertIn('/statistics/oj/tick/"', html)
        self.assertNotIn('tick/?key=', html)


class MeldungBeimLogin(_Basis):
    """07.11.2026: "eine kurze Nachricht, wenn the last zu lange her ist, wenn ich mich einlogge"."""

    def login_note(self, user=None):
        from django.contrib.auth.signals import user_logged_in
        from django.contrib.messages import get_messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore
        from django.test import RequestFactory
        req = RequestFactory().post('/login/')
        req.session = SessionStore()
        req._messages = FallbackStorage(req)
        user_logged_in.send(sender=User, request=req, user=user or self.chefin)
        return [str(m) for m in get_messages(req)]

    def set_tick(self, hours_ago):
        bm.ensure_table()
        with connection.cursor() as c:
            c.execute("UPDATE buffer_metrics_ticks SET at=%s WHERE id=1", [bm._utcnow() - timedelta(hours=hours_ago)])

    def test_alles_gut_keine_nachricht(self):
        self.client.logout()
        self.client.get('/statistics/oj/tick/')
        self.assertEqual([], self.login_note())

    def test_make_ruft_nicht_mehr_an(self):
        self.set_tick(5)
        notes = self.login_note()
        self.assertEqual(1, len(notes))
        self.assertIn('no call from Make since', notes[0])
        self.assertIn('(5 hours)', notes[0])
        self.assertEqual([], self.login_note(User.objects.create_user('kollegin', password='x')))
        self.client.logout()
        self.client.get('/statistics/oj/tick/')                # Make calls again
        self.assertEqual([], self.login_note())

    def test_ohne_jeden_aufruf_faellt_es_auch_auf(self):
        self.set_tick(4)                                       # table made 4 hours ago, Make never called
        self.assertIn('no call from Make', self.login_note()[0])

    def test_abruf_fehlgeschlagen(self):
        with mock.patch.object(bm, 'fetch_and_store', side_effect=Exception('Buffer did not answer as expected: 401')):
            self.assertTrue(bm.fetch_hourly(background=False))
        notes = self.login_note()
        self.assertIn('Hourly Buffer fetch failed at', notes[0])
        self.assertIn('401', notes[0])

    def test_ohne_tabellen_keine_nachricht(self):
        with connection.cursor() as c:
            c.execute("DROP TABLE IF EXISTS buffer_metrics_ticks")
        self.assertEqual([], self.login_note())
        self.assertEqual(0, self.rows("SELECT COUNT(*) FROM information_schema.tables "
                                      "WHERE table_name='buffer_metrics_ticks' AND table_schema=DATABASE()")[0][0])

    def test_login_bricht_nie(self):
        with mock.patch.object(bm, 'fetch_problem', side_effect=Exception('db down')):
            self.assertEqual([], self.login_note())
