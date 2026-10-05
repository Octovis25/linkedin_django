"""Web Analytics on one data basis (05.10.2026).

The checks Ortrud asked for:
  - place variants fall under the location rule as written
  - previews are marked and left out of the audience
  - one page without a time measurement is not automatically a bot
  - headless browsers are classified with a visible reason
  - UTM and referrer decide the source; a missing one stays unknown
  - article addresses (old and new) are assigned correctly
  - the same period and filters give the same numbers in every view
  - contact page views and contact actions stay apart

Matomo and WordPress are stood in for (wa_daten.py: patterns of the real log).
"""
import datetime as dt
import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from matomo import auswertung as aw
from matomo import views
from planner import utm

from . import wa_daten

HOLE = 'matomo.views.client.hole'
SEPT = (dt.date(2026, 9, 1), dt.date(2026, 9, 30))


def katalog(manual=()):
    return aw.Catalogue(posts=wa_daten.POSTS, pages=wa_daten.PAGES, manual=list(manual))


def einst(**kw):
    kw.setdefault('places', ['Herzogenaurach', 'Wasserburg am Inn'])
    kw.setdefault('linkedin_campaigns', (utm.CAMPAIGN,))
    return aw.Settings(**kw)


def bewerten(log=None, scope='human', **kw):
    return aw.evaluate(log if log is not None else wa_daten.log(), *SEPT, katalog(), einst(**kw), scope=scope)


def nach_id(ev):
    return {v['besucher']: v for v in ev.all}


class Orte(SimpleTestCase):
    def test_varianten_der_regel(self):
        regeln = ['Wasserburg am Inn', 'Herzogenaurach']
        self.assertEqual('Wasserburg am Inn', aw.place_rule_for('Wasserburg am Inn (Gabersee)', regeln))
        self.assertEqual('Wasserburg am Inn', aw.place_rule_for('  wasserburg  AM inn ', regeln))
        self.assertEqual('Herzogenaurach', aw.place_rule_for('HERZOGENAURACH', regeln))
        # a different place that merely starts the same way is NOT covered
        self.assertIsNone(aw.place_rule_for('Wasserburg (Bodensee)', regeln))
        self.assertIsNone(aw.place_rule_for('Wasserburger Land', regeln))
        self.assertIsNone(aw.place_rule_for('unknown', regeln))

    def test_regel_im_ergebnis(self):
        ev = bewerten()
        v = nach_id(ev)
        self.assertEqual('Wasserburg am Inn', v['o1']['ortsregel'])     # written with the district
        self.assertEqual('Herzogenaurach', v['o2']['ortsregel'])
        self.assertNotIn('o1', [x['besucher'] for x in ev.audience])
        # the rule is named as a location rule, not as proof of an own visit
        self.assertIn('location rule', v['o1']['ausschluesse'][0])
        self.assertEqual(aw.HUMAN, v['o1']['klasse'])                     # its class is not changed
        self.assertEqual([{'regel': 'Herzogenaurach', 'varianten': [('Herzogenaurach', 1)]},
                          {'regel': 'Wasserburg am Inn', 'varianten': [('Wasserburg am Inn (Gabersee)', 1)]}],
                         aw.place_variants(ev.all, ['Herzogenaurach', 'Wasserburg am Inn']))

    def test_orte_zaehlen_trotzdem(self):
        ev = aw.evaluate(wa_daten.log(), *SEPT, katalog(), einst(), count_places=True)
        self.assertIn('o1', [x['besucher'] for x in ev.audience])


