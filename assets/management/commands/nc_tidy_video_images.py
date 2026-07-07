"""
Verschiebt obj/snap-Dateien in Video_Images nach _data Unterordner.
Nur Preview-Dateien (*_preview.png) bleiben im Hauptordner.
Aktualisiert nc://-Referenzen in studio_video_templates.canvas_json.

Aufruf:
  python manage.py nc_tidy_video_images              # Dry-Run
  python manage.py nc_tidy_video_images --apply       # Ausführen
"""
import requests
from urllib.parse import quote, unquote
from xml.etree import ElementTree
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from django.db import connection
from posts_posted.nc_storage import _get_nc_credentials

FOLDER = "Marketing & Design/Octotrial_Assets/Studio_Output/Video_Images"
DATA = f"{FOLDER}/_data"


class Command(BaseCommand):
    help = "obj/snap-Dateien in _data verschieben, Preview im Hauptordner lassen"

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

        # _data Ordner anlegen
        if apply:
            requests.request("MKCOL", f"{base}/{quote(DATA, safe='/')}",
                             auth=auth, timeout=15)

        # Dateien listen
        files = self._list_files(base, FOLDER, auth, username)
        to_move = [f for f in files if '_obj' in f or '_snap' in f]
        to_keep = [f for f in files if f not in to_move]

        self.stdout.write(f"\n📁 {FOLDER}")
        self.stdout.write(f"  Bleiben: {len(to_keep)} (Previews)")
        self.stdout.write(f"  Verschieben: {len(to_move)} (obj/snap → _data/)")

        moved = 0
        for filename in to_move:
            old = f"{FOLDER}/{filename}"
            new = f"{DATA}/{filename}"
            if apply:
                src_url = f"{base}/{quote(old, safe='/')}"
                dest_url = f"{base}/{quote(new, safe='/')}"
                try:
                    r = requests.request("MOVE", src_url, auth=auth,
                        headers={"Destination": dest_url, "Overwrite": "F"}, timeout=30)
                    if r.status_code in (201, 204):
                        moved += 1
                    else:
                        self.stdout.write(f"  ❌ {filename}: {r.status_code}")
                except Exception as e:
                    self.stdout.write(f"  ❌ {filename}: {e}")
            else:
                moved += 1

        # DB: canvas_json nc://-Refs aktualisieren
        if apply:
            with connection.cursor() as c:
                c.execute("SELECT id, canvas_json FROM studio_video_templates")
                for vtid, cjson in c.fetchall():
                    if not cjson:
                        continue
                    updated = cjson
                    for filename in to_move:
                        old_ref = f"{FOLDER}/{filename}"
                        new_ref = f"{DATA}/{filename}"
                        updated = updated.replace(old_ref, new_ref)
                    if updated != cjson:
                        c.execute("UPDATE studio_video_templates SET canvas_json=%s WHERE id=%s",
                                  [updated, vtid])

        self.stdout.write(f"\n{'✅' if apply else '⚠️'} {moved} {'verschoben' if apply else '(Dry-Run)'}")

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
