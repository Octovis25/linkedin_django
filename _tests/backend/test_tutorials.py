"""Tutorials tab (08.10.2026): films, steps, uploads, the finished video.

Nextcloud is not reachable in the test run, so files go to the local fallback
(__local__/tutorials/...), which the Studio's proxy serves the same way.
"""
import json
from unittest import mock
import shutil
import os

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from tutorials import views as tv


PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
       b'\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84'
       b'\x00\x00\x00\x00IEND\xaeB`\x82')


class Basis(TransactionTestCase):
    # CREATE TABLE commits in MySQL - so no TestCase transaction around it.

    def setUp(self):
        super().setUp()
        tv.ensure_tables.ungepuffert()
        self.client.force_login(User.objects.create_user('tu', password='tu'))
        with connection.cursor() as c:
            c.execute("DELETE FROM tutorial_steps")
            c.execute("DELETE FROM tutorial_films")

    def tearDown(self):
        shutil.rmtree(os.path.join(settings.BASE_DIR, 'media', 'tutorials'), ignore_errors=True)
        super().tearDown()

    def zeile(self, sql, *werte):
        with connection.cursor() as c:
            c.execute(sql, list(werte))
            return c.fetchone()

    def api(self, url, **daten):
        antwort = self.client.post(url, json.dumps(daten), content_type='application/json')
        return antwort.status_code, antwort.json()

    def neuer_film(self, titel='Approve a draft', portal='sop'):
        status, j = self.api('/tutorials/api/film/', action='create', portal=portal, title=titel)
        self.assertEqual(200, status, j)
        return j['id']

    def hochladen(self, film_id, art='image', inhalt=PNG, typ='image/png', name='shot.png'):
        datei = SimpleUploadedFile(name, inhalt, content_type=typ)
        return self.client.post('/tutorials/api/upload/', {'film_id': film_id, 'kind': art, 'file': datei})