class Vorschau(SimpleTestCase):
    def test_erkannt(self):
        self.assertTrue(aw.is_preview('https://octotrial.com/?p=2200&preview=true'))
        self.assertTrue(aw.is_preview('https://octotrial.com/?preview_id=5&preview_nonce=x&preview=true'))
        self.assertTrue(aw.is_preview('https://octotrial.com/about-us/?elementor-preview=17&ver=1'))
        self.assertTrue(aw.is_preview('https://octotrial.com/?elementor_library=x&render_mode=y'))
        self.assertFalse(aw.is_preview('https://octotrial.com/?p=2200'))        # a public short link
        self.assertFalse(aw.is_preview('https://octotrial.com/services/'))

    def test_sitzung_markiert_und_ausgeschlossen(self):
        ev = bewerten()
        e1 = nach_id(ev)['e1']
        self.assertTrue(e1['bearbeitung'])
        self.assertIn('possible internal editing visit (preview opened)', e1['ausschluesse'])
        self.assertEqual((1, 1), (e1['aufrufe'], e1['vorschau_aufrufe']))
        self.assertEqual('preview', e1['seiten'][0]['art'])
        self.assertNotIn('e1', [x['besucher'] for x in ev.audience])
        # its live article view does not count for the article either
        cdm = next(a for a in aw.by_article(ev.audience, katalog(), einst())
                   if a['key'] == 'clinical-data-management-lifecycle')
        self.assertEqual(2, cdm['aufrufe'])                               # l1 and a4, not e1


class Klassifikation(SimpleTestCase):
    def test_eine_seite_null_sekunden_ist_unklar(self):
        v = nach_id(bewerten())
        self.assertEqual(aw.UNCLEAR, v['u1']['klasse'])
        self.assertEqual(['One page, time not measurable, no interaction'], v['u1']['gruende'])
        self.assertIsNone(v['u1']['dauer_sek'])
        self.assertEqual('not measured (1 page)', v['u1']['dauer_text'])

    def test_unklar_zaehlt_wenn_gewaehlt(self):
        self.assertNotIn('u1', [x['besucher'] for x in bewerten().audience])
        self.assertIn('u1', [x['besucher'] for x in bewerten(scope='human_unclear').audience])

    def test_headless_mit_grund(self):
        h1 = nach_id(bewerten())['h1']
        self.assertEqual(aw.AUTOMATION, h1['klasse'])
        self.assertIn('headless browser (Headless Chrome)', h1['gruende'][0])
        # its three seconds between two pages are a human signal - shown, but outweighed
        self.assertIn('also seen: reading time', h1['gruende'][1])

    def test_mehrere_seiten_allein_kein_mensch(self):
        f1 = nach_id(bewerten())['f1']
        self.assertEqual(aw.AUTOMATION, f1['klasse'])
        self.assertIn('5 pages, each left after ≤ 1 s', f1['gruende'][0])
        zwei = wa_daten.visit('z', '2026-09-05 10:00', [('/', 'Home', 2), ('/services/', 'Services', 0)])
        z = nach_id(bewerten([zwei]))['z']
        self.assertEqual(aw.UNCLEAR, z['klasse'])                          # 2 s: neither proof

    def test_interaktion_ist_menschlich(self):
        l1 = nach_id(bewerten())['l1']
        self.assertEqual(aw.HUMAN, l1['klasse'])

    def test_eigenes_geraet(self):
        ev = bewerten(own_ids={'a1'})
        a1 = nach_id(ev)['a1']
        self.assertEqual(aw.OWN, a1['klasse'])
        self.assertIn('confirmed own / test visit', a1['ausschluesse'])
        self.assertNotIn('a1', [x['besucher'] for x in ev.audience])


