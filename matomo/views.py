from __future__ import annotations

import datetime as dt
import hashlib
import json

from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import connection
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import auswertung as aw
from . import client
from .models import MatomoLauf, MatomoSnapshot

# Spalten, die in den Tabellen nur Ballast sind
VERSTECKT = {
    "idsubdatatable", "segment", "subtable", "logo", "logoWidth", "logoHeight",
    "logo_width", "logo_height", "idaction", "sum_daily_nb_uniq_visitors",
    "revenue", "goals", "nb_conversions", "nb_visits_converted",
}

# Verhältniszahlen: über mehrere Tage aufsummiert wären sie schlicht falsch.
# Beim Zusammenrechnen eines Zeitraums fallen sie deshalb weg.
NICHT_SUMMIERBAR = {
    "bounce_rate", "exit_rate", "conversion_rate", "avg_time_on_site",
    "avg_time_on_page", "avg_page_load_time", "avg_time_generation",
    "nb_actions_per_visit", "avg_time_network", "avg_time_server",
    "avg_time_transfer", "avg_time_dom_processing", "avg_time_dom_completion",
    "avg_time_on_load", "avg_bandwidth",
}

WOCHENTAGE = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]

MAX_TAGE = 400          # Schutz vor versehentlich riesigen Abfragen
BESUCHS_LIMIT = 2000    # so viele Einzelbesuche holen wir höchstens


# ── Orte, die nicht mitzählen (30.09.2026) ───────────────────────────────
#
# Ortrud: „Herzogenaurach und Wasserburg am Inn für die Statistik rausrechnen.“
# Eine kleine Tabelle statt eines Django-Modells: Render führt beim Deploy kein
# migrate aus, eine neue Modelltabelle käme dort nie an. Die Tabelle legt sich
# beim ersten Aufruf selbst an, mit den beiden Orten als Startliste - genau
# einmal; wer später alle entfernt, bekommt sie nicht wieder aufgedrängt.
ORTE_START = ("Herzogenaurach", "Wasserburg am Inn")
_orte_tabelle_da = False


