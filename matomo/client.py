"""Client für Matomo-for-WordPress über die WordPress-REST-API.

Warum dieser Weg und nicht die Matomo-Reporting-API unter
/wp-content/plugins/matomo/app: Diese Installation akzeptiert dort kein
Anwendungspasswort als token_auth (Matomo antwortet "Invalid token auth",
und `allow_app_password_as_token_auth` in der config.ini.php ändert daran
nichts). Die WordPress-REST-API dagegen nimmt das Anwendungspasswort ganz
normal per HTTP-Basic-Auth an — geprüft am 2026-08-30.

Zugangsdaten (aus .env bzw. Render → Environment):
    MATOMO_URL    https://octotrial.com          (Basis-Adresse der Website)
    MATOMO_SITE_ID  1
    MATOMO_TOKEN  <wp-benutzer>:<anwendungspasswort>
"""

from __future__ import annotations

import hashlib
import json
import logging

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

NAMENSRAUM = "/wp-json/matomo/v1"


class MatomoError(RuntimeError):
    """Matomo hat geantwortet, aber mit einem Fehler."""


def _basis() -> str:
    """Basis-Adresse der Website, egal ob MATOMO_URL die alte App-URL enthält."""
    url = (getattr(settings, "MATOMO_URL", "") or "").strip().rstrip("/")
    if not url:
        raise MatomoError("MATOMO_URL is not set.")
    for schnitt in ("/wp-content/", "/wp-json/", "/index.php"):
        if schnitt in url:
            url = url.split(schnitt)[0]
    return url.rstrip("/")


def _zugang():
    token = getattr(settings, "MATOMO_TOKEN", "") or ""
    if ":" not in token:
        raise MatomoError(
            "MATOMO_TOKEN is missing or malformed. Expected "
            "'<wp-user>:<application-password>' — set it in .env or, on Render, "
            "under Environment."
        )
    benutzer, passwort = token.split(":", 1)
    return benutzer, passwort


def _cache_key(pfad: str, params: dict) -> str:
    roh = json.dumps([pfad, sorted(params.items())], sort_keys=True, default=str)
    return "matomo:" + hashlib.sha1(roh.encode()).hexdigest()


def blog_beitraege(*, cache_seconds: int = 86400):
    """Alle veröffentlichten WordPress-Beiträge als [{"link", "titel", "datum"}].

    Warum (30.09.2026): Die Blogartikel liegen direkt unter der Domain, genau
    wie die Seiten - an der Adresse allein ist ein Artikel nicht zu erkennen.
    WordPress weiß es. /wp-json/wp/v2/posts ist normalerweise öffentlich; der
    Zugang geht trotzdem mit, falls ein Plugin die Liste nur Angemeldeten zeigt.

    Einmal am Tag abgefragt. Gibt WordPress die Liste nicht heraus, kommt ein
    MatomoError - und eine Stunde lang wird es nicht erneut versucht, damit
    nicht jeder Seitenaufruf auf eine Zeitüberschreitung wartet.
    """
    import html

    key, fehler_key = "matomo:wp-beitraege", "matomo:wp-beitraege:fehler"
    treffer = cache.get(key)
    if treffer is not None:
        return treffer
    alter_fehler = cache.get(fehler_key)
    if alter_fehler:
        raise MatomoError(alter_fehler)

    try:
        auth = _zugang()
    except MatomoError:
        auth = None
    raus = []
    try:
        for seite in range(1, 6):                       # höchstens 500 Beiträge
            antwort = requests.get(
                f"{_basis()}/wp-json/wp/v2/posts",
                params={"per_page": 100, "page": seite, "_fields": "link,title,date"},
                auth=auth, timeout=getattr(settings, "MATOMO_TIMEOUT", 30),
                headers={"User-Agent": "octovis-matomo-bridge"},
            )
            if antwort.status_code == 400 and seite > 1:
                break                                   # hinter der letzten Seite
            if antwort.status_code >= 400:
                raise MatomoError(f"WordPress posts: HTTP {antwort.status_code}")
            daten = antwort.json()
            if not isinstance(daten, list):
                raise MatomoError("WordPress posts: unexpected answer")
            for b in daten:
                if not isinstance(b, dict) or not b.get("link"):
                    continue
                titel = b.get("title")
                titel = titel.get("rendered", "") if isinstance(titel, dict) else str(titel or "")
                raus.append({"link": b["link"], "titel": html.unescape(titel).strip(),
                             "datum": str(b.get("date") or "")[:10]})
            if len(daten) < 100:
                break
    except MatomoError as e:
        cache.set(fehler_key, str(e), 3600)
        raise
    except (requests.RequestException, ValueError) as e:
        cache.set(fehler_key, f"WordPress posts: {e}", 3600)
        raise MatomoError(f"WordPress posts: {e}")

    cache.set(key, raus, cache_seconds)
    return raus