class Herkunft(SimpleTestCase):
    def test_utm_und_kampagne(self):
        l1 = nach_id(bewerten())['l1']
        self.assertEqual(aw.LINKEDIN, l1['quelle'])
        self.assertEqual(152, l1['post_id'])
        self.assertEqual('linkedin_posts', l1['kampagne'])
        self.assertEqual('UTM: utm_campaign=linkedin_posts, utm_content=post-152, utm_term=company_page', l1['beleg'])

    def test_utm_source_in_der_adresse(self):
        v = wa_daten.visit('x', '2026-09-05 10:00', [('/?utm_source=linkedin&utm_medium=organic_social&utm_content=post-7', 'Home', 0)])
        x = nach_id(bewerten([v]))['x']
        self.assertEqual((aw.LINKEDIN, 7), (x['quelle'], x['post_id']))

    def test_referrer(self):
        v = nach_id(bewerten(scope='human_unclear'))
        self.assertEqual((aw.SEARCH, 'Referrer: Google (www.google.com)'), (v['a1']['quelle'], v['a1']['beleg']))
        self.assertEqual(aw.AI, v['a4']['quelle'])
        self.assertEqual((aw.WEBSITE, 'Referrer: www.webdig.asia'), (v['s1']['quelle'], v['s1']['beleg']))
        li = wa_daten.visit('y', '2026-09-05 10:00', [('/', 'Home', 0)], rtype='social', rname='LinkedIn',
                            rurl='https://www.linkedin.com/')
        self.assertEqual((aw.LINKEDIN, 'Referrer: www.linkedin.com'),
                         (nach_id(bewerten([li]))['y']['quelle'], nach_id(bewerten([li]))['y']['beleg']))

    def test_fehlende_herkunft_bleibt_unbekannt(self):
        # a2 came minutes after the LinkedIn visit l1 would have - timing assigns nothing
        a2 = nach_id(bewerten())['a2']
        self.assertEqual((aw.UNKNOWN, 'No referrer'), (a2['quelle'], a2['beleg']))
        self.assertIsNone(a2['post_id'])
        intern = wa_daten.visit('i', '2026-09-05 10:00', [('/', 'Home', 0)], rurl='https://octotrial.com/services/')
        self.assertEqual(aw.UNKNOWN, nach_id(bewerten([intern]))['i']['quelle'])
        self.assertIn('octotrial.com itself', nach_id(bewerten([intern]))['i']['beleg'])

    def test_beitraege_tabelle(self):
        ev = bewerten()
        zeilen = aw.by_post(ev.audience, {152: {'titel': 'CDM', 'datum': '14.09.2026', 'kanal': 'Company page'}})
        self.assertEqual(1, len(zeilen))
        self.assertEqual((152, 'CDM', 1, 1), (zeilen[0]['post_id'], zeilen[0]['titel'], zeilen[0]['besuche'],
                                              zeilen[0]['kontaktaktionen']['n']))


class Artikel(SimpleTestCase):
    def test_zuordnung(self):
        k = katalog()
        self.assertEqual((aw.ARTICLE, 'lessons-learned', 'WordPress post'),
                         k.classify('/insights/lessons-learned/'))
        art, key, why = k.classify('/lessons-learned/')
        self.assertEqual((aw.ARTICLE, 'lessons-learned'), (art, key))
        self.assertIn('earlier address', why)
        self.assertEqual(aw.ARTICLE, k.classify('/insights/lessons-learned-2/')[0])   # WordPress' "-2"
        self.assertEqual(aw.OVERVIEW, k.classify('/insights/')[0])
        self.assertEqual(aw.OVERVIEW, k.classify('/category/ai-in-clinical-trials/')[0])
        self.assertEqual(aw.OVERVIEW, k.classify('/insights/series/clinical-data-management-lifecycle/')[0])
        self.assertEqual(aw.NOT_FOUND, k.classify('/blog-page/', 'Page not found')[0])
        self.assertEqual(aw.PAGE, k.classify('/services/')[0])
        self.assertEqual(aw.PAGE, k.classify('/')[0])
        self.assertEqual(aw.OTHER, k.classify('/why-ai-in-clinical-trials-still-needs-human-judgment/')[0])
        # entered by hand: counts as article from then on
        k2 = katalog(manual=['https://octotrial.com/why-ai-in-clinical-trials-still-needs-human-judgment'])
        self.assertEqual(aw.ARTICLE, k2.classify('/why-ai-in-clinical-trials-still-needs-human-judgment/')[0])

    def test_alte_und_neue_adresse_zusammen(self):
        ll = next(a for a in aw.by_article(bewerten().audience, katalog(), einst()) if a['key'] == 'lessons-learned')
        self.assertEqual([('/insights/lessons-learned/', 1), ('/lessons-learned/', 1)], sorted(ll['adressen']))
        self.assertEqual((2, 2, 1), (ll['ids'], ll['aufrufe'], ll['einstiege']))
        # a1: article -> services -> contact page; a2: ended on the article
        self.assertEqual([('Services', 1)], ll['weiter'])
        self.assertEqual(1, ll['ende'])
        self.assertEqual(({'n': 1, 'von': 2, 'pct': 50}, {'n': 1, 'von': 2, 'pct': 50}), (ll['angebot'], ll['kontakt']))
        self.assertEqual((95, 1), (ll['zeit'], ll['messungen']))          # a2's last page is not measured

    def test_ungelesen_und_ungemessen(self):
        sop = next(a for a in aw.by_article(bewerten().audience, katalog(), einst())
                   if a['key'] == 'sop-quality-in-clinical-trials')
        self.assertEqual((0, None, 'not measured'), (sop['aufrufe'], sop['zeit'], sop['zeit_text']))

    def test_letzte_seite_nicht_null(self):
        a2 = nach_id(bewerten())['a2']
        self.assertEqual([20, None], [p['zeit'] for p in a2['seiten']])

    def test_uebersichten_getrennt(self):
        ueber, rest = aw.overviews_and_unassigned(bewerten().audience, katalog())
        self.assertEqual({'/insights/', '/series/ai-in-clinical-trials-practical-support-not-magic/'},
                         {u['pfad'] for u in ueber})
        self.assertEqual({'/category/general/', '/why-ai-in-clinical-trials-still-needs-human-judgment/'},
                         {u['pfad'] for u in rest})


