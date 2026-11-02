"""Statistics → OJ (01.11.2026): post numbers from Buffer as daily snapshots,
the LinkedIn profile export, and API Connect without the key in the page.

Buffer is never called: the functions in planner.views that talk to Buffer
are replaced. The answers follow what Buffer returned on 01.11.2026
(check_buffer_scopes --insights --posting).
"""
import io
import json
import re
from datetime import date, timedelta
from unittest import mock

import openpyxl
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase

from linkedin_statistics import buffer_metrics as bm
from linkedin_statistics import oj_export
from planner import views as pv

from .basis import schema_aufbauen

def page_data(html):
    return json.loads(re.search(r'<script id="oj-data" type="application/json">(.*?)</script>', html, re.S).group(1))


KEY = 'buffer-key-0123456789-abcdefghijklmnopqrIaSs'
ORG = 'chan-org'
PERSON = 'chan-person'


def buffer_post(pid, channel, sent_at, **metrics):
    names = dict(bm.METRICS)
    return {'buffer_post_id': pid, 'channel_id': channel, 'sent_at': sent_at, 'due_at': sent_at,
            'status': 'sent' if sent_at else 'scheduled', 'text': f'Post {pid}\nsecond line',
            'thumbnail_url': None, 'metrics_updated_at': None,
            'metrics': [{'type': k, 'name': names.get(k, k), 'value': v, 'unit': 'count'}
                        for k, v in metrics.items()]}


def export_xlsx(english=False):
    """A small workbook shaped like LinkedIn's profile export."""
    wb = openpyxl.Workbook()
    ws = wb.active
    if english:
        ws.title = 'DISCOVERY'
        ws.append(['Overall Performance', '11/2/2025 - 11/1/2026'])
        ws.append(['Impressions', '1976'])
        ws.append(['Members reached', '576'])
    else:
        ws.title = 'AUFFINDBARKEIT'
        ws.append(['Performance insgesamt', '2.11.2025 bis 1.11.2026'])
        ws.append(['Impressions', '1976'])
        ws.append(['Erreichte Mitglieder', '576'])
    e = wb.create_sheet('ENGAGEMENT')
    e.append(['Date', 'Impressions', 'Engagement'])
    fmt = (lambda d: f'{d.month}/{d.day}/{d.year}') if english else (lambda d: f'{d.day}.{d.month}.{d.year}')
    for d, imp, eng in [(date(2026, 3, 13), 400, 15), (date(2026, 3, 14), 203, 14), (date(2026, 10, 30), 69, 3)]:
        e.append([fmt(d), str(imp), str(eng)])
    t = wb.create_sheet('TOP POSTS')
    t.append(['Max 50 posts', None])
    t.append([None])
    t.append(['Post URL', 'Post publish date', 'Engagements', '', 'Post URL', 'Post publish date', 'Impressions'])
    u1 = 'https://www.linkedin.com/posts/ortrud-junker-wolf_acdm-clinicaltrials-share-7437840547819565058-kSnW'
    u2 = 'https://www.linkedin.com/posts/ortrud-junker-wolf_halloween-sop-ugcPost-7521858930596130816-ADzV'
    t.append([u1, fmt(date(2026, 3, 13)), '17', '', u1, fmt(date(2026, 3, 13)), '456'])
    t.append([u2, fmt(date(2026, 10, 30)), '3', '', u2, fmt(date(2026, 10, 30)), '69'])
    f = wb.create_sheet('FOLLOWERS')
    f.append([f'Total followers on {fmt(date(2026, 11, 1))}:', '424'])
    f.append([None, None])
    f.append(['Date', 'New followers'])
    f.append([fmt(date(2026, 3, 13)), '4'])
    f.append([fmt(date(2026, 6, 12)), '25'])
    for name, rows in [('DEMOGRAPHICS', [('Industries' if english else 'Branche', 'Pharma', '32 %'),
                                         ('Locations' if english else 'Standort', 'Munich', '10\xa0%')]),
                       ('CONTENT DEMOGRAPHICS', [('Industries' if english else 'Branche', 'Pharma', '39 %'),
                                                 ('Locations' if english else 'Standort', 'Berlin', '< 1 %')])]:
        s = wb.create_sheet(name)
        s.append(['Top demographics', 'Value', 'Percentage'])
        for r in rows:
            s.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = 'AggregateAnalytics_test.xlsx'
    return buf


