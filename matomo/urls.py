from django.urls import path

from . import views

app_name = "matomo"

urlpatterns = [
    path("", views.uebersicht, name="uebersicht"),
    path("besucher/", views.besucher, name="besucher"),
    path("seiten/", views.seiten, name="seiten"),
    path("ki/", views.ki, name="ki"),
    path("protokoll/", views.protokoll, name="protokoll"),
    path("suchbegriffe/", views.suchbegriffe, name="suchbegriffe"),
    path("archiv/", views.archiv, name="archiv"),
    path("archiv/<int:pk>/", views.archiv_detail, name="archiv_detail"),
    path("json/<str:modul>/<str:aktion>/", views.api_proxy, name="json"),
    path("<str:modul>/<str:aktion>/", views.bericht, name="bericht"),
]
