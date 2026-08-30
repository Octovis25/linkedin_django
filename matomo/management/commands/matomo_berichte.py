"""Listet auf, welche Berichte dieses Matomo anbietet.

    python manage.py matomo_berichte
    python manage.py matomo_berichte --suche ai,bot,agent
"""
from django.core.management.base import BaseCommand

from matomo import client


class Command(BaseCommand):
    help = "Zeigt alle verfuegbaren Matomo-Berichte (Modul.Aktion, Name, Kategorie)."

    def add_arguments(self, p):
        p.add_argument("--suche", default=None,
                       help="Nur Berichte, deren Name/Modul einen dieser Begriffe "
                            "enthaelt (kommagetrennt, Gross/Klein egal)")

    def handle(self, *args, **o):
        berichte = client.report_metadata(cache_seconds=0)
        if not berichte:
            self.stdout.write(self.style.WARNING("Keine Berichtsliste erhalten."))
            return

        begriffe = [b.strip().lower() for b in (o["suche"] or "").split(",") if b.strip()]
        if begriffe:
            berichte = [
                b for b in berichte
                if any(t in f"{b.get('module','')} {b.get('action','')} "
                            f"{b.get('name','')} {b.get('category','')}".lower()
                       for t in begriffe)
            ]

        self.stdout.write(f"{len(berichte)} Berichte\n")
        letzte = None
        for b in sorted(berichte, key=lambda x: (x.get("category", ""), x.get("name", ""))):
            kat = b.get("category", "?")
            if kat != letzte:
                self.stdout.write(f"\n[{kat}]")
                letzte = kat
            self.stdout.write(f"  {b.get('module','')}.{b.get('action',''):<32} {b.get('name','')}")
