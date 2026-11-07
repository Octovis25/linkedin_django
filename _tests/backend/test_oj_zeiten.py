"""Heatmap on OJ analysis (05.11.2026): weekday × time of day of the posts,
impressions per post, in Berlin time."""
import json
import re
from datetime import date

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
