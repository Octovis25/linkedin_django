from django.contrib import admin

from .models import MatomoLauf, MatomoSnapshot


@admin.register(MatomoSnapshot)
class MatomoSnapshotAdmin(admin.ModelAdmin):
    list_display = ("datum", "periode", "kategorie", "name", "zeilen", "abgerufen_am")
    list_filter = ("periode", "kategorie", "datum")
    search_fields = ("unique_id", "name", "modul", "aktion")
    date_hierarchy = "datum"
    readonly_fields = ("abgerufen_am",)


@admin.register(MatomoLauf)
class MatomoLaufAdmin(admin.ModelAdmin):
    list_display = ("gestartet", "datum_von", "datum_bis",
                    "berichte_ok", "berichte_fehler", "beendet")
    readonly_fields = ("gestartet", "beendet")
