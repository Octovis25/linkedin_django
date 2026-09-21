"""Does a Studio video keep its teal on LinkedIn?

Measured on post #53 (21.09.2026): the recording stores its colours by the
BT.601 rule and does not say so. Players assume BT.709 for a video that size
and show the teal darker - green 133 becomes 119. The LinkedIn copy is now
converted and labelled (planner/views.py, _als_linkedin_mp4).

The two decisions - reading what a video says about itself, and the ffmpeg
call - are cut out of views.py and checked on their own. If ffmpeg is
available (pip install imageio-ffmpeg), a real clip is also made the way the
browser makes it, converted, and its teal measured the way a browser reads it.

    python _tests/video_farbe_test.py
"""
import os
import re
import subprocess
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
with open(os.path.join(WURZEL, 'planner', 'views.py'), encoding='utf-8') as fh:
    SRC = fh.read()
with open(os.path.join(WURZEL, 'requirements.txt'), encoding='utf-8') as fh:
    ANFORDERUNGEN = fh.read()


def herausschneiden(name):
    marke = '\ndef %s(' % name
    if marke not in SRC:
        raise SystemExit('not found in planner/views.py: ' + name)
    zeilen = SRC[SRC.index(marke) + 1:].split('\n')
    raus = [zeilen[0]]
    for zeile in zeilen[1:]:
        if zeile and not zeile[0].isspace():
            break
        raus.append(zeile)
    return '\n'.join(raus)


RAUM = {'__builtins__': __builtins__}
kurz = re.search(r'\nLINKEDIN_KURZE_SEITE = (\d+)', SRC)
RAUM['LINKEDIN_KURZE_SEITE'] = int(kurz.group(1)) if kurz else None
for name in ('_video_farbnorm', '_linkedin_mp4_befehl'):
    exec(compile(herausschneiden(name), 'planner/views.py (cut out)', 'exec'), RAUM)
farbnorm = RAUM['_video_farbnorm']
befehl = RAUM['_linkedin_mp4_befehl']

gut = schlecht = uebersprungen = 0


def pruefe(name, ok, extra=''):
    global gut, schlecht
    if ok:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FAIL ' + name + ('  -> ' + str(extra) if extra != '' else ''))


print('\n=== Reading what a video says about its colours ===')
# Real `ffmpeg -i` lines. The first is the #53 recording itself.
BROWSER = '  Stream #0:0(eng): Video: vp9 (Profile 0), yuv420p(tv), 2700x2700, SAR 1:1 DAR 1:1, 120 tbr'
HANDY = '  Stream #0:0: Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), 1920x1080'
ALT = '  Stream #0:0: Video: h264, yuvj420p(pc, bt470bg/bt470bg/smpte170m), 1280x720'
pruefe('the Studio recording names no rule', farbnorm(BROWSER) == (None, 'tv'), farbnorm(BROWSER))
pruefe('a phone video that names BT.709 is read by it', farbnorm(HANDY) == ('bt709', 'tv'),
       farbnorm(HANDY))
pruefe('an older full-range BT.601 file too', farbnorm(ALT) == ('bt601', 'pc'), farbnorm(ALT))
pruefe('no video line at all does not crash', farbnorm('') == (None, 'tv'))
pruefe('an RGB stream is not mistaken for anything',
       farbnorm('  Stream #0:0: Video: png, rgb24(pc), 800x800') == (None, 'tv'))

print('\n=== The ffmpeg call ===')
unser = befehl('ffmpeg', 'ein.webm', 'aus.mp4', None, 'tv')
text = ' '.join(unser)
pruefe('an untagged video is read as BT.601 - what our recorder writes',
       'in_color_matrix=bt601' in text, text)
pruefe('a tagged one is read by its own rule',
       'in_color_matrix=bt709' in ' '.join(befehl('ffmpeg', 'a', 'b', 'bt709', 'tv')))
pruefe('the colours are written as BT.709', 'out_color_matrix=bt709' in text)
for marke in ('-colorspace', '-color_primaries', '-color_trc'):
    stelle = unser.index(marke) if marke in unser else -1
    pruefe('and labelled so (%s bt709)' % marke,
           stelle >= 0 and unser[stelle + 1] == 'bt709', unser[stelle + 1] if stelle >= 0 else '')
