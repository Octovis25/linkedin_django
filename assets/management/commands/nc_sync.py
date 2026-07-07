"""
Synchronisiert DB mit Nextcloud: prüft ob referenzierte Dateien noch existieren.
Löscht verwaiste DB-Einträge wenn die NC-Datei fehlt.

Aufruf:
  python manage.py nc_sync              # Dry-Run: zeigt was fehlt
  python manage.py nc_sync --apply      # Löscht verwaiste Einträge
  python manage.py nc_sync --migrate    # Verschiebt zusätzlich alte Pfade nach Octotrial_Assets

Für regelmäßigen Abgleich z.B. als Cron-Job:
  */30 * * * * cd /app && python manage.py nc_sync --apply >> /tmp/nc_sync.log 2>&1
"""
import requests
from urllib.parse import quote
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from django.db import connection
from posts_posted.nc_storage import _get_nc_credentials

NEW_IMAGES = "Marketing & Design/Octotrial_Assets/Studio_Output/Images"
NEW_VIDEOS = "Marketing & Design/Octotrial_Assets/Studio_Output/Videos"


class Command(BaseCommand):
    help = "DB mit Nextcloud synchronisieren — verwaiste Einträge finden/löschen"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
            help="Verwaiste Einträge tatsächlich löschen")
        parser.add_argument("--migrate", action="store_true",
            help="Alte Pfade zusätzlich nach Octotrial_Assets verschieben")

    def handle(self, *args, **options):
        apply = options["apply"]
        migrate = options["migrate"]
        nc_url, username, password = _get_nc_credentials()
        if not all([nc_url, username, password]):
            self.stderr.write("NC Credentials fehlen!")
            return

        base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}"
        auth = HTTPBasicAuth(username, password)

        orphaned = 0
        migrated = 0
        ok_count = 0

        # --- media_library_items ---
        self.stdout.write("\n═══ media_library_items ═══")
        with connection.cursor() as c:
            c.execute("SELECT id, nc_path, title FROM media_library_items ORDER BY id")
            rows = c.fetchall()

        for item_id, nc_path, title in rows:
            if not nc_path or nc_path.startswith("__local__"):
                continue

            exists = self._file_exists(base, nc_path, auth)

            if exists:
                # Optional: migrate alte Pfade
                if migrate and "Octotrial_Assets" not in nc_path:
                    new_path = self._migrate_path(base, nc_path, auth)
                    if new_path:
                        with connection.cursor() as c2:
                            c2.execute("UPDATE media_library_items SET nc_path=%s WHERE id=%s",
                                       [new_path, item_id])
                        self.stdout.write(f"  🔄 #{item_id} {title} → migriert nach {new_path}")
                        migrated += 1
                        continue
                ok_count += 1
            else:
                orphaned += 1
                self.stdout.write(f"  ❌ #{item_id} {title} → FEHLT: {nc_path}")
                if apply:
                    with connection.cursor() as c2:
                        c2.execute("DELETE FROM media_library_items WHERE id=%s", [item_id])
                    self.stdout.write(f"      → gelöscht aus DB")

        # --- studio_images ---
        self.stdout.write("\n═══ studio_images ═══")
        with connection.cursor() as c:
            c.execute("SELECT id, nc_path, title FROM studio_images ORDER BY id")
            rows = c.fetchall()

        for sid, nc_path, title in rows:
            if not nc_path or nc_path.startswith("__local__"):
                # Lokale Einträge: prüfen ob sie je hochgeladen wurden
                continue

            exists = self._file_exists(base, nc_path, auth)

            if exists:
                if migrate and "Octotrial_Assets" not in nc_path:
                    new_path = self._migrate_path(base, nc_path, auth)
                    if new_path:
                        with connection.cursor() as c2:
                            c2.execute("UPDATE studio_images SET nc_path=%s WHERE id=%s",
                                       [new_path, sid])
                        self.stdout.write(f"  🔄 #{sid} {title} → migriert nach {new_path}")
                        migrated += 1
                        continue
                ok_count += 1
            else:
                orphaned += 1
                self.stdout.write(f"  ❌ #{sid} {title} → FEHLT: {nc_path}")
                if apply:
                    with connection.cursor() as c2:
                        c2.execute("DELETE FROM studio_images WHERE id=%s", [sid])
                    self.stdout.write(f"      → gelöscht aus DB")

        # --- asset_metadata (Octotrial Assets) ---
        self.stdout.write("\n═══ asset_metadata ═══")
        try:
            with connection.cursor() as c:
                c.execute("SELECT id, nc_path, filename FROM asset_metadata ORDER BY id")
                rows = c.fetchall()

            for mid, nc_path, filename in rows:
                if not nc_path:
                    continue
                exists = self._file_exists(base, nc_path, auth)
                if exists:
                    ok_count += 1
                else:
                    orphaned += 1
                    self.stdout.write(f"  ❌ #{mid} {filename} → FEHLT: {nc_path}")
                    if apply:
                        with connection.cursor() as c2:
                            c2.execute("DELETE FROM asset_tags WHERE asset_id=%s", [mid])
                            c2.execute("DELETE FROM asset_metadata WHERE id=%s", [mid])
                        self.stdout.write(f"      → gelöscht aus DB")
        except Exception:
            self.stdout.write("  (Tabelle existiert noch nicht)")

        # Summary
        self.stdout.write(f"\n{'✅' if apply else '⚠️'} Ergebnis: {ok_count} OK, "
                          f"{orphaned} verwaist{'(gelöscht)' if apply else ' (Dry-Run)'}"
                          f"{f', {migrated} migriert' if migrated else ''}")

    def _file_exists(self, base, nc_path, auth):
        """HEAD-Request um zu prüfen ob Datei auf NC existiert."""
        url = f"{base}/{quote(nc_path, safe='/')}"
        try:
            r = requests.head(url, auth=auth, timeout=10)
            return r.status_code in (200, 207)
        except Exception:
            return False

    def _migrate_path(self, base, old_path, auth):
        """Verschiebt Datei nach Octotrial_Assets und gibt neuen Pfad zurück."""
        is_video = old_path.lower().endswith(('.webm', '.mp4', '.mov'))
        new_folder = NEW_VIDEOS if is_video else NEW_IMAGES
        filename = old_path.rstrip('/').split('/')[-1]
        new_path = f"{new_folder}/{filename}"

        # Zielordner anlegen
        requests.request("MKCOL", f"{base}/{quote(new_folder, safe='/')}",
                         auth=auth, timeout=15)

        src_url = f"{base}/{quote(old_path, safe='/')}"
        dest_url = f"{base}/{quote(new_path, safe='/')}"
        try:
            r = requests.request("MOVE", src_url, auth=auth,
                                 headers={"Destination": dest_url, "Overwrite": "F"},
                                 timeout=30)
            if r.status_code in (201, 204):
                return new_path
        except Exception:
            pass
        return None
