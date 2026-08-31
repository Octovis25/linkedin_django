from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

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


# ── Zeitraum ─────────────────────────────────────────────────────────────

def _zeitfenster(request):
    """Liest von/bis aus dem Formular. Standard: die letzten 30 Tage."""
    heute = timezone.localdate()
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


# ── Besuchsprotokoll (Rohdaten, keine Vorberechnung nötig) ───────────────

def _erstes(quelle, *namen):
    """Erster nicht leerer Wert aus mehreren möglichen Feldnamen.

    Matomo benennt Felder im Besuchsprotokoll anders als in den Berichten und
    hat das über die Versionen mehrfach geändert - deshalb mehrere Kandidaten.
    """
    for name in namen:
        wert = quelle.get(name)
        if wert not in (None, "", "Unknown", "unknown"):
            return wert
    return None


def _besuchsprotokoll(von, bis, limit=BESUCHS_LIMIT, cache_seconds=300):
    """Alle Einzelbesuche im Zeitraum, bewertet als Mensch oder Bot.

    Die Regel wird PRO BESUCHER angewandt, nicht pro Besuch: Wer sich bei
    irgendeinem seiner Besuche wie ein Mensch verhalten hat - Verweildauer
    über 0 oder mehr als eine Seite -, gilt bei allen seinen Besuchen als
    Mensch. Sonst würde derselbe Besucher, der einmal länger liest und
    zweimal kurz vorbeischaut, als ein Mensch und zwei Bots gezählt.
    """
    roh = client.hole("live/last_visits_details", period="day",
                      date=_spanne_text(von, bis),
                      filter_limit=limit, cache_seconds=cache_seconds)

    # Bei mehreren Tagen kommt {datum: [besuche]}, bei einem Tag direkt eine Liste
    if isinstance(roh, dict):
        flach = []
        for wert in roh.values():
            if isinstance(wert, list):
                flach.extend(wert)
        roh = flach
    if not isinstance(roh, list):
        return []

    besuche = []
    for b in roh:
        if not isinstance(b, dict):
            continue
        dauer = _zahl(b.get("visitDuration")) or 0
        aktionen = _zahl(b.get("actions")) or 0

        zeit = b.get("serverTimePretty") or ""
        stunde = f"{zeit[:2]}:00" if len(zeit) >= 2 and zeit[:2].isdigit() else "unknown"

        # Wochentag aus dem Datum, das Matomo mitliefert
        tag, datum_iso, kw = "unknown", "unknown", "unknown"
        roh_datum = _erstes(b, "serverDate", "firstActionDateTime", "lastActionDateTime")
        if roh_datum:
            try:
                d = dt.date.fromisoformat(str(roh_datum)[:10])
                tag = WOCHENTAGE[d.weekday()]
                datum_iso = d.isoformat()
                jahr, woche, _ = d.isocalendar()
                kw = f"W{woche:02d} / {jahr}"
            except (ValueError, IndexError):
                pass

        aktionen_liste = []
        details = b.get("actionDetails") or []
        for a in details:
            if not isinstance(a, dict):
                continue
            aktionen_liste.append({
                "typ": (a.get("type") or "action").lower(),
                "url": a.get("url") or "",
                "titel": a.get("pageTitle") or "",
            })

        erste = ""
        if details and isinstance(details[0], dict):
            erste = details[0].get("url") or details[0].get("pageTitle") or ""
            for vorsatz in ("https://octotrial.com", "http://octotrial.com",
                            "https://www.octotrial.com", "http://www.octotrial.com"):
                if erste.startswith(vorsatz):
                    erste = erste[len(vorsatz):] or "/"
                    break

        besuche.append({
            "besucher": b.get("visitorId") or "",
            "zeit": f"{b.get('serverDatePretty','')} {zeit}".strip(),
            "datum_de": (dt.date.fromisoformat(datum_iso).strftime("%d.%m.%Y")
                         if datum_iso != "unknown" else "unknown"),
            "uhrzeit": zeit or "unknown",
            "sortier": b.get("serverTimestamp") or 0,
            "dauer_sek": int(dauer),
            "dauer": b.get("visitDurationPretty") or f"{int(dauer)}s",
            "aktionen": int(aktionen),
            "land": _erstes(b, "country", "countryName") or "unknown",
            "stadt": _erstes(b, "city", "cityName") or "unknown",
            "region": _erstes(b, "region", "regionName") or "unknown",
            "geraet": _erstes(b, "deviceType", "deviceTypeName") or "unknown",
            "browser": _erstes(b, "browserName", "browser") or "unknown",
            "system": _erstes(b, "operatingSystemName", "operatingSystem",
                              "operatingSystemCode") or "unknown",
            "sprache": _erstes(b, "language", "languageCode") or "unknown",
            "herkunft": _erstes(b, "referrerName", "referrerTypeName",
                                "referrerType") or "unknown",
            "herkunft_typ": (_erstes(b, "referrerType") or "").lower(),
            "stunde": stunde,
            "wochentag": tag,
            "datum": datum_iso,
            "kalenderwoche": kw,
            "erste_seite": erste,
            "aktionen_liste": aktionen_liste,
            # dieser einzelne Besuch für sich betrachtet
            "besuch_auffaellig": int(dauer) == 0 and int(aktionen) <= 1,
        })

    # Pro Besucher entscheiden
    menschliche_besucher = {
        b["besucher"] for b in besuche
        if b["besucher"] and not b["besuch_auffaellig"]
    }
    for b in besuche:
        b["ist_bot"] = b["besuch_auffaellig"] and b["besucher"] not in menschliche_besucher
        b["nachtraeglich_mensch"] = b["besuch_auffaellig"] and not b["ist_bot"]

    besuche.sort(key=lambda b: b["sortier"], reverse=True)
    return besuche


