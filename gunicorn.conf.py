# Gunicorn reads this file on its own when it starts in the project folder -
# the start command on Render ("gunicorn dashboard.wsgi:application") needs no
# change for it.
#
# Why: gunicorn kills a worker whose request takes longer than 30 seconds by
# default. Sending a video to LinkedIn does all of this in ONE request: fetch
# it from Nextcloud, convert it with ffmpeg (colour rule + LinkedIn size), upload
# it to Cloudinary, check the MP4 is there, hand it to Buffer. A 15-second
# 1080 x 1080 video takes longer than 30 s on Render's CPU. The worker was
# killed mid-way, Render answered with an HTML error page, and the planner
# showed "Unexpected token '<', "<!DOCTYPE" ... is not valid JSON".
timeout = 300          # seconds a request may take before the worker is killed
graceful_timeout = 30
