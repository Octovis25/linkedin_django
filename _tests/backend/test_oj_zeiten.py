"""Heatmap on OJ analysis (05.11.2026): weekday × time of day of the posts,
impressions per post, in Berlin time."""
import json
import re
from datetime import date, timedelta

from django.test import SimpleTestCase

from linkedin_statistics import buffer_metrics as bm
from linkedin_statistics import posting_times as pt

from .test_oj_statistik import ORG, PERSON, buffer_post
from .test_oj_tagesstand import _Basis


def post(sent_at, imp):
    return {'sent_at': sent_at, 'm': {'impressions': imp}}


class Heatmap(SimpleTestCase):
    def test_berliner_zeit_sommer_und_winter(self):
        h = pt.heatmap([post('2026-06-01T08:00:00Z', 50),      # Mon 10:00 CEST
                        post('2026-11-02T08:00:00Z', 60),      # Mon 09:00 CET
                        post('2026-11-06T07:30:00Z', 40),      # Fri 08:30 CET
                        post('2026-11-07T23:30:00Z', 9),       # Sun 00:30 -> night
                        post('2026-11-03T09:00:00Z', 0),       # 0 impressions: left out
                        post('', 70)])                          # no time: left out
        self.assertEqual({'0,1': [50, 60], '4,0': [40], '6,6': [9]}, h['cells'])
        self.assertEqual(4, h['n'])
        self.assertEqual('23–06', h['blocks'][6])

    def test_fast_alles_im_selben_feld(self):
        posts = [post('2026-11-02T08:00:00Z', 60 + i) for i in range(36)] + \
                [post('2026-11-06T08:00:00Z', 62 + i) for i in range(21)] + [post('2026-11-04T13:00:00Z', 300)]
        s = pt.heatmap(posts)['summary']
        self.assertEqual('none', s['verdict'])
        self.assertIn('57 of them went out on Mon 09–11 and Fri 09–11', s['lines'][0])
        self.assertIn('hardly changed', s['so'])
        self.assertIn('Mon 09–11 78 (36 posts)', s['lines'][1])          # 77.5 rounds up, like the page

    def test_hinweis_bei_klarem_unterschied(self):
        posts = [post('2026-11-02T08:00:00Z', 40) for _ in range(6)] + \
                [post('2026-11-04T13:00:00Z', 90) for _ in range(6)]
        s = pt.heatmap(posts)['summary']
        self.assertEqual('hint', s['verdict'])
        self.assertIn('Wed 13–16 does better than Mon 09–11', s['lines'][-1])

    def test_zu_wenige(self):
        s = pt.heatmap([post('2026-11-02T08:00:00Z', 40), post('2026-11-04T13:00:00Z', 90)])['summary']
        self.assertEqual('few', s['verdict'])
        self.assertEqual('few', pt.heatmap([])['summary']['verdict'])