def _haeufigkeit(besuche, felder, titel=None, sortiere_nach_name=False, ordnung=None):
    """Zählt ein oder mehrere Merkmale, getrennt nach Mensch und Bot.

    `felder` ist ein Feldname oder ein Tupel davon — jedes wird zu einer
    eigenen Spalte. Dahinter kommen Menschen, Bots und Gesamt.
    """
    if isinstance(felder, str):
        felder = (felder,)
    zaehler = {}
    for b in besuche:
        schluessel = tuple(b.get(f) or "unknown" for f in felder)
        eintrag = zaehler.setdefault(schluessel, [0, 0])
        eintrag[1 if b["ist_bot"] else 0] += 1

    zeilen = [list(k) + [m, bo, m + bo] for k, (m, bo) in zaehler.items()]
    if ordnung:
        rang = {name: i for i, name in enumerate(ordnung)}
        zeilen.sort(key=lambda z: (rang.get(z[0], len(rang)), str(z[0])))
    elif sortiere_nach_name:
        zeilen.sort(key=lambda z: z[0])
    else:
        zeilen.sort(key=lambda z: (-z[-1], str(z[0])))

    spalten = list(titel or felder) + ["Humans", "Bots", "Total"]
    return spalten, zeilen


def _besucher_liste(besuche):
    """Fasst die Einzelbesuche zu einer Zeile je Besucher zusammen."""
    leute = {}
    for b in besuche:
        kennung = b["besucher"] or "-"
        p = leute.get(kennung)
        if p is None:
            p = leute[kennung] = {
                "kennung": kennung, "besuche": 0, "seiten": 0, "dauer": 0,
                "erster": b["sortier"], "letzter": b["sortier"],
                "zuletzt_datum": b["datum_de"], "zuletzt_zeit": b["uhrzeit"],
                "zuletzt_iso": b["datum"], "land": b["land"], "stadt": b["stadt"],
                "geraet": b["geraet"], "browser": b["browser"], "system": b["system"],
                "herkunft": b["herkunft"], "ist_bot": True,
            }
        p["besuche"] += 1
        p["seiten"] += b["aktionen"]
        p["dauer"] += b["dauer_sek"]
        if b["sortier"] > p["letzter"]:
            p["letzter"] = b["sortier"]
            p["zuletzt_datum"], p["zuletzt_zeit"] = b["datum_de"], b["uhrzeit"]
            p["zuletzt_iso"] = b["datum"]
            p["herkunft"] = b["herkunft"]
        p["erster"] = min(p["erster"], b["sortier"])
        if not b["ist_bot"]:
            p["ist_bot"] = False

    liste = sorted(leute.values(), key=lambda p: (-p["letzter"],))
    for p in liste:
        p["art"] = "Bot" if p["ist_bot"] else "Mensch"
        p["dauer_text"] = (f"{p['dauer'] // 60}:{p['dauer'] % 60:02d} min"
                           if p["dauer"] >= 60 else f"{p['dauer']}s")
    return liste


