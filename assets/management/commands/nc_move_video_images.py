"""
Verschiebt Video-Bild-Dateien von LinkedIn/Studio/VideoVorlagen
nach Octotrial_Assets/Studio_Output/Video_Images auf NC.
Aktualisiert preview_nc_path und canvas_json nc://-Referenzen.

Aufruf:
  python manage.py nc_move_video_images              # Dry-Run
  python manage.py nc_move_video_images --apply       # Ausführen
"""
import re
import json
import requests
from urllib.parse import quote
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from django.db import connection
from posts_posted.nc_storage import _get_nc_credentials

OLD_FOLDER = "Marketing & Design/LinkedIn/Studio/VideoVorlagen"
NEW_FOLDER = "Marketing & Design/Octotrial_Assets/Studio_Output/Video_Images"


class Command(BaseCommand):
    help = "Video-Bild-Dateien nach Octotrial_Assets verschieben"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        apply = options["apply"]
        nc_url, username, password = _get_nc_credentials()
        if not all([nc_url, username, password]):
            self.stderr.write("NC Credentials fehlen!")
            return

        base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}"
        auth = HTTPBasicAuth(username, password)

        # Zielordner anlegen
        if apply:
            requests.request("MKCOL", f"{base}/{quote(NEW_FOLDER, safe='/')}",
                             auth=auth, timeout=15)

        # Alle Dateien im alten Ordner listen
        self.stdout.write(f"\n═══ Dateien in {OLD_FOLDER} ═══")
        old_files = self._list_files(base, OLD_FOLDER, auth, username)
        for f in old_files:
            self.stdout.write(f"  📄 {f}")

        if not old_files:
            self.stdout.write("  (leer oder nicht gefunden)")

        # Dateien verschieben
        moved = 0
        for filename in old_files:
            old_path = f"{OLD_FOLDER}/{filename}"
            new_path = f"{NEW_FOLDER}/{filename}"
            self.stdout.write(f"\n  🔄 {filename}")
            if apply:
                src_url = f"{base}/{quote(old_path, safe='/')}"
                dest_url = f"{base}/{quote(new_path, safe='/')}"
                try:
                    r = requests.request("MOVE", src_url, auth=auth,
                        headers={"Destination": dest_url, "Overwrite": "F"}, timeout=30)
                    if r.status_code in (201, 204):
                        self.stdout.write(f"      ✅ verschoben")
                        moved += 1
                    else:
                        self.stdout.write(f"      ❌ {r.status_code}")
                except Exception as e:
                    self.stdout.write(f"      ❌ {e}")
            else:
                self.stdout.write(f"      → würde verschieben")
                moved += 1

        # DB aktualisieren: preview_nc_path und canvas_json
        self.stdout.write(f"\n═══ DB-Einträge aktualisieren ═══")
        with connection.cursor() as c:
            c.execute("SELECT id, title, preview_nc_path, canvas_json FROM studio_video_templates")
            rows = c.fetchall()

        for vtid, title, prev_path, canvas_json in rows:
            needs_update = False
            new_prev = prev_path
            new_json = canvas_json

            # Fix preview_nc_path
            if prev_path and OLD_FOLDER in prev_path:
                new_prev = prev_path.replace(OLD_FOLDER, NEW_FOLDER)
                needs_update = True
            # Auch wenn es schon den neuen Pfad hat aber noch alte Refs im JSON
            if canvas_json and OLD_FOLDER in canvas_json:
                new_json = canvas_json.replace(OLD_FOLDER, NEW_FOLDER)
                needs_update = True

            if needs_update:
                self.stdout.write(f"  🔄 #{vtid} {title}")
                if apply:
                    with connection.cursor() as c2:
                        c2.execute("UPDATE studio_video_templates SET preview_nc_path=%s, canvas_json=%s WHERE id=%s",
                                   [new_prev, new_json, vtid])
                    self.stdout.write(f"      ✅ DB aktualisiert")
                else:
                    self.stdout.write(f"      → würde aktualisieren")
            else:
                self.stdout.write(f"  ✅ #{vtid} {title} — OK")

        self.stdout.write(f"\n{'✅' if apply else '⚠️'} {moved} Dateien {'verschoben' if apply else '(Dry-Run)'}")

    def _list_files(self, base, folder, auth, username):
        from xml.etree import ElementTree
        from urllib.parse import unquote
        url = f"{base}/{quote(folder, safe='/')}"
        try:
            r = requests.request("PROPFIND", url, auth=auth,
                headers={"Depth": "1", "Content-Type": "application/xml"}, timeout=20)
            if r.status_code not in (207, 200):
                return []
        except Exception:
            return []
        ns = {"d": "DAV:"}
        tree = ElementTree.fromstring(r.content)
        base_href = f"/remote.php/dav/files/{username}/{quote(folder, safe='/')}"
        files = []
        for resp in tree.findall("d:response", ns):
            href = resp.findtext("d:href", "", ns)
            if href.rstrip("/") == base_href.rstrip("/"):
                continue
            props = resp.find("d:propstat/d:prop", ns)
            is_dir = props.find("d:resourcetype/d:collection", ns) is not None if props else False
            if not is_dir:
                files.append(unquote(href.rstrip("/").split("/")[-1]))
        return files