class Tutorials(Basis):

    # ── the page ───────────────────────────────────────────────────────────
    def test_seite_ohne_film(self):
        antwort = self.client.get('/tutorials/')
        self.assertEqual(200, antwort.status_code)
        self.assertContains(antwort, 'No films for this portal yet')

    def test_seite_zeigt_film_und_portale(self):
        fid = self.neuer_film()
        antwort = self.client.get('/tutorials/?portal=sop')
        self.assertContains(antwort, 'Approve a draft')
        self.assertContains(antwort, f'data-film="{fid}"')
        self.assertContains(antwort, 'Developer Portal')

    def test_film_eines_anderen_portals_wird_nicht_geoeffnet(self):
        fid = self.neuer_film(portal='dev')
        antwort = self.client.get(f'/tutorials/?portal=sop&film={fid}')
        self.assertContains(antwort, 'data-film=""')

    def test_nur_angemeldet(self):
        self.client.logout()
        self.assertEqual(302, self.client.get('/tutorials/').status_code)

    # ── films ──────────────────────────────────────────────────────────────
    def test_film_braucht_titel_und_portal(self):
        self.assertEqual(400, self.api('/tutorials/api/film/', action='create', portal='sop', title=' ')[0])
        self.assertEqual(400, self.api('/tutorials/api/film/', action='create', portal='xx', title='T')[0])

    def test_film_aendern(self):
        fid = self.neuer_film()
        status, j = self.api('/tutorials/api/film/', action='update', id=fid,
                             title='Approve', page='Draft review', lang='de', status='In portal')
        self.assertEqual(200, status, j)
        self.assertEqual(('Approve', 'Draft review', 'de', 'In portal'),
                         self.zeile("SELECT title, page, lang, status FROM tutorial_films WHERE id=%s", fid))
        self.assertEqual(400, self.api('/tutorials/api/film/', action='update', id=fid, status='Gone')[0])

    # ── steps ──────────────────────────────────────────────────────────────
    def test_bild_hochladen_und_schritt_anlegen(self):
        fid = self.neuer_film()
        antwort = self.hochladen(fid)
        self.assertEqual(200, antwort.status_code, antwort.content)
        pfad = antwort.json()['nc_path']
        self.assertTrue(pfad.startswith(f'__local__/tutorials/sop/{fid}/screens/shot_'), pfad)
        status, j = self.api('/tutorials/api/step/', action='create', film_id=fid, image_nc_path=pfad)
        self.assertEqual(200, status, j)
        self.assertEqual(1, len(j['steps']))
        self.assertIn('/library/studio/nc-image/?p=__local__/tutorials/sop/', j['steps'][0]['image_url'])
        # the proxy serves it
        self.assertEqual(200, self.client.get(j['steps'][0]['image_url']).status_code)

    def test_fremder_pfad_wird_abgelehnt(self):
        fid = self.neuer_film()
        status, _ = self.api('/tutorials/api/step/', action='create', film_id=fid,
                             image_nc_path='Marketing & Design/Octotrial_Assets/Studio_Work/x.png')
        self.assertEqual(400, status)
        anderer = self.neuer_film('Other')
        status, _ = self.api('/tutorials/api/step/', action='create', film_id=fid,
                             image_nc_path=f'{tv.NC_ROOT}/sop/{anderer}/screens/a.png')
        self.assertEqual(400, status)
        status, _ = self.api('/tutorials/api/step/', action='create', film_id=fid,
                             image_nc_path=f'{tv.NC_ROOT}/sop/{fid}/../{anderer}/a.png')
        self.assertEqual(400, status)

    def test_falscher_dateityp(self):
        fid = self.neuer_film()
        antwort = self.hochladen(fid, inhalt=b'<html>', typ='text/html', name='x.html')
        self.assertEqual(400, antwort.status_code)
        antwort = self.hochladen(fid, art='audio', inhalt=PNG, typ='image/png')
        self.assertEqual(400, antwort.status_code)

    def test_schritt_aendern_mit_grenzen(self):
        fid = self.neuer_film()
        sid = self.api('/tutorials/api/step/', action='create', film_id=fid)[1]['id']
        status, j = self.api('/tutorials/api/step/', action='update', id=sid, click_x=0.25, click_y=0.5,
                             frame_x=0.1, frame_y=0.2, frame_w=0.3, frame_h=0.1, caption='Click Approve',
                             script='Read the changes.', audio_ms=4200, min_ms=5000, highlight='none')
        self.assertEqual(200, status, j)
        self.assertEqual((0.25, 0.5, 'Click Approve', 4200, 5000, 'none'),
                         self.zeile("""SELECT click_x, click_y, caption, audio_ms, min_ms, highlight
                                       FROM tutorial_steps WHERE id=%s""", sid))
        self.assertEqual(400, self.api('/tutorials/api/step/', action='update', id=sid, click_x=1.5)[0])
        self.assertEqual(400, self.api('/tutorials/api/step/', action='update', id=sid, highlight='glow')[0])
        # null clears the click point
        self.api('/tutorials/api/step/', action='update', id=sid, click_x=None, click_y=None)
        self.assertEqual((None, None), self.zeile("SELECT click_x, click_y FROM tutorial_steps WHERE id=%s", sid))

    def test_reihenfolge_und_entfernen(self):
        fid = self.neuer_film()
        ids = [self.api('/tutorials/api/step/', action='create', film_id=fid, caption=c)[1]['id']
               for c in 'ABC']
        j = self.api('/tutorials/api/step/', action='move', id=ids[2], dir=-1)[1]
        self.assertEqual(['A', 'C', 'B'], [s['caption'] for s in j['steps']])
        j = self.api('/tutorials/api/step/', action='move', id=ids[0], dir=-1)[1]   # already first
        self.assertEqual(['A', 'C', 'B'], [s['caption'] for s in j['steps']])
        j = self.api('/tutorials/api/step/', action='delete', id=ids[1])[1]
        self.assertEqual(['A', 'C'], [s['caption'] for s in j['steps']])

    def test_stimme_hochladen(self):
        fid = self.neuer_film()
        antwort = self.hochladen(fid, art='audio', inhalt=b'\x1aE\xdf\xa3fake', typ='audio/webm;codecs=opus',
                                 name='step1.webm')
        self.assertEqual(200, antwort.status_code, antwort.content)
        self.assertIn(f'/sop/{fid}/voice/step1_', antwort.json()['nc_path'])

    # ── the video ──────────────────────────────────────────────────────────
    def test_video_speichern_behaelt_alte_fassung(self):
        fid = self.neuer_film()
        video = SimpleUploadedFile('tutorial.webm', b'\x1aE\xdf\xa3video', content_type='video/webm')
        antwort = self.client.post('/tutorials/api/video/', {'film_id': fid, 'seconds': '72.4', 'video': video})
        self.assertEqual(200, antwort.status_code, antwort.content)
        film = antwort.json()['film']
        self.assertEqual('Video ready', film['status'])
        self.assertIn('Approve_a_draft_', film['video_nc_path'])
        self.assertAlmostEqual(72.4, film['video_seconds'])
        # a changed step means the video is out of date again
        sid = self.api('/tutorials/api/step/', action='create', film_id=fid)[1]['id']
        self.assertEqual('Draft', self.zeile("SELECT status FROM tutorial_films WHERE id=%s", fid)[0])
        self.api('/tutorials/api/film/', action='update', id=fid, status='Video ready')
        self.api('/tutorials/api/step/', action='update', id=sid, caption='x')
        self.assertEqual('Draft', self.zeile("SELECT status FROM tutorial_films WHERE id=%s", fid)[0])

    def test_liste_zeigt_laenge(self):
        fid = self.neuer_film()
        with connection.cursor() as c:
            c.execute("UPDATE tutorial_films SET video_seconds=72.4 WHERE id=%s", [fid])
        self.assertEqual('1:12', tv.film_list('sop')[0]['length'])