def _verlauf(besuche, von, bis):
    """Zahlen für die Verlaufslinien: Besuche je Tag, Menschen und Bots getrennt.

    Gezeichnet wird im Browser, nicht hier — nur so lässt sich eine Linie
    ausblenden und die Achse danach neu skalieren. Tage ohne Besuche werden als
    Null geführt; sonst spränge die Linie darüber hinweg und täuschte mehr
    Verkehr vor, als es gab.
    """
    tage = []
    d = von
    while d <= bis:
        tage.append(d)
        d += dt.timedelta(days=1)
    if len(tage) < 2:
        return None

    zaehler = {t.isoformat(): [0, 0] for t in tage}
    for b in besuche:
        eintrag = zaehler.get(b.get("datum"))
        if eintrag is not None:
            eintrag[1 if b["ist_bot"] else 0] += 1

    daten = []
    for t in tage:
        menschen, bots = zaehler[t.isoformat()]
        daten.append({
            "datum": t.isoformat(),
            "lang": f"{WOCHENTAGE[t.weekday()]}, {t.strftime('%d.%m.%Y')}",
            "kurz": t.strftime("%d.%m."),
            "ersterImMonat": t.day == 1,
            "istMontag": t.weekday() == 0,
            "menschen": menschen, "bots": bots,
        })

    return {
        "daten": daten, "tage": len(tage),
        "reihen": [
            {"feld": "menschen", "name": "Humans", "farbe": "#0093A1",
             "summe": sum(d["menschen"] for d in daten)},
            {"feld": "bots", "name": "Bots", "farbe": "#F56E28",
             "summe": sum(d["bots"] for d in daten)},
        ],
    }


def _stundenraster(besuche):
    """Zwei Raster nebeneinander: 7 Wochentage x 24 Stunden, Menschen und Bots.

    Beide teilen sich denselben Höchstwert für die Deckkraft — sonst sähe eine
    Stunde mit 2 Besuchen im einen Raster genauso kräftig aus wie eine mit 40
    im anderen, und der Vergleich wäre wertlos.
    """
    zaehler = {"menschen": {tag: [0] * 24 for tag in WOCHENTAGE},
               "bots": {tag: [0] * 24 for tag in WOCHENTAGE}}
    ohne_zeit = 0

    for b in besuche:
        tag = b.get("wochentag")
        stunde = b.get("stunde", "")
        if tag not in WOCHENTAGE or not stunde[:2].isdigit():
            ohne_zeit += 1
            continue
        zaehler["bots" if b["ist_bot"] else "menschen"][tag][int(stunde[:2])] += 1

    hoechstwert = max((w for art in zaehler.values() for stunden in art.values()
                       for w in stunden), default=0)

    def baue(art, nur):
        zeilen = []
        for tag in WOCHENTAGE:
            felder = [{
                "stunde": stunde,
                "stunde_text": f"{stunde:02d}:00",
                "anzahl": anzahl,
                "deckkraft": round(0.18 + 0.82 * anzahl / hoechstwert, 2) if hoechstwert else 0,
            } for stunde, anzahl in enumerate(zaehler[art][tag])]
            zeilen.append({"tag": tag, "kurz": tag[:2], "felder": felder,
                           "summe": sum(f["anzahl"] for f in felder)})
        return {"art": art, "nur": nur, "zeilen": zeilen,
                "summe": sum(z["summe"] for z in zeilen)}

    return {
        "menschen": baue("menschen", "menschen"),
        "bots": baue("bots", "bots"),
        "hoechstwert": hoechstwert,
        "ohne_zeit": ohne_zeit,
    }


