"""Zeigt, welche Begriffe in Beitraegen mit hoher bzw. niedriger CTR vorkommen.

    python manage.py analyze_terms
    python manage.py analyze_terms --min 6 --hook

Bewusst KEINE p-Werte. Bei rund 65 Posts und hundert getesteten Begriffen
waeren ein halbes Dutzend "signifikante" Treffer reiner Zufall, und die
groessten Stoergroessen (Zeit, Format, Thema) stecken ungefiltert in den
Zahlen. Was hier herauskommt, sind Kandidaten fuer einen geplanten Versuch -
keine Belege.

Warum CTR und nicht Impressionen
--------------------------------
Wie oft ein Beitrag ausgespielt wird, entscheidet der Algorithmus. Ob jemand
klickt, entscheidet ein Mensch, der den Beitrag bereits gesehen hat. Die CTR
ist damit auf die Reichweite normiert und deutlich weniger von Followerzahl,
Uhrzeit und Wochentag verzerrt. Die Impressionen stehen trotzdem mit dabei.

Der Zeitraum je Begriff wird mitgedruckt: Liegen alle Beitraege mit einem
Begriff im selben Monat, misst man den Monat und nicht den Begriff.
"""
import random
import re
from collections import defaultdict

from django.core.management.base import BaseCommand

from linkedin_statistics.post_text import posts_mit_text, abdeckung, wiederholungen

# Fuellwoerter aus beiden Sprachen. Keine Wissenschaft, nur Rauschfilter.
STOPP = set("""
the a an and or but if then than that this these those of to in on at for with
from by as is are was were be been being it its we our you your they their he
she his her i me my not no so such can could will would should may might do
does did done have has had he's we're it's don't doesn't isn't you're at about
into over under more most much many any all some each other new now just only
der die das ein eine einen einem einer und oder aber wenn dann als dass diese
dieser dieses von zu in im am auf fuer für mit aus bei nach vor ueber über
unter ist sind war waren sein wird werden kann koennen können soll sollen muss
muessen müssen hat haben hatte nicht kein keine auch noch nur schon sehr mehr
alle jeder jede jedes man wir ihr sie es du ich mein dein unser euer
""".split())

WORT = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]+")


