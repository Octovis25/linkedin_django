"""Step 1 of the Nextcloud refactor: the new client for controlled documents.

It may list, read and create - and nothing else. These tests make sure of
that: the root cannot be left, an existing name is never overwritten, and
there is no way to delete or move anything.

    python _tests/backend/lauf.py test_nextcloud_client
"""
import inspect

from django.test import SimpleTestCase

from core.nextcloud import (AlreadyExists, NextcloudClient, NextcloudError, NotConfigured,
                            NotFound, ParentMissing, PathNotAllowed, TooLarge)

from .fake_nextcloud import FAKE_PASSWORD, FAKE_URL, FAKE_USER, FakeNextcloud

ROOT = 'Octovis'


class ClientTest(SimpleTestCase):

    def setUp(self):
        self.nc = FakeNextcloud()
        self.nc.__enter__()
        self.addCleanup(self.nc.__exit__, None, None, None)
        self.addCleanup(lambda: self.assertEqual(self.nc.foreign, []))
        self.nc.add_folder(ROOT)
        self.log = []
        self.client = NextcloudClient(FAKE_URL, FAKE_USER, FAKE_PASSWORD, root=ROOT,
                                      on_call=lambda *a: self.log.append(a))


class Configuration(ClientTest):

    def test_own_environment_variables_not_the_apps(self):
        env = {'OCTOVIS_NC_URL': FAKE_URL, 'OCTOVIS_NC_USER': 'claude-service',
               'OCTOVIS_NC_APP_PASSWORD': 'x', 'NEXTCLOUD_URL': 'https://other.test',
               'NEXTCLOUD_USER': 'ortrud', 'NEXTCLOUD_APP_PASSWORD': 'y'}
        c = NextcloudClient.from_env(root=ROOT, environ=env)
        self.assertEqual((c.url, c.user), (FAKE_URL, 'claude-service'))

    def test_another_prefix_can_be_used(self):
        env = {'OCTOVAL_NC_URL': FAKE_URL, 'OCTOVAL_NC_USER': 'u', 'OCTOVAL_NC_APP_PASSWORD': 'p'}
        self.assertEqual(NextcloudClient.from_env('OCTOVAL_NC', environ=env).user, 'u')

    def test_missing_settings_are_refused(self):
        with self.assertRaises(NotConfigured):
            NextcloudClient.from_env(environ={})
        with self.assertRaises(NotConfigured):
            NextcloudClient('http://nc.test', 'u', 'p')          # no plain http

    def test_password_never_in_repr(self):
        c = NextcloudClient(FAKE_URL, 'u', 'very-secret', root=ROOT)
        self.assertNotIn('very-secret', repr(c))


class Paths(ClientTest):

    def test_paths_stay_inside_the_root(self):
        for bad in ['../x', 'a/../../x', '/Octovis/x', '..', 'a/./b', 'a\\b', 'a\x00b', 'a\nb']:
            with self.assertRaises(PathNotAllowed, msg=bad):
                self.client.full_path(bad)
        self.assertEqual(self.client.full_path('Policies/a.md'), 'Octovis/Policies/a.md')
        self.assertEqual(self.client.full_path(''), 'Octovis')

    def test_a_refused_path_sends_nothing(self):
        for call in (lambda: self.client.list_folder('../'),
                     lambda: self.client.read_file('../secret.txt'),
                     lambda: self.client.create_file('../x.md', b'x'),
                     lambda: self.client.create_folder('a/../../b')):
            with self.assertRaises(PathNotAllowed):
                call()
        self.assertEqual(self.nc.calls, [])

    def test_listing_never_shows_anything_outside_the_root(self):
        self.nc.add_file('Marketing_and_Design/secret.png')
        self.nc.add_file(ROOT + '/a.md')
        self.assertEqual([e.name for e in self.client.list_folder('')], ['a.md'])


