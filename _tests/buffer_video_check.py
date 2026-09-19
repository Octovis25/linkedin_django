"""Does the address we hand to Buffer really deliver a video?

Buffer does not fetch the file from us. It gets a public Cloudinary address and
fetches that itself, once, right after we send the post. If the address answers
with nothing - because Cloudinary has not produced the file yet, or produced
something else - the post goes out with an empty video and nobody is told.

This walks the same path: it runs the real _upload_video_to_cloudinary() from
planner/views.py, prints the address that Buffer would have been given, and then
fetches it the way Buffer would. Twice, a few seconds apart, because the
interesting question is whether the file only appears on the second try.

It does NOT send anything to Buffer. It does upload one file to Cloudinary -
the same upload the real send would do, under a new timestamped name.

    python _tests/buffer_video_check.py 53
"""
import os
import sys
import time

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                                    # noqa: E402

django.setup()

import requests                                  # noqa: E402
from django.db import connection                 # noqa: E402

if len(sys.argv) < 2 or not sys.argv[1].isdigit():
    print(__doc__)
    sys.exit(2)
POST = int(sys.argv[1])

with connection.cursor() as c:
    c.execute("""SELECT COALESCE(title,''), COALESCE(image,''), COALESCE(gif_nc_path,''),
                        COALESCE(video_nc_path,''), COALESCE(status,'')
                 FROM planner_posts WHERE id=%s""", [POST])
    row = c.fetchone()

if not row:
    print('There is no post #%d.' % POST)
    sys.exit(1)

titel, bild, gif, video, status = row
print('Post #%d  %s' % (POST, titel[:70]))
print('  status : %s' % (status or '(empty)'))
print('  image  : %s' % (bild or '-'))
print('  gif    : %s' % (gif or '-'))
print('  video  : %s' % (video or '-'))
datei = video or gif
if not datei:
    print('\nNo video and no GIF on this post - nothing that could have gone out empty.')
    sys.exit(0)
print('  the file is a %s' % ('GIF' if datei.lower().endswith('.gif') else 'video'))
print()

fehlt = [n for n in ('CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET')
         if not os.environ.get(n, '').strip()]
if fehlt:
    print('Cloudinary is not configured here: %s' % ', '.join(fehlt))
    print('Run this in the Render shell instead - that is where the real send runs.')
    sys.exit(3)

from planner.views import _upload_video_to_cloudinary    # noqa: E402

print('Uploading to Cloudinary, exactly as the send would…')
try:
    url = _upload_video_to_cloudinary(POST)
except Exception as fehler:
    print('  the upload itself fails: %s' % fehler)
    print('  -> Then the send would report an error, not go out empty.')
    sys.exit(1)

print('  address handed to Buffer: %s' % url)
weg = 'image endpoint, extension swapped to .mp4' if '/image/upload/' in url else 'video endpoint'
print('  route: %s' % weg)
print()


def hole(nr):
    try:
        r = requests.get(url, stream=True, timeout=60)
        laenge = r.headers.get('Content-Length')
        art = r.headers.get('Content-Type', '')
        # Read a little, so a body without a Content-Length is measured too.
        gelesen = 0
        for stueck in r.iter_content(chunk_size=65536):
            gelesen += len(stueck)
            if gelesen > 2 * 1024 * 1024:
                break
        r.close()
        print('  try %d: HTTP %s  type=%s  length=%s  first bytes read=%d'
              % (nr, r.status_code, art or '(none)', laenge or '(none)', gelesen))
        return r.status_code, art, gelesen
    except Exception as f:
        print('  try %d: the request fails: %s' % (nr, f))
        return 0, '', 0


code1, art1, gelesen1 = hole(1)
print('  waiting 8 seconds…')
time.sleep(8)
code2, art2, gelesen2 = hole(2)

print()
if code1 == 200 and gelesen1 > 0 and 'video' in art1:
    print('=> The address delivers a video right away, so Cloudinary is not the')
    print('   problem. What it delivers might still be.')
elif code2 == 200 and gelesen2 > 0:
    print('=> Only the SECOND try delivers something. Cloudinary produces the file')
    print('   on first request, and Buffer fetches once, at once. The conversion')
    print('   has to be finished BEFORE the address goes to Buffer.')
else:
    print('=> The address delivers nothing usable, not even on the second try.')

# ---- Would MP4 work? ------------------------------------------------------
# LinkedIn takes MP4 (H.264), not WebM. Cloudinary transcodes on request: ask
# for the same asset with a .mp4 extension. If that delivers a real MP4, the
# fix is to hand Buffer THAT address - but the first request is what triggers
# the conversion, so it may need a moment.
print()
print('Same file as MP4, which is what LinkedIn actually takes:')
stamm, _punkt, endung = url.rpartition('.')
if endung.lower() == 'mp4':
    print('  the address is already an MP4 - nothing to compare.')
else:
    mp4 = stamm + '.mp4'
    print('  %s' % mp4)
    alte_url = url
    url = mp4
    m1 = hole(1)
    if m1[0] != 200 or 'mp4' not in m1[1]:
        print('  waiting 15 seconds - the first request is what starts the conversion…')
        time.sleep(15)
        m2 = hole(2)
    else:
        m2 = m1
    url = alte_url
    print()
    if m2[0] == 200 and m2[2] > 0 and 'mp4' in m2[1]:
        print('=> MP4 works. The WebM we hand over today is the suspect: LinkedIn')
        print('   does not take WebM. The fix is to have Cloudinary convert first')
        print('   and give Buffer the MP4 address, not the original.')
    else:
        print('=> Even the MP4 address gives nothing usable. Then converting is not')
        print('   enough by itself and the upload needs an eager transformation.')

# ---- And what did Buffer actually store? ----------------------------------
print()
print('What Buffer has for this post:')
with connection.cursor() as c:
    c.execute("SELECT COALESCE(buffer_update_id,'') FROM planner_posts WHERE id=%s", [POST])
    r = c.fetchone()
buffer_id = (r or [''])[0]
if not buffer_id:
    print('  this post carries no Buffer id - it was never sent through Buffer.')
else:
    print('  Buffer id: %s' % buffer_id)
    try:
        with connection.cursor() as c:
            c.execute("""SELECT t.buffer_token FROM planner_linkedin_tokens t
                         JOIN auth_user u ON t.user_id = u.id
                         WHERE u.is_superuser = 1 AND t.buffer_token IS NOT NULL LIMIT 1""")
            tr = c.fetchone()
        if not tr or not tr[0]:
            print('  no Buffer token stored here - run this in the Render shell.')
        else:
            from planner.views import _buffer_fetch_posts_basic, _buffer_first_org_id
            org = _buffer_first_org_id(tr[0])
            treffer = [p for p in _buffer_fetch_posts_basic(tr[0], org, first=50, all_pages=True)
                       if str(p.get('buffer_post_id')) == str(buffer_id)]
            if not treffer:
                print('  Buffer does not list this post (any more).')
            else:
                p = treffer[0]
                print('  status    : %s' % p.get('status'))
                print('  sent at   : %s' % p.get('sent_at'))
                print('  thumbnail : %s' % (p.get('thumbnail_url') or '(none)'))
                if not p.get('thumbnail_url'):
                    print('  -> No thumbnail. Buffer has no usable video for this post -')
                    print('     it could not make anything of what we handed it.')
    except Exception as fehler:
        print('  asking Buffer failed: %s' % fehler)
