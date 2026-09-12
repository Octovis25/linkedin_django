"""Nur die Adressen, die geprueft werden. Die echte Wurzel-Adressdatei zieht
das halbe Projekt nach; hier soll der Prueflauf ohne all das starten."""
from django.urls import include, path

urlpatterns = [
    path('library/', include('media_library.urls')),
]
