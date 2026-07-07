"""
Zeigt alle Einträge in media_library_items und studio_images an,
damit man sieht wo die Dateien tatsächlich gespeichert sind.

Aufruf:
  python manage.py nc_find_media
  python manage.py nc_find_media --migrate   # Verschiebt alles nach Octotrial_Assets
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
    help = "Zeigt und migriert alle Medienbibliothek-Einträge"

    def add_arguments(self, parser):
        parser.add_argument("--migrate", action="store_true",
            help="Dateien auf NC verschieben + DB aktualisieren")

    def handle(self, *args, **options):
        migrate = options["migrate"]
        nc_url, username, password = _get_nc_credentials()
        base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}" if nc_url else None
        auth = HTTPBasicAuth(username, password) if username else None

        # media_library_items
        self.stdout.write("\n═══ media_library_items ═══")
        with connection.cursor() as c:
            c.execute("SELECT id, nc_path, title, tags FROM media_library_items ORDER BY id")
            rows = c.fetchall()
        for r in rows:
            item_id, nc_path, title, tags = r
            is_video = (nc_path or '').lower().endswith(('.webm', '.mp4', '.mov'))
            icon = "🎬" if is_video else "🖼️"
            already = "Octotrial_Assets" in (nc_path or '')
            marker = " ✅" if already else " ⚠️ ALT"
            self.stdout.write(f"  {icon} #{item_id} {title} → {nc_path}{marker}")

            if migrate and not already and nc_path and not nc_path.startswith('__local__'):
                new_folder = NEW_VIDEOS if is_video else NEW_IMAGES
                filename = nc_path.rstrip('/').split('/')[-1]
                new_path = f"{new_folder}/{filename}"
                ok = self._move_nc(base, nc_path, new_path, auth)
                if ok:
                    with connection.cursor() as c2:
                        c2.execute("UPDATE media_library_items SET nc_path=%s WHERE id=%s", [new_path, item_id])
                    self.stdout.write(f"      → verschoben nach {new_path} ✅")
                else:
                    self.stdout.write(f"      → MOVE fehlgeschlagen ❌")

            if migrate and nc_path and nc_path.startswith('__local__'):
                self.stdout.write(f"      → LOKAL gespeichert, muss manuell hochgeladen werden")

        # studio_images
        self.stdout.write("\n═══ studio_images ═══")
        with connection.cursor() as c:
            c.execute("SELECT id, nc_path, title FROM studio_images ORDER BY id")
            rows = c.fetchall()
        for r in rows:
            sid, nc_path, title = r
            already = "Octotrial_Assets" in (nc_path or '')
            marker = " ✅" if already else " ⚠️ ALT"
            self.stdout.write(f"  📐 #{sid} {title} → {nc_path}{marker}")

            if migrate and not already and nc_path and not nc_path.startswith('__local__'):
                is_video = (nc_path or '').lower().endswith(('.webm', '.mp4', '.mov'))
                new_folder = NEW_VIDEOS if is_video else NEW_IMAGES
                filename = nc_path.rstrip('/').split('/')[-1]
                new_path = f"{new_folder}/{filename}"
                # Don't move again if already moved via media_library_items
                with connection.cursor() as c2:
                    c2.execute("UPDATE studio_images SET nc_path=%s WHERE id=%s", [new_path, sid])
                self.stdout.write(f"      → DB aktualisiert auf {new_path}")

        if not migrate:
            self.stdout.write("\n💡 Mit --migrate werden Dateien nach Octotrial_Assets verschoben.")

    def _move_nc(self, base, src, dest, auth):
        if not base or not auth:
            return False
        # Ensure target folder exists
        dest_folder = '/'.join(dest.split('/')[:-1])
        requests.request("MKCOL", f"{base}/{quote(dest_folder, safe='/')}",
            auth=auth, timeout=15)
        src_url = f"{base}/{quote(src, safe='/')}"
        dest_url = f"{base}/{quote(dest, safe='/')}"
        try:
            r = requests.request("MOVE", src_url, auth=auth,
                headers={"Destination": dest_url, "Overwrite": "F"}, timeout=30)
            return r.status_code in (201, 204)
        except Exception:
            return False
