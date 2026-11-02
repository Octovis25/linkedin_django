"""
Diagnostic: shows which scopes a stored Buffer key has.

Usage:
    python manage.py check_buffer_scopes             # posting key (buffer_token)
    python manage.py check_buffer_scopes --insights  # insights key (buffer_insights_token)
    python manage.py check_buffer_scopes --insights --posting
                                                     # metrics test with the posting key

With --insights the command also fetches the newest posts with their metrics
and reports, per channel (company page / personal profile), whether Buffer
returns numbers. The key itself is never printed.
"""
import json
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand
from django.db import connection


def _get_superuser_row():
    """Buffer keys and channel ids of the superuser, or None."""
    with connection.cursor() as c:
        try:
            c.execute("""
                SELECT t.buffer_token, t.buffer_insights_token,
                       t.buffer_profile_id, t.buffer_profile_id_person
                FROM planner_linkedin_tokens t
                JOIN auth_user u ON t.user_id = u.id
                WHERE u.is_superuser = 1
                LIMIT 1
            """)
            row = c.fetchone()
        except Exception:
            return None
    if not row:
        return None
    return {'token': row[0], 'insights': row[1], 'org_channel': row[2], 'person_channel': row[3]}


def _get_buffer_token():
    row = _get_superuser_row()
    return row['token'] if row else None


class Command(BaseCommand):
    help = "Shows the scopes of a stored Buffer key."

    def add_arguments(self, parser):
        parser.add_argument('--token', type=str, default=None,
                            help='Pass a Buffer key directly (bypasses the database).')
        parser.add_argument('--insights', action='store_true',
                            help='Check the stored insights key instead of the posting key, '
                                 'and test whether post metrics come back.')
        parser.add_argument('--posting', action='store_true',
                            help='With --insights: run the metrics test with the posting key '
                                 '(buffer_token) instead of the insights key.')

    def handle(self, *args, **options):
        row = _get_superuser_row() or {}
        tok = options.get('token')
        label = 'key from --token'
        if not tok:
            if options.get('insights') and not options.get('posting'):
                tok, label = row.get('insights'), 'insights key (buffer_insights_token)'
            else:
                tok, label = row.get('token'), 'posting key (buffer_token)'
        if not tok:
            self.stderr.write(f"No {label} found. Pass one with --token or check the database connection.")
            return

        self.stdout.write(f"Checking the {label} ({len(tok)} characters) ...")

        def _post(query_str, variables=None):
            payload = {"query": query_str}
            if variables:
                payload["variables"] = variables
            req = urllib.request.Request(
                "https://api.buffer.com",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
            )
            req.add_header("Authorization", f"Bearer {tok}")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.status, resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8", errors="replace")
            except urllib.error.URLError as e:
                return 0, f"connection error: {e.reason}"

        # 1) Organization id - also shows whether Buffer accepts the key at all
        status, org_body = _post("query { account { organizations { id name } } }")
        org_id = None
        try:
            od = json.loads(org_body)
            orgs = ((od.get("data") or {}).get("account") or {}).get("organizations") or []
            if orgs:
                org_id = orgs[0].get("id")
                self.stdout.write(f"Buffer accepts the key. Organization: {orgs[0].get('name')}")
        except Exception:
            pass
        if not org_id:
            self.stdout.write(self.style.ERROR(
                f"Buffer does not accept this key (HTTP {status}) - expired, deleted or wrong."))
            self.stdout.write(org_body[:600])
            return

        # 2) Metrics query - a scope error reveals grantedScopes
        status, body = _post(
            'query { posts(input:{organizationId:"%s"}, first:1){ edges{ node{ id metrics{ type } } } } }'
            % org_id
        )
        try:
            data = json.loads(body)
        except Exception:
            self.stdout.write(f"Unexpected answer (HTTP {status}):")
            self.stdout.write(body[:1000])
            return

        granted = None
        for err in (data.get("errors") or []):
            ext = err.get("extensions") or {}
            if ext.get("grantedScopes"):
                granted = ext["grantedScopes"]
                break

        self.stdout.write("")
        if granted is not None:
            self.stdout.write("GRANTED SCOPES: " + ", ".join(granted))
            self.stdout.write(self.style.WARNING(
                "--> insights:read is MISSING. This key cannot read statistics."))
            return
        if data.get("errors"):
            self.stdout.write(self.style.WARNING("Buffer answered with an error:"))
            self.stdout.write(json.dumps(data["errors"], ensure_ascii=False)[:1200])
            return

        self.stdout.write(self.style.SUCCESS("--> insights:read is there: Buffer returns metrics."))
        if not options.get('insights'):
            return

        # 3) Do real numbers come back - per channel?
        status, body = _post(
            """query PostsMetrics($input: PostsInput!, $first: Int) {
                 posts(input: $input, first: $first) {
                   edges { node { id channelId dueAt status metrics { name value unit } } }
                 }
               }""",
            {"input": {"organizationId": org_id}, "first": 50},
        )
        try:
            data = json.loads(body)
            edges = ((data.get("data") or {}).get("posts") or {}).get("edges") or []
        except Exception:
            self.stdout.write(f"Could not read the posts answer (HTTP {status}).")
            return

        channels = {row.get('org_channel'): 'company page', row.get('person_channel'): 'personal profile'}
        summary = {}
        example = {}
        for e in edges:
            node = e.get("node") or {}
            name = channels.get(node.get("channelId"), f"other channel {node.get('channelId')}")
            s = summary.setdefault(name, [0, 0])
            s[0] += 1
            metrics = [m for m in (node.get("metrics") or []) if m.get("value") not in (None, 0)]
            if metrics:
                s[1] += 1
                example.setdefault(name, (node.get("dueAt"), metrics))

        self.stdout.write("")
        self.stdout.write(f"Newest {len(edges)} posts in Buffer:")
        for name, (n, with_numbers) in summary.items():
            self.stdout.write(f"  {name}: {n} posts, {with_numbers} with numbers")
        for name, (due, metrics) in example.items():
            values = ", ".join(f"{m.get('name')} {m.get('value')}" for m in metrics[:6])
            self.stdout.write(f"  Example {name} ({(due or '')[:10]}): {values}")
        if not any(s[1] for s in summary.values()):
            self.stdout.write(self.style.WARNING("No post came back with numbers."))
