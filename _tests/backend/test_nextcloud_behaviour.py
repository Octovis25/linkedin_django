"""Today's Nextcloud behaviour, written down before anything is refactored.

These are characterisation tests: they do not say what the app *should* do,
they record what it *does* on 14.10.2026 - including the parts that are about
to change (silent overwrites, three different credential functions). When a
call site is moved to the new client later, the test for it must stay green,
or the change in behaviour must be deliberate and the test changed with it.

Nextcloud is replaced by FakeNextcloud (fake_nextcloud.py). No request leaves
the process; a request to any other host fails the test.

    python _tests/backend/lauf.py test_nextcloud_behaviour
"""
import io
import json
import os
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, override_settings

from collectives.models import CollectivesConfig

from .basis import BackendTest
from .fake_nextcloud import FAKE_PASSWORD, FAKE_URL, FAKE_USER, FakeNextcloud, ForeignHostError

PLANNER_IMAGES = 'Marketing & Design/LinkedIn/Planner/Images'
PLANNER_VIDEOS = 'Marketing & Design/LinkedIn/Planner/Videos'
STUDIO_OUTPUT = 'Marketing & Design/Octotrial_Assets/Studio_Work/Output'
NC_ENV = ('NEXTCLOUD_URL', 'NEXTCLOUD_USER', 'NEXTCLOUD_APP_PASSWORD')


def _no_nc_env():
    """os.environ without the three Nextcloud variables."""
    return {k: v for k, v in os.environ.items() if k not in NC_ENV}