def _orte_tabelle():
    global _orte_tabelle_da
    if _orte_tabelle_da:
        return
    with connection.cursor() as c:
        c.execute("SHOW TABLES LIKE 'matomo_orte_raus'")
        if c.fetchone() is None:
            c.execute("""CREATE TABLE matomo_orte_raus (
                             id INT AUTO_INCREMENT PRIMARY KEY,
                             stadt VARCHAR(120) NOT NULL UNIQUE,
                             angelegt DATETIME DEFAULT CURRENT_TIMESTAMP
                         ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
            for ort in ORTE_START:
                c.execute("INSERT INTO matomo_orte_raus (stadt) VALUES (%s)", [ort])
    _orte_tabelle_da = True


def ausgeschlossene_orte():
    """Die Städte, deren Besuche nicht mitzählen, alphabetisch."""
    try:
        _orte_tabelle()
        with connection.cursor() as c:
            c.execute("SELECT stadt FROM matomo_orte_raus ORDER BY stadt")
            return [r[0] for r in c.fetchall()]
    except Exception as e:
        print("matomo, excluded places:", e)
        return []


def ort_normal(stadt):
    """Comparison form of a city: case, spaces and a district in brackets ignored
    ('Wasserburg am Inn (Gabersee)' falls under the rule 'Wasserburg am Inn')."""
    return aw.place_key(stadt)


def orte_filtern(besuche, orte):
    """(kept, left out) - a visit drops out when a location rule covers its city."""
    raus = {ort_normal(o) for o in orte if ort_normal(o)}
    if not raus:
        return list(besuche), 0
    behalten = [b for b in besuche if ort_normal(b.get("stadt")) not in raus]
    return behalten, len(besuche) - len(behalten)


class Besuche(list):
    """Die Besuchsliste, dazu was beim Holen auffiel.

    roh       - so viele Besuche hat Matomo geliefert (für „abgeschnitten“)
    versteckt - so viele davon kamen aus einem ausgeschlossenen Ort
    ev        - die gemeinsame Auswertung, aus der die Liste stammt
    """
    roh = 0
    versteckt = 0
    ev = None


def _alle_orte(request):
    """?alle_orte=1 - die ausgeschlossenen Orte ausnahmsweise mitzählen."""
    return request.GET.get("alle_orte") == "1"


def _orte_kontext(request, besuche):
    """Was die aufklappbare Liste „Left out of the statistics“ braucht."""
    ohne = request.GET.copy()
    ohne.pop("alle_orte", None)
    mit = request.GET.copy()
    mit["alle_orte"] = "1"
    return {
        "orte_liste": ausgeschlossene_orte(),
        "orte_versteckt": getattr(besuche, "versteckt", 0),
        "alle_orte": _alle_orte(request),
        "orte_link_mit": "?" + mit.urlencode(),
        "orte_link_ohne": "?" + ohne.urlencode(),
        "orte_zurueck": request.get_full_path(),
    }


def _abgeschnitten(besuche):
    return getattr(besuche, "roh", len(besuche)) >= BESUCHS_LIMIT


@require_POST
@login_required
def orte_aendern(request):
    """Einen Ort in die Liste aufnehmen oder wieder herausnehmen."""
    stadt = " ".join((request.POST.get("stadt") or "").split())[:120]
    aktion = request.POST.get("aktion")
    if stadt and aktion in ("dazu", "weg"):
        _orte_tabelle()
        with connection.cursor() as c:
            if aktion == "dazu":
                c.execute("SELECT stadt FROM matomo_orte_raus")
                if ort_normal(stadt) not in {ort_normal(r[0]) for r in c.fetchall()}:
                    c.execute("INSERT INTO matomo_orte_raus (stadt) VALUES (%s)", [stadt])
            else:
                c.execute("DELETE FROM matomo_orte_raus WHERE stadt = %s", [stadt])
    zurueck = request.POST.get("zurueck") or ""
    if not zurueck.startswith("/webstats/"):
        zurueck = "/webstats/"
    return redirect(zurueck)


# ── Zeitraum ─────────────────────────────────────────────────────────────

def _zeitfenster(request):
    """Liest von/bis aus dem Formular. Standard: die letzten 30 Tage."""
    heute = dt.datetime.now(aw.TZ).date()
    hinweis = None

    def lese(name, ersatz):
        roh = request.GET.get(name)
        if not roh:
            return ersatz
        try:
            return dt.date.fromisoformat(roh)
        except ValueError:
            return ersatz

    bis = lese("bis", heute)
    von = lese("von", bis - dt.timedelta(days=29))

    if von > bis:
        von, bis = bis, von
        hinweis = "From and To were swapped — I put them back in order."
    if bis > heute:
        bis = heute
    if (bis - von).days > MAX_TAGE:
        von = bis - dt.timedelta(days=MAX_TAGE)
        hinweis = f"Range limited to {MAX_TAGE} days."
    return von, bis, hinweis


def _spanne_text(von, bis):
    return f"{von.isoformat()},{bis.isoformat()}"


# ── Archivierte Berichte über einen Zeitraum zusammenrechnen ─────────────
#
# Matomo beantwortet period="range" auf dieser Installation nicht (die
# Vorberechnung freier Zeitspannen ist abgeschaltet, es kämen leere Berichte).
# Deshalb holen wir die Tage einzeln - period="day" mit "von,bis" liefert alle
# in einer Antwort - und addieren sie hier.

def _zahl(wert):
    try:
        return int(wert or 0)
    except (TypeError, ValueError):
        try:
            return float(wert)
        except (TypeError, ValueError):
            return None


def _tagesberichte(roh):
    """Zerlegt die Antwort in einzelne Tagesberichte (für Titel und Metadaten)."""
    if isinstance(roh, dict):
        if "reportData" in roh or "metadata" in roh:
            return [roh]
        werte = [v for v in roh.values() if isinstance(v, dict)]
        if werte and all("reportData" in v or "columns" in v for v in werte):
            return werte
    return []


def _datenquellen(inhalt, zeilenlisten, kennzahlen):
    """Sammelt aus einer beliebig verschachtelten Antwort Zeilen und Kennzahlen.

    Matomo verpackt einen Zeitraum je nach Bericht unterschiedlich:
    reportData ist entweder eine Liste von Zeilen (ein Tag), ein Verzeichnis
    Datum -> Zeilenliste (mehrere Tage) oder ein Verzeichnis von Kennzahlen.
    Diese Funktion löst alle drei Fälle auf.
    """
    if isinstance(inhalt, list):
        zeilenlisten.append([z for z in inhalt if isinstance(z, dict)])
    elif isinstance(inhalt, dict):
        if inhalt and all(isinstance(v, (list, dict)) for v in inhalt.values()):
            for wert in inhalt.values():
                _datenquellen(wert, zeilenlisten, kennzahlen)
        elif inhalt:
            kennzahlen.append(inhalt)


def _summiere(roh):
    """Addiert alles, was in der Antwort steckt, zu einer Tabelle: (Spalten, Zeilen)."""
    tage = _tagesberichte(roh)
    if not tage:
        return [], []

    titel = {}
    zeilenlisten, kennzahlsaetze = [], []
    for t in tage:
        titel.update(t.get("columns") or {})
        _datenquellen(t.get("reportData"), zeilenlisten, kennzahlsaetze)

    gesammelt, reihenfolge = {}, []
    for zeilen in zeilenlisten:
        for zeile in zeilen:
            name = zeile.get("label", "")
            if name not in gesammelt:
                gesammelt[name] = {}
                reihenfolge.append(name)
            for k, v in zeile.items():
                if k == "label" or k in VERSTECKT or k in NICHT_SUMMIERBAR:
                    continue
                n = _zahl(v)
                if n is None:
                    gesammelt[name].setdefault(k, v)
                else:
                    vorher = gesammelt[name].get(k)
                    gesammelt[name][k] = (vorher if isinstance(vorher, (int, float)) else 0) + n

    if not gesammelt and kennzahlsaetze:
        summen = {}
        for satz in kennzahlsaetze:
            for k, v in satz.items():
                if k in VERSTECKT or k in NICHT_SUMMIERBAR:
                    continue
                n = _zahl(v)
                if n is None:
                    summen.setdefault(k, v)
                else:
                    vorher = summen.get(k)
                    summen[k] = (vorher if isinstance(vorher, (int, float)) else 0) + n
        return ["Metric", "Value"], [[titel.get(k, k), v] for k, v in summen.items()]

    if not gesammelt:
        return [], []

    schluessel = []
    for werte in gesammelt.values():
        for k in werte:
            if k not in schluessel:
                schluessel.append(k)

    zeilen = [[name] + [gesammelt[name].get(k, 0) for k in schluessel] for name in reihenfolge]
    if schluessel:
        zeilen.sort(key=lambda z: (-(z[1] if isinstance(z[1], (int, float)) else 0), str(z[0])))

    spalten = ["Name"] + [titel.get(k, k) for k in schluessel]
    return spalten, zeilen


def _bloecke(von, bis, definitionen, flach=0, limit=100):
    """Holt mehrere Berichte für den Zeitraum. Ein Fehler kippt nur seinen Block."""
    datum = _spanne_text(von, bis)
    ergebnis = []
    for titel, modul, aktion, hinweis in definitionen:
        eintrag = {"titel": titel, "modul": modul, "aktion": aktion,
                   "hinweis": hinweis, "spalten": [], "zeilen": [], "fehler": None}
        try:
            roh = client.report(modul, aktion, period="day", date=datum,
                                filter_limit=limit, flat=flach)
            eintrag["spalten"], eintrag["zeilen"] = _summiere(roh)
        except Exception as e:
            eintrag["fehler"] = str(e)
        ergebnis.append(eintrag)
    return ergebnis


# ── Visit log: one evaluation for every view (05.10.2026) ────────────────

def _erstes(quelle, *namen):
    """First non-empty value among several possible field names."""
    for name in namen:
        wert = quelle.get(name)
        if wert not in (None, "", "Unknown", "unknown"):
            return wert
    return None


# Own / test devices: visitor IDs marked by hand. More reliable than a place -
# a place rule also hides strangers from the same town, and misses the laptop
# on the train.
_eigene_tabelle_da = False


def _eigene_tabelle():
    global _eigene_tabelle_da
    if _eigene_tabelle_da:
        return
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS matomo_eigene_besucher (
                         besucher VARCHAR(32) NOT NULL PRIMARY KEY,
                         notiz VARCHAR(120) NOT NULL DEFAULT '',
                         angelegt DATETIME DEFAULT CURRENT_TIMESTAMP
                     ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
    _eigene_tabelle_da = True


def eigene_besucher():
    """[(visitor ID, note)] marked as own / test device."""
    try:
        _eigene_tabelle()
        with connection.cursor() as c:
            c.execute("SELECT besucher, notiz FROM matomo_eigene_besucher ORDER BY angelegt")
            return [(r[0], r[1]) for r in c.fetchall()]
    except Exception as e:
        print("matomo, own devices:", e)
        return []


@require_POST
@login_required
def eigen_aendern(request):
    """Mark a visitor ID as own / test device, or take the mark back."""
    kennung = "".join(ch for ch in (request.POST.get("besucher") or "") if ch.isalnum())[:32]
    aktion = request.POST.get("aktion")
    if kennung and aktion in ("dazu", "weg"):
        _eigene_tabelle()
        with connection.cursor() as c:
            if aktion == "dazu":
                c.execute("INSERT IGNORE INTO matomo_eigene_besucher (besucher, notiz) VALUES (%s, %s)",
                          [kennung, (request.POST.get("notiz") or "")[:120]])
            else:
                c.execute("DELETE FROM matomo_eigene_besucher WHERE besucher = %s", [kennung])
    zurueck = request.POST.get("zurueck") or ""
    if not zurueck.startswith("/webstats/"):
        zurueck = "/webstats/"
    return redirect(zurueck)


def wp_katalog():
    """(Catalogue, info): what WordPress says is an article, a page, an overview."""
    info = {"wordpress": None, "seiten": None, "fehler": ""}
    posts, pages, ok = [], [], True
    try:
        posts = client.blog_beitraege()
        info["wordpress"] = len(posts)
    except Exception as e:
        info["fehler"], ok = str(e), False
    try:
        pages = client.wp_seiten()
        info["seiten"] = len(pages)
    except Exception as e:
        info["fehler"] = info["fehler"] or str(e)
        ok = False
    return aw.Catalogue(posts=posts, pages=pages, manual=blog_eigene(), wordpress_ok=ok), info


def _einstellungen():
    from planner import utm
    return aw.Settings(
        places=ausgeschlossene_orte(),
        own_ids={k for k, _ in eigene_besucher()},
        offer_pages=tuple(getattr(settings, "MATOMO_OFFER_PAGES", aw.OFFER_PAGES)),
        contact_pages=tuple(getattr(settings, "MATOMO_CONTACT_PAGES", aw.CONTACT_PAGES)),
        linkedin_campaigns=(utm.CAMPAIGN,),
    )


def _rohprotokoll(von, bis, cache_seconds=300):
    """Raw visits for von..bis in Europe/Berlin.

    Matomo keeps its days in the site's time zone (UTC on octotrial.com), so
    one day more is fetched at the start; aw.evaluate cuts by local date.
    """
    roh = client.hole("live/last_visits_details", period="day",
                      date=_spanne_text(von - dt.timedelta(days=1), bis),
                      filter_limit=BESUCHS_LIMIT, cache_seconds=cache_seconds)
    return aw.normalise_raw(roh)


def _umfang(request):
    u = request.GET.get("umfang", "human")
    return u if u in aw.SCOPES else "human"


def _auswertung(request, von, bis, cache_seconds=300, katalog=None):
    """(Evaluation, catalogue, catalogue info, error) - the one entry point."""
    if katalog is None:
        katalog = wp_katalog()
    kat, info = katalog
    fehler, roh = None, []
    try:
        roh = _rohprotokoll(von, bis, cache_seconds)
    except Exception as e:
        fehler = str(e)
    ev = aw.evaluate(roh, von, bis, kat, _einstellungen(), scope=_umfang(request),
                     count_places=_alle_orte(request),
                     truncated=len(roh) >= BESUCHS_LIMIT)
    return ev, kat, info, fehler


def _legacy(v):
    """The keys the timeline and goals were written against."""
    seiten = [s for s in v["schritte"] if not s.get("vorschau")]
    v.update({
        "ist_bot": not v.get("im_publikum"),
        "aktionen_liste": [{"typ": s["typ"], "url": s["url"], "titel": s["titel"],
                            "zeit": s.get("zeit")} for s in seiten],
        "aktionen": v["aufrufe"],
        "herkunft": v["quelle"],
        "erste_seite": (v["einstieg"] or {}).get("pfad", ""),
    })
    return v


def _besuchsprotokoll(von, bis, limit=BESUCHS_LIMIT, cache_seconds=300, alle_orte=False,
                      umfang="human"):
    """The evaluated visits as a list, for the timeline and the goals.

    Visits under a location rule are left out of the list (and counted in
    .versteckt), unless alle_orte. Everything else stays in, with ist_bot =
    "not in the audience" - so the callers count exactly what the overview counts.
    """
    roh = _rohprotokoll(von, bis, cache_seconds)
    kat, _info = wp_katalog()
    ev = aw.evaluate(roh, von, bis, kat, _einstellungen(), scope=umfang,
                     count_places=alle_orte)
    besuche = [_legacy(v) for v in ev.all if alle_orte or not v["ortsregel"]]
    ergebnis = Besuche(besuche)
    ergebnis.ev = ev
    ergebnis.roh = len(roh)
    ergebnis.versteckt = sum(1 for v in ev.all if v["ortsregel"]) if not alle_orte else 0
    return ergebnis


def _ausschluss_summe(ev):
    """The countable part of the exclusions - small enough to cache."""
    alle = ev.all
    orte = ausgeschlossene_orte()
    return {
        "gruende": {
            "automation": sum(1 for v in alle if v["klasse"] == aw.AUTOMATION),
            "unclear": sum(1 for v in alle if v["klasse"] == aw.UNCLEAR),
            "own": sum(1 for v in alle if v["klasse"] == aw.OWN),
            "preview": sum(1 for v in alle if v["bearbeitung"]),
            "places": sum(1 for v in alle if v["ortsregel"]),
        },
        "varianten": aw.place_variants(alle, orte),
        "ausgeschlossen": len(alle) - len(ev.audience),
        "gesamt": len(alle),
        "umfang": ev.scope,
        "alle_orte": ev.counted_places,
    }


def _ausschluss_kontext(request, ev=None, summe=None):
    """What the fold-out "Exclusions and classification" needs."""
    summe = summe or _ausschluss_summe(ev)
    mit = request.GET.copy()
    mit["alle_orte"] = "1"
    ohne = request.GET.copy()
    ohne.pop("alle_orte", None)
    zeigen = request.GET.copy()
    zeigen["ausgeschlossen"] = "1"
    for k in ("tag", "stunde"):
        zeigen.pop(k, None)
    ohne_kurz = request.GET.copy()
    for k in ("teil", "tag", "stunde", "klasse"):
        ohne_kurz.pop(k, None)
    return {
        "orte_liste": ausgeschlossene_orte(),
        "orte_varianten": summe["varianten"],
        "orte_versteckt": 0 if summe["alle_orte"] else summe["gruende"]["places"],
        "alle_orte": summe["alle_orte"],
        "orte_link_mit": "?" + mit.urlencode(),
        "orte_link_ohne": "?" + ohne.urlencode(),
        "orte_zurueck": request.get_full_path(),
        "eigene": eigene_besucher(),
        "regeln": aw.RULES,
        "klassen": aw.CLASSES,
        "gruende": summe["gruende"],
        "gesamt_alle": summe["gesamt"],
        "ausgeschlossen_zahl": summe["ausgeschlossen"],
        "ausgeschlossen_link": reverse("matomo:besucher") + "?" + zeigen.urlencode(),
        "besucher_link": reverse("matomo:besucher") + "?" + ohne_kurz.urlencode(),
        "gezaehlt_zahl": summe["gesamt"] - summe["ausgeschlossen"],
        "umfang": summe["umfang"],
        "umfaenge": [(k, v[0]) for k, v in aw.SCOPES.items()],
        "zeige_umfang": True,
        "zeitzone": aw.TIMEZONE,
    }


def _verlauf(besuche, von, bis):
    """Visits per day, one line per class. Drawn in the browser so a line can be
    hidden and the axis rescales. Days without visits are zero, not skipped."""
    tage = []
    d = von
    while d <= bis:
        tage.append(d)
        d += dt.timedelta(days=1)
    if len(tage) < 2:
        return None
    felder = {aw.HUMAN: "menschen", aw.UNCLEAR: "unklar", aw.AUTOMATION: "bots"}
    zaehler = {t.isoformat(): dict.fromkeys(felder.values(), 0) for t in tage}
    for b in besuche:
        eintrag = zaehler.get(b.get("datum"))
        feld = felder.get(b["klasse"])
        if eintrag is not None and feld:
            eintrag[feld] += 1
    daten = []
    for t in tage:
        daten.append({
            "datum": t.isoformat(),
            "lang": f"{WOCHENTAGE[t.weekday()]}, {t.strftime('%d.%m.%Y')}",
            "kurz": t.strftime("%d.%m."),
            "ersterImMonat": t.day == 1, "istMontag": t.weekday() == 0,
            **zaehler[t.isoformat()],
        })
    # Colours checked with the dataviz validator (September 2026); grey for "unclear".
    reihen = [("menschen", "Humans", "#0093A1"), ("unklar", "Unclear", "#8C9593"),
              ("bots", "Bots", "#F56E28")]
    return {"daten": daten, "tage": len(tage),
            "reihen": [{"feld": f, "name": n, "farbe": c, "summe": sum(x[f] for x in daten)}
                       for f, n, c in reihen]}


def _stundenraster(besuche):
    """Two 7 x 24 grids (Europe/Berlin), humans and bots, one shared scale.

    "Unclear" visits are in neither grid - a single page without a measurable
    time is not proof of a bot - and are counted below the grids instead.
    """
    zaehler = {aw.HUMAN: {tag: [0] * 24 for tag in WOCHENTAGE},
               aw.AUTOMATION: {tag: [0] * 24 for tag in WOCHENTAGE}}
    ohne_zeit = unklar = 0
    for b in besuche:
        tag, stunde = b.get("wochentag"), b.get("stunde", "")
        if b["klasse"] not in zaehler:
            unklar += b["klasse"] == aw.UNCLEAR
            continue
        if tag not in WOCHENTAGE or not stunde[:2].isdigit():
            ohne_zeit += 1
            continue
        zaehler[b["klasse"]][tag][int(stunde[:2])] += 1
    hoechstwert = max((w for art in zaehler.values() for stunden in art.values()
                       for w in stunden), default=0)

    def baue(klasse, art, titel):
        zeilen = []
        for tag in WOCHENTAGE:
            felder = [{"stunde": stunde, "stunde_text": f"{stunde:02d}:00", "anzahl": anzahl,
                       "deckkraft": round(0.18 + 0.82 * anzahl / hoechstwert, 2) if hoechstwert else 0}
                      for stunde, anzahl in enumerate(zaehler[klasse][tag])]
            zeilen.append({"tag": tag, "kurz": tag[:2], "felder": felder,
                           "summe": sum(f["anzahl"] for f in felder)})
        return {"art": art, "titel": titel, "klasse": klasse,
                "ausgeschlossen": klasse == aw.AUTOMATION,
                "zeilen": zeilen, "summe": sum(z["summe"] for z in zeilen)}

    return {"menschen": baue(aw.HUMAN, "menschen", "Humans"),
            "bots": baue(aw.AUTOMATION, "bots", "Bots"),
            "hoechstwert": hoechstwert, "ohne_zeit": ohne_zeit, "unklar": unklar}


def _zeitraum_kontext(von, bis, hinweis):
    return {"von": von.isoformat(), "bis": bis.isoformat(), "hinweis": hinweis,
            "tage": (bis - von).days + 1, "zeitzone": aw.TIMEZONE}


def _planner_posts(ids):
    """{planner id: {'titel', 'datum', 'kanal'}} for the LinkedIn rows."""
    ids = [i for i in ids if isinstance(i, int)]
    if not ids:
        return {}
    try:
        with connection.cursor() as c:
            platz = ",".join(["%s"] * len(ids))
            c.execute(f"SELECT id, title, planned_date, COALESCE(is_oj,0) FROM planner_posts "
                      f"WHERE id IN ({platz})", ids)
            return {r[0]: {"titel": r[1] or f"Post #{r[0]}",
                           "datum": r[2].strftime("%d.%m.%Y") if r[2] else "",
                           "kanal": "Personal profile" if r[3] else "Company page"}
                    for r in c.fetchall()}
    except Exception as e:
        print("matomo, planner posts:", e)
        return {}


def _diagnose(ev):
    """Technical detail, folded away on the overview."""
    alle = ev.all
    return [
        {"titel": "Places", "hinweis": "City and country are approximate, estimated from the "
                                      "IP address (a VPN shows the server's place). Never use "
                                      "them to identify a person.",
         **aw.frequencies(alle, ("stadt", "land"), ["City", "Country"])},
        {"titel": "Browsers", "hinweis": "", **aw.frequencies(alle, "browser", ["Browser"])},
        {"titel": "Operating systems", "hinweis": "",
         **aw.frequencies(alle, "system", ["System"])},
        {"titel": "Browser language", "hinweis": "",
         **aw.frequencies(alle, "sprache", ["Language"])},
        {"titel": "Device type", "hinweis": "", **aw.frequencies(alle, "geraet", ["Device"])},
    ]


# ── Views ────────────────────────────────────────────────────────────────

@login_required
def uebersicht(request):
    """Four figures and the three analyses - nothing else (05.10.2026)."""
    von, bis, hinweis = _zeitfenster(request)
    ev, kat, kat_info, fehler = _auswertung(request, von, bis)
    publikum = ev.audience
    artikel = aw.by_article(publikum, kat, _einstellungen())
    uebersichten, unzugeordnet = aw.overviews_and_unassigned(publikum, kat)
    posts = aw.by_post(publikum)
    infos = _planner_posts([r["post_id"] for r in posts])
    for r in posts:
        if r["post_id"] in infos:
            r.update(infos[r["post_id"]])
    return render(request, "matomo/uebersicht.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "k": aw.kpis(ev),
        "klein": len(publikum) < 30,
        "quellen": aw.by_source(publikum),
        "unbekannt_erklaert": aw.UNKNOWN_EXPLAINED,
        "artikel": artikel,
        "artikel_gelesen": sum(1 for a in artikel if a["aufrufe"]),
        "uebersichten": uebersichten,
        "unzugeordnet": unzugeordnet,
        "kat_info": kat_info,
        "blog_eigene": blog_eigene(),
        "posts": posts, "hat_utm": any(v["utm"] for v in ev.all),
        "angebotsseiten": _einstellungen().offer_pages,
        "kontaktseiten": _einstellungen().contact_pages,
        "letzter_lauf": MatomoLauf.objects.first(),
        "abgeschnitten": ev.truncated,
        **_ausschluss_kontext(request, ev),
        "ausschluss_kurz": True,
        "fehler": fehler,
    })


@login_required
def besucher(request):
    """Humans and bots per day, when they come, and every visit with its path.

    The rules and exclusions live here (and only here); the overview links to it.
    """
    von, bis, hinweis = _zeitfenster(request)
    ev, kat, _info, fehler = _auswertung(request, von, bis)
    zeige_aus = request.GET.get("ausgeschlossen") == "1"

    # The curve and the grids show the visitors of the site: without own
    # devices, editing visits with a preview, and (unless counted) the places.
    sonder = [v for v in ev.all if v["klasse"] == aw.OWN or v["bearbeitung"]
              or (v["ortsregel"] and not ev.counted_places)]
    sonder_ids = {id(v) for v in sonder}
    kurve = [v for v in ev.all if id(v) not in sonder_ids]
    klassen = {k: sum(1 for v in kurve if v["klasse"] == k) for k in aw.CLASSES}

    besuche = ev.all if zeige_aus else ev.audience
    klasse = request.GET.get("klasse", "")
    klasse = klasse if klasse in aw.CLASSES else ""
    if klasse:
        besuche = [b for b in besuche if b["klasse"] == klasse]
    tag = request.GET.get("tag", "")
    tag = tag if tag in WOCHENTAGE else ""
    stunde = request.GET.get("stunde", "")
    stunde = stunde if stunde.isdigit() and 0 <= int(stunde) <= 23 else ""
    if tag:
        besuche = [b for b in besuche if b["wochentag"] == tag]
    if stunde:
        besuche = [b for b in besuche if b["stunde"][:2] == f"{int(stunde):02d}"]

    ohne_filter = request.GET.copy()
    for k in ("tag", "stunde", "klasse"):
        ohne_filter.pop(k, None)
    gezaehlt = request.GET.copy()
    gezaehlt.pop("ausgeschlossen", None)
    return render(request, "matomo/besucher.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "besuche": besuche, "zeige_aus": zeige_aus,
        "tag": tag, "stunde": stunde, "klasse_filter": aw.CLASSES.get(klasse, ""),
        "filter_weg": "?" + ohne_filter.urlencode(),
        "nur_gezaehlt": "?" + gezaehlt.urlencode(),
        "k": aw.kpis(ev),
        "kl": klassen, "sonder": len(sonder),
        "verlauf": _verlauf(kurve, von, bis),
        "raster": _stundenraster(kurve),
        "diagnose": _diagnose(ev),
        "unbekannt_erklaert": aw.UNKNOWN_EXPLAINED,
        "abgeschnitten": ev.truncated,
        **_ausschluss_kontext(request, ev),
        "fehler": fehler,
    })


@login_required
def besucher_profil(request, kennung):
    """Everything Matomo knows about one visitor ID, evaluated like everywhere else."""
    fehler, profil, besuche = None, {}, []
    try:
        profil = client.hole("live/visitor_profile", visitorId=kennung, cache_seconds=120)
        if not isinstance(profil, dict):
            profil, fehler = {}, "Unexpected response from Matomo."
    except Exception as e:
        fehler = str(e)
    kat, _info = wp_katalog()
    einst = _einstellungen()
    for b in (profil.get("lastVisits") or []):
        if isinstance(b, dict):
            besuche.append(aw.prepare(b, kat, einst))
    eigen = kennung in einst.own_ids
    return render(request, "matomo/besucher_profil.html", {
        "kennung": kennung, "profil": profil, "besuche": besuche,
        "eigen": eigen, "vorschau": any(v["bearbeitung"] for v in besuche),
        "klassen": aw.CLASSES, "zeitzone": aw.TIMEZONE,
        "zurueck": request.GET.get("zurueck", ""),
        "hier": request.get_full_path(),
        "fehler": fehler,
    })


@login_required
def protokoll(request):
    """The former Log tab: the visit table now lives under Visitors."""
    ziel = request.GET.copy()
    nur = ziel.pop("nur", ["alle"])[-1]
    if nur in ("alle", "bots"):
        ziel["ausgeschlossen"] = "1"
    return redirect(reverse("matomo:besucher") + ("?" + ziel.urlencode() if ziel else ""))


MATOMO_BERICHT_HINWEIS = (
    "Matomo's finished reports: they count every visit Matomo kept - including the "
    "excluded places, previews, own visits and automated visits - and their days are "
    "Matomo's site days (UTC). Their numbers are therefore not directly comparable "
    "with Overview, Visitors and Timeline.")


# ── Matomo's own reports: one tab, three parts (05.10.2026) ──────────────
#
# Pages, Search terms and AI were three tabs with the same kind of content:
# Matomo's finished reports, on Matomo's data basis. Now one tab; only the
# chosen part is fetched, so the page stays as fast as one of the old tabs.

BERICHTE_TEILE = {
    "seiten": ("Pages", "Which content on octotrial.com was opened.", 1, 200, [
        ("Most visited pages", "Actions", "getPageUrls",
         "By address. “Unique pageviews” counts a visit once, even if someone opened "
         "the page several times."),
        ("Page titles", "Actions", "getPageTitles",
         "The same views, by heading instead of address — usually easier to read."),
        ("Entry pages", "Actions", "getEntryPageUrls",
         "Where visitors arrive."),
        ("Exit pages", "Actions", "getExitPageUrls", "Where they leave again."),
        ("Clicks on outgoing links", "Actions", "getOutlinks", ""),
        ("Downloaded files", "Actions", "getDownloads", ""),
    ]),
    "suche": ("Search terms", "What visitors searched for before they landed on octotrial.com.", 0, 100, [
        ("Search terms from search engines", "Referrers", "getKeywords",
         "Google and most other search engines have not passed on the search term for "
         "years. What you see here is a fraction — the rest shows up as "
         "“Keyword not defined”."),
        ("Search engines", "Referrers", "getSearchEngines",
         "Which search engines visitors came from — whether or not the term was passed on."),
        ("Search on your own site", "Actions", "getSiteSearchKeywords",
         "What visitors typed into the search box on octotrial.com. Stays empty if site "
         "search is not configured in Matomo."),
    ]),
    "ki": ("AI", "Visitors from AI assistants, and the AI bots that read octotrial.com.", 1, 150, [
        ("Visitors who came via an AI assistant", "Referrers", "getAIAssistants",
         "Real people: someone asked ChatGPT, Perplexity or similar, was given "
         "octotrial.com as a source, and clicked."),
        ("AI chatbots at a glance", "BotTracking", "get",
         "From here on it is about the bots themselves. They do NOT appear in the other "
         "tabs — Matomo keeps them out of the regular visitor statistics."),
        ("Which AI chatbots", "BotTracking", "getAIChatbotRequests",
         "GPTBot, ClaudeBot, PerplexityBot and relatives."),
        ("Pages read by bots", "BotTracking", "getAIChatbotContentPages", ""),
        ("Pages favoured by bots", "BotTracking", "getAIChatbotAIFavouredPages",
         "Content AI systems fetch more often than average."),
        ("Pages favoured by humans", "BotTracking", "getAIChatbotHumanFavouredPages",
         "The counter-check: what humans read but bots ignore."),
        ("Broken pages and documents", "BotTracking", "getAIChatbotBrokenContent",
         "Addresses where bots hit errors — usually broken for visitors too."),
        ("Documents fetched by bots", "BotTracking", "getAIChatbotContentDocuments",
         "PDFs and other files."),
        ("AI agent visits", "AIAgents", "get", "Agents acting on behalf of a user."),
    ]),
}


@login_required
def berichte(request):
    """Matomo's own reports: Pages, Search terms, AI, and the list of all reports."""
    von, bis, hinweis = _zeitfenster(request)
    teil = request.GET.get("teil", "seiten")
    if teil not in BERICHTE_TEILE and teil != "alle":
        teil = "seiten"
    bloecke, kategorien, fehler = [], {}, None
    if teil == "alle":
        try:
            for b in client.report_metadata(period="day", date=bis.isoformat()):
                kategorien.setdefault(b.get("category") or "Other", []).append(b)
        except Exception as e:
            fehler = str(e)
        titel, untertitel = "All reports", ("Every report Matomo offers for octotrial.com - "
                                            "enable a plugin there and its reports show up here.")
    else:
        titel, untertitel, flach, limit, definitionen = BERICHTE_TEILE[teil]
        bloecke = _bloecke(von, bis, definitionen, flach=flach, limit=limit)
    teile = [(k, v[0]) for k, v in BERICHTE_TEILE.items()] + [("alle", "All reports")]
    return render(request, "matomo/bloecke.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "seitentitel": "Matomo reports", "teil": teil, "teile": teile,
        "teil_titel": titel, "untertitel": untertitel,
        "bloecke": bloecke, "kategorien": dict(sorted(kategorien.items())),
        "anzahl_berichte": sum(len(v) for v in kategorien.values()),
        "datenbasis": MATOMO_BERICHT_HINWEIS, "mitnehmen_teil": teil,
        "fehler": fehler,
    })