class TextToVoice(Basis):
    """Stage 2: the spoken text becomes a voice through OpenAI (mocked here)."""

    def schritt(self, script='Click Approve.'):
        fid = self.neuer_film()
        sid = self.api('/tutorials/api/step/', action='create', film_id=fid)[1]['id']
        self.api('/tutorials/api/step/', action='update', id=sid, script=script)
        return fid, sid

    def test_ohne_schluessel_klare_meldung(self):
        _, sid = self.schritt()
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            status, j = self.api('/tutorials/api/tts/', id=sid)
        self.assertEqual(400, status)
        self.assertIn('OPENAI_API_KEY', j['error'])

    def test_stimme_wird_erzeugt_und_gespeichert(self):
        fid, sid = self.schritt()
        self.api('/tutorials/api/film/', action='update', id=fid, voice='nova', lang='de')
        antwort = mock.Mock(status_code=200, content=b'ID3fake-mp3')
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), \
             mock.patch('requests.post', return_value=antwort) as post:
            status, j = self.api('/tutorials/api/tts/', id=sid)
        self.assertEqual(200, status, j)
        gesendet = post.call_args.kwargs['json']
        self.assertEqual(('gpt-4o-mini-tts', 'nova', 'Click Approve.', 'mp3'),
                         (gesendet['model'], gesendet['voice'], gesendet['input'], gesendet['response_format']))
        self.assertIn('Deutsch', gesendet['instructions'])
        self.assertEqual('Bearer sk-test', post.call_args.kwargs['headers']['Authorization'])
        self.assertIn(f'/sop/{fid}/voice/tts_{sid}_', j['nc_path'])
        self.assertTrue(j['nc_path'].endswith('.mp3'))
        self.assertEqual(j['nc_path'], self.zeile("SELECT audio_nc_path FROM tutorial_steps WHERE id=%s", sid)[0])
        self.assertEqual(200, self.client.get(j['url']).status_code)

    def test_ohne_text_keine_stimme(self):
        _, sid = self.schritt(script='')
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), mock.patch('requests.post') as post:
            status, _ = self.api('/tutorials/api/tts/', id=sid)
        self.assertEqual(400, status)
        post.assert_not_called()

    def test_fehler_von_openai_wird_gezeigt(self):
        _, sid = self.schritt()
        antwort = mock.Mock(status_code=401)
        antwort.json.return_value = {'error': {'message': 'Incorrect API key provided'}}
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-bad'}), \
             mock.patch('requests.post', return_value=antwort):
            status, j = self.api('/tutorials/api/tts/', id=sid)
        self.assertEqual(502, status)
        self.assertIn('Incorrect API key', j['error'])

    def test_unbekannte_stimme(self):
        fid = self.neuer_film()
        self.assertEqual(400, self.api('/tutorials/api/film/', action='update', id=fid, voice='robot')[0])

    def test_spalte_wird_nachgeruestet(self):
        with connection.cursor() as c:
            c.execute("ALTER TABLE tutorial_films DROP COLUMN voice")
        tv.ensure_tables.ungepuffert()
        fid = self.neuer_film()
        self.assertEqual('marin', tv.load_film(fid)['voice'])
