"""The move of the Nextcloud folder to "Marketing_and_Design" (26.10.2026).

The folder "Marketing & Design" went missing on 23.10.2026 and came back as a
transfer; Ortrud had it copied to a name without spaces. The code now names
the new folder, and core/nc_root.py brings the database along once: every
stored path - plain, URL-encoded or JSON-escaped - points to the new folder.
Post texts and the audit log stay as they were. An address from before the
move still reaches the file through the image proxy.
"""
from django.db import connection
from django.test import TransactionTestCase

from core import nc_root
from core.nc_root import NC_ROOT, nc_pfad, pfade_umstellen, text_umstellen

from .basis import BackendTest, schema_aufbauen

ALT = 'Marketing & Design/LinkedIn/Planner/Videos/clip.webm'
NEU = 'Marketing_and_Design/LinkedIn/Planner/Videos/clip.webm'


class Pfad(TransactionTestCase):

    def test_old_path_becomes_new(self):
        self.assertEqual(nc_pfad(ALT), NEU)
        self.assertEqual(nc_pfad('/' + ALT), '/' + NEU)
        self.assertEqual(nc_pfad('Marketing & Design'), NC_ROOT)

    def test_other_paths_stay(self):
        for p in (NEU, 'Programming/x.png', '__local__/studio/a.png', '', None,
                  'Marketing & Designer/x.png'):
            self.assertEqual(nc_pfad(p), p)

    def test_every_form_in_text(self):
        text = ('{"srcUrl":"/library/studio/nc-image/?p=Marketing%20%26%20Design/a.png",'
                '"b":"Marketing+%26+Design/b.png","c":"Marketing \\u0026 Design/c.png",'
                '"d":"Marketing & Design/d.png"}')
        neu = text_umstellen(text)
        self.assertNotIn('Marketing &', neu)
        self.assertNotIn('%26', neu)
        self.assertNotIn('u0026', neu)
        self.assertEqual(neu.count(NC_ROOT + '/'), 4)


class Datenbank(TransactionTestCase):

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            c.execute("DROP TABLE IF EXISTS app_once")
            for spalte in ("video_nc_path VARCHAR(512) NULL", "gif_nc_path VARCHAR(512) NULL"):
                try:
                    c.execute("ALTER TABLE planner_posts ADD COLUMN " + spalte)
                except Exception:
                    pass
            c.execute("""INSERT INTO planner_posts (title, content, comment, image, video_nc_path)
                         VALUES ('Marketing & Design review', 'We thank Marketing & Design.',
                                 'Marketing & Design team', %s, %s)""",
                      ['Marketing & Design/LinkedIn/Planner/Images/a.png', ALT])
            self.post = c.lastrowid
            entwurf = ('{"fabric":{"objects":[{"type":"image",'
                       '"src":"/library/studio/nc-image/?p=Marketing%20%26%20Design/Octotrial_Assets/x.png",'
                       '"srcUrl":"/library/studio/nc-image/?p=Marketing & Design/Octotrial_Assets/x.png"}]}}')
            c.execute("INSERT INTO studio_images (nc_path, title, canvas_json, post_id) VALUES (%s,%s,%s,%s)",
                      [ALT, 'clip', entwurf, self.post])
            self.entwurf = c.lastrowid
        from audit import store
        store.ensure_table(force=True)
        with connection.cursor() as c:
            c.execute("""INSERT INTO audit_log (at, last_at, path, details)
                         VALUES (NOW(), NOW(), %s, %s)""", ['/x/', 'moved ' + ALT])
            self.log = c.lastrowid

    def zeile(self, sql, werte):
        with connection.cursor() as c:
            c.execute(sql, werte)
            return c.fetchone()

    def test_paths_point_to_the_new_folder(self):
        with connection.cursor() as c:
            self.assertGreaterEqual(pfade_umstellen(c), 3)
        bild, video = self.zeile("SELECT image, video_nc_path FROM planner_posts WHERE id=%s", [self.post])
        self.assertEqual(bild, 'Marketing_and_Design/LinkedIn/Planner/Images/a.png')
        self.assertEqual(video, NEU)
        pfad, entwurf = self.zeile("SELECT nc_path, canvas_json FROM studio_images WHERE id=%s",
                                   [self.entwurf])
        self.assertEqual(pfad, NEU)
        self.assertNotIn('Marketing &', entwurf)
        self.assertNotIn('%26', entwurf)
        self.assertEqual(entwurf.count('?p=Marketing_and_Design/Octotrial_Assets/x.png'), 2)

    def test_words_and_audit_log_stay(self):
        with connection.cursor() as c:
            pfade_umstellen(c)
        titel, text, kommentar = self.zeile(
            "SELECT title, content, comment FROM planner_posts WHERE id=%s", [self.post])
        self.assertEqual((titel, text, kommentar),
                         ('Marketing & Design review', 'We thank Marketing & Design.',
                          'Marketing & Design team'))
        self.assertEqual(self.zeile("SELECT details FROM audit_log WHERE id=%s", [self.log])[0],
                         'moved ' + ALT)

    def test_runs_only_once(self):
        with connection.cursor() as c:
            self.assertIsNotNone(pfade_umstellen(c))
            c.execute("UPDATE planner_posts SET image=%s WHERE id=%s",
                      ['Marketing & Design/later.png', self.post])
            self.assertIsNone(pfade_umstellen(c))
        self.assertEqual(self.zeile("SELECT image FROM planner_posts WHERE id=%s", [self.post])[0],
                         'Marketing & Design/later.png')

    def test_middleware_does_it_on_the_first_request(self):
        from django.conf import settings
        from django.contrib.auth.models import User
        from django.test import override_settings
        nc_root._erledigt = False
        try:
            self.client.force_login(User.objects.create_superuser('um', password='um'))
            with override_settings(MIDDLEWARE=list(settings.MIDDLEWARE) + ['core.nc_root.NcRootMiddleware']):
                self.client.get('/planner/scheduled/')
        finally:
            nc_root._erledigt = True
        self.assertEqual(self.zeile("SELECT video_nc_path FROM planner_posts WHERE id=%s",
                                    [self.post])[0], NEU)


class AlteAdresse(BackendTest):
    """An address from before the move still reaches the file."""

    def test_proxy_finds_the_file_under_its_old_name(self):
        with self.wolke() as w:
            w.dateien[NEU] = b'\x1a\x45\xdf\xa3' + b'x' * 100
            antwort = self.client.get('/library/studio/nc-image/', {'p': ALT})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(b''.join(antwort.streaming_content if antwort.streaming else [antwort.content])[:4],
                         b'\x1a\x45\xdf\xa3')


class Einstellungen(TransactionTestCase):

    def test_the_live_app_runs_the_middleware(self):
        import os
        wurzel = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(wurzel, 'dashboard', 'settings.py'), encoding='utf-8') as f:
            self.assertIn('"core.nc_root.NcRootMiddleware"', f.read())