def _weiter(request, ziel, **extra):
    """Old addresses keep working: same period, new place."""
    q = request.GET.copy()
    for k, v in extra.items():
        q[k] = v
    return redirect(reverse(ziel) + ("?" + q.urlencode() if q else ""))


@login_required
def seiten(request):
    return _weiter(request, "matomo:berichte", teil="seiten")


@login_required
def suchbegriffe(request):
    return _weiter(request, "matomo:berichte", teil="suche")


@login_required
def ki(request):
    return _weiter(request, "matomo:berichte", teil="ki")


@login_required
def bericht(request, modul, aktion):
    """Ein einzelner Bericht aus dem Verzeichnis."""
    von, bis, hinweis = _zeitfenster(request)
    try:
        limit = min(int(request.GET.get("limit", 100)), 1000)
    except ValueError:
        limit = 100

    fehler, spalten, zeilen, titel = None, [], [], ""
    try:
        roh = client.report(modul, aktion, period="day", date=_spanne_text(von, bis),
                            filter_limit=limit)
        tage = _tagesberichte(roh)
        if tage:
            titel = (tage[0].get("metadata") or {}).get("name", "") or ""
        spalten, zeilen = _summiere(roh)
    except Exception as e:
        fehler = str(e)

    return render(request, "matomo/bericht.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "modul": modul, "aktion": aktion, "titel": titel,
        "spalten": spalten, "zeilen": zeilen, "limit": limit,
        "datenbasis": MATOMO_BERICHT_HINWEIS,
        "fehler": fehler,
    })


