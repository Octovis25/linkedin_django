"""Website log of octotrial.com (04.11.2026): revisions and uploads copied
from WordPress (read only), shown as changes with person, kind, before/after
and notes. No working-time evaluation (Ortrud, 04.11.2026).

WordPress is never called: requests.get or the functions in wp are replaced.
"""
from datetime import date, datetime
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from website_changes import diff, log, wp

PAGE_V1 = ('<style>.x{color:red}</style><h2>OctoSOP</h2><p>OctoSOP keeps your SOPs in one place. '
           'Reviews happen by email.</p><img src="https://octotrial.com/wp-content/uploads/hero.png?v=2">'
           '<script>var a=1;</script>')
PAGE_V2 = ('<h2>OctoSOP</h2><p>OctoSOP keeps your SOPs in one place. '
           'Reviews and approvals happen in the portal.</p><img src="https://octotrial.com/wp-content/uploads/hero.png">')
PAGE_V3 = PAGE_V2.replace('hero.png', 'hero-2026.png')


class Text(SimpleTestCase):
    def test_text_ohne_style_und_script_bilder_als_name(self):
        self.assertEqual('OctoSOP\nOctoSOP keeps your SOPs in one place. Reviews happen by email.\n[Image hero.png]',
                         diff.text_plain(PAGE_V1))

    def test_art_und_zahl_der_saetze(self):
        a, b, c = (diff.text_plain(x) for x in (PAGE_V1, PAGE_V2, PAGE_V3))
        self.assertEqual((['Text'], 1), diff.compare(a, b, 'OctoSOP', 'OctoSOP'))
        self.assertEqual((['Image'], 0), diff.compare(b, c, 'OctoSOP', 'OctoSOP'))
        self.assertEqual((['Title'], 0), diff.compare(b, b, 'OctoSOP', 'OctoSOP portal'))
        self.assertEqual(([], 0), diff.compare(b, b, 'OctoSOP', 'OctoSOP'))

    def test_vorher_nachher_markiert_und_gekuerzt(self):
        alt = '\n'.join(f'Sentence {i}.' for i in range(20))
        neu = alt.replace('Sentence 10.', 'Sentence ten <b>.')
        links, rechts = diff.side_by_side(alt, neu)
        self.assertIn('<del>Sentence 10.</del>', links)
        self.assertIn('<ins>Sentence ten &lt;b&gt;.</ins>', rechts)       # escaped
        self.assertNotIn('Sentence 3.', links)                             # far away: cut
        self.assertIn('Sentence 9.', links)                                # context kept
        self.assertIn('…', links)


def antwort(status, daten, pages=1):
    return mock.Mock(status_code=status, json=mock.Mock(return_value=daten),
                     headers={'X-WP-TotalPages': str(pages)})


@override_settings(MATOMO_URL='https://octotrial.com', MATOMO_TOKEN='matomo:alt', WP_LOG_TOKEN='octovis-log:ab cd')
class Rest(SimpleTestCase):
    def test_seitenweise_mit_eigenem_zugang(self):
        with mock.patch('requests.get', side_effect=[antwort(200, [{'id': 1}], 2), antwort(200, [{'id': 2}], 2)]) as get:
            self.assertEqual([1, 2], [x['id'] for x in wp.get_all('media')])
        self.assertEqual([1, 2], [c.kwargs['params']['page'] for c in get.call_args_list])
        self.assertEqual(100, get.call_args.kwargs['params']['per_page'])
        self.assertEqual(('octovis-log', 'ab cd'), get.call_args.kwargs['auth'])

    def test_401_wird_nicht_wiederholt(self):
        with mock.patch('requests.get', return_value=antwort(401, {})) as get:
            with self.assertRaises(wp.AccessError):
                wp.objects()
        self.assertEqual(1, get.call_count)

    def test_serien_teile_kommen_dazu(self):
        def fake(url, params=None, **kw):
            if url.endswith('/pages'):
                return antwort(200, [{'id': 10, 'title': {'rendered': 'Home'}, 'link': 'h', 'modified_gmt': '2026-10-01T08:00:00'}])
            if url.endswith('/series'):
                return antwort(200, [{'id': 3}])
            if url.endswith('/posts') and params.get('series') == 3:
                return antwort(200, [{'id': 21, 'title': {'rendered': 'Part 2'}, 'link': 'p2', 'modified_gmt': ''},
                                     {'id': 20, 'title': {'rendered': 'Part 1'}, 'link': 'p1', 'modified_gmt': ''}])
            if url.endswith('/posts'):
                return antwort(200, [{'id': 20, 'title': {'rendered': 'Part 1'}, 'link': 'p1', 'modified_gmt': ''}])
            return antwort(404, {})
        with mock.patch('requests.get', side_effect=fake):
            objs = wp.objects()
        self.assertEqual({10: 'pages', 20: 'posts', 21: 'posts'}, {o['id']: o['kind'] for o in objs})

    def test_alter_zugang_wenn_neuer_fehlt(self):
        with self.settings(WP_LOG_TOKEN=''):
            with mock.patch('requests.get', return_value=antwort(200, [])) as get:
                wp.get_all('media')
        self.assertEqual(('matomo', 'alt'), get.call_args.kwargs['auth'])