def zeitpunkt_tabelle(besuche):
    """Wochentag und Uhrzeit in einer Tabelle, chronologisch über die Woche."""
    spalten, zeilen = _haeufigkeit(
        besuche, ("wochentag", "stunde"), ["Weekday", "Hour"])
    rang = {name: i for i, name in enumerate(WOCHENTAGE)}
    zeilen.sort(key=lambda z: (rang.get(z[0], len(rang)), str(z[1])))
    return {
        "titel": "Weekday and hour",
        "spalten": spalten, "zeilen": zeilen,
        "hinweis": "Counts visits, not people; server time, not the visitors’ local time. "
                   "Sorted from early Monday to late Sunday. Humans usually cluster on "
                   "weekdays and during the day — anything spread evenly across all days "
                   "and night hours suggests automation. Use the drop-downs to pick a "
                   "single day or hour.",
    }


def _zeitraum_kontext(von, bis, hinweis):
    return {"von": von.isoformat(), "bis": bis.isoformat(), "hinweis": hinweis,
            "tage": (bis - von).days + 1}


# ── Ansichten ────────────────────────────────────────────────────────────

def _sparkline(verlauf, breite=900, hoehe=160, rand=8):
    """Baut aus {datum: wert} die Punkte für eine <polyline> plus Eckdaten."""
    if not isinstance(verlauf, dict) or len(verlauf) < 2:
        return None
    werte = []
    for v in verlauf.values():
        n = _zahl(v)
        werte.append(float(n) if n is not None else 0.0)
    hoch = max(werte) or 1.0
    n = len(werte)
    punkte = []
    for i, w in enumerate(werte):
        x = rand + i * (breite - 2 * rand) / (n - 1)
        y = hoehe - rand - (w / hoch) * (hoehe - 2 * rand)
        punkte.append(f"{x:.1f},{y:.1f}")
    tage = list(verlauf.keys())
    return {
        "punkte": " ".join(punkte),
        "flaeche": f"{rand},{hoehe - rand} " + " ".join(punkte) + f" {breite - rand},{hoehe - rand}",
        "breite": breite, "hoehe": hoehe,
        "hoch": int(hoch), "erster": tage[0], "letzter": tage[-1],
    }


@login_required
def uebersicht(request):
    """Kopfzahlen, Verlauf und das Verzeichnis aller verfügbaren Berichte."""
    von, bis, hinweis = _zeitfenster(request)
    fehler, verlauf, kategorien, besuche = None, {}, {}, []

    try:
        besuche = _besuchsprotokoll(von, bis)
    except Exception as e:
        fehler = str(e)

    try:
        verlauf = client.hole("visits_summary/visits", period="day",
                              date=_spanne_text(von, bis))
        if not isinstance(verlauf, dict):
            verlauf = {}
    except Exception as e:
        fehler = fehler or str(e)

    try:
        for b in client.report_metadata(period="day", date=bis.isoformat()):
            kategorien.setdefault(b.get("category") or "Sonstiges", []).append(b)
    except Exception as e:
        fehler = fehler or str(e)

    menschen = [b for b in besuche if not b["ist_bot"]]
    dauern = [b["dauer_sek"] for b in menschen]

    return render(request, "matomo/uebersicht.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "gesamt": len(besuche), "menschen": len(menschen),
        "bots": len(besuche) - len(menschen),
        "seiten_menschen": sum(b["aktionen"] for b in menschen),
        "dauer_schnitt": round(sum(dauern) / len(dauern)) if dauern else 0,
        "sparkline": _sparkline(verlauf),
        "kategorien": dict(sorted(kategorien.items())),
        "anzahl_berichte": sum(len(v) for v in kategorien.values()),
        "letzter_lauf": MatomoLauf.objects.first(),
        "fehler": fehler,
    })