class Reading(ClientTest):

    def test_list_folder(self):
        self.nc.add_file(ROOT + '/SOP/b.docx', b'12345', 'application/vnd.openxmlformats')
        self.nc.add_file(ROOT + '/SOP/a.md', b'#', 'text/markdown')
        self.nc.add_folder(ROOT + '/SOP/Archive')
        entries = self.client.list_folder('SOP')
        self.assertEqual([(e.name, e.is_folder) for e in entries],
                         [('Archive', True), ('a.md', False), ('b.docx', False)])
        b = entries[2]
        self.assertEqual((b.path, b.size), ('SOP/b.docx', 5))
        self.assertTrue(b.modified.startswith('20'))
        self.assertEqual(self.nc.calls_of('PROPFIND')[0].headers['Depth'], '1')
        self.assertEqual(self.log[-1], ('list_folder', 'SOP', 'ok, 3 entries'))

    def test_read_file(self):
        self.nc.add_file(ROOT + '/a.md', b'hello')
        self.assertEqual(self.client.read_file('a.md'), b'hello')
        with self.assertRaises(NotFound):
            self.client.read_file('none.md')
        with self.assertRaises(PathNotAllowed):
            self.client.read_file('')

    def test_reading_a_huge_file_stops(self):
        self.nc.add_file(ROOT + '/big.bin', b'x' * 2000)
        small = NextcloudClient(FAKE_URL, FAKE_USER, FAKE_PASSWORD, root=ROOT, max_read=1000)
        with self.assertRaises(TooLarge):
            small.read_file('big.bin')

    def test_runs_as_the_configured_user_only(self):
        self.nc.add_file(ROOT + '/a.md')
        self.client.read_file('a.md')
        self.assertEqual({c.user for c in self.nc.calls}, {FAKE_USER})


class Creating(ClientTest):

    def test_create_file_sends_if_none_match(self):
        self.assertEqual(self.client.create_file('new.md', 'Hällo'), 'new.md')
        self.assertEqual(self.nc.files[ROOT + '/new.md'].content, 'Hällo'.encode('utf-8'))
        self.assertEqual(self.nc.calls_of('PUT')[0].headers['If-None-Match'], '*')

    def test_an_existing_name_is_never_overwritten(self):
        self.nc.add_file(ROOT + '/a.md', b'ORIGINAL')
        with self.assertRaises(AlreadyExists):
            self.client.create_file('a.md', b'NEW')
        self.assertEqual(self.nc.files[ROOT + '/a.md'].content, b'ORIGINAL')
        self.assertEqual(self.nc.overwritten, [])

    def test_a_server_that_replaces_anyway_is_reported_as_error(self):
        # If Nextcloud ever ignored If-None-Match it would answer 204 -
        # that must not be reported as success.
        self.nc.force[('PUT', ROOT + '/a.md')] = 204
        with self.assertRaises(NextcloudError):
            self.client.create_file('a.md', b'x')

    def test_missing_folder(self):
        with self.assertRaises(ParentMissing):
            self.client.create_file('no/such/folder.md', b'x')

    def test_create_folder_only_new(self):
        self.assertEqual(self.client.create_folder('Policies'), 'Policies')
        self.assertIn(ROOT + '/Policies', self.nc.folders)
        with self.assertRaises(AlreadyExists):
            self.client.create_folder('Policies')


class NothingElse(ClientTest):

    def test_there_is_no_method_to_change_or_remove(self):
        public = {n for n, _ in inspect.getmembers(NextcloudClient, inspect.isfunction)
                  if not n.startswith('_')}
        self.assertEqual(public, {'list_folder', 'read_file', 'create_folder', 'create_file',
                                  'full_path'})

    def test_no_dangerous_method_is_ever_sent(self):
        self.nc.add_file(ROOT + '/a.md')
        self.client.list_folder('')
        self.client.read_file('a.md')
        self.client.create_folder('F')
        self.client.create_file('F/b.md', b'x')
        for bad in ('x/../y', 'a.md'):
            try:
                self.client.create_file(bad, b'x')
            except NextcloudError:
                pass
        sent = set(self.nc.methods())
        self.assertTrue(sent <= {'PROPFIND', 'GET', 'MKCOL', 'PUT'}, sent)
        source = inspect.getsource(NextcloudClient)
        for word in ("'DELETE'", "'MOVE'", "'COPY'", "'PROPPATCH'", "'LOCK'"):
            self.assertNotIn(word, source)