class KontaktUndZeit(SimpleTestCase):
    def test_kontaktseite_und_kontaktaktion_getrennt(self):
        v = nach_id(bewerten())
        self.assertEqual((True, 0), (v['a1']['kontaktseite'], v['a1']['kontaktaktionen']))
        self.assertEqual((False, 1), (v['l1']['kontaktseite'], v['l1']['kontaktaktionen']))
        zeilen = {r['quelle']: r for r in aw.by_source(bewerten().audience)}
        self.assertEqual((1, 0), (zeilen[aw.SEARCH]['kontaktseite']['n'], zeilen[aw.SEARCH]['kontaktaktionen']['n']))
        self.assertEqual((0, 1), (zeilen[aw.LINKEDIN]['kontaktseite']['n'], zeilen[aw.LINKEDIN]['kontaktaktionen']['n']))
        self.assertEqual(5, zeilen['Total']['besuche'])

    def test_berliner_zeit(self):
        # 22:30 UTC on 30 September is 1 October in Berlin: outside September
        self.assertNotIn('m1', nach_id(bewerten()))
        okt = aw.evaluate(wa_daten.log(), dt.date(2026, 10, 1), dt.date(2026, 10, 1), katalog(), einst())
        m1 = nach_id(okt)['m1']
        self.assertEqual(('2026-10-01', '00:30', 'Thursday'), (m1['datum'], m1['uhrzeit'], m1['wochentag']))

    def test_monate_nicht_addiert(self):
        log = [wa_daten.visit('p', '2026-08-10 10:00', [('/', 'H', 30), ('/services/', 'S', 0)]),
               wa_daten.visit('p', '2026-09-10 10:00', [('/', 'H', 30), ('/services/', 'S', 0)], returning=True)]
        ev = aw.evaluate(log, dt.date(2026, 8, 1), dt.date(2026, 9, 30), katalog(), einst())
        monate = aw.monthly_ids(ev.audience, ['2026-08', '2026-09'])
        self.assertEqual([1, 1], [m['ids'] for m in monate])
        self.assertEqual(1, aw.kpis(ev)['besucher_ids'])                  # one ID, not two


