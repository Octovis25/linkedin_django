"""The audit trail: what gets recorded, what never does, and who may look.

    python _tests/backend/lauf.py test_audit
"""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory

from audit import store
from audit.access import may_view
from audit.middleware import AuditTrailMiddleware

from .basis import BackendTest


class AuditTest(BackendTest):

    def setUp(self):
        super().setUp()
        with connection.cursor() as c:
            c.execute("DELETE FROM audit_log")
        self.owner = User.objects.create_superuser('ortrud', password='pruefwort')

    def rows(self):
        with connection.cursor() as c:
            c.execute("SELECT username, method, path, view, action, object_id, status, "
                      "times, details FROM audit_log ORDER BY id")
            names = [d[0] for d in c.description]
            out = [dict(zip(names, r)) for r in c.fetchall()]
        for r in out:
            r['details'] = json.loads(r['details'] or '{}')
        return out

    def run_middleware(self, request, status=200):
        def view(_request):
            # a view that parses its form, like the real ones do
            _request.POST, _request.FILES
            return mock.Mock(status_code=status)
        return AuditTrailMiddleware(view)(request)


class Recording(AuditTest):

    def test_a_change_is_recorded_with_user_object_and_fields(self):
        req = RequestFactory().post('/planner/api/video/127/', {'title': 'Octo', 'note': 'x'})
        req.user = self.benutzer
        with mock.patch('audit.middleware.view_of', return_value=('planner:video_api', {'post_id': 127})):
            self.run_middleware(req)
        r = self.rows()[0]
        self.assertEqual((r['username'], r['method'], r['view'], r['object_id'], r['status']),
                         ('pruefer', 'POST', 'planner:video_api', '127', 200))
        self.assertEqual(r['details']['title'], 'Octo')
        self.assertNotIn('note', r['details'])          # not on the list of kept fields

    def test_reads_are_not_recorded(self):
        self.client.get('/planner/all/')
        self.assertEqual(self.rows(), [])

    def test_anonymous_posts_are_not_recorded(self):
        req = RequestFactory().post('/planner/api/post/', {'action': 'create'})
        from django.contrib.auth.models import AnonymousUser
        req.user = AnonymousUser()
        self.run_middleware(req)
        self.assertEqual(self.rows(), [])

    def test_claude_api_is_recorded_without_a_user(self):
        req = RequestFactory().post('/api/claude/upload/', {'title': 'x'})
        from django.contrib.auth.models import AnonymousUser
        req.user = AnonymousUser()
        self.run_middleware(req)
        self.assertEqual(self.rows()[0]['username'], 'Claude API')

    def test_secrets_and_big_content_never_land_in_the_trail(self):
        body = json.dumps({'action': 'save', 'post_id': 5, 'password': 'geheim',
                           'api_key': 'sk-123', 'token': 'abc', 'canvas_json': 'A' * 5000})
        req = RequestFactory().post('/library/studio/api/post-draft/', body,
                                    content_type='application/json')
        req.user = self.benutzer
        AuditTrailMiddleware(lambda r: mock.Mock(status_code=200))(req)
        r = self.rows()[0]
        text = json.dumps(r['details'])
        for secret in ('geheim', 'sk-123', 'abc', 'AAAA'):
            self.assertNotIn(secret, text)
        self.assertEqual((r['action'], r['object_id']), ('save', '5'))

    def test_uploads_keep_name_and_size_only(self):
        req = RequestFactory().post('/planner/api/video/9/', {
            'video': SimpleUploadedFile('clip.webm', b'V' * 1234, content_type='video/webm')})
        req.user = self.benutzer
        self.run_middleware(req)
        files = self.rows()[0]['details']['files']
        self.assertEqual(files, [{'field': 'video', 'name': 'clip.webm', 'size': 1234}])

    def test_an_unparsed_upload_is_not_read_again(self):
        # The view never touched request.POST - the middleware must not either,
        # or a big video would be read into memory a second time.
        req = RequestFactory().post('/planner/api/video/9/', {
            'video': SimpleUploadedFile('clip.webm', b'V' * 10)})
        req.user = self.benutzer
        AuditTrailMiddleware(lambda r: mock.Mock(status_code=200))(req)
        self.assertFalse(hasattr(req, '_post'))
        self.assertNotIn('files', self.rows()[0]['details'])

    def test_failures_are_recorded_as_failures(self):
        req = RequestFactory().post('/planner/api/post/', {'action': 'delete', 'id': '3'})
        req.user = self.benutzer
        self.run_middleware(req, status=500)
        self.assertEqual(self.rows()[0]['status'], 500)

    def test_repeats_fold_into_one_line(self):
        for _ in range(3):
            req = RequestFactory().post('/library/studio/api/save/', {'title': 'Header'})
            req.user = self.benutzer
            self.run_middleware(req)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['times'], 3)

    def test_after_the_fold_window_a_new_line_starts(self):
        now = store.utcnow()
        store.write('pruefer', 'POST', '/x/', view='v', now=now)
        store.write('pruefer', 'POST', '/x/', view='v',
                    now=now + timedelta(seconds=store.FOLD_SECONDS + 1))
        self.assertEqual(len(self.rows()), 2)

    def test_login_and_failed_login_come_from_signals(self):
        from django.contrib.auth import authenticate
        authenticate(username='pruefer', password='wrong')
        self.client.login(username='pruefer', password='pruefwort')
        actions = [(r['username'], r['action']) for r in self.rows()]
        self.assertIn(('pruefer', 'login failed'), actions)
        self.assertIn(('pruefer', 'login'), actions)
        self.assertNotIn('wrong', json.dumps(self.rows()))

    def test_a_broken_database_does_not_break_the_request(self):
        req = RequestFactory().post('/planner/api/post/', {'action': 'create'})
        req.user = self.benutzer
        with mock.patch('audit.store.connection') as conn:
            conn.cursor.side_effect = RuntimeError('db gone')
            response = self.run_middleware(req)
        self.assertEqual(response.status_code, 200)