class Seite(_Basis):
    def test_karte_auf_oj_analysis(self):
        bm.store_snapshot([buffer_post('o1', ORG, '2026-11-02T08:00:00Z', impressions=65),
                           buffer_post('p1', PERSON, '2026-11-04T08:00:00Z', impressions=399)], day=date(2026, 11, 5))
        html = self.client.get('/statistics/oj/analysis/').content.decode()
        self.assertIn('When the posts went out', html)
        data = json.loads(re.search(r'<script id="oja-heatmaps" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual({'0,1': [65]}, data['company']['cells'])
        self.assertEqual({'2,1': [399]}, data['oj']['cells'])

    def test_monatsgrafik_oben_auf_oj_profile(self):
        from unittest import mock
        from posts_posted import buffer_sync
        from .test_oj_statistik import export_xlsx
        from django.db import connection
        with connection.cursor() as c:
            for t in ('oj_export_meta', 'oj_export_daily', 'oj_export_top', 'oj_export_demo', 'oj_contacts'):
                c.execute(f"DROP TABLE IF EXISTS {t}")
        with mock.patch.object(buffer_sync, 'sync_for_today_in_background', return_value=False), \
             mock.patch.object(bm, 'fetch_hourly', return_value=False):
            html = self.client.get('/statistics/oj/').content.decode()
            self.assertNotIn('<script id="oj-months-data"', html)    # no export yet: no card
            self.client.post('/statistics/oj/upload/', {'export': export_xlsx()})
            html = self.client.get('/statistics/oj/').content.decode()
        self.assertIn('<script id="oj-months-data"', html)
        self.assertLess(html.index('id="oj-months"'), html.index('id="oj-ptl"'))   # before the timeline
        data = json.loads(re.search(r'<script id="oj-months-data" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual('months', data['kind'])
        self.assertTrue(data['months'])


class AktuellerMonat(_Basis):
    """06.11.2026: the month the export does not cover yet, from Buffer."""

    def test_gewinn_im_monat(self):
        bm.store_snapshot([buffer_post('alt', PERSON, '2026-10-30T09:00:00Z', impressions=69),
                           buffer_post('vorher', PERSON, '2026-10-01T09:00:00Z', impressions=50)], day=date(2026, 10, 31))
        bm.store_snapshot([buffer_post('alt', PERSON, '2026-10-30T09:00:00Z', impressions=75)], day=date(2026, 11, 1))
        bm.store_snapshot([buffer_post('alt', PERSON, '2026-10-30T09:00:00Z', impressions=90),
                           buffer_post('neu', PERSON, '2026-11-04T08:00:00Z', impressions=399),
                           buffer_post('firma', ORG, '2026-11-02T08:00:00Z', impressions=46)], day=date(2026, 11, 6))
        # alt: 90 - 69 (value before the month), neu: all of it, vorher: nothing new, firma: other channel
        self.assertEqual(21 + 399, bm.month_gain(PERSON, date(2026, 11, 1)))

    def test_grafik_bekommt_den_monat(self):
        from linkedin_statistics.stat_oj import current_month_from_buffer
        bm.store_snapshot([buffer_post('neu', PERSON, '2026-11-04T08:00:00Z', impressions=399)], day=date(2026, 11, 6))
        chart = {'kind': 'months', 'months': [{'month': '2026-10', 'impressions': 190, 'followers': 3, 'posts': 2, 'days': 31},
                                              {'month': '2026-11', 'impressions': 4, 'followers': 0, 'posts': 0, 'days': 1}]}
        out = current_month_from_buffer(chart, PERSON, today=date(2026, 11, 6))
        nov = out['months'][1]
        self.assertEqual((403, None, 1, True), (nov['impressions'], nov['followers'], nov['posts'], nov['partial']))
        self.assertEqual(chart['months'][1]['impressions'], 4)                 # the input is left alone
        full = {'kind': 'months', 'months': [{'month': '2026-11', 'impressions': 50, 'followers': 1, 'posts': 1, 'days': 6}]}
        self.assertIs(full, current_month_from_buffer(full, PERSON, today=date(2026, 11, 6)))


def timeline(html):
    return json.loads(re.search(r'<script id="oja-timeline" type="application/json">(.*?)</script>', html, re.S).group(1))


class Zeitraum(_Basis):
    """OJ analysis, 07.11.2026: only the heatmap, a timeline above it, a period like Web Analytics."""

    def setUp(self):
        super().setUp()
        today = bm.today_berlin()
        self.today = today
        self.old = (today - timedelta(days=200)).isoformat() + 'T08:00:00Z'
        self.new = (today - timedelta(days=20)).isoformat() + 'T08:00:00Z'
        bm.store_snapshot([buffer_post('o-alt', ORG, self.old, impressions=70),
                           buffer_post('o-neu', ORG, self.new, impressions=65),
                           buffer_post('p-neu', PERSON, self.new, impressions=399),
                           buffer_post('p-2022', PERSON, '2022-06-01T08:00:00Z', impressions=500)], day=today)

    def get(self, **q):
        return self.client.get('/statistics/oj/analysis/', q).content.decode()

    def test_standard_zwoelf_monate(self):
        html = self.get()
        t = timeline(html)
        self.assertEqual(((self.today - timedelta(days=364)).isoformat(), self.today.isoformat()), (t['von'], t['bis']))
        self.assertEqual(2, len(t['company']))
        self.assertEqual([399], [p['imp'] for p in t['oj']])
        self.assertNotIn('· 1 ·', html)                    # no numbered findings any more
        self.assertLess(html.index('id="tl-card"'), html.index('id="hm-card"'))

    def test_zeitraum_filtert_timeline_und_heatmap(self):
        von = (self.today - timedelta(days=60)).isoformat()
        html = self.get(von=von, bis=self.today.isoformat())
        self.assertEqual([65], [p['imp'] for p in timeline(html)['company']])
        data = json.loads(re.search(r'<script id="oja-heatmaps" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(1, data['company']['n'])
        self.assertIn(f'value="{von}"', html)

    def test_nie_vor_2023_und_nicht_in_der_zukunft(self):
        t = timeline(self.get(von='2020-01-01', bis='2099-01-01'))
        self.assertEqual(('2023-01-01', self.today.isoformat()), (t['von'], t['bis']))
        self.assertNotIn(500, [p['imp'] for p in t['oj']])

    def test_falsches_datum(self):
        html = self.get(von='gestern')
        self.assertIn('could not be read', html)
        self.assertEqual(self.today.isoformat(), timeline(html)['bis'])


def first(html):
    return json.loads(re.search(r'<script id="oja-first" type="application/json">(.*?)</script>', html, re.S).group(1))


class ErsteFuenfTage(_Basis):
    """07.11.2026: "damit ich die Posts über die ersten 5 Tage vergleichen kann"."""

    def test_stunden_nach_dem_posten(self):
        now = bm._utcnow()
        sent = now - timedelta(days=3)
        iso = lambda dt: dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        for hours, imp in ((9, 120), (33, 300)):
            p = buffer_post('p1', PERSON, iso(sent), impressions=imp)
            p['metrics_updated_at'] = iso(sent + timedelta(hours=hours))
            bm.store_snapshot([p])
        old = buffer_post('o1', ORG, iso(now - timedelta(days=40)), impressions=500)
        old['metrics_updated_at'] = iso(now - timedelta(days=40) + timedelta(hours=200))   # day 8: outside
        bm.store_snapshot([old])
        html = self.client.get('/statistics/oj/analysis/').content.decode()
        f = first(html)
        self.assertEqual([[9.0, 120], [33.0, 300]], f['oj'][0]['pts'])
        self.assertTrue(f['oj'][0]['young'])
        self.assertEqual([], f['company'])
        self.assertLess(html.index('id="tl-card"'), html.index('id="fd-card"'))
        self.assertLess(html.index('id="fd-card"'), html.index('id="hm-card"'))


class LetzterAbruf(_Basis):
    """OJ profile, 07.11.2026: "bei last auch die Uhrzeit"."""

    def test_uhrzeit_des_abrufs_und_von_buffer(self):
        from datetime import datetime
        from unittest import mock
        from posts_posted import buffer_sync
        self.assertIsNone(bm.last_fetch_at())
        p = buffer_post('p1', PERSON, '2026-11-02T08:00:00Z', impressions=9)
        p['metrics_updated_at'] = '2026-11-07T13:12:40.946Z'          # 14:12 in Berlin (CET)
        with mock.patch.object(bm, '_utcnow', return_value=datetime(2026, 11, 7, 13, 45, 3)):
            bm.store_snapshot([p], day=date(2026, 11, 7))
        self.assertEqual({'at': datetime(2026, 11, 7, 14, 45, 3), 'buffer': datetime(2026, 11, 7, 14, 12, 40)},
                         bm.last_fetch_at())
        with mock.patch.object(bm, 'fetch_hourly', return_value=False), \
             mock.patch.object(buffer_sync, 'sync_for_today_in_background', return_value=False):
            html = self.client.get('/statistics/oj/').content.decode()
        self.assertIn("last fetch 07.11.2026 14:45 · Buffer's numbers from 07.11. 14:12", html)
        self.assertIn('last fetch 07.11.2026 14:45', self.client.get('/statistics/oj/analysis/').content.decode())

    def test_vor_dem_ersten_abruf_mit_uhrzeit_nur_der_tag(self):
        from django.db import connection
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-11-02T08:00:00Z', impressions=9)], day=date(2026, 11, 6))
        with connection.cursor() as c:
            c.execute("DELETE FROM buffer_metrics_state")
        self.assertEqual({'day': date(2026, 11, 6), 'buffer': None}, bm.last_fetch_at())
