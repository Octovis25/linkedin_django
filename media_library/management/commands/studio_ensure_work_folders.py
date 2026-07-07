"""
studio_ensure_work_folders – legt den Studio-Arbeitsordner in Nextcloud an.

Idempotent: erstellt nur, was noch fehlt (MKCOL ignoriert bestehende Ordner).
Struktur:
    Octotrial_Assets/Studio_Work/
        Bilder/            (fertige statische Studio-Bilder)
        Bewegte_Bilder/    (GIF/WebM + Video-Vorlagen)
        Entwuerfe/         (Zwischenstände)
        _data/             (interne snap/obj/preview-Teile, versteckt)

Aufruf:
    python manage.py studio_ensure_work_folders
"""
from django.core.management.base import BaseCommand

WORK_ROOT = "Marketing & Design/Octotrial_Assets/Studio_Work"
SUBFOLDERS = ["Bilder", "Bewegte_Bilder", "Entwuerfe", "_data"]


class Command(BaseCommand):
    help = "Legt den Studio-Arbeitsordner (Studio_Work) in Nextcloud an."

    def handle(self, *args, **opt):
        from posts_posted.nc_storage import _get_nc_credentials
        from media_library.views import _nc_ensure_folder

        nc_url, user, pw = _get_nc_credentials()
        if not nc_url:
            self.stderr.write(self.style.ERROR("Keine Nextcloud-Zugangsdaten. Abbruch."))
            return

        _nc_ensure_folder(nc_url, user, pw, WORK_ROOT)
        for sub in SUBFOLDERS:
            _nc_ensure_folder(nc_url, user, pw, f"{WORK_ROOT}/{sub}")
            self.stdout.write(f"   ✓ {WORK_ROOT}/{sub}")

        self.stdout.write(self.style.SUCCESS("\nStudio_Work-Ordner sind angelegt (oder waren schon da)."))