@login_required
def besucher(request):
    """Wer kommt — Menschen und Bots getrennt ausgewiesen."""
    von, bis, hinweis = _zeitfenster(request)
    nur = request.GET.get("nur", "alle")
    if nur not in ("alle", "menschen", "bots"):
        nur = "alle"

    fehler, alle = None, []
    try:
        alle = _besuchsprotokoll(von, bis)
    except Exception as e:
        fehler = str(e)

    menschen = [b for b in alle if not b["ist_bot"]]
    bots = [b for b in alle if b["ist_bot"]]
    dauern = [b["dauer_sek"] for b in menschen]

    # Die Auswahl wirkt auf alle Tabellen; die Kacheln zeigen weiter das
    # Gesamtbild, damit der Bezug nicht verloren geht.
    if nur == "menschen":
        besuche = menschen
    elif nur == "bots":
        besuche = bots
    else:
        besuche = alle

    def tab(titel, felder, spaltentitel, hinweis="", nach_name=False, ordnung=None):
        spalten, zeilen = _haeufigkeit(besuche, felder, spaltentitel, nach_name, ordnung)
        return {"titel": titel, "spalten": spalten, "zeilen": zeilen, "hinweis": hinweis}

    direkte = [b for b in besuche if b["herkunft_typ"] == "direct"
               or b["herkunft"].lower().startswith("direkt")]

    leute = _besucher_liste(besuche)

    tabellen = [
        tab("Cities", ("stadt", "land"), ["City", "Country"],
            "Country as its own column so you can sort by it. Cities are far less exact "
            "than countries — a rough hint, never an address."),
        tab("Referrer", "herkunft", ["Referrer"],
            "“Direct entry” means the browser sent no referring page. What can still be "
            "said about those visits is in the table below."),
    ]

    if direkte:
        spalten, zeilen = _haeufigkeit(
            direkte, ("stadt", "land", "system", "erste_seite"),
            ["City", "Country", "System", "Entry page"])
        tabellen.append({
            "titel": "Direct entries in detail",
            "spalten": spalten, "zeilen": zeilen,
            "hinweis": "There is no referring page here, so this is what else can be "
                       "said about these visits. The same city, the same system and "
                       "always the same entry page, in numbers, is the pattern of a "
                       "script — not of an audience.",
        })

    tabellen += [
        zeitpunkt_tabelle(besuche),
        tab("Countries", "land", ["Country"],
            "Estimated from the IP address. For VPN users this is the VPN server’s country."),
        tab("Device type", "geraet", ["Device"]),
        tab("Browsers", "browser", ["Browser"]),
        tab("Operating systems", "system", ["System"],
            "A striking number of Linux desktops points to data centres."),
        tab("Browser language", "sprache", ["Language"],
            "Independent of the IP address and therefore often more telling than the country."),
    ]

    return render(request, "matomo/besucher.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "nur": nur, "angezeigt": len(besuche),
        "gesamt": len(alle), "menschen": len(menschen), "bots": len(bots),
        "anteil_bots": round(100 * len(bots) / len(alle)) if alle else 0,
        "seiten_menschen": sum(b["aktionen"] for b in menschen),
        "dauer_schnitt": round(sum(dauern) / len(dauern)) if dauern else 0,
        "gerettet": sum(1 for b in alle if b.get("nachtraeglich_mensch")),
        "direkte": len(direkte),
        "tabellen": tabellen, "leute": leute,
        "raster": _stundenraster(besuche),
        "verlauf": _verlauf(besuche, von, bis),
        "abgeschnitten": len(alle) >= BESUCHS_LIMIT,
        "fehler": fehler,
    })