class OjStatistik(TransactionTestCase):

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        pv._li_tabelle_geprueft = False
        with connection.cursor() as c:
            for t in ('buffer_post_metrics', 'buffer_posts_posted', 'planner_linkedin_tokens',
                      'oj_export_meta', 'oj_export_daily', 'oj_export_top', 'oj_export_demo', 'oj_contacts'):
                c.execute(f"DROP TABLE IF EXISTS {t}")
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
        super().tearDown()

    def rows(self, sql, *args):
        with connection.cursor() as c:
            c.execute(sql, list(args))
            return c.fetchall()

    # ── snapshots ──────────────────────────────────────────────────────────

    def test_snapshot_skips_queued_posts_and_overwrites_the_same_day(self):
        posts = [buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=40, reactions=1),
                 buffer_post('q1', PERSON, None, impressions=0)]
        self.assertEqual(bm.store_snapshot(posts, day=date(2026, 10, 31)), (1, 2))
        posts[0]['metrics'][0]['value'] = 69
        bm.store_snapshot(posts, day=date(2026, 10, 31))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM buffer_post_metrics")[0][0], 2)
        self.assertEqual(self.rows("""SELECT metric_value FROM buffer_post_metrics
                                      WHERE metric_type='impressions'""")[0][0], 69)
        bm.store_snapshot(posts, day=date(2026, 11, 1))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM buffer_post_metrics")[0][0], 4)

    def test_posts_before_2023_are_left_out_everywhere(self):
        bm.store_snapshot([buffer_post('x2011', PERSON, '2011-12-30T13:36:52Z', comments=0, reactions=0),
                           buffer_post('x2023', PERSON, '2023-04-09T18:36:46Z', impressions=11)], day=date(2026, 11, 1))
        self.assertEqual(self.rows("SELECT DISTINCT buffer_post_id FROM buffer_post_metrics"), (('x2023',),))
        with connection.cursor() as c:            # rows stored before the rule existed
            c.execute("""INSERT INTO buffer_post_metrics (fetched_date, buffer_post_id, channel_id, sent_at,
                             metric_type, metric_value) VALUES ('2026-11-01', 'x2013', %s, '2013-02-21T10:34:24Z',
                             'reactions', 0)""", [PERSON])
        self.assertEqual([p['id'] for p in bm.posts_with_latest(PERSON)], ['x2023'])
        self.assertEqual(list(bm.channel_timelines(PERSON)), ['x2023'])
        data = page_data(self.client.get('/statistics/oj/').content.decode())
        self.assertEqual([p['id'] for p in data['posts']], ['x2023'])

    def test_latest_values_per_channel_newest_first(self):
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-22T08:00:00Z', impressions=50)], day=date(2026, 10, 30))
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-22T08:00:00Z', impressions=105),
                           buffer_post('p2', PERSON, '2026-10-30T08:00:00Z', impressions=69, views=31),
                           buffer_post('o1', ORG, '2026-10-30T08:00:00Z', impressions=7)], day=date(2026, 11, 1))
        posts = bm.posts_with_latest(PERSON)
        self.assertEqual([p['id'] for p in posts], ['p2', 'p1'])
        self.assertEqual(posts[1]['m']['impressions'], 105)
        self.assertEqual(posts[1]['days'], 2)
        self.assertEqual(posts[0]['title'], 'Post p2')
        self.assertTrue(posts[0]['video'])
        self.assertFalse(posts[1]['video'])

    def test_text_from_the_sync_table_when_the_snapshot_has_none(self):
        post = buffer_post('j1', PERSON, '2026-06-26T08:00:00Z', impressions=12)
        post['text'] = ''
        bm.store_snapshot([post], day=date(2026, 6, 28))
        with connection.cursor() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS buffer_posts_posted (
                id INT AUTO_INCREMENT PRIMARY KEY, buffer_post_id VARCHAR(100) UNIQUE,
                post_text TEXT, thumbnail_url TEXT)""")
            c.execute("""INSERT INTO buffer_posts_posted (buffer_post_id, post_text, thumbnail_url)
                         VALUES ('j1', 'If nothing breaks today', 'https://images.buffer.com/thumbnail/abc')""")
        p = bm.posts_with_latest(PERSON)[0]
        self.assertEqual(p['title'], 'If nothing breaks today')
        self.assertEqual(p['thumb'], 'https://images.buffer.com/thumbnail/abc')
        data = page_data(self.client.get('/statistics/oj/').content.decode())
        self.assertEqual(data['posts'][0]['img'], 'https://images.buffer.com/thumbnail/abc')

    def test_timeline_counts_days_from_the_berlin_posting_day(self):
        sent = '2026-10-29T23:30:00Z'                    # 00:30 on 30.10. in Berlin
        for day, imp in [(date(2026, 10, 30), 20), (date(2026, 11, 1), 60), (date(2026, 10, 31), 45)]:
            bm.store_snapshot([buffer_post('p1', PERSON, sent, impressions=imp)], day=day)
        tl = bm.post_timeline('p1')
        self.assertEqual([(d['day'], d['impressions']) for d in tl], [(0, 20), (1, 45), (2, 60)])
        curves = bm.first_days_curves(bm.posts_with_latest(PERSON), ['impressions', 'views'])
        self.assertEqual(curves['impressions'][0]['points'], [(0, 20), (1, 45), (2, 60)])
        self.assertEqual(curves['views'], [])

    # ── daily run ──────────────────────────────────────────────────────────

    def _run_sync(self, metrics_effect):
        basic = [{'buffer_post_id': 'p1', 'channel_id': PERSON, 'sent_at': '2026-10-30T08:00:00Z',
                  'due_at': '2026-10-30T08:00:00Z', 'status': 'sent', 'text': 'Post p1',
                  'external_link': '', 'thumbnail_url': ''}]
        out = io.StringIO()
        with mock.patch.object(pv, '_buffer_first_org_id', return_value='org1'), \
             mock.patch.object(pv, '_buffer_fetch_posts_basic', return_value=basic), \
             mock.patch.object(pv, '_buffer_fetch_post_metrics', side_effect=metrics_effect) as m:
            call_command('fetch_buffer_posts', stdout=out, stderr=out)
        return out.getvalue(), m

    def test_daily_run_stores_todays_numbers(self):
        text, m = self._run_sync(lambda *a, **k: [buffer_post('p1', PERSON, '2026-10-30T08:00:00Z',
                                                              impressions=69, views=31)])
        self.assertEqual(m.call_args.args[:2], (KEY, 'org1'))
        self.assertTrue(m.call_args.kwargs.get('all_pages'))
        self.assertIn('Post numbers: 1 posts, 2 values', text)
        self.assertEqual(self.rows("SELECT fetched_date FROM buffer_post_metrics LIMIT 1")[0][0], bm.today_berlin())

    def test_daily_run_survives_a_failing_metrics_call(self):
        def boom(*a, **k):
            raise Exception('Buffer GraphQL HTTP 429: too many requests')
        text, _ = self._run_sync(boom)
        self.assertIn('Post numbers skipped', text)
        self.assertNotIn(KEY, text)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM buffer_posts_posted")[0][0], 1)

    # ── page ───────────────────────────────────────────────────────────────

    def test_page_data_posts_and_timelines(self):
        sent = '2026-10-30T08:00:00Z'
        bm.store_snapshot([buffer_post('p1', PERSON, sent, impressions=40, reactions=1)], day=date(2026, 10, 30))
        bm.store_snapshot([buffer_post('p1', PERSON, sent, impressions=69, reactions=2, engagementRate=2.9, views=31),
                           buffer_post('o1', ORG, sent, impressions=7)], day=date(2026, 11, 1))
        r = self.client.get('/statistics/oj/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        data = page_data(html)
        self.assertEqual([p['id'] for p in data['posts']], ['p1'])           # only the personal channel
        p = data['posts'][0]
        self.assertEqual((p['title'], p['date'], p['days']), ('Post p1', '2026-10-30', 2))
        self.assertEqual((p['m']['impressions'], p['m']['engagementRate'], p['m']['views']), (69, 2.9, 31))
        self.assertEqual([(d['day'], d['impressions']) for d in data['timelines']['p1']], [(0, 40), (2, 69)])
        self.assertNotIn('o1', data['timelines'])
        self.assertEqual((data['daily'], data['followers_total']), ([], None))
        self.assertIn('Upload the LinkedIn export below', html)
        self.assertNotIn(KEY, html)

    def test_page_is_for_superusers_only(self):
        self.client.force_login(User.objects.create_user('kollegin', password='x'))
        self.assertEqual(self.client.get('/statistics/oj/').status_code, 302)
        self.assertEqual(self.client.get('/statistics/oj/post/p1/').status_code, 302)
        self.assertEqual(self.client.post('/statistics/oj/fetch/').status_code, 302)
        self.assertFalse(self.rows("SHOW TABLES LIKE 'oj_export_meta'"))

    def test_post_timeline_json(self):
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=20)], day=date(2026, 10, 30))
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-10-30T08:00:00Z', impressions=69)], day=date(2026, 11, 1))
        days = self.client.get('/statistics/oj/post/p1/').json()['days']
        self.assertEqual([(d['day'], d['impressions']) for d in days], [(0, 20), (2, 69)])

    def test_fetch_now(self):
        with mock.patch.object(bm, 'fetch_and_store', return_value=(3, 12)) as m:
            r = self.client.post('/statistics/oj/fetch/', follow=True)
        m.assert_called_once_with(KEY)
        self.assertIn('Fetched: numbers for 3 posts', r.content.decode())
        with mock.patch.object(bm, 'fetch_and_store', side_effect=Exception('Buffer GraphQL HTTP 401: invalid')):
            r = self.client.post('/statistics/oj/fetch/', follow=True)
        html = r.content.decode()
        self.assertIn('Buffer did not answer as expected', html)
        self.assertNotIn(KEY, html)

    # ── LinkedIn export ────────────────────────────────────────────────────

    def test_upload_german_export(self):
        r = self.client.post('/statistics/oj/upload/', {'export': export_xlsx()}, follow=True)
        html = r.content.decode()
        self.assertIn('Export read and saved', html)
        s = oj_export.summary()
        self.assertEqual((s['period_from'], s['period_to']), (date(2025, 11, 2), date(2026, 11, 1)))
        self.assertEqual((s['impressions'], s['members_reached'], s['followers_total']), (1976, 576, 424))
        self.assertEqual(s['new_followers'], 29)
        self.assertEqual(s['growth'][-1], 424)
        self.assertEqual([m['month'] for m in s['months']], ['2026-03', '2026-06', '2026-10'])
        self.assertEqual(s['months'][0]['impressions'], 603)
        self.assertEqual(s['top'][0]['label'], '#acdm #clinicaltrials')
        self.assertEqual(s['top'][0]['rate'], 3.7)
        self.assertEqual(s['demo']['industry'][0], {'value': 'Pharma', 'audience': 32.0, 'content': 39.0})
        self.assertEqual(s['demo']['location'][1]['content'], 0.5)
        data = page_data(html)
        self.assertEqual((data['followers_total'], data['followers_date']), (424, '2026-11-01'))
        self.assertEqual(len(data['daily']), 4)
        self.assertEqual(data['daily'][0], ['2026-03-13', 400, 15, 4])
        self.assertEqual(data['demo']['industry'][0]['value'], 'Pharma')
        self.assertEqual(data['demo_categories'][0], ['industry', 'Industry'])

    def test_upload_english_export_and_replace(self):
        self.client.post('/statistics/oj/upload/', {'export': export_xlsx()})
        self.client.post('/statistics/oj/upload/', {'export': export_xlsx(english=True)})
        s = oj_export.summary()
        self.assertEqual(s['period_to'], date(2026, 11, 1))
        self.assertEqual(len(s['top']), 2)                        # replaced, not doubled
        self.assertEqual(self.rows("SELECT COUNT(*) FROM oj_export_daily")[0][0], 4)
        self.assertEqual(s['demo']['industry'][0]['audience'], 32.0)

    def test_upload_rejects_other_files(self):
        bad = io.BytesIO(b'not an excel file')
        bad.name = 'x.xlsx'
        html = self.client.post('/statistics/oj/upload/', {'export': bad}, follow=True).content.decode()
        self.assertIn('Not an Excel file LinkedIn exported', html)
        wb = openpyxl.Workbook()
        other = io.BytesIO()
        wb.save(other)
        other.seek(0)
        other.name = 'y.xlsx'
        html = self.client.post('/statistics/oj/upload/', {'export': other}, follow=True).content.decode()
        self.assertIn('fewer sheets than a LinkedIn profile export', html)
        self.assertIsNone(oj_export.summary())

    # ── contacts ───────────────────────────────────────────────────────────

    def _archive(self, with_connections=True):
        import zipfile
        csv_text = ('Notes:\n"When exporting your connection data, you may notice that some of the email addresses are missing."\n\n'
                    'First Name,Last Name,URL,Email Address,Company,Position,Connected On\n'
                    'Anna,Secret,https://www.linkedin.com/in/anna-secret,anna@example.com,Certara,Senior Biostatistician,24 Oct 2026\n'
                    'Bert,Hidden,https://www.linkedin.com/in/bert,,Viedoc,CEO & Founder,12 Jun 2026\n'
                    'Cleo,Private,https://www.linkedin.com/in/cleo,,,,"20 Jun 2011"\n')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('messages.csv', 'FROM,TO,CONTENT\nx,y,private message\n')
            if with_connections:
                z.writestr('Connections.csv', csv_text)
        buf.seek(0)
        buf.name = 'Basic_LinkedInDataExport_11-01-2026.zip.zip'
        return buf

    def test_contacts_upload_keeps_no_names(self):
        html = self.client.post('/statistics/oj/upload/', {'export': self._archive()}, follow=True).content.decode()
        self.assertIn('Contact list read: 3 contacts', html)
        rows = self.rows("SELECT connected_on, company, position, field, level FROM oj_contacts ORDER BY connected_on")
        self.assertEqual(rows[0], (date(2011, 6, 20), '', '', '(no job title)', '(no job title)'))
        self.assertEqual(rows[2], (date(2026, 10, 24), 'Certara', 'Senior Biostatistician', 'Biostatistics / programming', 'Senior / expert'))
        self.assertEqual(rows[1][3:], ('Not clear from the title', 'Founder / C-level'))
        dump = repr(self.rows("SELECT * FROM oj_contacts"))
        for secret in ('Anna', 'Secret', 'linkedin.com/in', 'anna@example.com', 'private message'):
            self.assertNotIn(secret, dump)
        data = page_data(html)
        self.assertEqual(data['contacts'][-1], ['2026-10-24', 'Biostatistics / programming', 'Senior / expert', 'Certara'])
        self.assertNotIn('Anna', html)

    def test_contacts_upload_replaces_and_rejects(self):
        self.client.post('/statistics/oj/upload/', {'export': self._archive()})
        self.client.post('/statistics/oj/upload/', {'export': self._archive()})
        self.assertEqual(self.rows("SELECT COUNT(*) FROM oj_contacts")[0][0], 3)
        html = self.client.post('/statistics/oj/upload/', {'export': self._archive(False)}, follow=True).content.decode()
        self.assertIn('The archive has no Connections.csv', html)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM oj_contacts")[0][0], 3)

    def test_contacts_finding_in_the_analysis(self):
        from linkedin_statistics import oj_analysis
        daily = [[(date(2026, 1, 1) + timedelta(days=i)).isoformat(), 2, 0, 1 if i % 4 == 0 else 0] for i in range(120)]
        contacts = [[(date(2026, 1, 1) + timedelta(days=i)).isoformat(), 'Sales / BD', 'Founder / C-level', 'X']
                    for i in range(0, 120, 5)]
        r = oj_analysis.analyse([], [], daily, 400, today=date(2026, 5, 1), contacts=contacts)
        f = {x['key']: x for x in r['findings']}['contacts']
        self.assertEqual(f['title'], 'Your followers grow through contacts')
        self.assertIn('<b>30</b> followers and <b>24</b> new contacts – about <b>80 %</b>', f['text'])
        self.assertIn('founder / c-level (24)', f['text'])
        self.assertEqual(sum(f['chart']['contacts']), 24)

    # ── API Connect ────────────────────────────────────────────────────────

    def test_api_connect_never_shows_the_key(self):
        html = self.client.get('/planner/api-connect/').content.decode()
        self.assertNotIn(KEY, html)
        self.assertIn('Saved key ••••IaSs', html)

    def test_saving_with_empty_key_field_keeps_the_key(self):
        self.client.post('/planner/api-connect/', {
            'buffer_token': '', 'buffer_profile_id': ORG, 'buffer_profile_name': 'Octovis',
            'buffer_profile_id_person': PERSON, 'buffer_profile_name_person': 'Ortrud'})
        self.assertEqual(self.rows("SELECT buffer_token FROM planner_linkedin_tokens")[0][0], KEY)
        self.client.post('/planner/api-connect/', {'buffer_token': 'new-key-xyz'})
        self.assertEqual(self.rows("SELECT buffer_token FROM planner_linkedin_tokens")[0][0], 'new-key-xyz')

    def test_load_profiles_without_typing_the_key(self):
        def gql(token, query, variables=None):
            self.assertEqual(token, KEY)
            if 'organizations' in query:
                return {'data': {'account': {'organizations': [{'id': 'org1', 'name': 'My Organization'}]}}}
            return {'data': {'channels': [{'id': PERSON, 'name': 'o', 'displayName': 'Ortrud', 'service': 'linkedin'}]}}
        with mock.patch.object(pv, '_buffer_graphql', side_effect=gql):
            r = self.client.post('/planner/api/buffer/profiles/', json.dumps({'token': ''}),
                                 content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['profiles'][0]['id'], PERSON)

    # ── analysis ───────────────────────────────────────────────────────────

    def test_analysis_page(self):
        self.client.post('/statistics/oj/upload/', {'export': export_xlsx()})
        bm.store_snapshot([buffer_post('p1', PERSON, '2026-03-13T08:00:00Z', impressions=456, reactions=13),
                           buffer_post('o1', ORG, '2026-03-13T08:00:00Z', impressions=40)], day=date(2026, 11, 1))
        r = self.client.get('/statistics/oj/analysis/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('OJ analysis', html)
        self.assertIn('too few posts yet', html)
        self.assertIn('oja-charts', html)
        self.client.force_login(User.objects.create_user('kollegin', password='x'))
        self.assertEqual(self.client.get('/statistics/oj/analysis/').status_code, 302)


class OjAnalyse(TransactionTestCase):
    """The numbers behind the findings, on a made-up year without a database."""

    def setUp(self):
        from linkedin_statistics import oj_analysis
        self.A = oj_analysis
        start = date(2025, 11, 2)
        self.posts = []
        posted = [start + timedelta(days=30 * k + 10) for k in range(10)]
        self.daily = []
        for i in range(365):
            d = start + timedelta(days=i)
            age = min((d - p).days for p in posted if p <= d) if any(p <= d for p in posted) else 99
            imp = {0: 90, 1: 30, 2: 10, 3: 6}.get(age, 2)
            fol = 1 if age in (0, 1) else (1 if i % 5 == 0 else 0)
            self.daily.append([d.isoformat(), imp, 0, fol])
        for k, p in enumerate(posted):
            text = 'See you at ACDM conference #a #b' if k % 2 else 'Why SOPs fail #c'
            self.posts.append({'id': f'p{k}', 'date': p, 'sent_at': f'{p.isoformat()}T08:00:00Z', 'text': text,
                               'title': text, 'm': {'impressions': 300 if k % 2 else 150, 'views': None}})
        self.company = [{'id': f'c{k}', 'date': date(2026, 6, 1) + timedelta(days=k), 'text': '', 'title': '',
                         'sent_at': '', 'm': {'impressions': 50}} for k in range(12)]

    def run_it(self):
        r = self.A.analyse(self.posts, self.company, self.daily, 400, today=date(2026, 11, 1))
        return {f['key']: f for f in r['findings']}, r

    def test_binomial_matches_known_values(self):
        self.assertAlmostEqual(self.A.binom_two_sided(19, 122, 35 / 365), 0.0308, places=3)
        self.assertEqual(self.A.binom_two_sided(0, 0, 0.5), 1.0)
        self.assertAlmostEqual(self.A.binom_two_sided(5, 10, 0.5), 1.0)

    def test_lifetime(self):
        f, _ = self.run_it()
        ev = f['lifetime']['chart']['values']
        self.assertEqual(ev[:4], [90, 30, 10, 6])
        self.assertEqual(f['lifetime']['chart']['baseline'], 2)
        self.assertEqual(f['lifetime']['title'], 'Two thirds of a post’s reach come on the day itself')
        self.assertEqual(f['lifetime']['verdict'], 'solid')

    def test_followers_effect_is_found(self):
        f, _ = self.run_it()
        a, b = f['followers']['chart']['values']
        self.assertGreater(a, b)
        self.assertIn(f['followers']['verdict'], ('solid', 'hint'))

    def test_types_and_company(self):
        f, _ = self.run_it()
        self.assertEqual(f['types']['title'], 'Conference posts do best')
        self.assertEqual(f['types']['verdict'], 'hint')
        self.assertEqual(f['company']['chart']['values'], [225, 50])
        self.assertIn('4.5×', f['company']['text'])

    def test_months_and_factors(self):
        f, r = self.run_it()
        self.assertEqual(r['n_posts'], 10)
        self.assertEqual(f['factors']['verdict'], 'few')
        self.assertEqual(f['factors']['table'][0][1], 'Before noon 10 posts, Ø 225 · afternoon/evening 0 posts, –')
        months = f['months']['chart']['months']
        self.assertEqual(sum(m['posts'] for m in months), 10)

    def test_no_export_leaves_out_what_needs_it(self):
        r = self.A.analyse(self.posts, self.company, [], None, today=date(2026, 11, 1))
        self.assertEqual([f['key'] for f in r['findings']], ['types', 'company', 'factors'])
        self.assertFalse(r['has_export'])


class FirmaTimeline(TransactionTestCase):
    """Statistics → Timeline: the company posts in the same timeline + table."""

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            for tname in ('linkedin_posts', 'linkedin_posts_posted', 'linkedin_posts_metrics'):
                c.execute(f"DROP TABLE IF EXISTS {tname}")
            c.execute("""CREATE TABLE linkedin_posts (post_id VARCHAR(40) PRIMARY KEY, post_title TEXT, post_date DATE,
                         post_url TEXT, content_type VARCHAR(40), created_at DATETIME NULL)""")
            c.execute("""CREATE TABLE linkedin_posts_posted (post_id VARCHAR(40) PRIMARY KEY, post_date DATE,
                         post_image TEXT, post_title TEXT)""")
            c.execute("""CREATE TABLE linkedin_posts_metrics (id INT AUTO_INCREMENT PRIMARY KEY, post_id VARCHAR(40),
                         metric_date DATE, impressions INT, clicks INT, likes INT, comments INT, direct_shares INT,
                         views INT NULL)""")
            c.execute("""INSERT INTO linkedin_posts VALUES
                ('111', 'Good SOPs reduce workarounds.', '2026-10-01', 'https://www.linkedin.com/feed/update/urn:li:activity:111', 'Video', NULL),
                ('222', 'Data is the new oil', '2026-06-12', '', 'Image', NULL)""")
            c.execute("INSERT INTO linkedin_posts_posted VALUES ('111', '2026-10-01', 'Marketing_and_Design/x.png', NULL)")
            for row in [('111', '2026-10-01', 20, 1, 1, 0, 0, 5), ('111', '2026-10-04', 60, 3, 2, 1, 0, 12),
                        ('111', '2026-10-20', 40, 2, 2, 1, 0, 12),          # shorter export: lower, ignored
                        ('222', '2026-06-15', 100, 10, 4, 0, 1, None)]:
                c.execute("""INSERT INTO linkedin_posts_metrics (post_id, metric_date, impressions, clicks, likes,
                             comments, direct_shares, views) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", list(row))
            c.execute("""CREATE TABLE IF NOT EXISTS planner_topics (id INT AUTO_INCREMENT PRIMARY KEY,
                         name VARCHAR(100), color VARCHAR(20))""")
        self.client.force_login(User.objects.create_user('kollegin', password='x'))

    def tearDown(self):
        with connection.cursor() as c:
            for tname in ('linkedin_posts', 'linkedin_posts_posted', 'linkedin_posts_metrics'):
                c.execute(f"DROP TABLE IF EXISTS {tname}")
        super().tearDown()

    def test_posts_and_timelines(self):
        from linkedin_statistics import company_posts
        posts, tl = company_posts.posts_and_timelines()
        self.assertEqual([p['id'] for p in posts], ['111', '222'])
        p = posts[0]
        self.assertEqual(p['img'], '/statistics/post-image/111/')
        self.assertTrue(p['video'])
        self.assertEqual(p['m']['impressions'], 60)                      # the dip to 40 is not a loss
        self.assertEqual((p['m']['ctr'], p['m']['engagementRate']), (5.0, 5.0))
        self.assertEqual([(d['day'], d['impressions']) for d in tl['111']], [(0, 20), (3, 60), (19, 60)])
        self.assertNotIn('views', posts[1]['m'])
        self.assertEqual(posts[1]['days'], 1)

    def test_page(self):
        r = self.client.get('/statistics/timeline/?from=2026-01-01&to=2026-11-01')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        data = json.loads(re.search(r'<script id="co-data" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(len(data['posts']), 2)
        self.assertEqual(data['cfg']['rates'], ['engagementRate', 'ctr'])
        self.assertIn("window.postTimelines.co.setRange('2026\\u002D01\\u002D01', '2026\\u002D11\\u002D01')", html)
        self.assertNotIn('buildGrowthChart', html)
        self.assertIn('id="perPeriod"', html)                    # one chart instead of two
        self.assertNotIn('id="interaktionen"', html)
        ctr = json.loads(re.search(r'const ctrData = (\[.*?\]);', html).group(1))
        labels = json.loads(re.search(r'const labels\s*=\s*(\[.*?\]);', html).group(1))
        self.assertEqual(ctr[labels.index('2026-10')], 5.0)       # 3 clicks / 60 impressions
        self.assertEqual(ctr[labels.index('2026-06')], 10.0)
