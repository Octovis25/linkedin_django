"""
Migrate all __local__/ images to Nextcloud and update DB paths.
Run once locally where the files exist:

    python manage.py migrate_local_to_nc

Also handles studio_templates and studio_video_templates tables.
"""
import os
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings


NC_LIBRARY_FOLDER = "Marketing & Design/LinkedIn/Medienbibliothek"


class Command(BaseCommand):
    help = "Upload all __local__/ images to Nextcloud and update DB paths"

    def handle(self, *args, **options):
        from posts_posted.nc_storage import _get_nc_credentials
        from requests.auth import HTTPBasicAuth
        from urllib.parse import quote
        import requests

        nc_url, username, password = _get_nc_credentials()
        if not all([nc_url, username, password]):
            self.stderr.write("ERROR: Nextcloud credentials not configured!")
            return

        self.stdout.write(f"NC URL: {nc_url}, User: {username}")

        # Ensure NC folder exists
        auth = HTTPBasicAuth(username, password)
        parts = NC_LIBRARY_FOLDER.split("/")
        for i in range(1, len(parts) + 1):
            folder = "/".join(parts[:i])
            mkcol_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(folder, safe='/')}"
            requests.request("MKCOL", mkcol_url, auth=auth, timeout=15)
        self.stdout.write(f"  Ensured NC folder: {NC_LIBRARY_FOLDER}")

        tables = [
            ("media_library_items", "nc_path", "id"),
            ("studio_templates", "nc_path", "id"),
            ("studio_video_templates", "preview_nc_path", "id"),
        ]

        for table, col, pk in tables:
            self._migrate_table(table, col, pk, nc_url, username, password, requests, HTTPBasicAuth, quote)

    def _migrate_table(self, table, col, pk, nc_url, username, password, requests, HTTPBasicAuth, quote):
        with connection.cursor() as c:
            try:
                c.execute(f"SELECT {pk}, {col} FROM {table} WHERE {col} LIKE '__local__/%%'")
                rows = c.fetchall()
            except Exception as e:
                self.stdout.write(f"  Skipping {table}: {e}")
                return

        if not rows:
            self.stdout.write(f"  {table}: no __local__ entries")
            return

        self.stdout.write(f"  {table}: {len(rows)} entries to migrate")

        for item_id, local_path in rows:
            rel = local_path[len("__local__/"):]

            # Find the actual file on disk
            file_path = None
            candidates = [
                os.path.join(settings.MEDIA_ROOT, "library_uploads", rel),
                os.path.join(settings.BASE_DIR, "media", rel),
                os.path.join(settings.MEDIA_ROOT, rel),
            ]
            for p in candidates:
                if os.path.exists(p):
                    file_path = p
                    break

            if not file_path:
                self.stderr.write(f"    SKIP {item_id}: file not found for {local_path}")
                continue

            # Upload to Nextcloud
            filename = os.path.basename(rel)
            nc_path = NC_LIBRARY_FOLDER + "/" + filename
            upload_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path, safe='/')}"

            with open(file_path, "rb") as f:
                content = f.read()

            ext = os.path.splitext(filename)[1].lower()
            ct_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".webm": "video/webm", ".mp4": "video/mp4", ".gif": "image/gif"}
            ct = ct_map.get(ext, "image/png")

            r = requests.put(upload_url, data=content,
                             auth=HTTPBasicAuth(username, password),
                             headers={"Content-Type": ct}, timeout=60)

            if r.status_code in [200, 201, 204]:
                with connection.cursor() as c:
                    c.execute(f"UPDATE {table} SET {col}=%s WHERE {pk}=%s", [nc_path, item_id])
                self.stdout.write(f"    OK {item_id}: {local_path} -> {nc_path}")
            else:
                self.stderr.write(f"    FAIL {item_id}: NC returned {r.status_code}")
