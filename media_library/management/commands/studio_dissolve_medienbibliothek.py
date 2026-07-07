"""
studio_dissolve_medienbibliothek – löst die DB-Medienbibliothek auf.

Für jede Zeile in media_library_items:
  1. Datei aus Nextcloud herunterladen (aktueller nc_path)
  2. Nach Octotrial_Assets/Studio_Work/Bilder/<dateiname> hochladen
     (bei Namenskollision automatisch _1, _2 … anhängen)
  3. NUR bei erfolgreichem Upload die DB-Zeile löschen

Sicherheiten:
  • Eine DB-Zeile wird NIE gelöscht, wenn die Datei nicht sicher am Ziel liegt.
  • Liegt die Datei bereits in Studio_Work/Bilder (gleicher Ordner), wird sie
    nicht kopiert, aber die DB-Zeile trotzdem entfernt (Datei bleibt erhalten).
  • Verwaiste Zeilen (NC-Datei fehlt) werden übersprungen und gemeldet.
  • __local__-Einträge werden übersprungen und gemeldet.

Aufruf:
    python manage.py studio_dissolve_medienbibliothek
"""
from urllib.parse import quote
from django.core.management.base import BaseCommand
from django.db import connection

TARGET_FOLDER = "Marketing & Design/Octotrial_Assets/Studio_Work/Bilder"


class Command(BaseCommand):
    help = "Kopiert alle Medienbibliothek-Bilder nach Studio_Work/Bilder und löscht die DB-Einträge."

    def _nc_exists(self, nc_path):
        import requests
        from requests.auth import HTTPBasicAuth
        from posts_posted.nc_storage import _get_nc_credentials
        nc_url, user, pw = _get_nc_credentials()
        url = f"{nc_url.rstrip('/')}/remote.php/dav/files/{user}/{quote(nc_path, safe='/')}"
        try:
            r = requests.request("PROPFIND", url, auth=HTTPBasicAuth(user, pw),
                                 headers={"Depth": "0"}, timeout=15)
            return r.status_code in (200, 207)
        except Exception:
            return False

    def handle(self, *args, **opt):
        from posts_posted.nc_storage import download_image_from_nextcloud
        from media_library.views import _nc_upload

        with connection.cursor() as c:
            c.execute("SELECT id, nc_path, title FROM media_library_items ORDER BY id")
            rows = c.fetchall()

        if not rows:
            self.stdout.write("Keine Einträge in media_library_items. Nichts zu tun.")
            return

        self.stdout.write(f"Gefundene Einträge: {len(rows)}\n")
        copied, deleted, skipped_orphan, skipped_local, failed = 0, 0, 0, 0, 0
        used_names = set()

        for rid, nc_path, title in rows:
            label = f"#{rid} {title or '(ohne Titel)'}"

            if not nc_path or nc_path.startswith("__local__/"):
                self.stdout.write(self.style.WARNING(f"  ⏭  {label}: lokaler Eintrag, übersprungen"))
                skipped_local += 1
                continue

            # Schon am Ziel? Dann nur DB-Zeile entfernen.
            if nc_path.startswith(TARGET_FOLDER + "/"):
                with connection.cursor() as c:
                    c.execute("DELETE FROM media_library_items WHERE id=%s", [rid])
                self.stdout.write(f"  ✓ {label}: lag bereits am Ziel, DB-Zeile entfernt")
                deleted += 1
                continue

            content, ct = download_image_from_nextcloud(nc_path)
            if not content:
                if not self._nc_exists(nc_path):
                    self.stdout.write(self.style.WARNING(f"  ⚠️  {label}: NC-Datei fehlt (verwaist), übersprungen"))
                    skipped_orphan += 1
                else:
                    self.stdout.write(self.style.ERROR(f"  ✗ {label}: Download fehlgeschlagen"))
                    failed += 1
                continue

            # Kollisionsfreien Dateinamen bestimmen.
            fname = nc_path.split("/")[-1]
            stem, dot, ext = fname.rpartition(".")
            base = stem if dot else fname
            candidate = fname
            i = 1
            while candidate.lower() in used_names:
                candidate = f"{base}_{i}.{ext}" if dot else f"{fname}_{i}"
                i += 1
            used_names.add(candidate.lower())

            dest = f"{TARGET_FOLDER}/{candidate}"
            result = _nc_upload(content, dest, ct or "image/png")
            if not result:
                self.stdout.write(self.style.ERROR(f"  ✗ {label}: Upload nach Ziel fehlgeschlagen – DB-Zeile bleibt"))
                failed += 1
                continue

            with connection.cursor() as c:
                c.execute("DELETE FROM media_library_items WHERE id=%s", [rid])
            self.stdout.write(f"  ✓ {label}  →  {candidate}")
            copied += 1
            deleted += 1

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== ZUSAMMENFASSUNG ==="))
        self.stdout.write(f"  Kopiert:              {copied}")
        self.stdout.write(f"  DB-Zeilen entfernt:   {deleted}")
        self.stdout.write(f"  Übersprungen (Leiche):{skipped_orphan}")
        self.stdout.write(f"  Übersprungen (lokal): {skipped_local}")
        self.stdout.write(f"  Fehlgeschlagen:       {failed}")
        if failed or skipped_orphan or skipped_local:
            self.stdout.write(self.style.WARNING(
                "\nHinweis: Nicht kopierte Einträge blieben in der DB erhalten (nichts verloren)."))
        self.stdout.write(self.style.SUCCESS("\nFertig."))
