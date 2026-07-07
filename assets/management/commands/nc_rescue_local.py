"""
Findet alle Einträge mit __local__-Pfaden, lädt die Dateien auf NC hoch
und aktualisiert die DB-Pfade.

Aufruf:
  python manage.py nc_rescue_local              # Dry-Run
  python manage.py nc_rescue_local --apply      # Hochladen + DB aktualisieren
"""
import os
import requests
from urllib.parse import quote
from requests.auth import HTTPBasicAuth
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from posts_posted.nc_storage import _get_nc_credentials

NC_IMAGES = "Marketing & Design/Octotrial_Assets/Studio_Output/Images"
NC_VIDEOS = "Marketing & Design/Octotrial_Assets/Studio_Output/Videos"


class Command(BaseCommand):
    help = "Lokale __local__-Dateien auf NC hochladen und DB aktualisieren"

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

        rescued = 0
        missing = 0

        for table in ["media_library_items", "studio_images"]:
            self.stdout.write(f"\n═══ {table} ═══")
            with connection.cursor() as c:
                c.execute(f"SELECT id, nc_path, title FROM {table} WHERE nc_path LIKE '__local__/%%' ORDER BY id")
                rows = c.fetchall()

            if not rows:
                self.stdout.write("  (keine __local__-Einträge)")
                continue

            for item_id, nc_path, title in rows:
                rel = nc_path[len("__local__/"):]
                local_path = os.path.join(settings.BASE_DIR, "media", rel)
                # Also check MEDIA_ROOT
                if not os.path.exists(local_path):
                    local_path = os.path.join(settings.MEDIA_ROOT, rel) if hasattr(settings, 'MEDIA_ROOT') else local_path
                # Also try library_uploads subfolder
                if not os.path.exists(local_path):
                    local_path = os.path.join(settings.MEDIA_ROOT, "library_uploads", rel) if hasattr(settings, 'MEDIA_ROOT') else local_path

                exists = os.path.exists(local_path)
                is_video = rel.lower().endswith(('.webm', '.mp4', '.mov'))
                nc_folder = NC_VIDEOS if is_video else NC_IMAGES
                filename = os.path.basename(rel)
                new_nc_path = f"{nc_folder}/{filename}"

                if exists:
                    size_kb = os.path.getsize(local_path) // 1024
                    self.stdout.write(f"  📄 #{item_id} {title} ({size_kb}KB) → {local_path}")

                    if apply:
                        # Zielordner sicherstellen
                        requests.request("MKCOL",
                            f"{base}/{quote(nc_folder, safe='/')}",
                            auth=auth, timeout=15)

                        # Upload
                        with open(local_path, "rb") as fh:
                            put_url = f"{base}/{quote(new_nc_path, safe='/')}"
                            r = requests.put(put_url, data=fh, auth=auth, timeout=60)

                        if r.status_code in (200, 201, 204):
                            with connection.cursor() as c2:
                                c2.execute(f"UPDATE {table} SET nc_path=%s WHERE id=%s",
                                           [new_nc_path, item_id])
                            self.stdout.write(f"      ✅ hochgeladen → {new_nc_path}")
                            rescued += 1
                        else:
                            self.stdout.write(f"      ❌ Upload fehlgeschlagen ({r.status_code})")
                    else:
                        self.stdout.write(f"      → würde hochladen nach {new_nc_path}")
                        rescued += 1
                else:
                    missing += 1
                    self.stdout.write(f"  ⚠️ #{item_id} {title} → DATEI FEHLT: {local_path}")

        # --- studio_video_templates: preview_nc_path auf alten Pfaden ---
        self.stdout.write(f"\n═══ studio_video_templates ═══")
        try:
            with connection.cursor() as c:
                c.execute("SELECT id, title, preview_nc_path, canvas_json FROM studio_video_templates ORDER BY id")
                rows = c.fetchall()
            new_vt_folder = "Marketing & Design/Octotrial_Assets/Studio_Output/Video_Images"
            old_vt_folder = "Marketing & Design/LinkedIn/Studio/VideoVorlagen"
            for vtid, vt_title, prev_path, canvas_json in rows:
                if not prev_path or new_vt_folder in prev_path:
                    self.stdout.write(f"  ✅ #{vtid} {vt_title} → bereits migriert")
                    continue
                filename = prev_path.rstrip('/').split('/')[-1]
                new_prev_path = f"{new_vt_folder}/{filename}"
                self.stdout.write(f"  🔄 #{vtid} {vt_title} → {prev_path}")

                if apply:
                    # MKCOL target folder
                    requests.request("MKCOL",
                        f"{base}/{quote(new_vt_folder, safe='/')}",
                        auth=auth, timeout=15)
                    # MOVE preview image
                    src_url = f"{base}/{quote(prev_path, safe='/')}"
                    dest_url = f"{base}/{quote(new_prev_path, safe='/')}"
                    try:
                        r = requests.head(src_url, auth=auth, timeout=10)
                        if r.status_code in (200, 207):
                            r2 = requests.request("MOVE", src_url, auth=auth,
                                headers={"Destination": dest_url, "Overwrite": "F"}, timeout=30)
                            if r2.status_code in (201, 204):
                                self.stdout.write(f"      ✅ Preview verschoben")
                            else:
                                self.stdout.write(f"      ⚠️ MOVE Preview: {r2.status_code}")
                        else:
                            self.stdout.write(f"      ⚠️ Preview nicht auf NC gefunden")
                    except Exception as e:
                        self.stdout.write(f"      ❌ {e}")

                    # Update canvas_json: replace old folder refs with new
                    updated_json = (canvas_json or '').replace(old_vt_folder, new_vt_folder)

                    # Move canvas_json nc:// referenced images
                    import re as _re
                    nc_refs = _re.findall(r'nc://([^"\\]+)', updated_json)
                    for ref_path in nc_refs:
                        if old_vt_folder in ref_path or "LinkedIn/Studio" in ref_path:
                            ref_filename = ref_path.rstrip('/').split('/')[-1]
                            new_ref = f"{new_vt_folder}/{ref_filename}"
                            ref_src = f"{base}/{quote(ref_path, safe='/')}"
                            ref_dst = f"{base}/{quote(new_ref, safe='/')}"
                            try:
                                r3 = requests.request("MOVE", ref_src, auth=auth,
                                    headers={"Destination": ref_dst, "Overwrite": "F"}, timeout=30)
                                if r3.status_code in (201, 204):
                                    updated_json = updated_json.replace(ref_path, new_ref)
                                    self.stdout.write(f"      ✅ NC-Ref verschoben: {ref_filename}")
                            except Exception:
                                pass

                    with connection.cursor() as c2:
                        c2.execute("UPDATE studio_video_templates SET preview_nc_path=%s, canvas_json=%s WHERE id=%s",
                                   [new_prev_path, updated_json, vtid])
                    self.stdout.write(f"      ✅ DB aktualisiert → {new_prev_path}")
                    rescued += 1
                else:
                    self.stdout.write(f"      → würde verschieben nach {new_prev_path}")
                    rescued += 1
        except Exception as e:
            self.stdout.write(f"  (Tabelle nicht vorhanden: {e})")

        self.stdout.write(f"\n{'✅' if apply else '⚠️'} {rescued} {'hochgeladen/verschoben' if apply else 'gefunden (Dry-Run)'}, {missing} lokale Dateien fehlen")