class Access(AuditTest):

    def test_only_the_owner_sees_the_page(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/audit/').status_code, 200)

    def test_another_superuser_does_not(self):
        self.client.force_login(self.admin)        # superuser 'chefin'
        self.assertEqual(self.client.get('/audit/').status_code, 404)

    def test_a_normal_user_does_not(self):
        self.assertEqual(self.client.get('/audit/').status_code, 404)

    def test_owner_must_also_be_superuser(self):
        self.owner.is_superuser = False
        self.assertFalse(may_view(self.owner))

    def test_viewers_come_from_the_environment(self):
        with mock.patch.dict('os.environ', {'AUDIT_TRAIL_VIEWERS': 'chefin'}):
            self.assertTrue(may_view(self.admin))
            self.assertFalse(may_view(self.owner))


class Page(AuditTest):

    def test_page_lists_rows_and_people(self):
        store.write('e.kirillova93', 'POST', '/planner/api/video/127/',
                    view='planner:video_api', object_id='127', status=200,
                    details={'title': 'Octo'})
        store.write('ortrud', 'POST', '/login/', view='auth:login', action='login', status=200)
        self.client.force_login(self.owner)
        html = self.client.get('/audit/').content.decode()
        self.assertIn('e.kirillova93', html)
        self.assertIn('#127', html)
        self.assertIn('planner · video api', html)
        self.assertIn('Signed in', html)

    def test_filters(self):
        store.write('a', 'POST', '/x/', view='v', object_id='1', status=200)
        store.write('b', 'POST', '/y/', view='w', object_id='2', status=200)
        self.client.force_login(self.owner)
        ctx = self.client.get('/audit/', {'user': 'a'}).context
        self.assertEqual([r['username'] for r in ctx['rows']], ['a'])
        ctx = self.client.get('/audit/', {'object': '#2'}).context
        self.assertEqual([r['object_id'] for r in ctx['rows']], ['2'])