class Verfolgungslinks(SimpleTestCase):
    def test_konvention(self):
        self.assertEqual('https://octotrial.com/services/?utm_source=linkedin&utm_medium=organic_social'
                         '&utm_campaign=linkedin_posts&utm_content=post-152&utm_term=company_page',
                         utm.tag('https://octotrial.com/services/', 152))
        self.assertTrue(utm.tag('https://www.octotrial.com/x/', 3, personal=True).endswith('utm_term=personal_profile'))

    def test_vorhandene_werte_bleiben_nichts_doppelt(self):
        a = utm.tag('https://octotrial.com/?utm_source=newsletter&x=1', 9)
        self.assertEqual(1, a.count('utm_source='))
        self.assertIn('utm_source=newsletter', a)
        self.assertIn('x=1', a)
        self.assertEqual(a, utm.tag(a, 9))                                 # twice = once

    def test_fremde_links_und_satzzeichen(self):
        self.assertEqual('https://example.com/a', utm.tag('https://example.com/a', 1))
        text, aend = utm.tag_text('Read https://octotrial.com/lean-oversight/. And <a href="https://octotrial.com/?a=1&amp;b=2">x</a> '
                                  'or https://linkedin.com/x', 4)
        self.assertEqual(2, len(aend))
        self.assertIn('https://octotrial.com/lean-oversight/?utm_source=linkedin', text)
        self.assertIn('utm_term=company_page. And', text)                 # the full stop stays outside
        self.assertIn('a=1&amp;b=2&amp;utm_source=linkedin', text)        # HTML stays HTML
        self.assertIn('https://linkedin.com/x', text)
        self.assertEqual([], utm.tag_text(text, 4)[1])
        _, eins = utm.tag_text('<a href="https://octotrial.com/x/">https://octotrial.com/x/</a>', 4)
        self.assertEqual(1, len(eins))                                    # href and text: one link

    def test_rundweg_ueber_die_auswertung(self):
        link = utm.tag('https://octotrial.com/services/', 77)
        v = wa_daten.visit('r', '2026-09-05 10:00', [(link, 'Services', 0)])
        r = nach_id(bewerten([v], scope='human_unclear'))['r']
        self.assertEqual((aw.LINKEDIN, 77, 'linkedin_posts'), (r['quelle'], r['post_id'], r['kampagne']))