@login_required
def besucher_profil(request, kennung):
    """Alles, was Matomo über einen einzelnen Besucher weiß."""
    fehler, profil, besuche = None, {}, []
    try:
        profil = client.hole("live/visitor_profile", visitorId=kennung,
                             cache_seconds=120)
        if not isinstance(profil, dict):
            profil, fehler = {}, "Unexpected response from Matomo."
    except Exception as e:
        fehler = str(e)

    for b in (profil.get("lastVisits") or []):
        if not isinstance(b, dict):
            continue
        seiten = []
        for a in (b.get("actionDetails") or []):
            if not isinstance(a, dict):
                continue
            adresse = a.get("url") or a.get("pageTitle") or a.get("type") or ""
            for vorsatz in ("https://octotrial.com", "http://octotrial.com",
                            "https://www.octotrial.com", "http://www.octotrial.com"):
                if adresse.startswith(vorsatz):
                    adresse = adresse[len(vorsatz):] or "/"
                    break
            seiten.append({"zeit": a.get("serverTimePretty") or "",
                           "adresse": adresse,
                           "titel": a.get("pageTitle") or ""})
        besuche.append({
            "zeit": f"{b.get('serverDatePretty','')} {b.get('serverTimePretty','')}".strip(),
            "dauer": b.get("visitDurationPretty") or "",
            "aktionen": _zahl(b.get("actions")) or 0,
            "herkunft": _erstes(b, "referrerName", "referrerTypeName") or "unknown",
            "land": _erstes(b, "country", "countryName") or "unknown",
            "stadt": _erstes(b, "city") or "",
            "geraet": _erstes(b, "deviceType") or "",
            "browser": _erstes(b, "browserName") or "",
            "system": _erstes(b, "operatingSystemName") or "",
            "seiten": seiten,
        })

    return render(request, "matomo/besucher_profil.html", {
        "kennung": kennung, "profil": profil, "besuche": besuche,
        "zurueck": request.GET.get("zurueck", ""),
        "fehler": fehler,
    })


@login_required
def protokoll(request):
    """Jeder einzelne Besuch, mit Kennzeichnung."""
    von, bis, hinweis = _zeitfenster(request)
    nur = request.GET.get("nur", "alle")
    if nur not in ("alle", "menschen", "bots"):
        nur = "alle"
    tag = request.GET.get("tag", "")
    if tag not in WOCHENTAGE:
        tag = ""
    stunde = request.GET.get("stunde", "")
    stunde = stunde if stunde.isdigit() and 0 <= int(stunde) <= 23 else ""

    fehler, besuche = None, []
    try:
        besuche = _besuchsprotokoll(von, bis)
    except Exception as e:
        fehler = str(e)

    gesamt = len(besuche)
    bots = sum(1 for b in besuche if b["ist_bot"])
    if nur == "menschen":
        besuche = [b for b in besuche if not b["ist_bot"]]
    elif nur == "bots":
        besuche = [b for b in besuche if b["ist_bot"]]
    if tag:
        besuche = [b for b in besuche if b.get("wochentag") == tag]
    if stunde:
        besuche = [b for b in besuche if b.get("stunde", "")[:2] == f"{int(stunde):02d}"]

    return render(request, "matomo/protokoll.html", {
        "tag": tag, "stunde": stunde,
        "stunde_text": f"{int(stunde):02d}:00 Uhr" if stunde else "",
        **_zeitraum_kontext(von, bis, hinweis),
        "besuche": besuche, "gesamt": gesamt, "bots": bots,
        "menschen": gesamt - bots, "angezeigt": len(besuche), "nur": nur,
        "abgeschnitten": gesamt >= BESUCHS_LIMIT,
        "fehler": fehler,
    })