# Goals (until 05.10.2026) counted the contact page, the offer pages and a few
# actions a second time - Analysis 1 on the overview has them now, per source.
@login_required
def ziele(request):
    return _weiter(request, "matomo:uebersicht")


# ── Zeitleiste: Menschen und Seiten pro Monat (30.09.2026) ───────────────
#
# Ortrud: „eine grafische Übersicht, wie lange welche Seite, wie viele unique
# Besucher, wie viele wiederkehren, und das pro Monat.“ Alles aus dem
# Besuchsprotokoll, nur Menschen, ohne die ausgeschlossenen Orte.
#
# Render-Grenzen (512 MB, knappe Bandbreite): Ein Jahr Protokoll sind einige MB
# JSON. Das Rohprotokoll wird dafür NICHT zwischengespeichert, nur das
# Ergebnis - ein paar KB - für 30 Minuten. Die Seite selbst schickt nur diese
# Zahlen; gezeichnet wird im Browser, ohne Bibliothek.

ZEITLINIE_MONATE = 12      # höchstens so viele Monate auf einmal
ZEITLINIE_STANDARD = 6     # ohne Angabe: die letzten sechs Monate
ZEITLINIE_SEITEN = 12      # so viele Seiten als eigene Zeile, der Rest als „Other pages“
ZEITLINIE_CACHE = 1800
MONATSNAMEN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def monats_anfang(tag, zurueck=0):
    """Der Erste des Monats, `zurueck` Monate vor dem von `tag`."""
    jahr, monat = tag.year, tag.month - zurueck
    while monat < 1:
        monat += 12
        jahr -= 1
    return dt.date(jahr, monat, 1)