@override_settings(USE_TZ=True, TIME_ZONE='Europe/Berlin')
class Ansichten(TransactionTestCase):
    """The same period and filters give the same numbers everywhere."""

    def setUp(self):
        cache.clear()
        for t in ('matomo_orte_raus', 'matomo_blog_adressen', 'matomo_eigene_besucher'):
            with connection.cursor() as c:
                c.execute('DROP TABLE IF EXISTS ' + t)
        views._orte_tabelle_da = views._blog_tabelle_da = views._eigene_tabelle_da = False
        for ziel, wert in (('matomo.views.client.blog_beitraege', wa_daten.POSTS),
                           ('matomo.views.client.wp_seiten', wa_daten.PAGES)):
            p = mock.patch(ziel, return_value=wert)
            p.start()
            self.addCleanup(p.stop)
        self.client.force_login(User.objects.create_user('wa', password='wa'))

    def hole(self, pfad, **kw):
        if pfad == 'live/last_visits_details':
            return wa_daten.log()
        if pfad == 'live/visitor_profile':
            return {'lastVisits': [v for v in wa_daten.log() if v['visitorId'] == kw.get('visitorId')]}
        return []

    def get(self, url):
        with mock.patch(HOLE, side_effect=self.hole) as h:
            r = self.client.get(url)
        self.assertEqual(200, r.status_code, url)
        return r, h

    def test_gleiche_zahlen(self):
        q = '?von=2026-09-01&bis=2026-09-30'
        ueber, h = self.get('/webstats/' + q)
        besucher, _ = self.get('/webstats/besucher/' + q)
        zeit, _ = self.get('/webstats/zeitlinie/' + q)
        self.assertEqual(5, ueber.context['k']['besuche'])
        self.assertEqual(5, len(besucher.context['besuche']))
        self.assertEqual(ueber.context['k'], besucher.context['k'])
        daten = json.loads(zeit.content.decode().split('id="zl-daten" type="application/json">', 1)[1].split('</script>', 1)[0])
        self.assertEqual(5, sum(m['alle'] for m in daten['monate']))         # one month: IDs = 5
        self.assertEqual(ueber.context['ausgeschlossen_zahl'], zeit.context['ausgeschlossen_zahl'])
        # the period starts a day earlier at Matomo (its days are UTC)
        self.assertTrue(h.call_args_list[0].kwargs['date'].startswith('2026-08-31,2026-09-30'))

    def test_umfang_wirkt_ueberall(self):
        q = '?von=2026-09-01&bis=2026-09-30&umfang=human_unclear'
        ueber, _ = self.get('/webstats/' + q)
        besucher, _ = self.get('/webstats/besucher/' + q)
        self.assertEqual(8, ueber.context['k']['besuche'])                  # + u1, u2, s1
        self.assertEqual(8, len(besucher.context['besuche']))

    def test_menschen_und_bots_je_tag(self):
        r, _ = self.get('/webstats/besucher/?von=2026-09-01&bis=2026-09-30')
        kl, sonder = r.context['kl'], r.context['sonder']
        # without own devices, previews and the location rule: o1, o2, e1, e2
        self.assertEqual((5, 3, 2, 0, 4), (kl['human'], kl['unclear'], kl['automation'], kl['own'], sonder))
        self.assertEqual(14, kl['human'] + kl['unclear'] + kl['automation'] + sonder)
        summen = {x['feld']: x['summe'] for x in r.context['verlauf']['reihen']}
        self.assertEqual({'menschen': 5, 'unklar': 3, 'bots': 2}, summen)    # the curve = the tiles
        raster = r.context['raster']
        self.assertEqual((5, 2, 3), (raster['menschen']['summe'], raster['bots']['summe'], raster['unklar']))
        html = r.content.decode()
        self.assertIn('Humans and bots per day', html)
        self.assertIn('Exclusions and classification', html)                # the full rules: here
        self.assertIn('klasse=automation', html)                             # a bot cell opens those visits

    def test_uebersicht_nur_eine_zeile_zu_den_ausschluessen(self):
        r, _ = self.get('/webstats/?von=2026-09-01&bis=2026-09-30')
        html = r.content.decode()
        self.assertNotIn('Exclusions and classification', html)
        self.assertIn('rules and exclusions on Visitors', html)
        self.assertIn('<strong>5</strong> visits counted · 9 not counted', html)
        self.assertNotIn('Humans and bots per day', html)

    def test_klassenfilter(self):
        r, _ = self.get('/webstats/besucher/?von=2026-09-01&bis=2026-09-30&ausgeschlossen=1&klasse=automation')
        self.assertEqual({'h1', 'f1'}, {v['besucher'] for v in r.context['besuche']})

    def test_alte_reiter_leiten_weiter(self):
        for alt, neu in (('/webstats/ziele/?von=2026-09-01', '/webstats/?von=2026-09-01'),
                         ('/webstats/seiten/?von=2026-09-01', '/webstats/berichte/?von=2026-09-01&teil=seiten'),
                         ('/webstats/suchbegriffe/', '/webstats/berichte/?teil=suche'),
                         ('/webstats/ki/', '/webstats/berichte/?teil=ki')):
            self.assertEqual(neu, self.client.get(alt)['Location'], alt)

    def test_matomo_berichte_ein_reiter(self):
        def hole(pfad, **kw):
            if pfad == 'api/processed_report':
                return {'reportData': [{'label': '/', 'nb_visits': 3}], 'columns': {'nb_visits': 'Visits'}}
            if pfad == 'api/report_metadata':
                return [{'category': 'Actions', 'name': 'Page URLs', 'module': 'Actions', 'action': 'getPageUrls'}]
            return []
        with mock.patch(HOLE, side_effect=hole) as h:
            seiten = self.client.get('/webstats/berichte/?von=2026-09-01&bis=2026-09-30')
        self.assertEqual(6, h.call_count)                                   # only the chosen part is fetched
        html = seiten.content.decode()
        self.assertIn('Most visited pages', html)
        self.assertIn('Different data basis.', html)
        self.assertIn('name="teil" value="seiten"', html)                   # the date form keeps the part
        with mock.patch(HOLE, side_effect=hole):
            alle = self.client.get('/webstats/berichte/?teil=alle').content.decode()
        self.assertIn('Every report Matomo offers (1)', alle)

    def test_ausgeschlossene_anzeigen(self):
        r, _ = self.get('/webstats/besucher/?von=2026-09-01&bis=2026-09-30&ausgeschlossen=1')
        self.assertEqual(14, len(r.context['besuche']))
        html = r.content.decode()
        self.assertIn('location rule “Wasserburg am Inn” (Matomo: Wasserburg am Inn (Gabersee))', html)
        self.assertIn('possible internal editing visit (preview opened)', html)
        self.assertIn('Automation signal: headless browser (Headless Chrome)', html)

    def test_eigenes_geraet_markieren_und_zuruecknehmen(self):
        a = self.client.post('/webstats/eigen/', {'aktion': 'dazu', 'besucher': 'a1', 'notiz': 'Laptop',
                                                  'zurueck': '/webstats/besucher/'})
        self.assertEqual('/webstats/besucher/', a['Location'])
        r, _ = self.get('/webstats/?von=2026-09-01&bis=2026-09-30')
        self.assertEqual(4, r.context['k']['besuche'])
        self.assertEqual(1, r.context['gruende']['own'])
        self.client.post('/webstats/eigen/', {'aktion': 'weg', 'besucher': 'a1'})
        r, _ = self.get('/webstats/?von=2026-09-01&bis=2026-09-30')
        self.assertEqual(5, r.context['k']['besuche'])
        self.assertEqual(405, self.client.get('/webstats/eigen/?aktion=dazu&besucher=x').status_code)

    def test_profil_zeigt_klasse_und_knopf(self):
        r, _ = self.get('/webstats/besucher/e1/')
        html = r.content.decode()
        self.assertIn('This is my device', html)
        self.assertIn('This ID opened a WordPress preview', html)

    def test_alter_log_reiter_leitet_um(self):
        r = self.client.get('/webstats/protokoll/?von=2026-09-01&bis=2026-09-30&nur=menschen')
        self.assertEqual('/webstats/besucher/?von=2026-09-01&bis=2026-09-30', r['Location'])
        r = self.client.get('/webstats/protokoll/?nur=bots&tag=Monday&stunde=3')
        self.assertIn('ausgeschlossen=1', r['Location'])
        self.assertIn('tag=Monday', r['Location'])

    def test_leere_zustaende(self):
        with mock.patch(HOLE, return_value=[]):
            html = self.client.get('/webstats/besucher/?von=2026-09-01&bis=2026-09-30').content.decode()
        self.assertIn('No visits recorded in this period.', html)
        with mock.patch(HOLE, side_effect=RuntimeError('timeout')):
            html = self.client.get('/webstats/besucher/?von=2026-09-01&bis=2026-09-30').content.decode()
        self.assertIn('Measurement not available', html)
        with mock.patch(HOLE, return_value=[wa_daten.visit('x', '2026-09-05 10:00', [('/', 'H', 30), ('/a/', 'A', 0)])]):
            html = self.client.get('/webstats/?von=2026-09-01&bis=2026-09-30').content.decode()
        self.assertIn('No visit with a LinkedIn tracking link yet', html)
        self.assertIn('cannot be assigned until posts carry tracking links', html)


