"""
Diagnose: zeigt, welche Scopes der gespeicherte Buffer-Token hat.
Aufruf:  python manage.py check_buffer_scopes
"""
from django.core.management.base import BaseCommand
from django.db import connection


def _get_buffer_token():
    with connection.cursor() as c:
        try:
            c.execute("""
                SELECT t.buffer_token
                FROM planner_linkedin_tokens t
                JOIN auth_user u ON t.user_id = u.id
                WHERE u.is_superuser = 1 AND t.buffer_token IS NOT NULL
                LIMIT 1
            """)
            row = c.fetchone()
            return row[0] if row else None
        except Exception:
            return None


class Command(BaseCommand):
    help = "Zeigt die Scopes des Buffer-Tokens an."

    def add_arguments(self, parser):
        parser.add_argument('--token', type=str, default=None,
                            help='Buffer-Token direkt angeben (umgeht die DB).')

    def handle(self, *args, **options):
        import urllib.request, urllib.error, json

        tok = options.get('token')
        if not tok:
            tok = _get_buffer_token()
        if not tok:
            self.stderr.write("Kein Buffer-Token. Gib ihn mit --token an oder pruefe die DB-Verbindung.")
            return

        self.stdout.write("Buffer-Token gefunden. Hole echte Organization-ID ...")

        def _post(query_str):
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

        # 1) Echte Org-ID holen
        org_body = _post("query { account { organizations { id name } } }")
        self.stdout.write("--- Org-Abfrage Rohantwort ---")
        self.stdout.write(org_body[:600])
        self.stdout.write("------------------------------")
        org_id = None
        try:
            od = json.loads(org_body)
            orgs = (od.get("data", {}) or {}).get("account", {}).get("organizations", []) or []
            if orgs:
                org_id = orgs[0].get("id")
                self.stdout.write(f"Organization: {orgs[0].get('name')} (id={org_id!r})")
        except Exception:
            pass

        if not org_id:
            self.stderr.write("Konnte keine Organization-ID holen (siehe Rohantwort oben).")
            return

        self.stdout.write("Frage Scopes ab (mit echter Org-ID) ...")
        # 2) Metrics-Query mit echter Org-ID -> Scope-Fehler verraet grantedScopes
        body = _post(
            'query { posts(input:{organizationId:"%s"}, first:1){ edges{ node{ id metrics{ type } } } } }'
            % org_id
        )

        # grantedScopes aus der Antwort herausziehen
        try:
            data = json.loads(body)
        except Exception:
            self.stdout.write("Rohantwort:")
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
            self.stdout.write(self.style.SUCCESS("GRANTED SCOPES: " + ", ".join(granted)))
            if "insights:read" in granted:
                self.stdout.write(self.style.SUCCESS("--> insights:read VORHANDEN. Statistik-Abruf moeglich!"))
            else:
                self.stdout.write(self.style.WARNING(
                    "--> insights:read FEHLT. Dieser Token kann KEINE Statistik lesen.\n"
                    "    (Buffer gibt insights:read nur fuer Personal API Keys, nicht fuer App-Tokens.)"
                ))
        else:
            # Kein Scope-Fehler -> evtl. hat der Token sogar insights und es kam echte Daten/anderer Fehler
            self.stdout.write("Keine grantedScopes in der Antwort gefunden. Volle Antwort:")
            self.stdout.write(json.dumps(data, ensure_ascii=False)[:1500])
