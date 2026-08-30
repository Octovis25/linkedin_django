from __future__ import annotations

import datetime as dt

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
        hinweis = "Von und Bis waren vertauscht — ich habe sie getauscht."
    if bis > heute:
        bis = heute
    if (bis - von).days > MAX_TAGE:
        von = bis - dt.timedelta(days=MAX_TAGE)
        hinweis = f"Zeitraum auf {MAX_TAGE} Tage begrenzt."
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
    """Zerlegt die Antwort in einzelne Tagesberichte."""
    if isinstance(roh, dict):
        if "reportData" in roh:
            return [roh]
        werte = [v for v in roh.values() if isinstance(v, dict)]
        if werte and all("reportData" in v or "columns" in v for v in werte):
            return werte
    return []


def _summiere(roh):
    """Addiert die Tagesberichte zu einer Tabelle: (Spalten, Zeilen)."""
    tage = _tagesberichte(roh)
    if not tage:
        return [], []

    titel = {}
    for t in tage:
        titel.update(t.get("columns") or {})

    gesammelt = {}      # label -> {schluessel: summe}
    reihenfolge = []
    kennzahlen = {}     # falls der Bericht gar keine Zeilen hat, sondern Werte

    for t in tage:
        daten = t.get("reportData")
        if isinstance(daten, list):
            for zeile in daten:
                if not isinstance(zeile, dict):
                    continue
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
                        gesammelt[name][k] = (vorher or 0) + n if isinstance(vorher, (int, float)) or vorher is None else v
        elif isinstance(daten, dict):
            for k, v in daten.items():
                if k in VERSTECKT or k in NICHT_SUMMIERBAR:
                    continue
                n = _zahl(v)
                if n is None:
                    kennzahlen.setdefault(k, v)
                else:
                    kennzahlen[k] = kennzahlen.get(k, 0) + n

    if kennzahlen and not gesammelt:
        return ["Kennzahl", "Wert"], [[titel.get(k, k), v] for k, v in kennzahlen.items()]

    if not gesammelt:
        return [], []

    schluessel = []
    for werte in gesammelt.values():
        for k in werte:
            if k not in schluessel:
                schluessel.append(k)

    zeilen = [[name] + [gesammelt[name].get(k, 0) for k in schluessel] for name in reihenfolge]
    # nach der ersten Zahlenspalte absteigend sortieren
    if schluessel:
        zeilen.sort(key=lambda z: (-(z[1] if isinstance(z[1], (int, float)) else 0), str(z[0])))

    spalten = ["Bezeichnung"] + [titel.get(k, k) for k in schluessel]
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
        stunde = f"{zeit[:2]} Uhr" if len(zeit) >= 2 and zeit[:2].isdigit() else "unbekannt"

        erste = ""
        details = b.get("actionDetails") or []
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
            "sortier": b.get("serverTimestamp") or 0,
            "dauer_sek": int(dauer),
            "dauer": b.get("visitDurationPretty") or f"{int(dauer)}s",
            "aktionen": int(aktionen),
            "land": _erstes(b, "country", "countryName") or "unbekannt",
            "stadt": _erstes(b, "city", "cityName") or "unbekannt",
            "region": _erstes(b, "region", "regionName") or "unbekannt",
            "geraet": _erstes(b, "deviceType", "deviceTypeName") or "unbekannt",
            "browser": _erstes(b, "browserName", "browser") or "unbekannt",
            "system": _erstes(b, "operatingSystemName", "operatingSystem",
                              "operatingSystemCode") or "unbekannt",
            "sprache": _erstes(b, "language", "languageCode") or "unbekannt",
            "herkunft": _erstes(b, "referrerName", "referrerTypeName",
                                "referrerType") or "unbekannt",
            "herkunft_typ": (_erstes(b, "referrerType") or "").lower(),
            "stunde": stunde,
            "erste_seite": erste,
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


