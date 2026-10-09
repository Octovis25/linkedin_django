"""Website changes of octotrial.com. For now: the check whether WordPress
hands out what we need (revisions with author and Elementor content)."""
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render

from . import inhalt, wp


@user_passes_test(lambda u: u.is_active and u.is_superuser)
def check(request):
    try:
        post_id = int(request.GET.get('post') or 1260)
    except ValueError:
        post_id = 1260
    daten = {'post_id': post_id}
    try:
        seite = wp.page(post_id)
        daten['page'] = seite
        if seite:
            revs = wp.revisions(seite['kind'], post_id, 10)
            for r in revs:
                r['author'] = wp.author_name(r['author_id'])
                r['found'] = inhalt.summary(r['content'])
            daten['revisions'] = revs
    except wp.WordPressError as fehler:
        daten['error'] = str(fehler)
    return render(request, 'website_changes/check.html', daten)
