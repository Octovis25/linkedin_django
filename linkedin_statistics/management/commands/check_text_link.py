"""Sucht die Bruecke zwischen Beitragstext und LinkedIn-Kennzahlen.

Runde 4 - die entscheidende. Stand nach Runde 3:

  * Der Weg ueber URLs und IDs ist tot: planner_posts.link ist ein Canva-Link,
    und linkedin_posts benutzt urn:li:activity waehrend Buffer urn:li:share
    bzw. urn:li:ugcPost fuehrt - andere Zahlen, derselbe Beitrag.
  * Der Weg ueber den Inhalt traegt: die ersten 25 Zeichen von Titel und
    Buffer-Text stimmen bei 66 von 74 Posts ueberein (89 %).
  * Laengere Vergleiche brechen an Kleinigkeiten - der Titel hat ein
    Leerzeichen, wo der Text zwei hat.

Dieser Lauf sucht die beste Normalisierung UND prueft, wie eindeutig sie ist.
Eine Zuordnung, die zwei Texte auf denselben Post wirft, ist schlimmer als
gar keine. Er veraendert nichts.

    python manage.py check_text_link
"""
from django.core.management.base import BaseCommand
from django.db import connection

K = "COLLATE utf8mb4_unicode_ci"

# Alles Weissraum raus, dann die ersten N Zeichen. Das ueberlebt doppelte
# Leerzeichen, Zeilenumbrueche und unterschiedliche Einrueckung.
def norm(ausdruck, n):
    x = ausdruck
    for weg in ("'\\n'", "'\\r'", "' '", "'\\t'"):
        x = "REPLACE(%s, %s, '')" % (x, weg)
    return "LEFT(%s, %d) %s" % (x, n, K)


TITEL = "COALESCE(NULLIF(pp.post_title,''), NULLIF(lp.post_title_raw,''), lp.post_title)"


def zahl(c, sql):
    try:
        c.execute(sql)
        r = c.fetchone()
        return r[0] if r else 0
    except Exception as e:
        return "FEHLER: " + str(e)[:130]


def zeilen(c, sql, n=12):
    try:
        c.execute(sql)
        return c.fetchmany(n)
    except Exception as e:
        return [("FEHLER: " + str(e)[:120], "")]


class Command(BaseCommand):
    help = "Sucht die beste und eindeutigste Zuordnung von Beitragstext zu Kennzahlen."

    def handle(self, *args, **options):
        p = self.stdout.write
        with connection.cursor() as c:
            gesamt = zahl(c, "SELECT COUNT(*) FROM linkedin_posts")

            p("")
            p("=== 1. Welche Titelspalte, welche Laenge? ===")
            p("  Zugeordnet = mindestens ein Buffer-Text passt.")
            p("  Eindeutig  = genau einer passt. Nur die Zahl zaehlt.")
            p("")
            p("  Titelquelle     Zeichen   zugeordnet   eindeutig")

            beste = None
            for quelle, bez in ((TITEL, "title/raw"),
                                ("lp.post_title_raw", "raw      "),
                                ("lp.post_title", "title    ")):
                for n in (20, 30, 45, 60):
                    sql = """
                        SELECT COUNT(*), SUM(CASE WHEN t = 1 THEN 1 ELSE 0 END)
                        FROM (
                          SELECT lp.post_id, COUNT(DISTINCT b.post_text) AS t
                          FROM linkedin_posts lp
                          LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                          JOIN buffer_posts_posted b
                            ON {tn} = {bn}
                          WHERE {titel} IS NOT NULL AND {titel} <> ''
                          GROUP BY lp.post_id
                        ) x
                    """.format(tn=norm(quelle, n), bn=norm("b.post_text", n), titel=quelle)
                    try:
                        c.execute(sql)
                        r = c.fetchone()
                        zu, ein = int(r[0] or 0), int(r[1] or 0)
                    except Exception as e:
                        p("  %s   %3d      FEHLER: %s" % (bez, n, str(e)[:70]))
                        continue
                    p("  %s       %3d   %3d von %d   %3d" % (bez, n, zu, gesamt, ein))
                    if beste is None or ein > beste[0]:
                        beste = (ein, zu, quelle, n, bez)

            if not beste:
                p("\n  Keine Variante hat funktioniert.")
                return

            ein, zu, quelle, n, bez = beste
            p("")
            p("=== 2. Beste Variante ===")
            p("  Titelquelle %s, erste %d Zeichen ohne Weissraum" % (bez.strip(), n))
            p("  %d von %d zugeordnet, davon %d eindeutig" % (zu, gesamt, ein))
            p("")

            p("=== 3. Die Mehrdeutigen (falls es welche gibt) ===")
            mehr = zeilen(c, """
                SELECT LEFT({titel}, 60), COUNT(DISTINCT b.post_text)
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                JOIN buffer_posts_posted b ON {tn} = {bn}
                WHERE {titel} IS NOT NULL AND {titel} <> ''
                GROUP BY lp.post_id, LEFT({titel}, 60)
                HAVING COUNT(DISTINCT b.post_text) > 1
                ORDER BY 2 DESC
            """.format(titel=quelle, tn=norm(quelle, n), bn=norm("b.post_text", n)), 8)
            if not mehr:
                p("  Keine. Jede Zuordnung ist eindeutig.")
            for r in mehr:
                p("  %sx  %s" % (r[1], r[0]))

            p("")
            p("=== 4. Die Uebriggebliebenen ===")
            p("  Diese Posts finden keinen Text. Wenn das Bildbeitraege ohne")
            p("  Fliesstext sind, ist das in Ordnung.")
            p("")
            fehlt = zeilen(c, """
                SELECT DATE(COALESCE(pp.post_date, lp.post_date)),
                       LEFT(COALESCE({titel}, '(kein Titel)'), 58),
                       COALESCE(lp.content_type, '-')
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                WHERE NOT EXISTS (
                  SELECT 1 FROM buffer_posts_posted b WHERE {tn} = {bn}
                )
                ORDER BY 1 DESC
            """.format(titel=quelle, tn=norm(quelle, n), bn=norm("b.post_text", n)), 15)
            for r in fehlt:
                p("  %s  %-58s  %s" % (r[0], r[1], r[2]))

            p("")
            p("=== Fertig. Bitte Abschnitt 1 bis 4 zurueckgeben. ===")
            p("")
