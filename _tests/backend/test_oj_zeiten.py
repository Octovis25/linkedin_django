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
