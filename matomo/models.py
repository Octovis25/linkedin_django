from django.db import models


class MatomoSnapshot(models.Model):
    """Ein nächtlich gespeicherter Matomo-Bericht für genau einen Zeitraum.

    Absichtlich generisch: statt für jeden Berichtstyp eine eigene Tabelle
    zu bauen, wird die Antwort als JSON abgelegt. Damit deckt eine Tabelle
    alles ab, was Matomo liefert — auch Berichte, die es heute noch nicht gibt.
    """

    PERIODEN = [
        ("day", "Tag"),
        ("week", "Woche"),
        ("month", "Monat"),
        ("year", "Jahr"),
    ]

    datum = models.DateField(db_index=True, help_text="Erster Tag des Zeitraums")
    periode = models.CharField(max_length=10, choices=PERIODEN, default="day")

    unique_id = models.CharField(
        max_length=255, db_index=True,
        help_text="uniqueId aus API.getReportMetadata, z.B. Actions_getPageUrls",
    )
    modul = models.CharField(max_length=100)
    aktion = models.CharField(max_length=100)
    kategorie = models.CharField(max_length=150, blank=True)
    name = models.CharField(max_length=250, blank=True)

    daten = models.JSONField(default=list)
    zeilen = models.PositiveIntegerField(default=0)
    abgerufen_am = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Matomo-Bericht"
        verbose_name_plural = "Matomo-Berichte"
        constraints = [
            models.UniqueConstraint(
                fields=["datum", "periode", "unique_id"],
                name="matomo_snapshot_eindeutig",
            )
        ]
        indexes = [models.Index(fields=["periode", "datum"])]
        ordering = ["-datum", "kategorie", "name"]

    def __str__(self):
        return f"{self.name or self.unique_id} · {self.datum} ({self.periode})"


class MatomoLauf(models.Model):
    """Protokoll eines nächtlichen Abgleichs — damit sichtbar ist, ob er lief."""

    gestartet = models.DateTimeField(auto_now_add=True)
    beendet = models.DateTimeField(null=True, blank=True)
    datum_von = models.DateField()
    datum_bis = models.DateField()
    berichte_ok = models.PositiveIntegerField(default=0)
    berichte_fehler = models.PositiveIntegerField(default=0)
    meldung = models.TextField(blank=True)

    class Meta:
        verbose_name = "Matomo-Abgleich"
        verbose_name_plural = "Matomo-Abgleiche"
        ordering = ["-gestartet"]

    def __str__(self):
        return f"Abgleich {self.datum_von}-{self.datum_bis} ({self.berichte_ok} OK)"
