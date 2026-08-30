"""Zeigt, welche Felder Matomo im Besuchsprotokoll tatsaechlich liefert.

    python manage.py matomo_besuchsfelder
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from matomo import client

INTERESSANT = ("country", "city", "region", "continent", "location", "browser",
               "operating", "device", "language", "referrer", "visitor",
               "visitDuration", "actions", "server")


class Command(BaseCommand):
    help = "Listet die Feldnamen des neuesten Besuchs auf."

    def add_arguments(self, p):
        p.add_argument("--tage", type=int, default=30)
        p.add_argument("--alle", action="store_true", help="wirklich alle Felder zeigen")

    def handle(self, *args, **o):
        import datetime as dt
        bis = timezone.localdate()
        von = bis - dt.timedelta(days=o["tage"])
        roh = client.hole("live/last_visits_details", period="day",
                          date=f"{von.isoformat()},{bis.isoformat()}",
                          filter_limit=5, cache_seconds=0)
        if isinstance(roh, dict):
            flach = []
            for w in roh.values():
                if isinstance(w, list):
                    flach.extend(w)
            roh = flach
        if not roh:
            self.stdout.write(self.style.WARNING("Keine Besuche im Zeitraum."))
            return

        b = roh[0]
        self.stdout.write(f"{len(roh)} Besuche gefunden, Felder des ersten:\n")
        for k in sorted(b):
            if not o["alle"] and not any(t.lower() in k.lower() for t in INTERESSANT):
                continue
            wert = b[k]
            if isinstance(wert, (list, dict)):
                wert = f"<{type(wert).__name__} mit {len(wert)} Einträgen>"
            self.stdout.write(f"  {k:<34} {str(wert)[:70]}")
        if not o["alle"]:
            self.stdout.write("\n(--alle zeigt jedes Feld)")