@override_settings(USE_TZ=True, TIME_ZONE='Europe/Berlin')
class PlannerUtm(TransactionTestCase):
    def setUp(self):
        with connection.cursor() as c:
            c.execute('CREATE TABLE IF NOT EXISTS planner_posts (id INT PRIMARY KEY, title VARCHAR(200), is_oj TINYINT)')
            c.execute('DELETE FROM planner_posts')
            c.execute("INSERT INTO planner_posts (id, title, is_oj) VALUES (152, 'Company', 0), (153, 'Mine', 1)")
        self.client.force_login(User.objects.create_user('pl', password='pl'))

    def test_link_und_text(self):
        r = self.client.get('/planner/api/utm/', {'post_id': 153, 'url': 'https://octotrial.com/services/'})
        self.assertEqual('personal_profile', r.json()['channel'])
        self.assertIn('utm_content=post-153', r.json()['url'])
        r = self.client.post('/planner/api/utm/', json.dumps({'post_id': 152, 'text': 'See https://octotrial.com/x/'}),
                             content_type='application/json')
        self.assertEqual(1, len(r.json()['changes']))
        self.assertIn('utm_term=company_page', r.json()['text'])
        self.assertEqual(400, self.client.get('/planner/api/utm/', {'post_id': 152, 'url': 'https://evil.example/'}).status_code)
        self.assertEqual(404, self.client.get('/planner/api/utm/', {'post_id': 999, 'url': 'https://octotrial.com/'}).status_code)