def _haeufigkeit(besuche, felder, titel=None, sortiere_nach_name=False):
    """Zählt ein oder mehrere Merkmale, getrennt nach Mensch und Bot.

    `felder` ist ein Feldname oder ein Tupel davon — jedes wird zu einer
    eigenen Spalte. Dahinter kommen Menschen, Bots und Gesamt.
    """
    if isinstance(felder, str):
        felder = (felder,)
    zaehler = {}
    for b in besuche:
        schluessel = tuple(b.get(f) or "unbekannt" for f in felder)
        eintrag = zaehler.setdefault(schluessel, [0, 0])
        eintrag[1 if b["ist_bot"] else 0] += 1

    zeilen = [list(k) + [m, bo, m + bo] for k, (m, bo) in zaehler.items()]
    if sortiere_nach_name:
        zeilen.sort(key=lambda z: z[0])
    else:
        zeilen.sort(key=lambda z: (-z[-1], str(z[0])))

    spalten = list(titel or felder) + ["Menschen", "Bots", "Gesamt"]
    return spalten, zeilen


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

    def tab(titel, felder, spaltentitel, hinweis="", nach_name=False):
        spalten, zeilen = _haeufigkeit(besuche, felder, spaltentitel, nach_name)
        return {"titel": titel, "spalten": spalten, "zeilen": zeilen, "hinweis": hinweis}

    direkte = [b for b in besuche if b["herkunft_typ"] == "direct"
               or b["herkunft"].lower().startswith("direkt")]

    tabellen = [
        tab("Städte", ("stadt", "land"), ["Stadt", "Land"],
            "Land als eigene Spalte, damit du danach sortieren kannst. Städte sind "
            "deutlich ungenauer als Länder — ein grober Anhaltspunkt, keine Adresse."),
        tab("Herkunft", "herkunft", ["Herkunft"],
            "„Direkte Zugriffe“ heißt: Der Browser hat keine verweisende Seite "
            "mitgeschickt. Woher diese Besuche stammen, steht in der Tabelle darunter."),
    ]

    if direkte:
        spalten, zeilen = _haeufigkeit(
            direkte, ("stadt", "land", "system", "erste_seite"),
            ["Stadt", "Land", "System", "Erste Seite"])
        tabellen.append({
            "titel": "Direkte Zugriffe im Detail",
            "spalten": spalten, "zeilen": zeilen,
            "hinweis": "Eine verweisende Seite gibt es hier nicht — deshalb das, was "
                       "sich sonst über diese Besuche sagen lässt. Gleiche Stadt, "
                       "gleiches System und immer dieselbe Einstiegsseite in großer "
                       "Zahl ist das Muster eines Skripts, nicht eines Publikums.",
        })

    tabellen += [
        tab("Länder", "land", ["Land"],
            "Aus der IP-Adresse geschätzt. Bei VPN-Nutzern steht das Land des VPN-Servers."),
        tab("Gerätetyp", "geraet", ["Gerät"]),
        tab("Browser", "browser", ["Browser"]),
        tab("Betriebssysteme", "system", ["System"],
            "Auffällig viele Linux-Desktops sind ein Hinweis auf Rechenzentren."),
        tab("Sprache des Browsers", "sprache", ["Sprache"],
            "Hängt nicht von der IP ab und ist deshalb oft aussagekräftiger als das Land."),
        tab("Nach Uhrzeit", "stunde", ["Uhrzeit"],
            "Serverzeit. Gleichmäßige Verteilung über die Nacht spricht für Automatisierung.",
            nach_name=True),
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
        "tabellen": tabellen,
        "abgeschnitten": len(alle) >= BESUCHS_LIMIT,
        "fehler": fehler,
    })


@login_required
def protokoll(request):
    """Jeder einzelne Besuch, mit Kennzeichnung."""
    von, bis, hinweis = _zeitfenster(request)
    nur = request.GET.get("nur", "alle")
    if nur not in ("alle", "menschen", "bots"):
        nur = "alle"

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

    return render(request, "matomo/protokoll.html", {
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
        ("Meistbesuchte Seiten", "Actions", "getPageUrls",
         "Nach Adresse. „Eindeutige Seitenansichten“ zählt einen Besuch nur einmal, "
         "auch wenn jemand die Seite mehrfach geöffnet hat."),
        ("Seitentitel", "Actions", "getPageTitles",
         "Dieselben Aufrufe, nur nach Überschrift statt nach Adresse — meist besser lesbar."),
        ("Einstiegsseiten", "Actions", "getEntryPageUrls",
         "Wo Besucher ankommen. Die interessanteste Tabelle, wenn du wissen willst, "
         "welche Inhalte Leute überhaupt hereinholen."),
        ("Ausstiegsseiten", "Actions", "getExitPageUrls",
         "Wo sie wieder gehen."),
        ("Klicks auf externe Links", "Actions", "getOutlinks", ""),
        ("Heruntergeladene Dateien", "Actions", "getDownloads", ""),
    ], flach=1, limit=200)
    return render(request, "matomo/bloecke.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "seitentitel": "Seiten",
        "untertitel": "Welche Inhalte von octotrial.com aufgerufen wurden.",
        "bloecke": bloecke, "fehler": None,
    })