@login_required
def seiten(request):
    """Welche Inhalte aufgerufen wurden."""
    von, bis, hinweis = _zeitfenster(request)
    bloecke = _bloecke(von, bis, [
        ("Most visited pages", "Actions", "getPageUrls",
         "By address. “Unique pageviews” counts a visit once, even if someone opened "
         "the page several times."),
        ("Page titles", "Actions", "getPageTitles",
         "The same views, by heading instead of address — usually easier to read."),
        ("Entry pages", "Actions", "getEntryPageUrls",
         "Where visitors arrive. The most interesting table if you want to know which "
         "content brings people in at all."),
        ("Exit pages", "Actions", "getExitPageUrls",
         "Where they leave again."),
        ("Clicks on outgoing links", "Actions", "getOutlinks", ""),
        ("Downloaded files", "Actions", "getDownloads", ""),
    ], flach=1, limit=200)
    return render(request, "matomo/bloecke.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "seitentitel": "Pages",
        "untertitel": "Which content on octotrial.com was opened.",
        "bloecke": bloecke, "fehler": None,
    })


@login_required
def suchbegriffe(request):
    """Nur das, wonach gesucht wurde."""
    von, bis, hinweis = _zeitfenster(request)
    bloecke = _bloecke(von, bis, [
        ("Search terms from search engines", "Referrers", "getKeywords",
         "Google and most other search engines have not passed on the search term for "
         "years. What you see here is a fraction — the rest shows up as "
         "“Keyword not defined”."),
        ("Search engines", "Referrers", "getSearchEngines",
         "Which search engines visitors came from — whether or not the term was passed on."),
        ("Search on your own site", "Actions", "getSiteSearchKeywords",
         "What visitors typed into the search box on octotrial.com. Stays empty if site "
         "search is not configured in Matomo."),
    ])
    return render(request, "matomo/bloecke.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "seitentitel": "Search terms",
        "untertitel": "What visitors searched for before they landed on octotrial.com.",
        "bloecke": bloecke, "fehler": None,
    })


@login_required
def ki(request):
    """KI-Verkehr: Menschen über KI-Assistenten und die Bots selbst."""
    von, bis, hinweis = _zeitfenster(request)
    bloecke = _bloecke(von, bis, [
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
        ("AI agent visits", "AIAgents", "get",
         "Agents acting on behalf of a user."),
    ], flach=1, limit=150)
    return render(request, "matomo/bloecke.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "seitentitel": "AI",
        "untertitel": "Visitors from AI assistants, and the AI bots that read octotrial.com.",
        "bloecke": bloecke, "fehler": None,
    })


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
        "fehler": fehler,
    })


# Ziele werden NICHT in Matomo eingerichtet, sondern hier aus dem Besuchs-
# protokoll abgeleitet. Vorteil: nichts zu konfigurieren, und es gilt rückwirkend
# für alle Besuche, die Matomo schon aufgezeichnet hat.
# Über MATOMO_ZIELE in den Settings lässt sich die Liste ersetzen.
STANDARD_ZIELE = [
    {"name": "Contact page reached", "art": "seite", "muster": "/kontakt",
     "beschreibung": "visited a page whose address contains /kontakt"},
    {"name": "Email address clicked", "art": "mailto", "muster": "",
     "beschreibung": "clicked a mailto: link"},
    {"name": "File downloaded", "art": "download", "muster": "",
     "beschreibung": "downloaded a file (PDF and the like)"},
    {"name": "Left to LinkedIn", "art": "outlink", "muster": "linkedin.com",
     "beschreibung": "followed an outgoing link to linkedin.com"},
    {"name": "Read three pages or more", "art": "tiefe", "muster": "3",
     "beschreibung": "opened at least 3 pages in one visit"},
    {"name": "Stayed two minutes or longer", "art": "dauer", "muster": "120",
     "beschreibung": "spent 120 seconds or more on the site"},
]


