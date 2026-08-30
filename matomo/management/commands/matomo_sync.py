"""Nächtlicher Abgleich: holt ALLE Matomo-Berichte und legt sie in der DB ab.

    python manage.py matomo_sync                    # gestern
    python manage.py matomo_sync --tage 7           # die letzten 7 Tage
    python manage.py matomo_sync --datum 2026-08-01
    python manage.py matomo_sync --periode month --datum 2026-08-01
    python manage.py matomo_sync --nur Actions,Referrers
"""

from __future__ import annotations

import datetime as dt
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from matomo import client
from matomo.models import MatomoLauf, MatomoSnapshot


def _zeilenzahl(inhalt):
    """Wie viele Datenzeilen steckten in der Antwort (processed_report oder Liste)."""
    if isinstance(inhalt, dict) and "reportData" in inhalt:
        inhalt = inhalt.get("reportData")
    if isinstance(inhalt, (list, dict)):
        return len(inhalt)
    return 0


class Command(BaseCommand):
    help = "Holt alle Matomo-Berichte und speichert sie als Snapshots."

    def add_arguments(self, p):
        p.add_argument("--tage", type=int, default=1,
                       help="Wie viele Zeitraeume rueckwaerts ab --datum (Standard 1)")
        p.add_argument("--datum", type=str, default=None,
                       help="Enddatum JJJJ-MM-TT (Standard: gestern)")
        p.add_argument("--periode", default="day", choices=["day", "week", "month", "year"])
        p.add_argument("--nur", type=str, default=None,
                       help="Nur diese Module, kommagetrennt, z.B. Actions,Referrers")
        p.add_argument("--limit", type=int, default=500,
                       help="Maximale Zeilen je Bericht (Standard 500)")
        p.add_argument("--pause", type=float, default=0.2,
                       help="Sekunden Pause zwischen den Aufrufen, schont den Webhosting-Server")
        p.add_argument("--ueberschreiben", action="store_true",
                       help="Vorhandene Snapshots neu holen statt ueberspringen")

    def handle(self, *args, **o):
        if o["datum"]:
            try:
                bis = dt.date.fromisoformat(o["datum"])
            except ValueError:
                raise CommandError("--datum bitte als JJJJ-MM-TT angeben")
        else:
            bis = timezone.localdate() - dt.timedelta(days=1)

        periode = o["periode"]
        tage = max(1, o["tage"])
        schritt = {"day": 1, "week": 7, "month": 30, "year": 365}[periode]
        daten = [bis - dt.timedelta(days=i * schritt) for i in range(tage)]
        von = min(daten)

        lauf = MatomoLauf.objects.create(datum_von=von, datum_bis=bis)

        try:
            berichte = client.report_metadata(period=periode, date=bis.isoformat())
        except Exception as e:
            lauf.meldung = f"Berichtsliste nicht abrufbar: {e}"
            lauf.beendet = timezone.now()
            lauf.save()
            raise CommandError(lauf.meldung)

        if o["nur"]:
            gewuenscht = {m.strip() for m in o["nur"].split(",") if m.strip()}
            berichte = [b for b in berichte if b.get("module") in gewuenscht]

        self.stdout.write(
            f"{len(berichte)} Berichte x {len(daten)} Zeitraeume ({periode}) - los."
        )

        ok = fehler = uebersprungen = 0
        probleme = []

        for datum in sorted(daten):
            for b in berichte:
                modul, aktion = b.get("module"), b.get("action")
                if not modul or not aktion:
                    continue
                uid = b.get("uniqueId") or f"{modul}_{aktion}"

                if not o["ueberschreiben"] and MatomoSnapshot.objects.filter(
                    datum=datum, periode=periode, unique_id=uid
                ).exists():
                    uebersprungen += 1
                    continue

                try:
                    inhalt = client.report(
                        modul, aktion,
                        period=periode,
                        date=datum.isoformat(),
                        filter_limit=o["limit"],
                        cache_seconds=0,          # beim Sync nie aus dem Cache
                    )
                except Exception as e:
                    fehler += 1
                    probleme.append(f"{uid} @ {datum}: {e}")
                    continue

                MatomoSnapshot.objects.update_or_create(
                    datum=datum, periode=periode, unique_id=uid,
                    defaults={
                        "modul": modul,
                        "aktion": aktion,
                        "kategorie": b.get("category", "") or "",
                        "name": b.get("name", "") or "",
                        "daten": inhalt,
                        "zeilen": _zeilenzahl(inhalt),
                    },
                )
                ok += 1
                if o["pause"]:
                    time.sleep(o["pause"])

            self.stdout.write(f"  {datum}: {ok} gespeichert, {fehler} Fehler")

        lauf.berichte_ok = ok
        lauf.berichte_fehler = fehler
        lauf.meldung = "\n".join(probleme[:50])
        lauf.beendet = timezone.now()
        lauf.save()

        self.stdout.write(self.style.SUCCESS(
            f"Fertig: {ok} gespeichert, {uebersprungen} uebersprungen, {fehler} Fehler."
        ))
        for p in probleme[:10]:
            self.stdout.write(self.style.WARNING("  " + p))