@login_required
def suchbegriffe(request):
    """Nur das, wonach gesucht wurde."""
    von, bis, hinweis = _zeitfenster(request)
    bloecke = _bloecke(von, bis, [
        ("Suchbegriffe aus Suchmaschinen", "Referrers", "getKeywords",
         "Google und die meisten anderen Suchmaschinen geben den Suchbegriff seit "
         "Jahren nicht mehr weiter. Was hier steht, ist deshalb nur ein Bruchteil — "
         "der Rest erscheint als „Keyword not defined“."),
        ("Suchmaschinen", "Referrers", "getSearchEngines",
         "Über welche Suchmaschinen Besucher kamen — unabhängig davon, ob der "
         "Suchbegriff mitgeliefert wurde."),
        ("Suche auf der eigenen Website", "Actions", "getSiteSearchKeywords",
         "Wonach Besucher im Suchfeld von octotrial.com gesucht haben. Bleibt leer, "
         "wenn die Website-Suche in Matomo nicht eingerichtet ist."),
    ])
    return render(request, "matomo/bloecke.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "seitentitel": "Suchbegriffe",
        "untertitel": "Wonach Besucher gesucht haben, bevor sie auf octotrial.com landeten.",
        "bloecke": bloecke, "fehler": None,
    })


@login_required
def ki(request):
    """KI-Verkehr: Menschen über KI-Assistenten und die Bots selbst."""
    von, bis, hinweis = _zeitfenster(request)
    bloecke = _bloecke(von, bis, [
        ("Besucher, die über einen KI-Assistenten kamen", "Referrers", "getAIAssistants",
         "Echte Menschen: Jemand hat ChatGPT, Perplexity oder Ähnliches gefragt, "
         "octotrial.com als Quelle genannt bekommen und geklickt."),
        ("KI-Chatbots im Überblick", "BotTracking", "get",
         "Ab hier geht es um die Bots selbst. Sie erscheinen NICHT in den anderen "
         "Reitern — Matomo hält sie aus der normalen Besucherstatistik heraus."),
        ("Welche KI-Chatbots", "BotTracking", "getAIChatbotRequests",
         "GPTBot, ClaudeBot, PerplexityBot und Verwandte."),
        ("Von Bots gelesene Seiten", "BotTracking", "getAIChatbotContentPages", ""),
        ("Von Bots bevorzugte Seiten", "BotTracking", "getAIChatbotAIFavouredPages",
         "Inhalte, die KI-Systeme überdurchschnittlich oft holen."),
        ("Von Menschen bevorzugte Seiten", "BotTracking", "getAIChatbotHumanFavouredPages",
         "Die Gegenprobe: Was Menschen lesen, Bots aber links liegen lassen."),
        ("Fehlerhafte Seiten und Dokumente", "BotTracking", "getAIChatbotBrokenContent",
         "Adressen, an denen Bots auf Fehler stoßen — meist auch für Besucher kaputt."),
        ("Von Bots geholte Dokumente", "BotTracking", "getAIChatbotContentDocuments",
         "PDFs und andere Dateien."),
        ("KI-Agentenbesuche", "AIAgents", "get",
         "Agenten, die im Auftrag eines Nutzers handeln."),
    ], flach=1, limit=150)
    return render(request, "matomo/bloecke.html", {
        **_zeitraum_kontext(von, bis, hinweis),
        "seitentitel": "KI",
        "untertitel": "Besucher aus KI-Assistenten und die KI-Bots, die octotrial.com lesen.",
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
