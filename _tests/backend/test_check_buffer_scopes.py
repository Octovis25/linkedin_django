"""check_buffer_scopes --insights: reads the stored insights key, never prints it,
and reports per channel whether Buffer returns numbers.

Buffer is replaced by a fake urlopen; the answers follow the shapes Buffer's
GraphQL API gave in June 2026 (scope error with grantedScopes, metrics list).
"""
import io
import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection

from linkedin_statistics.management.commands.check_buffer_scopes import Command
from django.test import TransactionTestCase

POSTING_KEY = 'posting-key-0123456789-abcdefghijklmnopqrs'
INSIGHTS_KEY = 'insights-key-9876543210-zyxwvutsrqponmlkji'
ORG_CH = 'chan-org'
PERSON_CH = 'chan-person'


class _Antwort:
    def __init__(self, status, daten):
        self.status = status
        self._roh = json.dumps(daten).encode('utf-8')

    def read(self):
        return self._roh

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _buffer_attrappe(modus, gesehen):
    """modus: 'ok' | 'ohne_scope' | 'abgelehnt'."""
    import urllib.error

    def urlopen(req, timeout=30):
        gesehen.append(req.get_header('Authorization'))
        frage = json.loads(req.data.decode('utf-8'))['query']
        if modus == 'abgelehnt':
            raise urllib.error.HTTPError(req.full_url, 401, 'Unauthorized', {},
                                         io.BytesIO(b'{"errors":[{"message":"invalid token"}]}'))
        if 'organizations' in frage:
            return _Antwort(200, {'data': {'account': {'organizations': [{'id': 'org1', 'name': 'My Organization'}]}}})
        if modus == 'ohne_scope':
            return _Antwort(200, {'errors': [{'message': 'Missing scope', 'extensions': {
                'grantedScopes': ['posts:read', 'posts:write', 'account:read']}}]})
        if 'PostsMetrics' not in frage:
            return _Antwort(200, {'data': {'posts': {'edges': [{'node': {'id': 'p0', 'metrics': [{'type': 'impressions'}]}}]}}})
        kanten = [
            {'node': {'id': 'p1', 'channelId': PERSON_CH, 'dueAt': '2026-10-30T08:00:00Z', 'status': 'sent',
                      'metrics': [{'name': 'Impressions', 'value': 69, 'unit': None},
                                  {'name': 'Reactions', 'value': 3, 'unit': None}]}},
            {'node': {'id': 'p2', 'channelId': PERSON_CH, 'dueAt': '2026-10-22T08:00:00Z', 'status': 'sent',
                      'metrics': []}},
            {'node': {'id': 'p3', 'channelId': ORG_CH, 'dueAt': '2026-10-27T08:00:00Z', 'status': 'sent',
                      'metrics': [{'name': 'Impressions', 'value': 41, 'unit': None}]}},
        ]
        return _Antwort(200, {'data': {'posts': {'edges': kanten}}})
    return urlopen


class CheckBufferScopesTest(TransactionTestCase):

    def setUp(self):
        u = User.objects.create_superuser('ortrud', 'o@example.com', 'x')
        with connection.cursor() as c:
            c.execute("DROP TABLE IF EXISTS planner_linkedin_tokens")
            c.execute("""CREATE TABLE planner_linkedin_tokens (
                id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL UNIQUE,
                buffer_token TEXT, buffer_insights_token TEXT,
                buffer_profile_id VARCHAR(100), buffer_profile_id_person VARCHAR(100))""")
            c.execute("""INSERT INTO planner_linkedin_tokens
                (user_id, buffer_token, buffer_insights_token, buffer_profile_id, buffer_profile_id_person)
                VALUES (%s, %s, %s, %s, %s)""", [u.id, POSTING_KEY, INSIGHTS_KEY, ORG_CH, PERSON_CH])

    def tearDown(self):
        with connection.cursor() as c:
            c.execute("DROP TABLE IF EXISTS planner_linkedin_tokens")

    def _lauf(self, modus, *args):
        gesehen = []
        aus, fehler = io.StringIO(), io.StringIO()
        with mock.patch('urllib.request.urlopen', _buffer_attrappe(modus, gesehen)):
            call_command(Command(), *args, stdout=aus, stderr=fehler)
        return aus.getvalue() + fehler.getvalue(), gesehen

    def test_insights_uses_insights_key_and_never_prints_it(self):
        text, gesehen = self._lauf('ok', '--insights')
        self.assertTrue(gesehen)
        self.assertTrue(all(h == f'Bearer {INSIGHTS_KEY}' for h in gesehen))
        self.assertNotIn(INSIGHTS_KEY, text)
        self.assertNotIn(POSTING_KEY, text)
        self.assertIn('insights key', text)

    def test_insights_reports_numbers_per_channel(self):
        text, _ = self._lauf('ok', '--insights')
        self.assertIn('insights:read is there', text)
        self.assertIn('personal profile: 2 posts, 1 with numbers', text)
        self.assertIn('company page: 1 posts, 1 with numbers', text)
        self.assertIn('Impressions 69', text)

    def test_insights_with_posting_key(self):
        text, gesehen = self._lauf('ok', '--insights', '--posting')
        self.assertTrue(all(h == f'Bearer {POSTING_KEY}' for h in gesehen))
        self.assertIn('posting key', text)
        self.assertIn('personal profile: 2 posts, 1 with numbers', text)
        self.assertNotIn(POSTING_KEY, text)

    def test_without_flag_uses_posting_key(self):
        text, gesehen = self._lauf('ok')
        self.assertTrue(all(h == f'Bearer {POSTING_KEY}' for h in gesehen))
        self.assertNotIn('personal profile', text)   # no per-channel part

    def test_missing_scope_is_reported(self):
        text, _ = self._lauf('ohne_scope', '--insights')
        self.assertIn('insights:read is MISSING', text)
        self.assertIn('posts:read', text)
        self.assertNotIn(INSIGHTS_KEY, text)

    def test_rejected_key_is_reported(self):
        text, _ = self._lauf('abgelehnt', '--insights')
        self.assertIn('Buffer does not accept this key (HTTP 401)', text)
        self.assertNotIn(INSIGHTS_KEY, text)

    def test_no_insights_key_stored(self):
        with connection.cursor() as c:
            c.execute("UPDATE planner_linkedin_tokens SET buffer_insights_token=NULL")
        text, gesehen = self._lauf('ok', '--insights')
        self.assertEqual(gesehen, [])
        self.assertIn('No insights key', text)
