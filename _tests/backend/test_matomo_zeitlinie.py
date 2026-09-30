"""Web Analytics (30.09.2026): places left out, humans first, the timeline.

Matomo itself is stood in for - the tests hand the views a visit log of their
own through a mocked client.hole, against a real database for the list of
places.
"""
import datetime as dt
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase, override_settings

from matomo import views

HOLE = 'matomo.views.client.hole'
WP = 'matomo.views.client.blog_beitraege'


def besuch(wer, tag, stadt='Munich', typ='new', seiten=(('/', 30),), dauer=None):
    """One visit as Matomo's live/last_visits_details returns it."""
    aktionen = [{'type': 'action', 'url': 'https://octotrial.com' + url, 'pageTitle': url,
                 'timeSpent': str(zeit)} for url, zeit in seiten]
    return {
        'visitorId': wer, 'serverDate': tag, 'serverTimePretty': '10:00:00',
        'serverTimestamp': int(dt.datetime.fromisoformat(tag).timestamp()),
        'visitDuration': dauer if dauer is not None else sum(z for _, z in seiten),
        'actions': len(aktionen), 'city': stadt, 'country': 'Germany',
        'visitorType': typ, 'actionDetails': aktionen,
    }


# The portal runs with Django's default USE_TZ=True (dashboard/settings.py
# does not set it); the shared test settings switch it off.
@override_settings(USE_TZ=True, TIME_ZONE='Europe/Berlin')
class Grundlage(TransactionTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        views._orte_tabelle_da = False
        views._blog_tabelle_da = False
        with connection.cursor() as c:
            c.execute('DROP TABLE IF EXISTS matomo_orte_raus')
            c.execute('DROP TABLE IF EXISTS matomo_blog_adressen')
        # WordPress is never asked for real in a test; a test that needs posts sets them.
        wp = mock.patch(WP, return_value=[])
        self.wp = wp.start()
        self.addCleanup(wp.stop)
        self.client.force_login(User.objects.create_user('wa', password='wa'))


class Orte(Grundlage):
    def test_startliste_genau_einmal(self):
        self.assertEqual(['Herzogenaurach', 'Wasserburg am Inn'], views.ausgeschlossene_orte())
        with connection.cursor() as c:
            c.execute('DELETE FROM matomo_orte_raus')
        views._orte_tabelle_da = False            # as after a restart
        self.assertEqual([], views.ausgeschlossene_orte())

    def test_filtern_ohne_gross_klein_und_leerzeichen(self):
        b = [{'stadt': 'Wasserburg  am inn'}, {'stadt': 'HERZOGENAURACH'}, {'stadt': 'Munich'}]
        behalten, raus = views.orte_filtern(b, ['Herzogenaurach', 'Wasserburg am Inn'])
        self.assertEqual(([{'stadt': 'Munich'}], 2), (behalten, raus))

    def test_protokoll_laesst_die_orte_weg_und_zaehlt_sie(self):
        log = [besuch('a', '2026-09-10'), besuch('b', '2026-09-11', 'Herzogenaurach'),
               besuch('c', '2026-09-12', 'Wasserburg am Inn')]
        with mock.patch(HOLE, return_value=log):
            b = views._besuchsprotokoll(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
            alle = views._besuchsprotokoll(dt.date(2026, 9, 1), dt.date(2026, 9, 30), alle_orte=True)
        self.assertEqual((['a'], 2, 3), ([x['besucher'] for x in b], b.versteckt, b.roh))
        self.assertEqual(3, len(alle))

    def test_eigener_besuch_macht_niemanden_zum_menschen(self):
        # x: one bot-like visit in Munich, one long one from Herzogenaurach
        log = [besuch('x', '2026-09-10', seiten=(('/', 0),), dauer=0),
               besuch('x', '2026-09-11', 'Herzogenaurach', seiten=(('/', 50), ('/about/', 40)))]
        with mock.patch(HOLE, return_value=log):
            b = views._besuchsprotokoll(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
        self.assertEqual(1, len(b))
        self.assertTrue(b[0]['ist_bot'])

    def test_liste_aendern(self):
        a = self.client.post('/webstats/orte/', {'aktion': 'dazu', 'stadt': '  Erlangen ', 'zurueck': '/webstats/besucher/'})
        self.assertEqual('/webstats/besucher/', a['Location'])
        self.client.post('/webstats/orte/', {'aktion': 'dazu', 'stadt': 'erlangen'})   # no duplicate
        self.client.post('/webstats/orte/', {'aktion': 'weg', 'stadt': 'Herzogenaurach'})
        self.assertEqual(['Erlangen', 'Wasserburg am Inn'], views.ausgeschlossene_orte())

    def test_zurueck_nur_ins_portal(self):
        a = self.client.post('/webstats/orte/', {'aktion': 'dazu', 'stadt': 'X', 'zurueck': 'https://example.com/'})
        self.assertEqual('/webstats/', a['Location'])

    def test_nur_per_post(self):
        self.assertEqual(405, self.client.get('/webstats/orte/?aktion=weg&stadt=Herzogenaurach').status_code)
        self.assertIn('Herzogenaurach', views.ausgeschlossene_orte())

    def test_besucherseite(self):
        log = [besuch('a', '2026-09-10'), besuch('b', '2026-09-11', 'Herzogenaurach')]
        with mock.patch(HOLE, return_value=log):
            seite = self.client.get('/webstats/besucher/?von=2026-09-01&bis=2026-09-30').content.decode()
            mit = self.client.get('/webstats/besucher/?von=2026-09-01&bis=2026-09-30&alle_orte=1').content.decode()
        self.assertIn('Left out of the statistics: 2 places', seite)
        self.assertIn('1 visit hidden in this period', seite)
        self.assertNotIn('>Herzogenaurach</td>', seite)
        self.assertIn('counted anyway right now', mit)
        self.assertIn('name="alle_orte" value="1"', mit)       # the date form keeps it
        self.assertIn('data-vorwahl="Human"', seite)


class Zeitlinie(Grundlage):
    def test_rechnen(self):
        b = [
            besuch('a', '2026-08-05', seiten=(('/', 30), ('/services/', 90), ('/contact/', 999))),
            besuch('a', '2026-08-20', typ='returning', seiten=(('/', 50), ('/services?x=1', 60))),
            besuch('b', '2026-09-02', typ='returning', seiten=(('/services/', 120),)),
            besuch('c', '2026-09-03', seiten=(('/', 10), ('/about', 20))),
        ]
        with mock.patch(HOLE, return_value=b):
            besuche = views._besuchsprotokoll(dt.date(2026, 8, 1), dt.date(2026, 9, 30))
        z = views.zeitlinie_rechnen(besuche, dt.date(2026, 8, 1), dt.date(2026, 9, 30))
        self.assertEqual([('2026-08', 1, 1, 0), ('2026-09', 2, 1, 1)],
                         [(m['schluessel'], m['alle'], m['wieder'], m['neu']) for m in z['monate']])
        s = {r['seite']: r for r in z['seiten']}
        self.assertEqual([1, 1], s['/services/']['u'])            # one person twice, once with ?x=1
        self.assertEqual([1, 1], s['/services/']['r'])
        # August: 90 s from the first visit; the second visit's /services is its last page
        self.assertEqual(90, s['/services/']['t'][0])
        self.assertEqual(0, s['/services/']['t'][1])              # only a last page - no time
        self.assertEqual([40, 10], s['/']['t'])                   # (30+50)/2, then 10
        self.assertEqual([0, 0], s['/contact/']['t'])             # last page, 999 s ignored
        self.assertIn('/about/', s)                               # normalised with a slash

    def test_bots_zaehlen_nicht(self):
        b = [besuch('bot', '2026-09-02', seiten=(('/', 0),), dauer=0), besuch('m', '2026-09-03')]
        with mock.patch(HOLE, return_value=b):
            besuche = views._besuchsprotokoll(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
        z = views.zeitlinie_rechnen(besuche, dt.date(2026, 9, 1), dt.date(2026, 9, 30))
        self.assertEqual(1, z['monate'][0]['alle'])

    def test_andere_seiten_werden_zusammengefasst(self):
        b = [besuch('p%d' % i, '2026-09-03', seiten=(('/s%d/' % i, 5), ('/', 5))) for i in range(15)]
        with mock.patch(HOLE, return_value=b):
            besuche = views._besuchsprotokoll(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
        z = views.zeitlinie_rechnen(besuche, dt.date(2026, 9, 1), dt.date(2026, 9, 30), seiten_max=5)
        self.assertEqual(6, len(z['seiten']))
        self.assertEqual('/', z['seiten'][0]['seite'])
        self.assertEqual('Other pages (11)', z['seiten'][-1]['seite'])
        self.assertEqual([11], z['seiten'][-1]['u'])

    def test_monate(self):
        self.assertEqual(['2025-11', '2025-12', '2026-01', '2026-02'],
                         views.monate_zwischen(dt.date(2025, 11, 20), dt.date(2026, 2, 3)))
        self.assertEqual(dt.date(2025, 10, 1), views.monats_anfang(dt.date(2026, 3, 15), 5))

    def test_seite_mit_zwischenspeicher_und_ohne_rohcache(self):
        log = [besuch('a', '2026-09-10'), besuch('b', '2026-09-11', 'Herzogenaurach')]
        with mock.patch(HOLE, return_value=log) as hole:
            a = self.client.get('/webstats/zeitlinie/?von=2026-08-01&bis=2026-09-30')
            b = self.client.get('/webstats/zeitlinie/?von=2026-08-01&bis=2026-09-30')
        self.assertEqual(200, a.status_code)
        self.assertEqual(1, hole.call_count)                        # the second one came from the cache
        self.assertEqual(0, hole.call_args.kwargs['cache_seconds'])  # a year of raw log is not kept
        html = a.content.decode()
        self.assertIn('id="zl-daten"', html)
        self.assertIn('1 visit hidden in this period', html)
        daten = lambda antwort: antwort.content.decode().split('id="zl-daten"', 1)[1].split('</script>', 1)[0]
        self.assertEqual(daten(a), daten(b))
        # A changed list of places throws the counted numbers away.
        self.client.post('/webstats/orte/', {'aktion': 'weg', 'stadt': 'Herzogenaurach'})
        with mock.patch(HOLE, return_value=log) as hole:
            self.client.get('/webstats/zeitlinie/?von=2026-08-01&bis=2026-09-30')
        self.assertEqual(1, hole.call_count)

    def test_hoechstens_zwoelf_monate(self):
        with mock.patch(HOLE, return_value=[]) as hole:
            a = self.client.get('/webstats/zeitlinie/?von=2025-01-01&bis=2026-09-30')
        self.assertIn('at most 12 months', a.content.decode())
        self.assertTrue(hole.call_args.kwargs['date'].startswith('2025-10-01,'))

    def test_ohne_angabe_sechs_monate(self):
        with mock.patch(HOLE, return_value=[]) as hole:
            self.client.get('/webstats/zeitlinie/')
        von = dt.date.fromisoformat(hole.call_args.kwargs['date'].split(',')[0])
        self.assertEqual(1, von.day)
        heute = dt.date.today()
        self.assertEqual((heute.year * 12 + heute.month) - (von.year * 12 + von.month), 5)

    def test_matomo_antwortet_nicht(self):
        with mock.patch(HOLE, side_effect=RuntimeError('timeout')):
            a = self.client.get('/webstats/zeitlinie/?von=2026-09-01&bis=2026-09-30')
        self.assertEqual(200, a.status_code)
        self.assertIn('timeout', a.content.decode())


class Blog(Grundlage):
    ARTIKEL = [
        {'link': 'https://octotrial.com/clinical-data-management-lifecycle/', 'titel': 'The CDM lifecycle', 'datum': '2026-07-01'},
        {'link': 'https://octotrial.com/lessons-learned/', 'titel': 'Lessons learned', 'datum': '2026-08-01'},
    ]

    def log(self):
        li = dict(referrerName='LinkedIn', referrerType='social')
        eintraege = [
            dict(besuch('a', '2026-08-04', seiten=(('/clinical-data-management-lifecycle/', 120), ('/services/', 30))), **li),
            dict(besuch('b', '2026-09-02', typ='returning', seiten=(('/', 20), ('/clinical-data-management-lifecycle/', 200), ('/contact-page/', 5)))),
            dict(besuch('b', '2026-09-20', typ='returning', seiten=(('/clinical-data-management-lifecycle', 10),)), referrerType='search', referrerName='Google'),
            dict(besuch('c', '2026-09-21', seiten=(('/insights/', 15), ('/about-us/', 9)))),
        ]
        return eintraege

    def rechnen(self, blog):
        with mock.patch(HOLE, return_value=self.log()):
            besuche = views._besuchsprotokoll(dt.date(2026, 8, 1), dt.date(2026, 9, 30))
        return views.zeitlinie_rechnen(besuche, dt.date(2026, 8, 1), dt.date(2026, 9, 30), blog=blog)

    def test_artikel_ausfuehrlich(self):
        blog = {'/clinical-data-management-lifecycle/': 'The CDM lifecycle', '/lessons-learned/': 'Lessons learned'}
        z = self.rechnen(blog)
        a = {x['seite']: x for x in z['blog']}
        cdm = a['/clinical-data-management-lifecycle/']
        self.assertEqual((2, 1, 3), (cdm['leser'], cdm['wieder'], cdm['views']))
        self.assertEqual(2, cdm['start'])                 # a started on it, and b's second visit
        self.assertEqual(160, cdm['zeit'])                # (120 + 200) / 2; the 10 s last page does not count
        self.assertEqual(2, cdm['gemessen'])
        self.assertEqual(1, cdm['linkedin'])
        self.assertEqual('Aug 2026', cdm['erste'])
        self.assertEqual([('/contact-page/', 1), ('/services/', 1)], cdm['weiter'])
        self.assertEqual([1, 0, 0, 0], cdm['monate'][0]['quellen'])      # LinkedIn in August
        self.assertEqual([0, 1, 0, 1], cdm['monate'][1]['quellen'])      # September: Google, and one without referrer
        # an article nobody read is still listed
        self.assertEqual((0, ''), (a['/lessons-learned/']['leser'], a['/lessons-learned/']['erste']))
        self.assertEqual('The CDM lifecycle', z['blog'][0]['titel'])

    def test_in_der_matrix_eine_zeile(self):
        z = self.rechnen({'/clinical-data-management-lifecycle/': '', '/lessons-learned/': ''})
        namen = [r['seite'] for r in z['seiten']]
        self.assertIn('Blog – all articles (2)', namen)
        self.assertNotIn('/clinical-data-management-lifecycle/', namen)
        self.assertIn('/insights/', namen)                # the overview page stays a page
        zeile = next(r for r in z['seiten'] if r['seite'].startswith('Blog'))
        self.assertEqual([1, 1], zeile['u'])

    def test_quelle(self):
        self.assertEqual('LinkedIn', views.quelle_art({'herkunft': 'LinkedIn', 'herkunft_typ': 'social'}))
        self.assertEqual('LinkedIn', views.quelle_art({'herkunft': 'lnkd.in', 'herkunft_typ': 'website'}))
        self.assertEqual('Search', views.quelle_art({'herkunft': 'Google', 'herkunft_typ': 'search'}))
        self.assertEqual('Direct', views.quelle_art({'herkunft': 'Direct Entry', 'herkunft_typ': 'direct'}))
        self.assertEqual('Other', views.quelle_art({'herkunft': 'example.com', 'herkunft_typ': 'website'}))

    def test_wordpress_und_eigene_liste(self):
        self.wp.return_value = self.ARTIKEL
        self.client.post('/webstats/blog/', {'aktion': 'dazu', 'pfad': 'https://octotrial.com/clinical-trial-conduct'})
        artikel, info = views.blog_artikel()
        self.assertEqual({'/clinical-data-management-lifecycle/', '/lessons-learned/', '/clinical-trial-conduct/'}, set(artikel))
        self.assertEqual('The CDM lifecycle', artikel['/clinical-data-management-lifecycle/'])
        self.assertEqual(2, info['wordpress'])
        self.client.post('/webstats/blog/', {'aktion': 'weg', 'pfad': '/clinical-trial-conduct/'})
        self.assertEqual([], views.blog_eigene())

    def test_wordpress_antwortet_nicht(self):
        self.wp.side_effect = views.client.MatomoError('WordPress posts: HTTP 401')
        self.client.post('/webstats/blog/', {'aktion': 'dazu', 'pfad': '/lessons-learned/'})
        artikel, info = views.blog_artikel()
        self.assertEqual(['/lessons-learned/'], list(artikel))
        self.assertIn('HTTP 401', info['fehler'])

    def test_blog_zurueck_nur_ins_portal(self):
        a = self.client.post('/webstats/blog/', {'aktion': 'dazu', 'pfad': '/x/', 'zurueck': 'https://evil.example/'})
        self.assertEqual('/webstats/zeitlinie/', a['Location'])
        self.client.post('/webstats/blog/', {'aktion': 'dazu', 'pfad': '/'})     # the home page is never an article
        self.assertEqual(['/x/'], views.blog_eigene())

    def test_seite(self):
        self.wp.return_value = self.ARTIKEL
        with mock.patch(HOLE, return_value=self.log()):
            html = self.client.get('/webstats/zeitlinie/?von=2026-08-01&bis=2026-09-30').content.decode()
        self.assertIn('<h2>Blog articles</h2>', html)
        self.assertIn('The CDM lifecycle', html)
        self.assertIn('not read in this range', html)       # Lessons learned
        self.assertIn('2 from WordPress', html)
        self.assertIn('class="mt-sortierbar zl-blogtabelle"', html)
        import json
        daten = json.loads(html.split('id="zl-daten" type="application/json">', 1)[1].split('</script>', 1)[0])
        self.assertIn('Blog – all articles (2)', [z['seite'] for z in daten['seiten']])

    def test_neuer_artikel_rechnet_neu(self):
        with mock.patch(HOLE, return_value=self.log()) as hole:
            self.client.get('/webstats/zeitlinie/?von=2026-08-01&bis=2026-09-30')
            self.wp.return_value = self.ARTIKEL
            self.client.get('/webstats/zeitlinie/?von=2026-08-01&bis=2026-09-30')
        self.assertEqual(2, hole.call_count)


class WordPressListe(TransactionTestCase):
    """client.blog_beitraege against a stand-in for WordPress's REST API."""

    def setUp(self):
        cache.clear()

    def antwort(self, status, daten):
        a = mock.Mock(status_code=status)
        a.json.return_value = daten
        return a

    @override_settings(MATOMO_URL='https://octotrial.com', MATOMO_TOKEN='u:p')
    def test_seiten_titel_und_cache(self):
        erste = [{'link': 'https://octotrial.com/p%d/' % i, 'title': {'rendered': 'A &amp; B %d' % i}, 'date': '2026-09-01T10:00:00'} for i in range(100)]
        zweite = [{'link': 'https://octotrial.com/letzter/', 'title': {'rendered': 'Last &#8211; one'}, 'date': '2026-09-02T10:00:00'}]
        with mock.patch('matomo.client.requests.get', side_effect=[self.antwort(200, erste), self.antwort(200, zweite)]) as get:
            liste = views.client.blog_beitraege()
            nochmal = views.client.blog_beitraege()
        self.assertEqual(2, get.call_count)                  # two pages, then from the cache
        self.assertEqual(101, len(liste))
        self.assertEqual('A & B 0', liste[0]['titel'])
        self.assertEqual('Last – one', liste[-1]['titel'])
        self.assertEqual('2026-09-02', liste[-1]['datum'])
        self.assertEqual(liste, nochmal)

    @override_settings(MATOMO_URL='https://octotrial.com', MATOMO_TOKEN='u:p')
    def test_fehler_wird_eine_stunde_gemerkt(self):
        with mock.patch('matomo.client.requests.get', return_value=self.antwort(401, {'code': 'rest_forbidden'})) as get:
            with self.assertRaises(views.client.MatomoError):
                views.client.blog_beitraege()
            with self.assertRaises(views.client.MatomoError):
                views.client.blog_beitraege()
        self.assertEqual(1, get.call_count)