def monate_zwischen(von, bis):
    """['2026-04', '2026-05', ...] - jeder Monat, den von..bis berührt."""
    raus, d = [], monats_anfang(von)
    while d <= bis:
        raus.append(f"{d.year}-{d.month:02d}")
        d = monats_anfang(dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1))
    return raus


def seiten_pfad(url):
    """'/services/' aus 'https://octotrial.com/services?x=1#top' - eine Seite, ein Schlüssel."""
    if not url:
        return ""
    pfad = urlsplit(str(url)).path or "/"
    letzter = pfad.rsplit("/", 1)[-1]
    if not pfad.endswith("/") and "." not in letzter:
        pfad += "/"
    return pfad


QUELLEN = ("LinkedIn", "Search", "Direct", "Other")


def quelle_art(besuch):
    """Woher ein Besuch kam, in vier Gruppen: LinkedIn, Search, Direct, Other."""
    gemeinsam = {aw.LINKEDIN: "LinkedIn", aw.SEARCH: "Search", aw.UNKNOWN: "Direct",
                 aw.WEBSITE: "Other", aw.AI: "Other"}.get(besuch.get("quelle"))
    if gemeinsam:
        return gemeinsam
    name = str(besuch.get("herkunft") or "").lower()
    typ = str(besuch.get("herkunft_typ") or "").lower()
    if "linkedin" in name or "lnkd.in" in name:
        return "LinkedIn"
    if typ == "search":
        return "Search"
    if typ == "direct" or name.startswith(("direct", "direkt")):
        return "Direct"
    return "Other"


