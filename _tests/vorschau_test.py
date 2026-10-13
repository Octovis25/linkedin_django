"""Tests for planner/vorschau.py - the small preview pictures in the post lists.

Runs without the portal's database or Nextcloud:
    python _tests/vorschau_test.py
Needs Pillow, imageio-ffmpeg and Django (all in requirements.txt).
"""
import io
import os
import subprocess
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, '..', 'planner'))
ARBEIT = tempfile.mkdtemp()

import django
from django.conf import settings
settings.configure(
    BASE_DIR=ARBEIT, DEBUG=True, SECRET_KEY='test', ALLOWED_HOSTS=['*'],
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    MIDDLEWARE=['django.contrib.sessions.middleware.SessionMiddleware',
                'django.contrib.auth.middleware.AuthenticationMiddleware'],
    ROOT_URLCONF=__name__, LOGIN_URL='/login/')
django.setup()

import imageio_ffmpeg
from PIL import Image
from django.urls import path
import vorschau as v

urlpatterns = [path('planner/thumb/<int:post_id>/', v.post_vorschau)]

OK = FEHL = 0


def pruefe(name, bedingung, info=''):
    global OK, FEHL
    print(('OK  ' if bedingung else 'FEHL'), name, info if not bedingung else '')
    if bedingung:
        OK += 1
    else:
        FEHL += 1


# ── Helpers ────────────────────────────────────────────────────────────────
bild = Image.new('RGBA', (1080, 1080), (0, 133, 145, 255))
bild.putpixel((0, 0), (0, 0, 0, 0))
puffer = io.BytesIO(); bild.save(puffer, 'PNG'); PNG = puffer.getvalue()
klein = v.bild_verkleinern(PNG, 112)
r = Image.open(io.BytesIO(klein))
pruefe('A 1080 px PNG becomes a 112 px JPEG', r.format == 'JPEG' and r.size == (112, 112), (r.format, r.size))
pruefe('and is small', len(klein) < 10000, len(klein))

bilder = [Image.new('RGB', (400, 300), farbe) for farbe in [(255, 0, 0), (0, 0, 255)]]
puffer = io.BytesIO(); bilder[0].save(puffer, 'GIF', save_all=True, append_images=bilder[1:])
r = Image.open(io.BytesIO(v.bild_verkleinern(puffer.getvalue(), 112)))
px = r.convert('RGB').getpixel((50, 40))
pruefe('A GIF shows its first frame', px[0] > 200 and px[2] < 60, px)
pruefe('and keeps its proportions', r.size == (112, 84), r.size)

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
video = os.path.join(ARBEIT, 'video.webm')
subprocess.run([ffmpeg, '-y', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'color=c=red:s=640x640:d=1',
                '-f', 'lavfi', '-i', 'color=c=blue:s=640x640:d=2',
                '-filter_complex', '[0][1]concat=n=2:v=1', '-c:v', 'libvpx-vp9', '-b:v', '200k', video],
               check=True)
with open(video, 'rb') as f:
    VIDEO = f.read()
erstes = v.erstes_videobild(VIDEO, '.webm', 112)
r = Image.open(io.BytesIO(erstes))
px = r.convert('RGB').getpixel((50, 50))
pruefe('A video shows its first frame (red, not the blue that follows)', px[0] > 180 and px[2] < 80, px)
pruefe('as a small picture', r.size == (112, 112) and len(erstes) < 8000, (r.size, len(erstes)))

pruefe('The picture wins over the video', v.quelle_des_posts('Marketing & Design/x.png', 'a.webm') == ('Marketing & Design/x.png', 'image'))
pruefe('An old local name points to the planner folder', v.quelle_des_posts('planner/abc.png', '')[0] == v.PLANNER_BILDER + 'abc.png')
pruefe('GIF is recognised', v.quelle_des_posts('', 'Marketing & Design/a.GIF')[1] == 'gif')
pruefe('Video is recognised', v.quelle_des_posts('', 'Marketing & Design/a.webm')[1] == 'video')
pruefe('No media, no source', v.quelle_des_posts('', '') == (None, None))
pruefe('The key changes with the post', v.schluessel('a', 1, 112) != v.schluessel('a', 2, 112))

# ── The view ───────────────────────────────────────────────────────────────
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import Client

call_command('migrate', verbosity=0)
with connection.cursor() as c:
    c.execute("CREATE TABLE planner_posts (id INTEGER PRIMARY KEY, image TEXT, video_nc_path TEXT, updated_at TEXT)")
    c.execute("INSERT INTO planner_posts VALUES (1, 'Marketing & Design/LinkedIn/Planner/Images/a.png', '', '2026-10-13 10:00:00')")
    c.execute("INSERT INTO planner_posts VALUES (2, '', '', '2026-10-13 10:00:00')")
    c.execute("INSERT INTO planner_posts VALUES (3, '', 'Marketing & Design/LinkedIn/Planner/Videos/v.webm', '2026-10-13 10:00:00')")
abrufe = []
v._rohdaten = lambda p: (abrufe.append(p), VIDEO if p.endswith('.webm') else PNG)[1]

client = Client()
pruefe('Without login: no picture', client.get('/planner/thumb/1/').status_code == 302)
client.force_login(User.objects.create_user('o', 'o@x', 'pw'))
r = client.get('/planner/thumb/1/?v=1')
pruefe('With login: a JPEG', r.status_code == 200 and r['Content-Type'] == 'image/jpeg')
pruefe('which the browser may keep for a day', r['Cache-Control'] == 'private, max-age=86400', r['Cache-Control'])
etag = r['ETag']
client.get('/planner/thumb/1/?v=1')
pruefe('The second call comes from the disk, not from Nextcloud', len(abrufe) == 1, abrufe)
r = client.get('/planner/thumb/1/', HTTP_IF_NONE_MATCH=etag)
pruefe('An unchanged picture is answered with 304, without content', r.status_code == 304 and not r.content)
with connection.cursor() as c:
    c.execute("UPDATE planner_posts SET updated_at='2026-10-13 11:00:00' WHERE id=1")
r = client.get('/planner/thumb/1/', HTTP_IF_NONE_MATCH=etag)
pruefe('After a change the new picture comes', r.status_code == 200 and r['ETag'] != etag)
pruefe('and without ?v= the browser asks again each time', r['Cache-Control'] == 'private, no-cache')
r = client.get('/planner/thumb/3/')
pruefe('A video post gets its first frame', r.status_code == 200 and r['Content-Type'] == 'image/jpeg')
pruefe('A post without media: 404', client.get('/planner/thumb/2/').status_code == 404)
pruefe('No such post: 404', client.get('/planner/thumb/9/').status_code == 404)

print('\n%d ok, %d failed' % (OK, FEHL))
sys.exit(1 if FEHL else 0)
