"""Two things that go wrong in templates, checked in every template we have.

Both have already happened in this project, and both were found by hand:

  * {# ... #} comments out exactly ONE line. A note written over two lines is
    printed into the page, word for word, where a reader takes it for content.
    A check for this existed - but only for kalender.html, and the next one I
    wrote went into base.html, where nothing was looking.
  * {% static 'images/x.png' %} names a file. If that file is not there, the
    page still renders: the browser gets a 404 for an image nobody notices,
    and a logo or an icon is simply missing.

No Django, no server - the templates are read as text.

    python _tests/vorlagen_test.py
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)

# Everything Django would load, and nothing that is only built output.
UEBERSPRINGEN = ('.git', 'venv', '.venv', 'staticfiles', 'node_modules', '_mockups')

VORLAGEN = []
for ordner, unter, dateien in os.walk(WURZEL):
    unter[:] = [u for u in unter if u not in UEBERSPRINGEN]
    if os.path.basename(ordner) == 'templates' or os.sep + 'templates' + os.sep in ordner:
        for name in dateien:
            if name.endswith('.html'):
                VORLAGEN.append(os.path.join(ordner, name))
VORLAGEN.sort()

gut = schlecht = 0


def pruefe(name, ok, extra=''):
    global gut, schlecht
    if ok:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FAIL ' + name + ('  -> ' + str(extra) if extra != '' else ''))


def kurz(pfad):
    return os.path.relpath(pfad, WURZEL).replace(os.sep, '/')


print('\n=== The templates that were found ===')
pruefe('there are templates to look at at all', len(VORLAGEN) >= 10, len(VORLAGEN))
print('  %d templates' % len(VORLAGEN))

print('\n=== No template comment runs over more than one line ===')
schuldige = []
for pfad in VORLAGEN:
    text = open(pfad, encoding='utf-8').read()
    for kommentar in re.findall(r'\{#.*?#\}', text, re.S):
        if '\n' in kommentar:
            schuldige.append('%s: %s...' % (kurz(pfad), kommentar[:40].replace('\n', ' ')))
pruefe('{# ... #} stays on its line everywhere', not schuldige, schuldige[:3])

print('\n=== Every file a template asks for is really there ===')
# Only the plain ones: {% static 'images/logo.png' %}. Anything built from a
# variable cannot be checked here, and is left alone on purpose.
SUCHORTE = [os.path.join(WURZEL, 'static'),
            os.path.join(WURZEL, 'core', 'static'),
            os.path.join(WURZEL, 'media_library', 'static'),
            os.path.join(WURZEL, 'planner', 'static')]
fehlend = []
gefunden = 0
for pfad in VORLAGEN:
    text = open(pfad, encoding='utf-8').read()
    for treffer in re.findall(r"\{%\s*static\s+'([^'{}]+)'\s*%\}", text):
        gefunden += 1
        if not any(os.path.exists(os.path.join(ort, *treffer.split('/'))) for ort in SUCHORTE):
            fehlend.append('%s: %s' % (kurz(pfad), treffer))
pruefe('%d static files, all of them present' % gefunden, not fehlend, fehlend[:4])

print('\n=== The logo and the browser tab ===')
basis = open(os.path.join(WURZEL, 'core', 'templates', 'core', 'base.html'),
             encoding='utf-8').read()
pruefe('the header shows the logo', "images/octovis_logo.png" in basis)
pruefe('the tab has an icon', 'rel="icon"' in basis)
pruefe('and one that Apple uses too', 'apple-touch-icon' in basis)

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
