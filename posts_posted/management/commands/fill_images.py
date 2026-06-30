"""Fuellt fehlende Overview-Bilder automatisch mit Buffer-Thumbnails (Text-Match).
Nur LEERE Bilder werden gesetzt; vorhandene bleiben unangetastet.

Aufruf:
    python manage.py fill_images
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fuellt fehlende Overview-Bilder aus Buffer-Thumbnails (Text-Match)."

    def handle(self, *args, **options):
        from posts_posted.views import fill_missing_post_images
        filled, checked, errors, dates_filled = fill_missing_post_images()
        self.stdout.write(self.style.SUCCESS(
            f"Bilder befuellt: {filled} (geprueft {checked}, Fehler {errors}). "
            f"Daten befuellt: {dates_filled}."
        ))