def _zeit_text(sek):
    return f"{sek // 60}:{sek % 60:02d}" if sek else "–"


def zeitlinie_rechnen(besuche, von, bis, seiten_max=ZEITLINIE_SEITEN, blog=None):
    """Menschen pro Monat (neu / wiederkehrend) und je Seite und Monat
    Unique Besucher, wiederkehrende davon und die mittlere Zeit auf der Seite.

    - unique: verschiedene visitorIds; fünf Besuche einer Person zählen einmal
    - wiederkehrend: in diesem Monat mit einem Besuch, den Matomo als
      „returning“ führt
    - Zeit: timeSpent je Seitenaufruf. Die letzte Seite eines Besuchs hat kein
      Ende, ihre Zeit wäre geraten - sie zählt nicht zum Durchschnitt.

    blog: {pfad: titel} der Blogartikel (30.09.2026). Sie werden in der
    Seitenmatrix zu einer Zeile „Blog – all articles“ und bekommen eine eigene,
    ausführliche Liste - auch Artikel, die im Zeitraum niemand gelesen hat.
    """
    blog = blog or {}
    monate = monate_zwischen(von, bis)
    platz = {m: i for i, m in enumerate(monate)}
    n = len(monate)
    alle = [set() for _ in monate]
    wieder = [set() for _ in monate]
    seiten = {}

    def eintrag(pfad, titel=""):
        e = seiten.get(pfad)
        if e is None:
            e = seiten[pfad] = {"titel": titel,
                                "alle": [set() for _ in monate],
                                "wieder": [set() for _ in monate],
                                "zeit": [0] * n, "gezaehlt": [0] * n,
                                "views": [0] * n, "start": [0] * n,
                                "quelle": [dict.fromkeys(QUELLEN, 0) for _ in monate],
                                "linkedin": set(), "weiter": {}}
        return e

    for pfad in blog:
        eintrag(pfad)

    for b in besuche:
        if b.get("ist_bot"):
            continue
        i = platz.get(str(b.get("datum", ""))[:7])
        if i is None:
            continue
        wer = b.get("besucher") or f"ohne-kennung-{id(b)}"
        kehrt_wieder = bool(b.get("wiederkehrend"))
        alle[i].add(wer)
        if kehrt_wieder:
            wieder[i].add(wer)
        quelle = quelle_art(b)
        aufrufe = [a for a in b.get("aktionen_liste") or []
                   if a.get("typ") == "action" and a.get("url")]
        pfade = [seiten_pfad(a["url"]) for a in aufrufe]
        gesehen = set()
        for k, a in enumerate(aufrufe):
            pfad = pfade[k]
            e = eintrag(pfad, a.get("titel") or "")
            if not e["titel"]:
                e["titel"] = a.get("titel") or ""
            e["alle"][i].add(wer)
            e["views"][i] += 1
            if kehrt_wieder:
                e["wieder"][i].add(wer)
            if k == 0:
                e["start"][i] += 1
            zeit = a.get("zeit")
            if zeit is not None and k < len(aufrufe) - 1:
                e["zeit"][i] += int(zeit)
                e["gezaehlt"][i] += 1
            if k < len(aufrufe) - 1 and pfade[k + 1] != pfad:
                e["weiter"][pfade[k + 1]] = e["weiter"].get(pfade[k + 1], 0) + 1
            # Herkunft je Besuch einmal pro Seite, nicht je Aufruf
            if pfad not in gesehen:
                gesehen.add(pfad)
                e["quelle"][i][quelle] += 1
                if quelle == "LinkedIn":
                    e["linkedin"].add(wer)

    def union(eintraege, feld, i):
        return set().union(*(e[feld][i] for e in eintraege))

    def zeile(name, titel, eintraege):
        u = [len(union(eintraege, "alle", i)) for i in range(n)]
        r = [len(union(eintraege, "wieder", i)) for i in range(n)]
        t = []
        for i in range(n):
            gezaehlt = sum(e["gezaehlt"][i] for e in eintraege)
            # None = not measured; shown as "–", never as 0 seconds.
            t.append(round(sum(e["zeit"][i] for e in eintraege) / gezaehlt) if gezaehlt else None)
        return {"seite": name, "titel": titel, "u": u, "r": r, "t": t}

    def leser_gesamt(eintraege):
        return len(set().union(*(e["alle"][i] for e in eintraege for i in range(n))))

    normal = [p for p in seiten if p not in blog]
    reihenfolge = sorted(normal, key=lambda p: (-leser_gesamt([seiten[p]]), p))
    zeilen = [(leser_gesamt([seiten[p]]), zeile(p, seiten[p]["titel"], [seiten[p]]))
              for p in reihenfolge[:seiten_max]]
    rest = reihenfolge[seiten_max:]
    if blog:
        artikel = [seiten[p] for p in blog]
        zeilen.append((leser_gesamt(artikel),
                       zeile(f"Blog – all articles ({len(blog)})", "", artikel)))
    zeilen.sort(key=lambda z: -z[0])
    zeilen = [z for _, z in zeilen]
    if rest:
        zeilen.append(zeile(f"Other pages ({len(rest)})", "", [seiten[p] for p in rest]))

    # Die Blogliste: eine Zeile je Artikel, ausführlich.
    blogliste = []
    for pfad, titel in blog.items():
        e = seiten[pfad]
        leser = set().union(*e["alle"])
        zurueck = set().union(*e["wieder"])
        gezaehlt = sum(e["gezaehlt"])
        quellen = {q: sum(m[q] for m in e["quelle"]) for q in QUELLEN}
        haupt = max(QUELLEN, key=lambda q: quellen[q]) if any(quellen.values()) else ""
        u = [len(x) for x in e["alle"]]
        hoch = max(u + [1])
        erste = next((monate[i] for i in range(n) if u[i]), "")
        zeit = round(sum(e["zeit"]) / gezaehlt) if gezaehlt else 0
        blogliste.append({
            "seite": pfad, "titel": titel or e["titel"] or pfad,
            "anker": "blog-" + hashlib.sha1(pfad.encode()).hexdigest()[:10],
            "erste": (f"{MONATSNAMEN[int(erste[5:]) - 1]} {erste[:4]}" if erste else ""),
            "leser": len(leser), "wieder": len(zurueck), "views": sum(e["views"]),
            "zeit": zeit, "zeit_text": _zeit_text(zeit), "gemessen": gezaehlt,
            "start": sum(e["start"]), "haupt": haupt, "linkedin": len(e["linkedin"]),
            "balken": [{"hoehe": round(22 * x / hoch) if x else 0, "wert": x,
                        "monat": f"{MONATSNAMEN[int(m[5:]) - 1]} {m[:4]}"}
                       for x, m in zip(u, monate)],
            "monate": [{
                "name": f"{MONATSNAMEN[int(m[5:]) - 1]} {m[:4]}",
                "leser": u[i], "wieder": len(e["wieder"][i]), "views": e["views"][i],
                "zeit_text": _zeit_text(round(e["zeit"][i] / e["gezaehlt"][i]) if e["gezaehlt"][i] else 0),
                "start": e["start"][i],
                "quellen": [e["quelle"][i][q] for q in QUELLEN],
            } for i, m in enumerate(monate)],
            "weiter": sorted(e["weiter"].items(), key=lambda x: (-x[1], x[0]))[:3],
        })
    blogliste.sort(key=lambda z: (-z["leser"], -z["views"], z["seite"]))

    return {
        "monate": [{
            "schluessel": m,
            "name": f"{MONATSNAMEN[int(m[5:]) - 1]} {m[:4]}",
            "kurz": MONATSNAMEN[int(m[5:]) - 1],
            "alle": len(alle[i]), "wieder": len(wieder[i]),
            "neu": len(alle[i]) - len(wieder[i]),
        } for i, m in enumerate(monate)],
        "seiten": zeilen,
        "blog": blogliste,
    }


