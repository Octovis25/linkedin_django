"""
Test: prueft, ob euer LinkedIn-Token die Post-Statistik (organic) lesen darf.
Ruft organizationalEntityShareStatistics fuer eure Organisation ab.

Aufruf:  python manage.py test_linkedin_stats

Zeigt entweder echte Statistik-Daten oder den Berechtigungsfehler.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Testet den Zugriff auf LinkedIn Post-Statistik (organizationalEntityShareStatistics)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=str, default=None,
                            help='Org-ID direkt angeben (numerisch, z.B. 107030717).')

    def handle(self, *args, **options):
        import requests as _req
        from planner.views import _li_get_superuser_token

        token = _li_get_superuser_token()
        if not token or not token.get('access_token'):
            self.stderr.write("Kein LinkedIn-Token gefunden.")
            return
        headers = {
            'Authorization': f"Bearer {token['access_token']}",
            'Linkedin-Version': '202604',
            'X-Restli-Protocol-Version': '2.0.0',
        }

        # Org-ID: Vorrang hat das --org-Argument, sonst aus dem Token.
        org_id = options.get('org') or token.get('org_id')
        self.stdout.write(f"Verwende org_id: {org_id!r}")
        org_num = str(org_id).split(':')[-1] if org_id else ''
        if not org_num or not org_num.isdigit():
            self.stderr.write(
                "Keine gueltige Org-ID im Token gespeichert.\n"
                "Bitte auf der API-Connect-Seite die LinkedIn-Org-ID eintragen "
                "(die numerische ID eurer Firmenseite)."
            )
            return

        org_urn = f"urn:li:organization:{org_num}"
        self.stdout.write(f"Org: {org_urn}")
        self.stdout.write("Frage Lifetime-Statistik der Organisation ab ...")

        # Lifetime-Statistik der gesamten Organisation (kein timeIntervals).
        from urllib.parse import quote
        org_enc = quote(org_urn, safe='')  # urn%3Ali%3Aorganization%3A107030717

        # Restli 2.0: URN muss URL-encodiert sein. Wir bauen die URL selbst,
        # damit requests sie nicht nochmal anfasst.
        url = (
            "https://api.linkedin.com/rest/organizationalEntityShareStatistics"
            f"?q=organizationalEntity&organizationalEntity={org_enc}"
        )
        self.stdout.write(f"URL: {url}")
        try:
            r = _req.get(url, headers=headers, timeout=20)
        except Exception as e:
            self.stderr.write(f"Netzwerkfehler: {e}")
            return

        self.stdout.write(f"\nHTTP {r.status_code}")
        self.stdout.write(r.text[:2500])

        if r.status_code == 200:
            self.stdout.write(self.style.SUCCESS(
                "\n--> Zugriff funktioniert! LinkedIn liefert Statistik. "
                "Pro-Post-Statistik ist damit ebenfalls moeglich."
            ))
        elif r.status_code in (401, 403):
            self.stdout.write(self.style.WARNING(
                "\n--> Kein Zugriff (401/403). Der Token darf Analytics nicht lesen.\n"
                "    Moeglich: Scope r_organization_social fehlt ODER die LinkedIn-App\n"
                "    hat das Produkt 'Community Management API' nicht freigeschaltet."
            ))
