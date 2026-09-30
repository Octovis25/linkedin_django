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
        with connection.cursor() as c:
            c.execute('DROP TABLE IF EXISTS matomo_orte_raus')
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
