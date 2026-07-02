"""
Management command: Nextcloud Marketing & Design aufräumen.

Schritt 1: "Octovis Assets" → "Octotrial_Assets" umbenennen (MOVE)
Schritt 2: Design-relevante Ordner/Dateien in Octotrial_Assets einsortieren
Schritt 3: Fehlende Unterordner per MKCOL anlegen

Aufruf:
  python manage.py nc_cleanup          # Nur anzeigen was passieren würde (Dry-Run)
  python manage.py nc_cleanup --apply  # Tatsächlich ausführen
"""
import requests
from urllib.parse import quote, unquote
from xml.etree import ElementTree
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from posts_posted.nc_storage import _get_nc_credentials
from assets.nc_folders import FOLDER_TREE

ROOT = "Marketing & Design"
OLD_ASSETS = "Marketing & Design/Octovis Assets"
NEW_ASSETS = "Marketing & Design/Octotrial_Assets"

# Mapping: Quellordner in Marketing & Design → Ziel in Octotrial_Assets
MOVE_MAP = {
    "Styleguide Octotrial":     "",                  # Styleguide → Root-Ebene
    "Logo":                     "Logos",             # Logo → Logos
    "CD":                       "Templates",        # Corporate Design → Templates
    "Desktophintergruende":     "Backgrounds",       # Hintergründe → Backgrounds
    "Bilder_Bibliothek":        "Illustrations",     # Bilderbibliothek → Illustrations
    "Landingpage":              "Templates/Website", # Landingpage → Templates/Website
    "ReDesign Webseite":        "Templates/Website", # Redesign → Templates/Website
    "Aquise":                   "Templates/Offer",   # Akquise → Templates/Offer
    "Flyer_OversightPackage_2026": "Templates",      # Flyer → Templates
    "Flyer_SetupPackage_2025":  "Templates",         # Flyer → Templates
}

# Einzeldateien die verschoben werden sollen (Name → Zielordner)
FILE_MOVE_MAP = {
    "Styleguide Octotrial.pdf": "",                  # Root-Ebene
}


class Command(BaseCommand):
    help = "Nextcloud Marketing & Design aufräumen und in Octotrial_Assets einsortieren"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Tatsächlich ausführen (sonst Dry-Run)")

    def handle(self, *args, **options):
        apply = options["apply"]
        nc_url, username, password = _get_nc_credentials()
        if not all([nc_url, username, password]):
            self.stderr.write("❌ NC Credentials fehlen!")
            return

        base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}"
        auth = HTTPBasicAuth(username, password)

        # ── Schritt 0: Was liegt in Marketing & Design? ──
        self.stdout.write("\n📂 Inhalt von Marketing & Design:")
        items = self._propfind(base, ROOT, auth, username)
        for it in items:
            icon = "📁" if it["is_dir"] else "📄"
            self.stdout.write(f"  {icon} {it['name']}")

        # ── Schritt 1: Umbenennen Octovis Assets → Octotrial_Assets ──
        old_exists = any(i["name"] == "Octovis Assets" and i["is_dir"] for i in items)
        new_exists = any(i["name"] == "Octotrial_Assets" and i["is_dir"] for i in items)

        if old_exists and not new_exists:
            self.stdout.write(f"\n🔄 Umbenennen: Octovis Assets → Octotrial_Assets")
            if apply:
                ok = self._move(base, OLD_ASSETS, NEW_ASSETS, auth)
                self.stdout.write(f"   {'✅ Erledigt' if ok else '❌ Fehler'}")
            else:
                self.stdout.write("   (Dry-Run — --apply zum Ausführen)")
        elif new_exists:
            self.stdout.write(f"\n✅ Octotrial_Assets existiert bereits")
        elif not old_exists and not new_exists:
            self.stdout.write(f"\n📁 Erstelle Octotrial_Assets per MKCOL")
            if apply:
                self._mkcol(base, NEW_ASSETS, auth)

        # ── Schritt 2: Ordner verschieben ──
        self.stdout.write("\n📦 Ordner verschieben:")
        for src_name, dest_sub in MOVE_MAP.items():
            src_item = next((i for i in items if i["name"] == src_name), None)
            if not src_item:
                self.stdout.write(f"  ⏭️  {src_name} — nicht gefunden, überspringe")
                continue
            src_path = f"{ROOT}/{src_name}"
            safe_name = src_name.replace(' ', '_')
            if dest_sub:
                dest_path = f"{NEW_ASSETS}/{dest_sub}/{safe_name}"
                label = f"{dest_sub}/{safe_name}"
            else:
                dest_path = f"{NEW_ASSETS}/{safe_name}"
                label = safe_name
            self.stdout.write(f"  📁 {src_name} → {label}")
            if apply:
                if dest_sub:
                    self._mkcol(base, f"{NEW_ASSETS}/{dest_sub}", auth)
                ok = self._move(base, src_path, dest_path, auth)
                self.stdout.write(f"     {'✅' if ok else '❌'}")
            else:
                self.stdout.write("     (Dry-Run)")

        # ── Schritt 2b: Einzeldateien verschieben ──
        for file_name, dest_sub in FILE_MOVE_MAP.items():
            src_item = next((i for i in items if i["name"] == file_name and not i["is_dir"]), None)
            if not src_item:
                continue
            src_path = f"{ROOT}/{file_name}"
            safe_name = file_name.replace(" ", "_")
            if dest_sub:
                dest_path = f"{NEW_ASSETS}/{dest_sub}/{safe_name}"
                label = f"{dest_sub}/{safe_name}"
            else:
                dest_path = f"{NEW_ASSETS}/{safe_name}"
                label = safe_name
            self.stdout.write(f"  📄 {file_name} → {label}")
            if apply:
                if dest_sub:
                    self._mkcol(base, f"{NEW_ASSETS}/{dest_sub}", auth)
                ok = self._move(base, src_path, dest_path, auth)
                self.stdout.write(f"     {'✅' if ok else '❌'}")
            else:
                self.stdout.write("     (Dry-Run)")

        # ── Schritt 3: Fehlende Unterordner anlegen ──
        self.stdout.write("\n📁 Fehlende Ordner anlegen:")
        for folder in FOLDER_TREE:
            full = f"{NEW_ASSETS}/{folder}"
            if apply:
                r = requests.request("MKCOL",
                    f"{base}/{quote(full, safe='/')}",
                    auth=auth, timeout=15)
                status = "✅ erstellt" if r.status_code == 201 else "✔️ existiert" if r.status_code == 405 else f"❌ {r.status_code}"
                self.stdout.write(f"  {folder}: {status}")
            else:
                self.stdout.write(f"  {folder}: (Dry-Run)")

        # ── Zusammenfassung ──
        if apply:
            self.stdout.write("\n✅ Aufräumen abgeschlossen!")
        else:
            self.stdout.write("\n⚠️  Dry-Run — nichts wurde geändert. Mit --apply ausführen.")

    def _propfind(self, base, folder, auth, username):
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

    def _move(self, base, src, dest, auth):
        src_url = f"{base}/{quote(src, safe='/')}"
        dest_url = f"{base}/{quote(dest, safe='/')}"
        try:
            r = requests.request("MOVE", src_url, auth=auth,
                headers={"Destination": dest_url, "Overwrite": "F"}, timeout=30)
            return r.status_code in (201, 204)
        except Exception as e:
            self.stderr.write(f"   MOVE error: {e}")
            return False

    def _mkcol(self, base, path, auth):
        url = f"{base}/{quote(path, safe='/')}"
        try:
            requests.request("MKCOL", url, auth=auth, timeout=15)
        except Exception:
            pass
