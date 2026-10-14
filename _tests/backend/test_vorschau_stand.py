"""The planner preview picture follows the FILE, not only the post row.

#130, 14.10.2026: the Studio saved the video again under the same name; the
card kept the old picture and the old date.

    python _tests/backend/lauf.py test_vorschau_stand
"""
from unittest import mock

from collectives.models import CollectivesConfig

from .basis import BackendTest
from .fake_nextcloud import FAKE_PASSWORD, FAKE_URL, FAKE_USER, FakeNextcloud

VIDEO = 'Marketing & Design/LinkedIn/Planner/Videos/Requirements.webm'


class FileVersion(BackendTest):

    def setUp(self):
        super().setUp()
        CollectivesConfig.objects.all().delete()
        CollectivesConfig.objects.create(pk=1, nextcloud_url=FAKE_URL, username=FAKE_USER,
                                         app_password=FAKE_PASSWORD, connected=True)
        self.nc = FakeNextcloud()
        self.nc.__enter__()
        self.addCleanup(self.nc.__exit__, None, None, None)

    def test_saving_the_same_name_again_changes_the_version(self):
        from planner.vorschau import _dateistand
        self.nc.add_file(VIDEO, b'old')
        first = _dateistand(VIDEO)
        self.assertTrue(first)
        self.nc.add_file(VIDEO, b'new')               # same path, new file
        self.assertNotEqual(_dateistand(VIDEO), first)
        self.assertEqual(self.nc.calls_of('PROPFIND')[0].headers['Depth'], '0')
        self.assertEqual(self.nc.foreign, [])

    def test_unknown_version_is_empty_not_an_error(self):
        from planner.vorschau import _dateistand
        self.assertEqual(_dateistand(VIDEO), '')      # 404 in the fake
        CollectivesConfig.objects.all().delete()
        self.assertEqual(_dateistand(VIDEO), '')      # no credentials at all


class PostMarkedChanged(BackendTest):

    def test_marks_the_post(self):
        from media_library.views import _post_geaendert
        c = mock.Mock()
        _post_geaendert(c, 130)
        sql, args = c.execute.call_args[0]
        self.assertIn('updated_at=CURRENT_TIMESTAMP', sql)
        self.assertEqual(args, [130])

    def test_a_database_without_the_column_is_no_problem(self):
        from media_library.views import _post_geaendert
        c = mock.Mock()
        c.execute.side_effect = RuntimeError('Unknown column updated_at')
        _post_geaendert(c, 130)                       # must not raise
