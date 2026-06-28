"""
Diagnose: liest EINEN Buffer-Post komplett aus (ohne das metrics-Feld) und zeigt
alle verfuegbaren Felder. So sehen wir, ob ausserhalb von 'metrics' Statistik-
werte mitkommen (die keinen insights:read-Scope brauchen).

Aufruf:  python manage.py dump_buffer_post --token DEIN_TOKEN
"""
from django.core.management.base import BaseCommand
import json


class Command(BaseCommand):
    help = "Liest einen Buffer-Post komplett aus (ohne metrics) und zeigt alle Felder."

    def add_arguments(self, parser):
        parser.add_argument('--token', type=str, required=True, help='Buffer-Token.')

    def handle(self, *args, **options):
        import urllib.request, urllib.error

        tok = options['token']

        def post(query_str):
            req = urllib.request.Request(
                "https://api.buffer.com",
                data=json.dumps({"query": query_str}).encode("utf-8"),
                method="POST",
            )
            req.add_header("Authorization", f"Bearer {tok}")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                return e.read().decode("utf-8", errors="replace")

        # Org-ID holen
        ob = post("query { account { organizations { id } } }")
        try:
            org_id = json.loads(ob)["data"]["account"]["organizations"][0]["id"]
        except Exception:
            self.stderr.write("Org-ID nicht ladbar: " + ob[:400])
            return

        # Posts auslesen MIT vielen moeglichen Feldern, OHNE metrics.
        # Wir probieren breit, was Buffer ueber den Post zurueckgibt.
        query = '''
        query Dump($input: PostsInput!) {
          posts(input: $input, first: 3) {
            edges {
              node {
                id
                status
                text
                dueAt
                sentAt
                createdAt
                updatedAt
                channelId
                via
                __typename
              }
            }
          }
        }''' .replace("$input", "$input")

        body = post(
            'query { posts(input:{organizationId:"%s"}, first:3){ edges{ node{ '
            'id status text dueAt createdAt updatedAt channelId __typename '
            '} } } }' % org_id
        )

        self.stdout.write("=== ROHANTWORT (erste Posts, ohne metrics) ===")
        try:
            data = json.loads(body)
            self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False)[:4000])
        except Exception:
            self.stdout.write(body[:4000])