def rev(rid, author, when, content, title='OctoSOP'):
    return {'id': rid, 'author_id': author, 'modified_gmt': when, 'title': title, 'content': content}


OBJ = {'id': 2263, 'kind': 'pages', 'title': 'OctoSOP', 'link': 'https://octotrial.com/octosop/',
       'modified_gmt': '2026-10-22T09:00:40'}
REVS = [rev(101, 7, '2026-10-20T08:00:00', PAGE_V1),
        # one Elementor save = three revisions in the same minute
        rev(110, 6, '2026-10-22T09:00:05', PAGE_V2), rev(111, 6, '2026-10-22T09:00:20', PAGE_V2),
        rev(112, 6, '2026-10-22T09:00:40', PAGE_V2)]


class Log(TransactionTestCase):
    def setUp(self):
        super().setUp()
        with connection.cursor() as c:
            for t in ('wp_log_objects', 'wp_log_revisions', 'wp_log_media', 'wp_log_notes',
                      'wp_log_authors', 'wp_log_sync'):
                c.execute(f"DROP TABLE IF EXISTS {t}")
        self.chefin = User.objects.create_superuser('ortrud', password='x')

    def sync(self, objs=None, revs=None, media=None, **kw):
        with mock.patch.object(wp, 'objects', return_value=objs if objs is not None else [OBJ]), \
             mock.patch.object(wp, 'revisions', return_value=revs if revs is not None else REVS) as r, \
             mock.patch.object(wp, 'media', return_value=media or []):
            return log.sync(**kw), r

    def test_speichern_eine_aenderung_pro_speicherung(self):
        res, _ = self.sync()
        self.assertTrue(res['ok'] and res['complete'])
        self.assertEqual(4, res['new_revisions'])
        rows, total = log.changes(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(2, total)
        neu = rows[0]
        self.assertEqual(('Ekaterina', 3, ['Text'], 1), (neu['person'], neu['revisions'], neu['kinds'], neu['changed']))
        self.assertEqual('22.10.2026 11:00', neu['berlin'].strftime('%d.%m.%Y %H:%M'))     # CEST
        self.assertEqual((['New'], 'Ortrud Junker-Wolf'), (rows[1]['kinds'], rows[1]['person']))

    def test_nur_geaenderte_seiten_werden_nachgefragt(self):
        self.sync()
        res, r = self.sync()
        self.assertEqual(0, r.call_count)
        self.assertEqual(0, res['new_revisions'])
        res, r = self.sync(objs=[{**OBJ, 'modified_gmt': '2026-10-28T15:40:00'}],
                           revs=REVS + [rev(120, 12, '2026-10-28T15:40:00', PAGE_V3)])
        self.assertEqual((1, 1), (r.call_count, res['new_revisions']))
        rows, _ = log.changes(date(2026, 10, 28), date(2026, 10, 28))
        self.assertEqual(('User 12', ['Image']), (rows[0]['person'], rows[0]['kinds']))

    def test_mit_claude_und_filter(self):
        log.save_author(9, 'Claude (Ortrud)', 'Ortrud Junker-Wolf', True)
        self.sync(revs=REVS + [rev(130, 9, '2026-10-23T10:00:00', PAGE_V3)])
        rows, _ = log.changes(date(2026, 10, 1), date(2026, 10, 31), person='Ortrud Junker-Wolf')
        self.assertEqual([True, False], [r['with_claude'] for r in rows])
        rows, _ = log.changes(date(2026, 10, 1), date(2026, 10, 31), kind='Image')
        self.assertEqual(['Ortrud Junker-Wolf'], [r['person'] for r in rows])
        self.assertIn('Ortrud Junker-Wolf', log.people())

    def test_berliner_tag(self):
        # 31.10. 23:30 UTC is 01.11. 00:30 in Berlin (CET)
        self.sync(objs=[{**OBJ, 'modified_gmt': '2026-10-31T23:30:00'}], revs=[rev(140, 6, '2026-10-31T23:30:00', PAGE_V1)])
        self.assertEqual(0, log.changes(date(2026, 10, 31), date(2026, 10, 31))[1])
        self.assertEqual(1, log.changes(date(2026, 11, 1), date(2026, 11, 1))[1])

    def test_vorher_ist_die_revision_davor_egal_von_wem(self):
        self.sync()
        rows, _ = log.changes(date(2026, 10, 22), date(2026, 10, 22))
        d = log.detail(rows[0]['key'])
        self.assertEqual('Ortrud Junker-Wolf', d['before_who'])
        self.assertIn('<del>Reviews happen by email.</del>', d['before'])
        self.assertIn('<ins>Reviews and approvals happen in the portal.</ins>', d['after'])
        self.assertIsNone(log.detail('nonsense'))

    def test_uploads(self):
        self.sync(media=[{'id': 900, 'author_id': 6, 'date_gmt': '2026-10-15T12:00:00', 'title': 'hero-2026',
                          'url': 'https://octotrial.com/wp-content/uploads/hero-2026.png'}])
        rows, _ = log.changes(date(2026, 10, 15), date(2026, 10, 15))
        self.assertEqual([('Ekaterina', ['Upload'], 'hero-2026')], [(r['person'], r['kinds'], r['title']) for r in rows])

    def test_zugriff_verweigert_bricht_ab(self):
        with mock.patch.object(wp, 'objects', side_effect=wp.AccessError('WordPress refused (403)')), \
             mock.patch.object(wp, 'revisions') as r, mock.patch.object(wp, 'media') as m:
            res = log.sync()
        self.assertFalse(res['ok'])
        self.assertEqual((0, 0), (r.call_count, m.call_count))
        s = log.last_sync()
        self.assertEqual((False, 'WordPress refused (403)'), (s['ok'], s['message']))

    def test_zeitbudget_rest_beim_naechsten_mal(self):
        res, r = self.sync(budget_seconds=-1)
        self.assertTrue(res['ok'])
        self.assertFalse(res['complete'])
        self.assertIn('1 pages left', res['message'])
        res, r = self.sync()
        self.assertEqual((1, 4), (r.call_count, res['new_revisions']))

    def test_nur_lesen_kein_schreiben_an_wordpress(self):
        def fake(url, params=None, **kw):
            if url.endswith('/pages'):
                return antwort(200, [{'id': 2263, 'title': {'rendered': 'OctoSOP'}, 'link': 'l',
                                      'modified_gmt': '2026-10-22T09:00:40'}])
            if url.endswith('/2263/revisions'):
                return antwort(200, [{'id': 1, 'author': 6, 'modified_gmt': '2026-10-22T09:00:40', 'slug': '2263-revision-v1',
                                      'title': {'rendered': 'OctoSOP'}, 'content': {'rendered': PAGE_V2}},
                                     {'id': 2, 'author': 6, 'modified_gmt': '2026-10-22T09:01:00', 'slug': '2263-autosave-v1',
                                      'title': {'rendered': 'OctoSOP'}, 'content': {'rendered': ''}}])
            return antwort(200, [])
        nein = mock.Mock(side_effect=AssertionError('only GET'))
        with self.settings(MATOMO_URL='https://octotrial.com', WP_LOG_TOKEN='octovis-log:x'), \
             mock.patch('requests.get', side_effect=fake), mock.patch('requests.post', nein), \
             mock.patch('requests.put', nein), mock.patch('requests.delete', nein), mock.patch('requests.patch', nein):
            res = log.sync()
        self.assertEqual((True, 1), (res['ok'], res['new_revisions']))      # autosave left out

    # -- the page ----------------------------------------------------------
    def test_seite_nur_fuer_superuser(self):
        User.objects.create_user('kollege', password='x')
        self.client.login(username='kollege', password='x')
        self.assertEqual(302, self.client.get('/webstats/changes/').status_code)
        self.assertEqual(302, self.client.get('/webstats/changes/detail/?key=1:1:202610220900').status_code)

    def test_seite_detail_notiz_person(self):
        self.sync()
        self.client.force_login(self.chefin)
        html = self.client.get('/webstats/changes/?from=2026-10-01&to=2026-10-31').content.decode()
        self.assertIn('Ekaterina', html)
        self.assertIn('k-Text', html)
        self.assertNotIn('Work blocks', html)
        key = log.changes(date(2026, 10, 22), date(2026, 10, 22))[0][0]['key']
        j = self.client.get('/webstats/changes/detail/', {'key': key}).json()
        self.assertIn('<ins>', j['after'])
        self.client.post('/webstats/changes/note/', {'key': key, 'wp_id': '2263', 'text': 'AI section OctoSOP, 3 Nov'})
        self.client.post('/webstats/changes/note/', {'wp_id': '', 'text': 'General note'})
        rows, _ = log.changes(date(2026, 10, 22), date(2026, 10, 22))
        self.assertEqual(['AI section OctoSOP, 3 Nov'], rows[0]['notes'])
        self.assertEqual(2, len(log.notes()))
        self.client.post('/webstats/changes/author/', {'wp_user_id': '9', 'name': 'Claude (Ekaterina)',
                                                       'person': 'Ekaterina', 'with_claude': '1'})
        self.assertIn({'id': 9, 'name': 'Claude (Ekaterina)', 'person': 'Ekaterina', 'with_claude': True}, log.authors())

    def test_knopf_aktualisieren(self):
        self.client.force_login(self.chefin)
        with mock.patch.object(log, 'sync', return_value={'ok': True, 'complete': True, 'message': '0 new revisions'}) as s:
            r = self.client.post('/webstats/changes/sync/')
        self.assertEqual((302, 1), (r.status_code, s.call_count))
        self.assertEqual(405, self.client.get('/webstats/changes/sync/').status_code)