def hole(pfad: str, *, cache_seconds: int | None = None, **params):
    """Ruft eine Route unterhalb von /wp-json/matomo/v1/ auf.

    pfad    z.B. "api/report_metadata", "api/processed_report", "visits_summary/get"
    params  period, date, apiModule, apiAction, filter_limit, segment, ...
    """
    benutzer, passwort = _zugang()

    daten = {"idSite": getattr(settings, "MATOMO_SITE_ID", "1"),
             "language": getattr(settings, "MATOMO_SPRACHE", "de")}
    daten.update({k: v for k, v in params.items() if v is not None})

    if cache_seconds is None:
        cache_seconds = getattr(settings, "MATOMO_CACHE_SECONDS", 900)

    key = _cache_key(pfad, daten)
    if cache_seconds:
        treffer = cache.get(key)
        if treffer is not None:
            return treffer

    antwort = requests.get(
        f"{_basis()}{NAMENSRAUM}/{pfad.lstrip('/')}",
        params=daten,
        auth=(benutzer, passwort),
        timeout=getattr(settings, "MATOMO_TIMEOUT", 30),
        headers={"User-Agent": "octovis-matomo-bridge"},
    )

    text = antwort.text.strip()
    if not text.startswith(("{", "[")):
        if "wp-login" in text or "Log In" in text:
            raise MatomoError(
                "WordPress rejected the sign-in (login page instead of data). Check the "
                "application password or create a new one in WordPress."
            )
        raise MatomoError(f"No JSON response from {pfad}: {text[:200]}")

    ergebnis = antwort.json()

    if isinstance(ergebnis, dict):
        if ergebnis.get("result") == "error":
            raise MatomoError(f"{pfad}: {ergebnis.get('message')}")
        if ergebnis.get("code") and ergebnis.get("message"):
            raise MatomoError(f"{pfad}: {ergebnis['message']} ({ergebnis['code']})")

    if antwort.status_code >= 400:
        raise MatomoError(f"{pfad}: HTTP {antwort.status_code}")

    if cache_seconds:
        cache.set(key, ergebnis, cache_seconds)
    return ergebnis


def report_metadata(*, period="day", date="yesterday", cache_seconds=3600):
    """Liste ALLER Berichte, die Matomo für diese Seite liefern kann.

    Jeder Eintrag hat u.a. module, action, name, category, uniqueId.
    Grundlage dafür, dass der Tab alles zeigt, ohne dass jeder Bericht
    einzeln programmiert werden muss.
    """
    daten = hole("api/report_metadata", period=period, date=date,
                 cache_seconds=cache_seconds)
    return daten if isinstance(daten, list) else []


def report(module: str, action: str, *, period="day", date="yesterday",
           flat=1, filter_limit=100, segment=None, cache_seconds=None, **weitere):
    """Einen einzelnen Bericht abrufen, so wie ihn report_metadata beschreibt.

    Liefert die processed_report-Antwort: ein dict mit u.a.
    'metadata' (Name, Kategorie), 'columns' (schöne Spaltentitel) und
    'reportData' (die eigentlichen Zeilen).
    """
    return hole("api/processed_report",
                apiModule=module, apiAction=action,
                period=period, date=date, flat=flat,
                filter_limit=filter_limit, segment=segment,
                cache_seconds=cache_seconds, **weitere)


def kennzahlen(*, period="day", date="yesterday", segment=None, cache_seconds=None):
    """Kopfzahlen: Besuche, Besucher, Seitenaufrufe, Absprungrate, Verweildauer."""
    return hole("visits_summary/get", period=period, date=date,
                segment=segment, cache_seconds=cache_seconds)


def verlauf(*, tage="last30", cache_seconds=None):
    """Besuche je Tag für die Kurve auf der Übersicht."""
    return hole("visits_summary/visits", period="day", date=tage,
                cache_seconds=cache_seconds)
