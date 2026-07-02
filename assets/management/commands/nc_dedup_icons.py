"""
Bereinigt Duplikate im Icons-Ordner auf Nextcloud UND legt neue Output-Ordner an.

Schritt 1: Duplikate in Icons bereinigen (mit/ohne Unterstrich)
Schritt 2: Neue Ordner Studio_Output + Uploads anlegen

Aufruf:
  python manage.py nc_dedup_icons          # Dry-Run
  python manage.py nc_dedup_icons --apply  # Ausführen
"""
import requests
from urllib.parse import quote, unquote
from xml.etree import ElementTree
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from posts_posted.nc_storage import _get_nc_credentials

ASSETS_ROOT = "Marketing & Design/Octotrial_Assets"
ICONS_PATH = f"{ASSETS_ROOT}/Icons"

# Paare: (mit_leerzeichen, mit_unterstrich)
DUPES = [
    ("Data Management", "Data_Management"),
    ("Clinical Data Management", "Clinical_Data_Management"),
    ("Statistical Programming", "Statistical_Programming"),
    ("Data Management", "Data_Management"),
    ("Icon Only", "Icon_Only"),
    ("Blank Templates", "Blank_Templates"),
]

# Ordner in denen Duplikate sein können
DUPE_PARENTS = [
    ICONS_PATH,
    f"{ASSETS_ROOT}/Logos",
    f"{ASSETS_ROOT}/Backgrounds",
]

# Neue Ordner die angelegt werden sollen
NEW_FOLDERS = [
    f"{ASSETS_ROOT}/Studio_Output",
    f"{ASSETS_ROOT}/Studio_Output/Images",
    f"{ASSETS_ROOT}/Studio_Output/Videos",
    f"{ASSETS_ROOT}/Uploads",
]


class Command(BaseCommand):
    help = "NC-Duplikate bereinigen + Output-Ordner anlegen"

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

        # ── Schritt 1: Duplikate bereinigen ──
        self.stdout.write("\n═══ Schritt 1: Duplikate bereinigen ═══")

        for parent in DUPE_PARENTS:
            self.stdout.write(f"\n📂 Prüfe {parent}:")
            items = self._list_folder(base, parent, auth, username)
            if not items:
                self.stdout.write("   (leer oder nicht gefunden)")
                continue

            # Finde alle Duplikat-Paare in diesem Ordner
            names = [i["name"] for i in items]
            found_dupes = []
            for space_name, under_name in DUPES:
                if space_name in names and under_name in names:
                    found_dupes.append((space_name, under_name))

            if not found_dupes:
                self.stdout.write("   ✔️ Keine Duplikate")
                continue

            for space_name, under_name in found_dupes:
                self.stdout.write(f"\n   🔍 '{space_name}' vs '{under_name}':")
                space_count = self._count_files(base, f"{parent}/{space_name}", auth, username)
                under_count = self._count_files(base, f"{parent}/{under_name}", auth, username)
                self.stdout.write(f"      '{space_name}': {space_count} Dateien")
                self.stdout.write(f"      '{under_name}': {under_count} Dateien")

                if space_count > 0 and under_count == 0:
                    self.stdout.write(f"      → Lösche leeren '{under_name}', benenne '{space_name}' um")
                    if apply:
                        self._delete(base, f"{parent}/{under_name}", auth)
                        self._move(base, f"{parent}/{space_name}", f"{parent}/{under_name}", auth)
                        self.stdout.write("      ✅")
                elif under_count > 0 and space_count == 0:
                    self.stdout.write(f"      → Lösche leeren '{space_name}'")
                    if apply:
                        self._delete(base, f"{parent}/{space_name}", auth)
                        self.stdout.write("      ✅")
                elif space_count == 0 and under_count == 0:
                    self.stdout.write(f"      → Beide leer, lösche '{space_name}'")
                    if apply:
                        self._delete(base, f"{parent}/{space_name}", auth)
                        self.stdout.write("      ✅")
                else:
                    self.stdout.write(f"      ⚠️  Beide haben Inhalt! Bitte manuell prüfen.")

        # ── Schritt 2: Neue Output-Ordner anlegen ──
        self.stdout.write("\n\n═══ Schritt 2: Output-Ordner anlegen ═══")
        for folder in NEW_FOLDERS:
            if apply:
                url = f"{base}/{quote(folder, safe='/')}"
                r = requests.request("MKCOL", url, auth=auth, timeout=15)
                if r.status_code == 201:
                    self.stdout.write(f"   ✅ {folder} erstellt")
                elif r.status_code == 405:
                    self.stdout.write(f"   ✔️ {folder} existiert bereits")
                else:
                    self.stdout.write(f"   ❌ {folder}: {r.status_code}")
            else:
                self.stdout.write(f"   📁 {folder} (Dry-Run)")

        if not apply:
            self.stdout.write("\n⚠️  Dry-Run. Mit --apply ausführen.")
        else:
            self.stdout.write("\n✅ Alles erledigt!")

    def _list_folder(self, base, folder, auth, username):
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
            name = unquote(href.rstrip("/").split("/")[-1])
            items.append({"name": name, "is_dir": is_dir})
        return items

    def _count_files(self, base, path, auth, username):
        url = f"{base}/{quote(path, safe='/')}"
        try:
            r = requests.request("PROPFIND", url, auth=auth,
                headers={"Depth": "1", "Content-Type": "application/xml"}, timeout=20)
            if r.status_code not in (207, 200):
                return -1
        except Exception:
            return -1
        ns = {"d": "DAV:"}
        tree = ElementTree.fromstring(r.content)
        base_href = f"/remote.php/dav/files/{username}/{quote(path, safe='/')}"
        count = 0
        for resp in tree.findall("d:response", ns):
            href = resp.findtext("d:href", "", ns)
            if href.rstrip("/") != base_href.rstrip("/"):
                count += 1
        return count

    def _delete(self, base, path, auth):
        url = f"{base}/{quote(path, safe='/')}"
        try:
            requests.request("DELETE", url, auth=auth, timeout=15)
        except Exception as e:
            self.stderr.write(f"DELETE error: {e}")

    def _move(self, base, src, dest, auth):
        src_url = f"{base}/{quote(src, safe='/')}"
        dest_url = f"{base}/{quote(dest, safe='/')}"
        try:
            requests.request("MOVE", src_url, auth=auth,
                headers={"Destination": dest_url, "Overwrite": "F"}, timeout=30)
        except Exception as e:
            self.stderr.write(f"MOVE error: {e}")