# ── Welche Adressen Blogartikel sind (30.09.2026) ────────────────────────
#
# Die Artikel liegen direkt unter der Domain wie die Seiten. Erkannt werden sie
# aus WordPress selbst (client.blog_beitraege, einmal am Tag). Dazu eine
# kleine eigene Liste - für den Fall, dass WordPress die Beiträge nicht
# herausgibt, oder für Seiten, die wie ein Artikel zählen sollen.
_blog_tabelle_da = False


def _blog_tabelle():
    global _blog_tabelle_da
    if _blog_tabelle_da:
        return
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS matomo_blog_adressen (
                         id INT AUTO_INCREMENT PRIMARY KEY,
                         pfad VARCHAR(255) NOT NULL UNIQUE,
                         angelegt DATETIME DEFAULT CURRENT_TIMESTAMP
                     ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
    _blog_tabelle_da = True


def blog_eigene():
    """Die im Portal eingetragenen Blog-Adressen."""
    try:
        _blog_tabelle()
        with connection.cursor() as c:
            c.execute("SELECT pfad FROM matomo_blog_adressen ORDER BY pfad")
            return [r[0] for r in c.fetchall()]
    except Exception as e:
        print("matomo, blog addresses:", e)
        return []


def blog_artikel():
    """({pfad: titel}, info) - aus WordPress und der eigenen Liste zusammen."""
    artikel, info = {}, {"wordpress": None, "fehler": ""}
    try:
        beitraege = client.blog_beitraege()
        info["wordpress"] = len(beitraege)
        for b in beitraege:
            pfad = seiten_pfad(b["link"])
            if pfad and pfad != "/":
                artikel[pfad] = b.get("titel") or ""
    except Exception as e:
        info["fehler"] = str(e)
    for pfad in blog_eigene():
        artikel.setdefault(pfad, "")
    return artikel, info


@require_POST
@login_required
def blog_aendern(request):
    """Eine Adresse als Blogartikel eintragen oder wieder austragen."""
    pfad = seiten_pfad((request.POST.get("pfad") or "").strip())[:255]
    aktion = request.POST.get("aktion")
    if pfad and pfad != "/" and aktion in ("dazu", "weg"):
        _blog_tabelle()
        with connection.cursor() as c:
            if aktion == "dazu":
                c.execute("INSERT IGNORE INTO matomo_blog_adressen (pfad) VALUES (%s)", [pfad])
            else:
                c.execute("DELETE FROM matomo_blog_adressen WHERE pfad = %s", [pfad])
    zurueck = request.POST.get("zurueck") or ""
    if not zurueck.startswith("/webstats/"):
        zurueck = "/webstats/"
    return redirect(zurueck)

@login_required
def zeitlinie(request):
    """Menschen und Seiten pro Monat (die Artikel stehen jetzt in der Übersicht)."""
    heute = dt.datetime.now(aw.TZ).date()
    hinweis = None
    if request.GET.get("von") or request.GET.get("bis"):
        von, bis, hinweis = _zeitfenster(request)
    else:
        bis = heute
        von = monats_anfang(heute, ZEITLINIE_STANDARD - 1)
    if len(monate_zwischen(von, bis)) > ZEITLINIE_MONATE:
        von = monats_anfang(bis, ZEITLINIE_MONATE - 1)
        hinweis = f"The timeline shows at most {ZEITLINIE_MONATE} months."

    alle_orte = _alle_orte(request)
    umfang = _umfang(request)
    orte = ausgeschlossene_orte()
    kat, kat_info = wp_katalog()
    # Everything that changes the result is in the key: a changed list recounts.
    schluessel = "matomo:zeitlinie:" + hashlib.sha1(json.dumps(
        [von.isoformat(), bis.isoformat(), alle_orte, umfang,
         [ort_normal(o) for o in orte], sorted(k for k, _ in eigene_besucher()),
         sorted((k, a["link"]) for k, a in kat.articles.items())]).encode()).hexdigest()
    fehler, ergebnis = None, cache.get(schluessel)
    if ergebnis is None:
        try:
            # cache_seconds=0: a year of raw log is not kept in memory.
            besuche = _besuchsprotokoll(von, bis, cache_seconds=0, alle_orte=alle_orte,
                                        umfang=umfang)
            # Articles under every address they had (old /slug/ and /insights/slug/).
            blog = {a["link"]: a["titel"] for a in kat.articles.values()}
            for b in besuche:
                for p in b["seiten"]:
                    if p["art"] == aw.ARTICLE:
                        blog.setdefault(p["pfad"], kat.article_title(p["artikel"], p["titel"]))
            ergebnis = zeitlinie_rechnen(besuche, von, bis, blog=blog)
            ergebnis["ids_monat"] = aw.monthly_ids([b for b in besuche if not b["ist_bot"]],
                                                   monate_zwischen(von, bis))
            ergebnis["summe"] = _ausschluss_summe(besuche.ev)
            ergebnis["abgeschnitten"] = _abgeschnitten(besuche)
            ergebnis.pop("blog", None)
            del besuche
            cache.set(schluessel, ergebnis, ZEITLINIE_CACHE)
        except Exception as e:
            fehler, ergebnis = str(e), {"monate": [], "seiten": [], "abgeschnitten": False,
                                        "summe": None}

    summe = ergebnis.get("summe") or {
        "gruende": {"automation": 0, "unclear": 0, "own": 0, "preview": 0, "places": 0},
        "varianten": [], "ausgeschlossen": 0, "gesamt": 0, "umfang": umfang,
        "alle_orte": alle_orte}
    return render(request, "matomo/zeitlinie.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "zeitlinie": {"monate": ergebnis["monate"], "seiten": ergebnis["seiten"]},
        "monate": ergebnis["monate"],
        "kat_info": kat_info,
        "abgeschnitten": ergebnis.get("abgeschnitten"),
        **_ausschluss_kontext(request, summe=summe),
        "ausschluss_kurz": True,
        "fehler": fehler,
    })