def median(werte):
    w = sorted(v for v in werte if v is not None)
    if not w:
        return None
    n = len(w)
    return w[n // 2] if n % 2 else (w[n // 2 - 1] + w[n // 2]) / 2.0


class Command(BaseCommand):
    help = "Begriffe gegen CTR und Impressionen - als Hypothesenliste, nicht als Beleg."

    def add_arguments(self, parser):
        parser.add_argument('--min', type=int, default=8,
                            help='Mindestzahl Beitraege je Begriff (Standard 8).')
        parser.add_argument('--hook', action='store_true',
                            help='Nur die ersten 200 Zeichen ansehen - das, was vor '
                                 '"mehr anzeigen" steht und die Entscheidung traegt.')
        parser.add_argument('--min-impressionen', type=int, default=0,
                            dest='min_imp',
                            help='Beitraege mit weniger Impressionen ganz weglassen - '
                                 'gegen Reste geloeschter Beitraege.')
        parser.add_argument('--permutation', type=int, default=0, metavar='N',
                            help='N Zufallsdurchlaeufe: wie gross waere der groesste '
                                 'Unterschied, wenn KEIN Wort wirkt? Beantwortet die '
                                 'Multiplizitaet richtig. 2000 ist ein guter Wert.')
        parser.add_argument('--top', type=int, default=25,
                            help='Wie viele Begriffe je Richtung (Standard 25).')

    def handle(self, *args, **o):
        p = self.stdout.write
        posts = posts_mit_text()
        zugeordnet, gesamt = len(posts), abdeckung()[1]
        if o['min_imp']:
            vorher = len(posts)
            posts = [x for x in posts if (x['impressionen'] or 0) >= o['min_imp']]
            self.stdout.write("%d Beitrag/Beitraege unter %d Impressionen weggelassen."
                              % (vorher - len(posts), o['min_imp']))

        p("")
        p("Grundlage: %d von %d Beitraegen haben einen zugeordneten Text." % (zugeordnet, gesamt))
        if not posts:
            p("Ohne Texte keine Auswertung.")
            return
        mit_ctr = [x for x in posts if x['ctr'] is not None]
        p("Davon %d mit Impressionen > 0, also mit berechenbarer CTR." % len(mit_ctr))
        doppelt, roh = wiederholungen()
        if doppelt:
            p("%d Zeile(n) als Wiederholung desselben Textes zusammengefasst." % doppelt)
            p("  (Geloescht und neu veroeffentlicht - die Stummelzeile vor dem")
            p("   Loeschen wuerde jeden Mittelwert nach unten ziehen.)")
        p("Zeitraum: %s bis %s" % (min(x['datum'] for x in posts), max(x['datum'] for x in posts)))
        if o['hook']:
            p("Betrachtet wird nur der Anfang (200 Zeichen) - der sichtbare Teil.")
        p("")

        gesamt_ctr = median([x['ctr'] for x in mit_ctr])
        gesamt_imp = median([x['impressionen'] for x in posts])
        gesamt_kli = median([x['klicks'] for x in posts])
        p("Median ueber alles:  CTR %.2f %%   Impressionen %.0f   Klicks %.0f"
          % (gesamt_ctr or 0, gesamt_imp or 0, gesamt_kli or 0))
        p("")
        # Sehr kleine Reichweiten sind fast immer Reste geloeschter Beitraege.
        # Sie stehen hier, damit man sie sieht statt sie im Median zu verstecken.
        winzig = sorted(x for x in (z['impressionen'] or 0 for z in posts) if x < 25)
        if winzig:
            p("Auffaellig: %d Beitrag/Beitraege mit weniger als 25 Impressionen (%s)."
              % (len(winzig), ", ".join(str(w) for w in winzig)))
            p("  Meist Reste geloeschter Beitraege. Mit --min-impressionen ausschliessen.")
            p("")

        # Begriff -> Menge von Post-Indizes (einmal je Beitrag, nicht je Vorkommen)
        vorkommen = defaultdict(set)
        for i, x in enumerate(posts):
            text = x['text'] or ''
            if o['hook']:
                text = text[:200]
            for w in set(m.group(0).lower() for m in WORT.finditer(text)):
                if len(w) > 2 and w not in STOPP:
                    vorkommen[w].add(i)

        # Begriffe, die in GENAU denselben Beitraegen stehen, sind kein
        # eigenstaendiger Befund - sie sind ein Textbaustein. "share", "opinion",
        # "comments" und "follow" kommen bei dir immer gemeinsam vor: ein
        # Aufruf-Block, viermal gezaehlt. Solche Gruppen kommen in eine Zeile.
        nach_fussabdruck = defaultdict(list)
        for wort, idx in vorkommen.items():
            if len(idx) >= o['min']:
                nach_fussabdruck[frozenset(idx)].append(wort)

        zeilen = []
        for idx, woerter in nach_fussabdruck.items():
            drin = [posts[i] for i in idx]
            draussen = [posts[i] for i in range(len(posts)) if i not in idx]
            c_drin = median([x['ctr'] for x in drin if x['ctr'] is not None])
            c_drau = median([x['ctr'] for x in draussen if x['ctr'] is not None])
            if c_drin is None or c_drau is None:
                continue
            monate = sorted(set(str(x['datum'])[:7] for x in drin))
            woerter = sorted(woerter)
            name = woerter[0] if len(woerter) == 1 else \
                "%s +%d" % (woerter[0], len(woerter) - 1)
            zeilen.append({
                'name': name, 'woerter': woerter, 'n': len(idx),
                'ctr_drin': c_drin, 'ctr_draussen': c_drau,
                'delta': c_drin - c_drau,
                'klicks': median([x['klicks'] for x in drin]),
                'imp': median([x['impressionen'] for x in drin]),
                'von': monate[0], 'bis': monate[-1], 'monate': len(monate),
            })

        if not zeilen:
            p("Kein Begriff kommt in mindestens %d Beitraegen vor. Mit --min "
              "kleiner versuchen - aber je kleiner, desto mehr Zufall." % o['min'])
            return

        zeilen.sort(key=lambda z: z['delta'], reverse=True)
        # Die beiden Listen duerfen sich nicht ueberschneiden, sonst steht
        # derselbe Begriff einmal als "hoeher" und einmal als "niedriger" da.
        k = min(o['top'], len(zeilen) // 2) or 1
        oben, unten = zeilen[:k], list(reversed(zeilen[-k:]))

        kopf = ("  %-26s %4s  %7s %7s %8s  %6s %6s  %s"
                % ("Begriff", "n", "CTR mit", "ohne", "Diff", "Klick", "Impr.", "Zeitraum"))

        def block(titel, liste):
            p(titel)
            p(kopf)
            for z in liste:
                warn = "  << nur %d Monat" % z['monate'] if z['monate'] <= 2 else ""
                p("  %-26s %4d  %6.2f%% %6.2f%% %+7.2f  %6.0f %6.0f  %s-%s%s"
                  % (z['name'], z['n'], z['ctr_drin'], z['ctr_draussen'],
                     z['delta'], z['klicks'] or 0, z['imp'] or 0,
                     z['von'], z['bis'], warn))
            p("")
            gruppen = [z for z in liste if len(z['woerter']) > 1]
            if gruppen:
                p("  Bausteine (Woerter, die immer gemeinsam auftreten):")
                for z in gruppen:
                    p("    %s = %s" % (z['name'], ", ".join(z['woerter'])))
                p("")

        block("=== Begriffe in Beitraegen mit hoeherer CTR ===", oben)
        block("=== Begriffe in Beitraegen mit niedrigerer CTR ===", unten)

        p("%d Begriffsgruppen erreichen die Mindestzahl von %d Beitraegen."
          % (len(zeilen), o['min']))
        p("")

        if o['permutation']:
            self._permutation(p, posts, nach_fussabdruck, zeilen, o['permutation'])
        p("Zu lesen als: In Beitraegen mit diesem Wort lag die CTR im Mittel so,")
        p("in den uebrigen so. Das ist eine Beobachtung, keine Wirkung - ein Wort")
        p("kann schlicht fuer sein Thema oder seinen Monat stehen.")
        p("")
        p("Auf die Klick-Spalte achten: bei rund 100 Impressionen sind drei")
        p("Prozent CTR drei Klicks. Zwischen drei und acht Prozent liegen also")
        p("fuenf Klicks. Prozente sehen bei solchen Zahlen groesser aus als sie sind.")
        p("")
        p("Ein mit '<< nur N Monat' markierter Begriff kam nur in ein oder zwei")
        p("Monaten vor. Dort misst man die Zeit, nicht den Begriff.")
        p("")
        p("Naechster ehrlicher Schritt: zwei, drei Kandidaten vorab festlegen und")
        p("ueber die naechsten 20 Beitraege geplant einsetzen, verteilt ueber")
        p("Format und Zeit. Dann hat man ein Design statt einer Nachbetrachtung.")
        p("")

    def _permutation(self, p, posts, gruppen, zeilen, runden):
        """Die einzige Frage, die bei 72 getesteten Gruppen zaehlt:

        Wie gross waere der groesste Unterschied, den man findet, wenn gar kein
        Wort wirkt? Dazu werden die CTR-Werte wiederholt zufaellig auf die
        Beitraege verteilt - Gruppengroessen und Ueberlappungen bleiben also
        genau wie sie sind - und jedes Mal der groesste Unterschied notiert.

        Liegt der echte Spitzenwert mitten in dieser Verteilung, ist er das,
        wonach er aussieht: der groesste von vielen Zufallswerten.
        """
        mit = [i for i, x in enumerate(posts) if x['ctr'] is not None]
        if len(mit) < 12:
            p("Zu wenige Beitraege mit CTR fuer den Zufallstest.")
            return
        pos = {idx: k for k, idx in enumerate(mit)}
        werte = [posts[i]['ctr'] for i in mit]

        # Gruppen auf die Positionen in `werte` umrechnen, kleine weglassen.
        mengen = []
        for idx in gruppen:
            innen = [pos[i] for i in idx if i in pos]
            if 3 <= len(innen) <= len(werte) - 3:
                mengen.append(set(innen))
        if not mengen:
            p("Keine Gruppe gross genug fuer den Zufallstest.")
            return

        def groesster_unterschied(w):
            best = 0.0
            for m in mengen:
                drin = sorted(w[i] for i in m)
                drau = sorted(w[i] for i in range(len(w)) if i not in m)
                a, b = len(drin), len(drau)
                md = drin[a // 2] if a % 2 else (drin[a // 2 - 1] + drin[a // 2]) / 2.0
                mo = drau[b // 2] if b % 2 else (drau[b // 2 - 1] + drau[b // 2]) / 2.0
                d = abs(md - mo)
                if d > best:
                    best = d
            return best

        echt = groesster_unterschied(werte)
        zufall = []
        gemischt = list(werte)
        for _ in range(runden):
            random.shuffle(gemischt)
            zufall.append(groesster_unterschied(gemischt))
        zufall.sort()

        def quantil(q):
            return zufall[min(len(zufall) - 1, int(q * len(zufall)))]

        groesser = sum(1 for z in zufall if z >= echt)
        p("=== Zufallstest ueber %d Durchlaeufe, %d Gruppen ===" % (runden, len(mengen)))
        p("")
        p("  Groesster echter Unterschied:        %+.2f Prozentpunkte" % echt)
        p("  Bei reinem Zufall typischerweise:   %.2f  (Median)" % quantil(0.50))
        p("                      in 95 %% der Faelle unter:  %.2f" % quantil(0.95))
        p("")
        p("  In %d von %d Zufallsdurchlaeufen war der groesste Unterschied"
          % (groesser, runden))
        p("  mindestens so gross wie der echte.  ->  p = %.3f"
          % ((groesser + 1.0) / (runden + 1.0)))
        p("")
        if (groesser + 1.0) / (runden + 1.0) > 0.10:
            p("  Damit ist der Spitzenwert nicht von Zufall zu unterscheiden.")
            p("  Bei %d Gruppen findet man solche Unterschiede auch dann," % len(mengen))
            p("  wenn kein einziges Wort irgendeine Wirkung hat.")
        else:
            p("  Das ist mehr, als Zufall bei dieser Gruppenzahl ueblicherweise")
            p("  hergibt. Ein Grund, den Spitzenreiter geplant zu testen -")
            p("  weiterhin kein Beleg, aber ein begruendeter Verdacht.")
        p("")
