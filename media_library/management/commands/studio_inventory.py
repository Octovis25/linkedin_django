"""
studio_inventory – REINES LESE-Kommando (Phase 0 der Bild-Vereinheitlichung).

Ändert NICHTS. Erstellt eine Bestandsaufnahme der drei Bildquellen:
  1. Medienbibliothek  (DB-Tabelle media_library_items → NC-Dateien)
  2. Assets            (rein Nextcloud, Octotrial_Assets)
  3. Studio-Output     (Octotrial_Assets/Studio_Output/…)

Zeigt:
  • NC-Ordnerbaum mit Datei-/Bildanzahl je Wurzel
  • DB-Zeilen, deren NC-Datei fehlt (verwaiste Einträge / "Leichen")
  • Dateien, die in mehreren Wurzeln liegen (mögliche Dubletten nach Dateiname)
  • Zusammenfassung mit Zahlen

Aufruf:
    python manage.py studio_inventory
    python manage.py studio_inventory --depth 3          # tiefer scannen
    python manage.py studio_inventory --csv inventory.csv # Ergebnis als CSV
"""
import csv
from collections import defaultdict
from urllib.parse import quote, unquote
from xml.etree import ElementTree

import requests
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from django.db import connection

# Die drei Wurzeln, die vereinheitlicht werden sollen.
ROOTS = {
    "Medienbibliothek": "Marketing & Design/LinkedIn/Medienbibliothek",
    "Assets":           "Marketing & Design/Octotrial_Assets",
    "Studio-Output":    "Marketing & Design/Octotrial_Assets/Studio_Output",
}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")


