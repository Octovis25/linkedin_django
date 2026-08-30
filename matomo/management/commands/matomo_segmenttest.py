"""Prueft, ob Matomo Segmente auf dieser Installation beantwortet.

    python manage.py matomo_segmenttest
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from matomo import client


class Command(BaseCommand):
    help = "Testet, ob segmentierte Berichte Daten liefern."

    def handle(self, *args, **o):
        datum = timezone.localdate().isoformat()

        faelle = [
            ("ohne Segment", None),
            ("Menschen  visitDuration>0", "visitDuration>0"),
            ("Bots      visitDuration==0", "visitDuration==0"),
            ("Menschen  actions>1", "actions>1"),
        ]

        self.stdout.write(f"Zeitraum: Monat {datum}\n")
        self.stdout.write(f"{'Fall':<34}{'Besuche':>9}{'Seiten-Berichtszeilen':>24}")
        self.stdout.write("-" * 67)

        for name, segment in faelle:
            try:
                k = client.hole("visits_summary/get", period="month", date=datum,
                                segment=segment, cache_seconds=0)
                besuche = k.get("nb_visits", "?") if isinstance(k, dict) else "?"
            except Exception as e:
                besuche = f"FEHLER {str(e)[:40]}"
            try:
                r = client.report("Actions", "getPageUrls", period="month", date=datum,
                                  segment=segment, filter_limit=50, flat=1, cache_seconds=0)
                daten = r.get("reportData") if isinstance(r, dict) else None
                zeilen = len(daten) if isinstance(daten, (list, dict)) else "?"
            except Exception as e:
                zeilen = f"FEHLER {str(e)[:40]}"
            self.stdout.write(f"{name:<34}{str(besuche):>9}{str(zeilen):>24}")

        self.stdout.write(
            "\nErwartung, wenn Segmente funktionieren: Menschen + Bots ergeben "
            "zusammen die Zahl aus 'ohne Segment'."
        )