def _ziel_trifft(regel, b):
    """Prüft eine Zielregel gegen einen einzelnen Besuch."""
    art = regel.get("art")
    muster = (regel.get("muster") or "").lower()
    aktionen = b.get("aktionen_liste") or []

    if art == "seite":
        return any(a["typ"] == "action" and muster in (a["url"] or "").lower()
                   for a in aktionen)
    if art == "mailto":
        return any((a["url"] or "").lower().startswith("mailto:") for a in aktionen)
    if art == "download":
        return any(a["typ"] == "download" for a in aktionen)
    if art == "outlink":
        return any(a["typ"] == "outlink" and muster in (a["url"] or "").lower()
                   for a in aktionen)
    if art == "titel":
        return any(muster in (a["titel"] or "").lower() for a in aktionen)
    if art == "tiefe":
        try:
            return b["aktionen"] >= int(muster or 0)
        except ValueError:
            return False
    if art == "dauer":
        try:
            return b["dauer_sek"] >= int(muster or 0)
        except ValueError:
            return False
    return False


@login_required
def ziele(request):
    """Goals, abgeleitet aus dem Besuchsprotokoll - ohne Einrichtung in Matomo."""
    von, bis, hinweis = _zeitfenster(request)
    laenge = (bis - von).days + 1
    vor_bis = von - dt.timedelta(days=1)
    vor_von = vor_bis - dt.timedelta(days=laenge - 1)

    regeln = getattr(settings, "MATOMO_ZIELE", None) or STANDARD_ZIELE

    fehler, besuche, vorbesuche = None, [], []
    try:
        besuche = [b for b in _besuchsprotokoll(von, bis) if not b["ist_bot"]]
        vorbesuche = [b for b in _besuchsprotokoll(vor_von, vor_bis) if not b["ist_bot"]]
    except Exception as e:
        fehler = str(e)

    ziele_liste, mit_ziel = [], set()
    for nummer, regel in enumerate(regeln):
        treffer = [b for b in besuche if _ziel_trifft(regel, b)]
        vortreffer = sum(1 for b in vorbesuche if _ziel_trifft(regel, b))
        for b in treffer:
            mit_ziel.add(id(b))
        ziele_liste.append({
            "nummer": nummer,
            "name": regel.get("name") or f"Goal {nummer + 1}",
            "bedingung": regel.get("beschreibung") or regel.get("art", ""),
            "anzahl": len(treffer),
            "vorher": vortreffer,
            "unterschied": len(treffer) - vortreffer,
            "quote": round(100 * len(treffer) / len(besuche), 1) if besuche else 0.0,
            "besuche": treffer,
        })

    hoechster = max([z["anzahl"] for z in ziele_liste], default=0)
    for z in ziele_liste:
        z["anteil"] = round(100 * z["anzahl"] / hoechster) if hoechster else 0
    ziele_liste.sort(key=lambda z: (-z["anzahl"], z["name"]))

    erfolgreiche = [b for b in besuche if id(b) in mit_ziel]

    # Woher kamen die, die etwas getan haben - und wo fing es an
    def aufschluesselung(feld, titel):
        zaehler = {}
        for b in besuche:
            eintrag = zaehler.setdefault(b.get(feld) or "unknown", [0, 0])
            eintrag[0] += 1
            if id(b) in mit_ziel:
                eintrag[1] += 1
        zeilen = [[name, ges, mit, round(100 * mit / ges, 1) if ges else 0.0]
                  for name, (ges, mit) in zaehler.items()]
        zeilen.sort(key=lambda z: (-z[2], -z[1]))
        return {"titel": titel, "spalten": [titel, "Visits", "With goal", "Rate %"],
                "zeilen": zeilen}

    return render(request, "matomo/ziele.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "ziele": ziele_liste,
        "gesamt": sum(z["anzahl"] for z in ziele_liste),
        "mit_treffern": sum(1 for z in ziele_liste if z["anzahl"]),
        "erfolgreiche": len(erfolgreiche),
        "besuche": len(besuche), "vorbesuche": len(vorbesuche),
        "unterschied": len(besuche) - len(vorbesuche),
        "quote": round(100 * len(erfolgreiche) / len(besuche), 1) if besuche else 0.0,
        "vor_von": vor_von.isoformat(), "vor_bis": vor_bis.isoformat(),
        "herkunft": aufschluesselung("herkunft", "Referrer"),
        "einstieg": aufschluesselung("erste_seite", "Entry page"),
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