class Command(BaseCommand):
    help = "Bestandsaufnahme der Bildquellen (read-only, Phase 0)."

    def add_arguments(self, parser):
        parser.add_argument("--depth", type=int, default=2, help="Wie tief NC-Ordner scannen (Standard 2).")
        parser.add_argument("--csv", type=str, default="", help="Ergebnis zusätzlich als CSV schreiben.")

    # ---- NC-Zugriff -------------------------------------------------------
    def _creds(self):
        from posts_posted.nc_storage import _get_nc_credentials
        nc_url, user, pw = _get_nc_credentials()
        if not nc_url:
            return None, None, None
        base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{user}"
        return base, user, pw

    def _propfind(self, base, user, pw, rel):
        """Eine Ebene listen. Gibt [(name, is_dir, size)] zurück."""
        url = f"{base}/{quote(rel, safe='/')}"
        try:
            r = requests.request("PROPFIND", url, auth=HTTPBasicAuth(user, pw),
                                  headers={"Depth": "1"}, timeout=25)
            if r.status_code not in (200, 207):
                return []
        except Exception as e:
            self.stderr.write(f"   PROPFIND-Fehler {rel}: {e}")
            return []
        ns = {"d": "DAV:"}
        tree = ElementTree.fromstring(r.content)
        base_href = f"/remote.php/dav/files/{user}/{quote(rel, safe='/')}".rstrip("/")
        out = []
        for resp in tree.findall("d:response", ns):
            href = resp.findtext("d:href", "", ns).rstrip("/")
            if href == base_href:
                continue
            props = resp.find("d:propstat/d:prop", ns)
            if props is None:
                continue
            is_dir = props.find("d:resourcetype/d:collection", ns) is not None
            try:
                size = int(props.findtext("d:getcontentlength", "0", ns) or 0)
            except (ValueError, TypeError):
                size = 0
            name = unquote(href.split("/")[-1])
            out.append((name, is_dir, size))
        return out

    def _walk(self, base, user, pw, rel, depth, acc):
        """Rekursiv scannen bis Tiefe. acc: dict rel -> {files, images, subdirs}."""
        entries = self._propfind(base, user, pw, rel)
        files = [e for e in entries if not e[1]]
        dirs = [e for e in entries if e[1]]
        images = [e for e in files if e[0].lower().endswith(IMAGE_EXT)]
        acc[rel] = {"files": len(files), "images": len(images),
                    "image_names": {e[0] for e in images}, "subdirs": len(dirs)}
        if depth > 1:
            for name, _, _ in dirs:
                self._walk(base, user, pw, f"{rel}/{name}", depth - 1, acc)

    # ---- Hauptlauf --------------------------------------------------------
    def handle(self, *args, **opt):
        base, user, pw = self._creds()
        if not base:
            self.stderr.write(self.style.ERROR("Keine Nextcloud-Zugangsdaten gefunden. Abbruch."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== NEXTCLOUD-ORDNERBAUM ==="))
        all_images_by_name = defaultdict(list)   # dateiname -> [wurzel-namen]
        root_totals = {}
        for label, root in ROOTS.items():
            acc = {}
            self._walk(base, user, pw, root, opt["depth"], acc)
            tot_files = sum(v["files"] for v in acc.values())
            tot_imgs = sum(v["images"] for v in acc.values())
            root_totals[label] = (tot_files, tot_imgs, len(acc))
            self.stdout.write(f"\n📁 {self.style.HTTP_INFO(label)}  ({root})")
            for rel in sorted(acc):
                v = acc[rel]
                indent = "   " * (rel.count("/") - root.count("/"))
                short = rel.split("/")[-1] or rel
                self.stdout.write(f"   {indent}• {short}: {v['images']} Bilder, {v['subdirs']} Unterordner")
                for nm in v["image_names"]:
                    all_images_by_name[nm].append(label)

        # ---- DB: media_library_items prüfen -------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== DATENBANK: media_library_items ==="))
        db_rows = []
        try:
            with connection.cursor() as c:
                c.execute("SELECT id, nc_path, title, tags, folder_id FROM media_library_items ORDER BY id")
                db_rows = c.fetchall()
        except Exception as e:
            self.stderr.write(f"DB-Fehler: {e}")

        # NC-Existenz je nc_path prüfen (leichtgewichtig via PROPFIND Depth 0)
        def nc_exists(nc_path):
            if not nc_path or nc_path.startswith("__local__/"):
                return None   # lokaler Fallback → separat behandeln
            url = f"{base}/{quote(nc_path, safe='/')}"
            try:
                r = requests.request("PROPFIND", url, auth=HTTPBasicAuth(user, pw),
                                     headers={"Depth": "0"}, timeout=15)
                return r.status_code in (200, 207)
            except Exception:
                return False

        orphans, locals_, ok = [], [], 0
        for rid, nc_path, title, tags, folder_id in db_rows:
            exists = nc_exists(nc_path)
            if exists is None:
                locals_.append((rid, nc_path, title))
            elif exists:
                ok += 1
            else:
                orphans.append((rid, nc_path, title))

        self.stdout.write(f"   Zeilen gesamt: {len(db_rows)}")
        self.stdout.write(f"   ✅ NC-Datei vorhanden: {ok}")
        self.stdout.write(self.style.WARNING(f"   ⚠️  Verwaist (DB-Zeile, NC-Datei fehlt): {len(orphans)}"))
        for rid, p, t in orphans[:30]:
            self.stdout.write(f"      #{rid}  {t or '(ohne Titel)'}  →  {p}")
        if len(orphans) > 30:
            self.stdout.write(f"      … und {len(orphans) - 30} weitere")
        if locals_:
            self.stdout.write(self.style.WARNING(f"   📎 Lokaler Fallback (__local__): {len(locals_)}"))

        # ---- Dubletten nach Dateiname über Wurzeln hinweg -----------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== MÖGLICHE DUBLETTEN (gleicher Dateiname in mehreren Wurzeln) ==="))
        dupes = {nm: roots for nm, roots in all_images_by_name.items() if len(set(roots)) > 1}
        if not dupes:
            self.stdout.write("   Keine wurzelübergreifenden Namensdubletten gefunden.")
        for nm, roots in list(dupes.items())[:40]:
            self.stdout.write(f"   • {nm}  →  {', '.join(sorted(set(roots)))}")
        if len(dupes) > 40:
            self.stdout.write(f"   … und {len(dupes) - 40} weitere")

        # ---- Zusammenfassung ---------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== ZUSAMMENFASSUNG ==="))
        for label, (f, i, d) in root_totals.items():
            self.stdout.write(f"   {label:16s}: {i} Bilder in {d} Ordnern")
        self.stdout.write(f"   DB-Zeilen: {len(db_rows)}  |  verwaist: {len(orphans)}  |  Namensdubletten: {len(dupes)}")
        self.stdout.write(self.style.SUCCESS("\nFertig – es wurde NICHTS verändert.\n"))

        # ---- Optional CSV -------------------------------------------------
        if opt["csv"]:
            with open(opt["csv"], "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["kategorie", "wert1", "wert2"])
                for label, (f, i, d) in root_totals.items():
                    w.writerow(["wurzel", label, f"{i} Bilder / {d} Ordner"])
                for rid, p, t in orphans:
                    w.writerow(["verwaist", f"#{rid} {t}", p])
                for nm, roots in dupes.items():
                    w.writerow(["dublette", nm, ", ".join(sorted(set(roots)))])
            self.stdout.write(self.style.SUCCESS(f"CSV geschrieben: {opt['csv']}"))
