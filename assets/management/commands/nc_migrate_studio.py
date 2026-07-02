"""
Verschiebt bestehende Studio-Bilder und -Videos von den alten NC-Pfaden
in die neue Octotrial_Assets-Struktur.

Alt:  Marketing & Design/LinkedIn/Studio/Bibliothek/  → Neu: .../Studio_Output/Images/
Alt:  Marketing & Design/LinkedIn/Studio/Videos/       → Neu: .../Studio_Output/Videos/

Aktualisiert auch die DB-Einträge (media_library_items, studio_images, planner_posts).

Aufruf:
  python manage.py nc_migrate_studio          # Dry-Run
  python manage.py nc_migrate_studio --apply  # Ausführen
"""
import requests
from urllib.parse import quote, unquote
from xml.etree import ElementTree
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from django.db import connection
from posts_posted.nc_storage import _get_nc_credentials

OLD_IMAGES = "Marketing & Design/LinkedIn/Studio/Bibliothek"
OLD_VIDEOS = "Marketing & Design/LinkedIn/Studio/Videos"
NEW_IMAGES = "Marketing & Design/Octotrial_Assets/Studio_Output/Images"
NEW_VIDEOS = "Marketing & Design/Octotrial_Assets/Studio_Output/Videos"


class Command(BaseCommand):
    help = "Studio-Dateien von alten NC-Pfaden nach Octotrial_Assets migrieren"

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

        # Zielordner sicherstellen
        if apply:
            for p in [NEW_IMAGES, NEW_VIDEOS]:
                url = f"{base}/{quote(p, safe='/')}"
                requests.request("MKCOL", url, auth=auth, timeout=15)

        total_moved = 0

        for old_folder, new_folder, label in [
            (OLD_IMAGES, NEW_IMAGES, "Bilder"),
            (OLD_VIDEOS, NEW_VIDEOS, "Videos"),
        ]:
            self.stdout.write(f"\n═══ {label}: {old_folder} → {new_folder} ═══")
            files = self._list_files(base, old_folder, auth, username)
            if not files:
                self.stdout.write("   (leer oder nicht gefunden)")
                continue

            for f in files:
                old_path = f"{old_folder}/{f['name']}"
                new_path = f"{new_folder}/{f['name']}"
                self.stdout.write(f"   📄 {f['name']}")

                if apply:
                    # MOVE auf NC
                    ok = self._move(base, old_path, new_path, auth)
                    if ok:
                        # DB-Pfade aktualisieren
                        self._update_db_paths(old_path, new_path)
                        self.stdout.write(f"      ✅ verschoben + DB aktualisiert")
                        total_moved += 1
                    else:
                        self.stdout.write(f"      ❌ MOVE fehlgeschlagen")
                else:
                    self.stdout.write(f"      (Dry-Run)")
                    total_moved += 1

        self.stdout.write(f"\n{'✅' if apply else '⚠️'} {total_moved} Dateien {'verschoben' if apply else 'gefunden (Dry-Run)'}.")

    def _list_files(self, base, folder, auth, username):
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
        items = []
        for resp in tree.findall("d:response", ns):
            href = resp.findtext("d:href", "", ns)
            if href.rstrip("/") == base_href.rstrip("/"):
                continue
            props = resp.find("d:propstat/d:prop", ns)
            is_dir = props.find("d:resourcetype/d:collection", ns) is not None if props else False
            if is_dir:
                continue
            name = unquote(href.rstrip("/").split("/")[-1])
            items.append({"name": name})
        return items

    def _move(self, base, src, dest, auth):
        src_url = f"{base}/{quote(src, safe='/')}"
        dest_url = f"{base}/{quote(dest, safe='/')}"
        try:
            r = requests.request("MOVE", src_url, auth=auth,
                headers={"Destination": dest_url, "Overwrite": "F"}, timeout=30)
            return r.status_code in (201, 204)
        except Exception as e:
            self.stderr.write(f"MOVE error: {e}")
            return False

    def _update_db_paths(self, old_path, new_path):
        """Update all DB tables that reference this nc_path."""
        with connection.cursor() as c:
            for table, col in [
                ("media_library_items", "nc_path"),
                ("studio_images", "nc_path"),
                ("planner_posts", "image"),
            ]:
                try:
                    c.execute(f"UPDATE {table} SET {col}=%s WHERE {col}=%s", [new_path, old_path])
                except Exception:
                    pass
