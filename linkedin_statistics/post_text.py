"""DIE Verknuepfung zwischen LinkedIn-Kennzahlen und Beitragstext.

Eine Stelle, nicht mehrere. Wer Text zu Kennzahlen braucht, holt ihn hier -
damit nicht jede Auswertung ihre eigene Fassung dieser Zuordnung erfindet und
die Fassungen auseinanderlaufen.

Warum es so kompliziert ist
---------------------------
Es gibt keinen Schluessel zwischen den Tabellen:

  * ``planner_posts.link`` ist ein CANVA-Link, keine LinkedIn-URL.
  * ``linkedin_posts`` fuehrt ``urn:li:activity:<n>``, ``buffer_posts_posted``
    dagegen ``urn:li:share:<n>`` und ``urn:li:ugcPost:<n>``. Das sind bei
    LinkedIn drei verschiedene Kennungen desselben Beitrags - die Zahlen
    dahinter stimmen nicht ueberein.
  * ``buffer_posts_posted.planner_post_id`` ist bei 4 von 112 Zeilen gesetzt.

Bleibt der Inhalt: Der Titel in ``linkedin_posts`` ist der Anfang des
Beitragstextes. Verglichen werden die ersten 45 Zeichen, nachdem aller
Weissraum entfernt wurde - der Titel hat an manchen Stellen ein Leerzeichen,
wo der Text zwei hat, und laengere Vergleiche brechen genau daran.

Gemessen am 11.09.2026: 65 von 74 Posts zugeordnet, alle 65 eindeutig
(keine Mehrfachtreffer). Die 9 ohne Text stammen samtlich aus Juni bis
Oktober 2025 - aus der Zeit vor Buffer. Ab November 2025 ist die Abdeckung
lueckenlos.

Warum 45 und nicht 20
---------------------
20 Zeichen ordnen einen Post mehr zu (66), aber nur 62 davon eindeutig: mehrere
Beitraege beginnen gleich ("Behind the Scenes of Data Management ..."). Bei 45
Zeichen sind alle Treffer eindeutig. Eine falsche Zuordnung ist schlimmer als
eine fehlende - deshalb die laengere Variante.

Die Kollationen der Tabellen sind gemischt (utf8mb4_unicode_ci gegen
utf8mb4_0900_ai_ci), jeder Vergleich muss sie erzwingen.
"""
from django.db import connection

KOLLATION = "COLLATE utf8mb4_unicode_ci"
ZEICHEN = 45


def _ohne_weissraum(ausdruck):
    """SQL-Ausdruck: Weissraum entfernt, auf ZEICHEN gekuerzt, feste Kollation."""
    x = ausdruck
    for weg in ("'\\n'", "'\\r'", "'\\t'", "' '"):
        x = "REPLACE(%s, %s, '')" % (x, weg)
    return "LEFT(%s, %d) %s" % (x, ZEICHEN, KOLLATION)


# Titel: der gepflegte aus linkedin_posts_posted hat Vorrang, dann der rohe.
TITEL = ("COALESCE(NULLIF(pp.post_title, ''), NULLIF(lp.post_title_raw, ''), "
         "lp.post_title)")

SQL = """
    SELECT lp.post_id,
           COALESCE(pp.post_date, lp.post_date)      AS datum,
           COALESCE(lp.content_type, '')             AS art,
           COALESCE(m.impressions, 0)                AS impressionen,
           COALESCE(m.clicks, 0)                     AS klicks,
           COALESCE(m.likes, 0)                      AS likes,
           COALESCE(m.comments, 0)                   AS kommentare,
           b.post_text                               AS text
    FROM linkedin_posts lp
    LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
    LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
        AND m.metric_date = (
            SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
            WHERE m2.post_id = m.post_id)
    JOIN buffer_posts_posted b ON {titel_norm} = {text_norm}
    WHERE {titel} IS NOT NULL AND {titel} <> ''
    ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
""".format(titel=TITEL,
           titel_norm=_ohne_weissraum(TITEL),
           text_norm=_ohne_weissraum("b.post_text"))


def _inhalts_schluessel(text):
    """Erste ZEICHEN Zeichen ohne Weissraum, klein - dieselbe Regel wie im SQL."""
    t = (text or '')
    for weg in ('\n', '\r', '\t', ' '):
        t = t.replace(weg, '')
    return t[:ZEICHEN].lower()


def posts_mit_text(alle_fassungen=False):
    """Liste von dicts: post_id, datum, art, impressionen, klicks, likes,
    kommentare, text, ctr. Nur Posts, denen ein Text zugeordnet werden konnte.

    Genau EINE Zeile je Beitrag. In buffer_posts_posted stehen einzelne Texte
    mehrfach (112 Zeilen fuer deutlich weniger Beitraege); ohne diese Stufe
    liefert der Join fuer solche Beitraege zwei Zeilen, und sie zaehlen in
    jedem Mittelwert doppelt."""
    with connection.cursor() as c:
        c.execute(SQL)
        spalten = [s[0] for s in c.description]
        roh = [dict(zip(spalten, r)) for r in c.fetchall()]

    gesehen, zeilen = set(), []
    for z in roh:
        if z['post_id'] in gesehen:
            continue
        gesehen.add(z['post_id'])
        zeilen.append(z)

    for z in zeilen:
        imp = z['impressionen'] or 0
        z['ctr'] = (100.0 * (z['klicks'] or 0) / imp) if imp else None
        z['ist_video'] = (z['art'] or '').lower() == 'video'

    if alle_fassungen:
        return zeilen

    # Geloescht und neu veroeffentlicht: derselbe Text steht dann zweimal in
    # linkedin_posts - einmal als Stummel mit der Reichweite der paar Stunden
    # vor dem Loeschen, einmal mit der echten. Beide zu zaehlen ist doppelt
    # falsch: derselbe Inhalt zweimal, und die Stummelzeile zieht jeden
    # Mittelwert nach unten. Behalten wird die Fassung, die tatsaechlich lief -
    # die mit den meisten Impressionen.
    beste = {}
    for z in zeilen:
        k = _inhalts_schluessel(z['text'])
        if not k:
            beste[('leer', z['post_id'])] = z
            continue
        vorher = beste.get(k)
        if vorher is None or (z['impressionen'] or 0) > (vorher['impressionen'] or 0):
            beste[k] = z
    behalten = list(beste.values())
    behalten.sort(key=lambda z: z['datum'] or '', reverse=True)
    return behalten


def wiederholungen():
    """(zusammengefasst, gesamt_zeilen) - wie viele Beitraege als Wiederholung
    desselben Textes verschmolzen wurden. Gehoert in jeden Bericht, damit
    niemand die Fallzahl fuer groesser haelt, als sie ist."""
    alle = posts_mit_text(alle_fassungen=True)
    return len(alle) - len(posts_mit_text()), len(alle)


def abdeckung():
    """(zugeordnet, gesamt) - fuer den Fall, dass jemand wissen will, worauf
    eine Auswertung eigentlich beruht. Gehoert in jeden Bericht.
    Gezaehlt werden Beitraege, nicht Trefferzeilen."""
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM linkedin_posts")
        gesamt = c.fetchone()[0]
    return len(posts_mit_text()), gesamt