pruefe('the shorter side is capped at LinkedIn\'s 1080',
       RAUM['LINKEDIN_KURZE_SEITE'] == 1080 and 'min(iw,1080)' in text and 'min(ih,1080)' in text)
pruefe('at most 60 frames a second', '-fpsmax' in unser and unser[unser.index('-fpsmax') + 1] == '60')
pruefe('written to the target, H.264', unser[-1] == 'aus.mp4' and 'libx264' in unser)

print('\n=== Wired in, and never the reason a post fails ===')
HOCHLADEN = herausschneiden('_upload_video_to_cloudinary')
pruefe('the upload makes the LinkedIn copy', '_als_linkedin_mp4(local_path)' in HOCHLADEN)
pruefe('before it uploads anything',
       HOCHLADEN.index('_als_linkedin_mp4(') < HOCHLADEN.index('_req.post('))
pruefe('a GIF keeps its own path', "if not local_path.lower().endswith('.gif'):" in HOCHLADEN)
pruefe('and without a copy the original goes, as before',
       'if kopie:' in HOCHLADEN)
KOPIE = herausschneiden('_als_linkedin_mp4')
pruefe('no ffmpeg means no copy, not an error', 'return None' in KOPIE
       and 'import imageio_ffmpeg' in KOPIE)
pruefe('Render gets ffmpeg through requirements.txt', 'imageio-ffmpeg' in ANFORDERUNGEN)

print('\n=== On a real clip ===')
try:
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FF = None
if not FF:
    uebersprungen += 1
    print('  skip ffmpeg is not installed here (pip install imageio-ffmpeg to run this part)')
else:
    def pixel(datei, matrix):
        roh = subprocess.run(
            [FF, '-v', 'error', '-i', datei, '-frames:v', '1', '-vf',
             'crop=2:2:40:40,scale=in_color_matrix=%s:in_range=tv:out_range=pc,format=rgb24'
             % matrix, '-f', 'rawvideo', '-'], capture_output=True).stdout
        return tuple(roh[:3])

    with tempfile.TemporaryDirectory() as ordner:
        quelle = os.path.join(ordner, 'studio.webm')
        ziel = os.path.join(ordner, 'linkedin.mp4')
        # The teal as the browser records it: 2700 square, BT.601, NO label.
        # Without setparams ffmpeg writes "bt470bg" into the file, and the test
        # would check an easier case than the real one - it did, the first
        # time, and passed while the untagged case was broken.
        subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=0x008591:s=2700x2700:d=1:r=30',
                        '-vf', 'scale=out_color_matrix=bt601:out_range=tv,'
                               'setparams=colorspace=unknown:color_primaries=unknown:'
                               'color_trc=unknown',
                        '-c:v', 'libvpx-vp9', '-b:v', '2M', '-pix_fmt', 'yuv420p', quelle],
                       check=True)
        meldung = subprocess.run([FF, '-hide_banner', '-i', quelle],
                                 capture_output=True, text=True).stderr
        pruefe('the test clip is as unlabelled as the #53 recording',
               farbnorm(meldung) == (None, 'tv'), farbnorm(meldung))
        vorher = pixel(quelle, 'bt709')
        pruefe('the problem is reproduced: read as a browser reads it, it is darker',
               vorher[1] < 125, vorher)

        m, b = farbnorm(meldung)
        subprocess.run(befehl(FF, quelle, ziel, m, b), check=True)
        nachher = pixel(ziel, 'bt709')
        soll = (0, 133, 145)
        pruefe('after the conversion the teal is back (within 5 of #008591)',
               all(abs(a - z) <= 5 for a, z in zip(nachher, soll)), nachher)
        info = subprocess.run([FF, '-hide_banner', '-i', ziel],
                              capture_output=True, text=True).stderr
        pruefe('the copy is 1080 x 1080', '1080x1080' in info)
        pruefe('and says BT.709 about itself', farbnorm(info)[0] == 'bt709', farbnorm(info))

print('\n%d ok, %d failed%s' % (gut, schlecht,
      ', %d skipped' % uebersprungen if uebersprungen else ''))
sys.exit(1 if schlecht else 0)