class NextcloudTest(BackendTest):
    """Fake Nextcloud on, database credentials pointing at it, no env vars."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The views run the schema upkeep; its CREATE/ALTER would commit the
        # test's transaction in MySQL. setUpClass has just built the schema.
        from media_library import views
        views._SCHEMA_GEPRUEFT.update({'_ensure_table', '_ensure_studio_tables',
                                       '_ensure_video_template_table',
                                       '_ensure_brand_colors_table'})

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, _no_nc_env(), clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.set_db_credentials(FAKE_URL, FAKE_USER, FAKE_PASSWORD)
        self.nc = FakeNextcloud()
        self.nc.__enter__()
        self.addCleanup(self.nc.__exit__, None, None, None)
        self.addCleanup(self._no_foreign_requests)

    def _no_foreign_requests(self):
        self.assertEqual(self.nc.foreign, [], 'a request went somewhere other than the fake')

    def set_db_credentials(self, url, user, password, pk=1, connected=True):
        CollectivesConfig.objects.all().delete()
        CollectivesConfig.objects.create(pk=pk, nextcloud_url=url, username=user,
                                         app_password=password, connected=connected)

    def no_credentials_anywhere(self):
        CollectivesConfig.objects.all().delete()


# ---------------------------------------------------------------------------
# 1 · Credentials
# ---------------------------------------------------------------------------
class CredentialTests(NextcloudTest):

    def creds(self):
        from posts_posted.nc_storage import _get_nc_credentials
        return _get_nc_credentials()

    def core_creds(self):
        from core.nc_storage import _get_nc_credentials
        return _get_nc_credentials()

    def test_database_wins_when_all_three_fields_are_filled(self):
        with mock.patch.dict(os.environ, {'NEXTCLOUD_URL': 'https://env.test',
                                          'NEXTCLOUD_USER': 'env-user',
                                          'NEXTCLOUD_APP_PASSWORD': 'env-pw'}):
            self.assertEqual(self.creds(), (FAKE_URL, FAKE_USER, FAKE_PASSWORD))
            self.assertEqual(self.core_creds(), (FAKE_URL, FAKE_USER, FAKE_PASSWORD))

    def test_one_empty_database_field_falls_back_to_env_for_all_three(self):
        self.set_db_credentials(FAKE_URL, FAKE_USER, '')
        with mock.patch.dict(os.environ, {'NEXTCLOUD_URL': 'https://env.test',
                                          'NEXTCLOUD_USER': 'env-user',
                                          'NEXTCLOUD_APP_PASSWORD': 'env-pw'}):
            self.assertEqual(self.creds(), ('https://env.test', 'env-user', 'env-pw'))
            self.assertEqual(self.core_creds(), ('https://env.test', 'env-user', 'env-pw'))

    def test_fresh_database_creates_an_empty_row_and_uses_env(self):
        self.no_credentials_anywhere()
        with mock.patch.dict(os.environ, {'NEXTCLOUD_URL': ' https://env.test ',
                                          'NEXTCLOUD_USER': 'env-user',
                                          'NEXTCLOUD_APP_PASSWORD': 'env-pw'}):
            self.assertEqual(self.creds(), ('https://env.test', 'env-user', 'env-pw'))
        # get_config() is a get_or_create(pk=1): the empty row now exists.
        self.assertTrue(CollectivesConfig.objects.filter(pk=1, username='').exists())

    def test_nothing_configured_gives_three_empty_strings(self):
        self.no_credentials_anywhere()
        self.assertEqual(self.creds(), ('', '', ''))
        self.assertEqual(self.core_creds(), ('', '', ''))

    def test_posts_posted_strips_whitespace_core_does_not(self):
        self.set_db_credentials(' %s ' % FAKE_URL, FAKE_USER, FAKE_PASSWORD)
        self.assertEqual(self.creds()[0], FAKE_URL)
        self.assertEqual(self.core_creds()[0], ' %s ' % FAKE_URL)

    def test_core_reads_the_first_row_posts_posted_only_row_one(self):
        # Today's divergence: a config stored under another id is seen by
        # core (objects.first()) but not by posts_posted (get_or_create(pk=1)).
        self.set_db_credentials(FAKE_URL, FAKE_USER, FAKE_PASSWORD, pk=5)
        self.assertEqual(self.core_creds(), (FAKE_URL, FAKE_USER, FAKE_PASSWORD))
        self.assertEqual(self.creds(), ('', '', ''))

    def test_collectives_page_reads_the_database_only_never_env(self):
        from collectives.views import test_connection
        self.no_credentials_anywhere()
        with mock.patch.dict(os.environ, {'NEXTCLOUD_URL': FAKE_URL,
                                          'NEXTCLOUD_USER': FAKE_USER,
                                          'NEXTCLOUD_APP_PASSWORD': FAKE_PASSWORD}):
            req = RequestFactory().post('/collectives/test/')
            req.user = self.benutzer
            data = json.loads(test_connection(req).content)
        self.assertFalse(data['success'])
        self.assertEqual(data['message'], 'Please fill in all fields')
        self.assertEqual(self.nc.calls, [])

    def test_every_call_runs_as_the_one_configured_user(self):
        from posts_posted.nc_storage import download_image_from_nextcloud
        self.nc.add_file(PLANNER_IMAGES + '/a.png', b'png')
        download_image_from_nextcloud(PLANNER_IMAGES + '/a.png')
        self.assertEqual([c.user for c in self.nc.calls], [FAKE_USER])

    def test_without_credentials_no_function_sends_a_request(self):
        from posts_posted import nc_storage as pp
        from core import nc_storage as core
        from planner import views as pv
        from media_library import views as mv
        from assets import views as av
        from assets.nc_folders import ensure_nc_folders
        self.no_credentials_anywhere()
        f = SimpleUploadedFile('a.png', b'png', content_type='image/png')
        self.assertIsNone(pp.upload_image_to_nextcloud(f, 'a.png'))
        self.assertEqual(pp.download_image_from_nextcloud('x'), (None, None))
        self.assertEqual(pp.stream_from_nextcloud('x')[0], None)
        self.assertEqual(pp.delete_from_nextcloud_detail('x')[0], False)
        with tempfile.NamedTemporaryFile(suffix='.xlsx') as t:
            self.assertFalse(core.upload_excel_to_nextcloud(t.name, 'content'))
        self.assertIsNone(pv._nc_move('a', 'b'))
        with self.assertRaises(Exception):
            pv._upload_video_to_nextcloud(SimpleUploadedFile('v.mp4', b'v'), 1)
        self.assertIsNone(mv._nc_upload(b'x', 'a/b.png'))
        self.assertEqual(mv._nc_dateien('a'), [])
        self.assertEqual(av._nc_list_folder('Icons'), [])
        self.assertFalse(av._nc_upload_file(io.BytesIO(b'x'), 'a/b.png'))
        self.assertEqual(ensure_nc_folders(), (False, 'NC credentials missing'))
        self.assertEqual(self.nc.calls, [])


# ---------------------------------------------------------------------------
# 2 · posts_posted/nc_storage.py - the shared helpers
# ---------------------------------------------------------------------------
class PostsPostedStorageTests(NextcloudTest):

    def setUp(self):
        super().setUp()
        self.nc.add_folder(PLANNER_IMAGES)
        self.nc.add_folder(PLANNER_VIDEOS)

    def test_image_upload_puts_into_planner_images(self):
        from posts_posted.nc_storage import upload_image_to_nextcloud
        f = SimpleUploadedFile('my post.png', b'PNG', content_type='image/png')
        path = upload_image_to_nextcloud(f, 'some/dir/my post.png')
        self.assertEqual(path, PLANNER_IMAGES + '/my_post.png')   # basename, spaces -> _
        self.assertEqual(self.nc.files[path].content, b'PNG')
        call = self.nc.calls_of('PUT')[0]
        self.assertEqual(call.headers['Content-Type'], 'image/png')
        self.assertNotIn('If-None-Match', call.headers)

    def test_image_upload_overwrites_an_existing_file_silently(self):
        from posts_posted.nc_storage import upload_image_to_nextcloud
        self.nc.add_file(PLANNER_IMAGES + '/x.png', b'OLD')
        path = upload_image_to_nextcloud(SimpleUploadedFile('x.png', b'NEW'), 'x.png')
        self.assertEqual(path, PLANNER_IMAGES + '/x.png')
        self.assertEqual(self.nc.files[path].content, b'NEW')
        self.assertEqual(self.nc.overwritten, [path])

    def test_upload_does_not_create_the_folder(self):
        from posts_posted.nc_storage import _upload_file_to_nextcloud
        path = _upload_file_to_nextcloud(io.BytesIO(b'x'), 'a.png', 'Missing/Folder')
        self.assertIsNone(path)                       # 409 from Nextcloud
        self.assertEqual(self.nc.methods(), ['PUT'])  # no MKCOL tried

    def test_video_upload_puts_into_planner_videos(self):
        from posts_posted.nc_storage import upload_video_to_nextcloud
        f = SimpleUploadedFile('clip.mp4', b'MP4', content_type='video/mp4')
        self.assertEqual(upload_video_to_nextcloud(f, 'clip.mp4'), PLANNER_VIDEOS + '/clip.mp4')

    def test_trailing_slash_in_url_and_quoting(self):
        from posts_posted.nc_storage import upload_image_to_nextcloud
        self.set_db_credentials(FAKE_URL + '/', FAKE_USER, FAKE_PASSWORD)
        with mock.patch.object(self.nc, '_handle', wraps=self.nc._handle) as h:
            upload_image_to_nextcloud(SimpleUploadedFile('a.png', b'x'), 'a.png')
        url = h.call_args[0][1]
        self.assertEqual(url, FAKE_URL + '/remote.php/dav/files/' + FAKE_USER
                         + '/Marketing%20%26%20Design/LinkedIn/Planner/Images/a.png')

    def test_download_returns_bytes_and_type(self):
        from posts_posted.nc_storage import download_image_from_nextcloud
        self.nc.add_file(PLANNER_IMAGES + '/a.png', b'PNG', 'image/png')
        self.assertEqual(download_image_from_nextcloud(PLANNER_IMAGES + '/a.png'),
                         (b'PNG', 'image/png'))
        self.assertEqual(download_image_from_nextcloud(PLANNER_IMAGES + '/none.png'),
                         (None, None))

    def test_stream_passes_range_through(self):
        from posts_posted.nc_storage import stream_from_nextcloud
        self.nc.add_file(PLANNER_VIDEOS + '/v.mp4', b'0123456789', 'video/mp4')
        r, reason = stream_from_nextcloud(PLANNER_VIDEOS + '/v.mp4', 'bytes=2-5')
        self.assertEqual(reason, '')
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(b''.join(r.iter_content(3)), b'2345')
        self.assertEqual(self.nc.calls[-1].headers['Range'], 'bytes=2-5')

    def test_stream_of_a_missing_file_says_why(self):
        from posts_posted.nc_storage import stream_from_nextcloud
        self.assertEqual(stream_from_nextcloud(PLANNER_VIDEOS + '/x.mp4'),
                         (None, 'Nextcloud answered 404'))

    def test_delete_reasons(self):
        from posts_posted.nc_storage import delete_from_nextcloud_detail, delete_image_from_nextcloud
        p = PLANNER_IMAGES + '/a.png'
        self.nc.add_file(p)
        self.assertEqual(delete_from_nextcloud_detail(p), (True, ''))
        self.assertNotIn(p, self.nc.files)
        self.assertEqual(delete_from_nextcloud_detail(p), (True, ''))      # 404 counts as gone
        self.nc.force[('DELETE', p)] = 423
        ok, reason = delete_from_nextcloud_detail(p)
        self.assertFalse(ok)
        self.assertIn('locked', reason)
        self.nc.force[('DELETE', p)] = 401
        self.assertIn('app password', delete_from_nextcloud_detail(p)[1])
        self.nc.force[('DELETE', p)] = 500
        self.assertEqual(delete_from_nextcloud_detail(p), (False, 'Nextcloud answered 500'))
        self.assertFalse(delete_image_from_nextcloud(p))

    def test_delete_removes_a_whole_folder_when_given_one(self):
        # Nothing stops a folder path today - DELETE on WebDAV is recursive.
        from posts_posted.nc_storage import delete_from_nextcloud_detail
        self.nc.add_file(PLANNER_IMAGES + '/a.png')
        self.assertEqual(delete_from_nextcloud_detail(PLANNER_IMAGES), (True, ''))
        self.assertNotIn(PLANNER_IMAGES + '/a.png', self.nc.files)


# ---------------------------------------------------------------------------
# 3 · core/nc_storage.py - statistics Excel upload
# ---------------------------------------------------------------------------
class CoreExcelUploadTests(NextcloudTest):

    def upload(self, file_type, content=b'XLSX'):
        from core.nc_storage import upload_excel_to_nextcloud
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'export.xlsx')
            with open(p, 'wb') as f:
                f.write(content)
            return upload_excel_to_nextcloud(p, file_type)

    def test_creates_every_folder_level_then_puts(self):
        self.assertTrue(self.upload('followers'))
        target = 'Marketing & Design/LinkedIn/Statistics/data/followers'
        self.assertEqual([c.path for c in self.nc.calls_of('MKCOL')],
                         ['Marketing & Design', 'Marketing & Design/LinkedIn',
                          'Marketing & Design/LinkedIn/Statistics',
                          'Marketing & Design/LinkedIn/Statistics/data', target])
        self.assertEqual(self.nc.files[target + '/export.xlsx'].content, b'XLSX')

    def test_existing_folders_are_fine_and_file_is_overwritten(self):
        self.upload('content', b'OLD')
        self.nc.calls.clear()
        self.assertTrue(self.upload('posts', b'NEW'))    # 'posts' maps to content/
        p = 'Marketing & Design/LinkedIn/Statistics/data/content/export.xlsx'
        self.assertEqual(self.nc.files[p].content, b'NEW')
        self.assertEqual(self.nc.overwritten, [p])

    def test_unknown_type_goes_to_content(self):
        self.upload('something-else')
        self.assertIn('Marketing & Design/LinkedIn/Statistics/data/content/export.xlsx',
                      self.nc.files)

    def test_failed_put_returns_false(self):
        self.nc.force[('PUT', 'Marketing & Design/LinkedIn/Statistics/data/content/export.xlsx')] = 507
        self.assertFalse(self.upload('content'))


# ---------------------------------------------------------------------------
# 4 · planner/views.py
# ---------------------------------------------------------------------------
class PlannerNextcloudTests(NextcloudTest):

    def setUp(self):
        super().setUp()
        self.nc.add_folder(PLANNER_VIDEOS)
        self.nc.add_folder(PLANNER_IMAGES)
        self.nc.add_folder(STUDIO_OUTPUT)

    def test_video_upload_gets_a_timestamped_name(self):
        from planner.views import _upload_video_to_nextcloud
        with mock.patch('time.time', return_value=1790000000):
            path = _upload_video_to_nextcloud(
                SimpleUploadedFile('Mein Clip.webm', b'WEBM', content_type='video/webm'), 42)
        self.assertEqual(path, PLANNER_VIDEOS + '/video_42_1790000000.webm')
        self.assertEqual(self.nc.files[path].content_type, 'video/webm')

    def test_video_upload_raises_on_refusal(self):
        from planner.views import _upload_video_to_nextcloud
        self.nc.force[('PUT', PLANNER_VIDEOS + '/video_1_1.mp4')] = 507
        with mock.patch('time.time', return_value=1):
            with self.assertRaisesRegex(Exception, 'NC HTTP 507'):
                _upload_video_to_nextcloud(SimpleUploadedFile('a.mp4', b'x'), 1)

    def test_move_overwrites_by_default(self):
        from planner.views import _nc_move
        self.nc.add_file(STUDIO_OUTPUT + '/a.png', b'NEW')
        self.nc.add_file(PLANNER_IMAGES + '/a.png', b'OLD')
        self.assertEqual(_nc_move(STUDIO_OUTPUT + '/a.png', PLANNER_IMAGES + '/a.png'),
                         PLANNER_IMAGES + '/a.png')
        self.assertEqual(self.nc.files[PLANNER_IMAGES + '/a.png'].content, b'NEW')
        call = self.nc.calls_of('MOVE')[0]
        self.assertEqual(call.headers['Overwrite'], 'T')
        self.assertTrue(call.headers['Destination'].startswith(FAKE_URL + '/remote.php/dav/files/'))

    def test_move_without_overwrite_reports_a_taken_name_as_false(self):
        from planner.views import _nc_move
        self.nc.add_file(STUDIO_OUTPUT + '/a.png', b'A')
        self.nc.add_file(PLANNER_IMAGES + '/a.png', b'B')
        self.assertIs(_nc_move(STUDIO_OUTPUT + '/a.png', PLANNER_IMAGES + '/a.png',
                               overwrite=False), False)
        self.assertEqual(self.nc.files[PLANNER_IMAGES + '/a.png'].content, b'B')
        self.assertIn(STUDIO_OUTPUT + '/a.png', self.nc.files)

    def test_move_of_a_missing_file_is_none(self):
        from planner.views import _nc_move
        self.assertIsNone(_nc_move(STUDIO_OUTPUT + '/none.png', PLANNER_IMAGES + '/none.png'))

    def test_replaced_medium_goes_back_to_outputs_under_a_free_name(self):
        from planner.views import _move_replaced_media_to_outputs
        self.nc.add_file(PLANNER_VIDEOS + '/clip.mp4', b'V')
        self.nc.add_file(STUDIO_OUTPUT + '/clip.mp4', b'other')
        self.nc.add_file(STUDIO_OUTPUT + '/clip_2.mp4', b'other2')
        self.assertEqual(_move_replaced_media_to_outputs(PLANNER_VIDEOS + '/clip.mp4'),
                         STUDIO_OUTPUT + '/clip_3.mp4')
        self.assertEqual(self.nc.files[STUDIO_OUTPUT + '/clip.mp4'].content, b'other')
        self.assertEqual(self.nc.overwritten, [])

    def test_delete_and_empty_path(self):
        from planner.views import _nc_delete
        self.assertFalse(_nc_delete(''))
        self.assertEqual(self.nc.calls, [])
        self.nc.add_file(PLANNER_VIDEOS + '/v.mp4')
        self.assertTrue(_nc_delete(PLANNER_VIDEOS + '/v.mp4'))
        self.assertNotIn(PLANNER_VIDEOS + '/v.mp4', self.nc.files)

    def test_list_folder_media_filters_and_sorts_newest_name_first(self):
        from planner.views import _list_nextcloud_videos
        for n in ('video_1_100.mp4', 'video_2_300.webm', 'notes.txt', 'video_3_200.mov'):
            self.nc.add_file(PLANNER_VIDEOS + '/' + n)
        self.nc.add_folder(PLANNER_VIDEOS + '/sub.mp4')
        names = [v['filename'] for v in _list_nextcloud_videos()]
        # Today a FOLDER whose name ends in .mp4 is listed as a video too:
        # only the name is checked, not the resource type.
        self.assertEqual(names, ['video_3_200.mov', 'video_2_300.webm', 'video_1_100.mp4',
                                 'sub.mp4'])

    def test_temp_video_copy_for_buffer(self):
        from planner.views import _prepare_temp_video, _ensure_media_columns
        _ensure_media_columns()
        with connection.cursor() as c:
            c.execute("INSERT INTO planner_posts (title, video_nc_path) VALUES ('t', %s)",
                      ['video_9_1.mp4'])            # an old short name
            post_id = c.lastrowid
        self.nc.add_file(PLANNER_VIDEOS + '/video_9_1.mp4', b'VIDEO')
        with tempfile.TemporaryDirectory() as d, override_settings(BUFFER_VIDEO_TEMP_DIR=d):
            local = _prepare_temp_video(post_id)
            with open(local, 'rb') as f:
                self.assertEqual(f.read(), b'VIDEO')
            self.assertEqual(os.path.basename(local), 'post_%d_video_9_1.mp4' % post_id)
            # a second call uses the local copy, no new download
            n = len(self.nc.calls)
            _prepare_temp_video(post_id)
            self.assertEqual(len(self.nc.calls), n)


# ---------------------------------------------------------------------------
# 5 · media_library/views.py (Studio, library)
# ---------------------------------------------------------------------------
class MediaLibraryNextcloudTests(NextcloudTest):

    def test_ensure_folder_sends_mkcol_per_level_and_ignores_existing(self):
        from media_library.views import _nc_ensure_folder
        self.nc.add_folder('Marketing & Design')
        _nc_ensure_folder(FAKE_URL, FAKE_USER, FAKE_PASSWORD, '/Marketing & Design/New/Deep/')
        self.assertEqual([c.path for c in self.nc.calls_of('MKCOL')],
                         ['Marketing & Design', 'Marketing & Design/New',
                          'Marketing & Design/New/Deep'])
        self.assertIn('Marketing & Design/New/Deep', self.nc.folders)

    def test_upload_creates_parents_and_overwrites_silently(self):
        from media_library.views import _nc_upload
        p = STUDIO_OUTPUT + '/Images/Header.png'
        self.assertEqual(_nc_upload(b'ONE', p), p)
        self.assertEqual(_nc_upload(b'TWO', p, 'image/png'), p)
        self.assertEqual(self.nc.files[p].content, b'TWO')
        self.assertEqual(self.nc.overwritten, [p])
        self.assertTrue(all('If-None-Match' not in c.headers for c in self.nc.calls_of('PUT')))

    def test_upload_failure_returns_none(self):
        from media_library.views import _nc_upload
        p = STUDIO_OUTPUT + '/Images/x.png'
        self.nc.force[('PUT', p)] = 507
        self.assertIsNone(_nc_upload(b'x', p))

    def test_delete_old_files_does_nothing_today(self):
        # Found while writing these tests: media_library/views.py never imports
        # `requests` at module level, so the PROPFIND in _nc_delete_old_files
        # raises NameError, which its own `except Exception: pass` swallows.
        # The function has deleted nothing in production. Recorded as is; the
        # intended rule (prefix + 10-digit timestamp + preview|snap|obj|fab)
        # gets its own test when the function is moved.
        from media_library.views import _nc_delete_old_files
        folder = STUDIO_OUTPUT + '/Images'
        names = ['Header.png', 'Header_1790000000_preview.png',
                 '_data/Header_1790000002_obj.json']
        for n in names:
            self.nc.add_file(folder + '/' + n)
        _nc_delete_old_files(folder, 'Header')
        self.assertEqual(self.nc.calls, [])
        for n in names:
            self.assertIn(folder + '/' + n, self.nc.files)

    def test_list_one_folder_skips_helpers_dotfiles_and_subfolders(self):
        from media_library.views import _nc_dateien
        folder = STUDIO_OUTPUT + '/Images'
        for n in ('b.png', 'a.jpg', '.hidden.png', 'x_preview.png', 'notes.txt'):
            self.nc.add_file(folder + '/' + n)
        self.nc.add_folder(folder + '/Sub')
        names = sorted(e['name'] for e in _nc_dateien(folder))
        self.assertEqual(names, ['a.jpg', 'b.png', 'notes.txt'])
        self.assertEqual(sorted(e['name'] for e in _nc_dateien(folder, {'.png'})), ['b.png'])
        self.assertEqual(_nc_dateien(folder + '/Missing'), [])        # 404 -> []
        self.assertEqual(_nc_dateien('a/../b'), [])

    def test_library_upload_puts_to_nextcloud_or_keeps_it_local(self):
        from media_library import views as mv
        mv._ensure_table()
        self.nc.add_folder(mv.NC_LIBRARY_FOLDER)
        with tempfile.TemporaryDirectory() as d, override_settings(MEDIA_ROOT=d), \
                mock.patch('time.time', return_value=1790000000):
            self.client.post('/library/upload/', {
                'image': SimpleUploadedFile('p.png', b'PNG', content_type='image/png'),
                'title': 'one'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            nc_path = mv.NC_LIBRARY_FOLDER + '/lib_1790000000.png'
            self.assertEqual(self.nc.files[nc_path].content, b'PNG')
            self.assertEqual(self.zeile(
                "SELECT nc_path FROM media_library_items WHERE title='one'")[0], nc_path)
            # Nextcloud refuses -> the row points at the local copy
            self.nc.force[('PUT', mv.NC_LIBRARY_FOLDER + '/lib_1790000000.jpg')] = 500
            self.client.post('/library/upload/', {
                'image': SimpleUploadedFile('p.jpg', b'JPG', content_type='image/jpeg'),
                'title': 'two'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(self.zeile(
                "SELECT nc_path FROM media_library_items WHERE title='two'")[0],
                '__local__/lib_1790000000.jpg')

    def test_folder_create_makes_one_nextcloud_folder(self):
        from media_library import views as mv
        self.nc.add_folder(mv.NC_LIBRARY_FOLDER)
        r = self.client.post('/library/folder/create/', json.dumps({'name': 'Octos'}),
                             content_type='application/json')
        self.assertTrue(r.json()['ok'])
        self.assertEqual([c.path for c in self.nc.calls_of('MKCOL')],
                         [mv.NC_LIBRARY_FOLDER + '/Octos'])
        self.assertIn(mv.NC_LIBRARY_FOLDER + '/Octos', self.nc.folders)

    def test_studio_browse_lists_images_and_subfolders(self):
        from media_library import views as mv
        root = mv.NC_ASSETS_ROOT + '/Icons'
        self.nc.add_file(root + '/Octo_happy.png', b'x', 'image/png')
        self.nc.add_file(root + '/readme.txt')
        self.nc.add_folder(root + '/AI')
        self.nc.add_folder(root + '/_data')
        r = self.client.get('/library/studio/api/nc-browse/', {'folder': 'Icons'}).json()
        self.assertEqual([i['nc_path'] for i in r['items']], [root + '/Octo_happy.png'])
        self.assertEqual(r['items'][0]['title'], 'Octo happy')
        self.assertEqual(r['subfolders'], [{'name': 'AI'}])
        self.assertEqual(self.nc.calls_of('PROPFIND')[0].headers['Depth'], '1')
        self.assertEqual(self.client.get('/library/studio/api/nc-browse/',
                                         {'folder': '../x'}).json()['error'], 'Invalid path')

    def test_studio_browse_all_retries_with_depth_one_on_507(self):
        from media_library import views as mv
        self.nc.add_folder(mv.NC_ASSETS_ROOT)
        real = self.nc._do_PROPFIND

        def once_too_big(path, url, body, headers, user):
            if headers.get('Depth') == 'infinity':
                return self.nc._response(507, url)
            return real(path, url, body, headers, user)
        with mock.patch.object(self.nc, '_do_PROPFIND', once_too_big):
            r = self.client.get('/library/studio/api/nc-browse/', {'folder': '__all__'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c.headers['Depth'] for c in self.nc.calls_of('PROPFIND')],
                         ['infinity', '1'])


# ---------------------------------------------------------------------------
# 6 · assets
# ---------------------------------------------------------------------------
class AssetsNextcloudTests(NextcloudTest):

    def setUp(self):
        super().setUp()
        from assets.nc_folders import NC_ASSETS_ROOT
        self.root = NC_ASSETS_ROOT
        self.nc.add_folder(self.root + '/Icons')

    def test_list_folder(self):
        from assets.views import _nc_list_folder
        self.nc.add_file(self.root + '/Icons/a b.png', b'12345', 'image/png')
        self.nc.add_folder(self.root + '/Icons/AI')
        items = sorted(_nc_list_folder('Icons'), key=lambda i: i['name'])
        self.assertEqual([(i['name'], i['is_dir'], i['size']) for i in items],
                         [('AI', True, 0), ('a b.png', False, 5)])
        self.assertEqual(items[1]['nc_path'], self.root + '/Icons/a b.png')
        self.assertEqual(_nc_list_folder('Missing'), [])

    def test_upload_overwrites_silently(self):
        from assets.views import _nc_upload_file
        p = self.root + '/Icons/a.png'
        self.assertTrue(_nc_upload_file(io.BytesIO(b'ONE'), p))
        self.assertTrue(_nc_upload_file(io.BytesIO(b'TWO'), p))
        self.assertEqual(self.nc.files[p].content, b'TWO')
        self.assertEqual(self.nc.overwritten, [p])

    def test_mkdir_treats_existing_as_success(self):
        from assets.views import _nc_mkdir
        self.assertTrue(_nc_mkdir(self.root + '/Icons/New'))
        self.assertTrue(_nc_mkdir(self.root + '/Icons/New'))           # 405
        self.assertFalse(_nc_mkdir(self.root + '/No/Parent'))          # 409

    def test_delete_and_move(self):
        from assets.views import _nc_delete, _nc_move
        a, b = self.root + '/Icons/a.png', self.root + '/Icons/b.png'
        self.nc.add_file(a, b'A')
        self.nc.add_file(b, b'B')
        self.assertFalse(_nc_move(a, b))                    # Overwrite: F -> 412
        self.assertEqual(self.nc.files[b].content, b'B')
        self.assertTrue(_nc_move(a, self.root + '/Icons/c.png'))
        self.assertTrue(_nc_delete(b))
        self.assertTrue(_nc_delete(b))                      # 404 counts as success
        self.assertTrue(_nc_delete(self.root + '/Icons'))   # folders too, recursively
        self.assertNotIn(self.root + '/Icons/c.png', self.nc.files)

    def test_ensure_nc_folders_creates_the_tree(self):
        from assets.nc_folders import FOLDER_TREE, ensure_nc_folders
        self.nc.folders = {''}                   # an empty Nextcloud
        ok, info = ensure_nc_folders()
        self.assertFalse(ok)                     # 'Marketing & Design' itself is not created
        self.assertEqual(len(self.nc.calls_of('MKCOL')), 1 + len(FOLDER_TREE))
        self.nc.add_folder('Marketing & Design')
        self.nc.calls.clear()
        ok, info = ensure_nc_folders()
        self.assertTrue(ok, info)
        self.assertEqual(info['errors'], [])
        self.assertIn(self.root + '/Studio_Output/Video_Images', self.nc.folders)


# ---------------------------------------------------------------------------
# 7 · collectives
# ---------------------------------------------------------------------------
class CollectivesNextcloudTests(NextcloudTest):

    def call(self, view, method='get'):
        req = getattr(RequestFactory(), method)('/collectives/x/')
        req.user = self.benutzer
        return json.loads(view(req).content)

    def test_connection_test_sets_connected(self):
        from collectives.views import test_connection
        self.set_db_credentials(FAKE_URL, FAKE_USER, FAKE_PASSWORD, connected=False)
        data = self.call(test_connection, 'post')
        self.assertTrue(data['success'])
        self.assertEqual(self.nc.calls_of('PROPFIND')[0].headers['Depth'], '0')
        self.assertTrue(CollectivesConfig.objects.get(pk=1).connected)

    def test_get_pages_reads_markdown_pages_of_the_collective(self):
        from collectives.views import get_pages
        c = CollectivesConfig.objects.get(pk=1)
        c.kollektive_name = 'Marketing & Design'
        c.save()
        base = 'Kollektive/Marketing & Design'
        self.nc.add_file(base + '/Readme.md', b'# home', 'text/markdown')
        self.nc.add_file(base + '/Posts/Week 1.md', b'# w1', 'text/markdown')
        self.nc.add_file(base + '/Posts/.attachments/x.png')
        data = self.call(get_pages)
        self.assertTrue(data['success'])
        self.assertEqual(sorted(p['title'] for p in data['pages']), ['Readme', 'Week 1'])
        self.assertEqual(self.nc.calls_of('PROPFIND')[0].headers['Depth'], 'infinity')
        self.assertEqual(self.nc.calls_of('PROPFIND')[0].path, base)

    def test_get_pages_needs_connected_and_a_name(self):
        from collectives.views import get_pages
        self.set_db_credentials(FAKE_URL, FAKE_USER, FAKE_PASSWORD, connected=False)
        self.assertEqual(self.call(get_pages)['message'], 'Not connected')
        self.set_db_credentials(FAKE_URL, FAKE_USER, FAKE_PASSWORD, connected=True)
        self.assertEqual(self.call(get_pages)['message'], 'No collective configured')
        self.assertEqual(self.nc.calls, [])


# ---------------------------------------------------------------------------
# 8 · The fake itself
# ---------------------------------------------------------------------------
class FakeGuardTests(NextcloudTest):

    def test_a_foreign_host_fails_loudly(self):
        import requests
        with self.assertRaises(ForeignHostError):
            requests.get('https://nc.octotrial.com/remote.php/dav/files/x/a.png')
        self.nc.foreign.clear()      # expected here

    def test_create_only_header_is_honoured(self):
        # Not used by the app yet - the new client will rely on it.
        import requests
        self.nc.add_file('a.txt', b'OLD')
        url = FAKE_URL + '/remote.php/dav/files/%s/a.txt' % FAKE_USER
        r = requests.put(url, data=b'NEW', headers={'If-None-Match': '*'})
        self.assertEqual(r.status_code, 412)
        self.assertEqual(self.nc.files['a.txt'].content, b'OLD')