@login_required
def archiv(request):
    """Was der nächtliche Abgleich gespeichert hat."""
    periode = request.GET.get("periode", "day")
    if periode not in ("day", "week", "month", "year"):
        periode = "day"
    eintraege = MatomoSnapshot.objects.filter(periode=periode)

    kategorie = request.GET.get("kategorie") or ""
    if kategorie:
        eintraege = eintraege.filter(kategorie=kategorie)
    datum = request.GET.get("datum") or ""
    if datum:
        eintraege = eintraege.filter(datum=datum)

    return render(request, "matomo/archiv.html", {
        "eintraege": eintraege[:300],
        "kategorien": (MatomoSnapshot.objects.exclude(kategorie="")
                       .values_list("kategorie", flat=True).distinct().order_by("kategorie")),
        "laeufe": MatomoLauf.objects.all()[:10],
        "periode": periode,
        "perioden": [("day", "Tag"), ("week", "Woche"), ("month", "Monat"), ("year", "Jahr")],
        "kategorie": kategorie, "datum": datum,
        "gesamt": MatomoSnapshot.objects.count(),
        "fehler": None,
    })


@login_required
def archiv_detail(request, pk):
    eintrag = get_object_or_404(MatomoSnapshot, pk=pk)
    spalten, zeilen = _summiere(eintrag.daten)
    return render(request, "matomo/bericht.html", {
        "modul": eintrag.modul, "aktion": eintrag.aktion, "titel": eintrag.name,
        "spalten": spalten, "zeilen": zeilen,
        "von": eintrag.datum.isoformat(), "bis": eintrag.datum.isoformat(),
        "hinweis": None, "tage": 1, "limit": eintrag.zeilen,
        "aus_archiv": True, "fehler": None,
    })


@login_required
def api_proxy(request, modul, aktion):
    """JSON für eigene Auswertungen, ohne den Token ins Frontend zu geben."""
    von, bis, _ = _zeitfenster(request)
    try:
        limit = min(int(request.GET.get("limit", 100)), 1000)
    except ValueError:
        limit = 100
    try:
        return JsonResponse(
            client.report(modul, aktion, period="day", date=_spanne_text(von, bis),
                          filter_limit=limit),
            safe=False,
        )
    except Exception as e:
        return JsonResponse({"fehler": str(e)}, status=502)
