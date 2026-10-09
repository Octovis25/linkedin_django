"""Check: does WordPress hand out the revisions of a page (REST, read only)?

    python manage.py wp_check            # homepage 1260
    python manage.py wp_check --post 2263
"""
from django.core.management.base import BaseCommand, CommandError

from website_changes import inhalt, wp


class Command(BaseCommand):
    help = 'Lists the latest revisions of a WordPress page through the REST API.'

    def add_arguments(self, parser):
        parser.add_argument('--post', type=int, default=1260)
        parser.add_argument('--limit', type=int, default=10)

    def handle(self, *args, **opts):
        try:
            seite = wp.page(opts['post'])
            if not seite:
                raise CommandError(f"No page or post with ID {opts['post']}.")
            revs = wp.revisions(seite['kind'], opts['post'], opts['limit'])
        except wp.WordPressError as fehler:
            raise CommandError(str(fehler))
        self.stdout.write(f"#{seite['id']} {seite['title']} ({seite['type']}, {seite['status']})")
        self.stdout.write(f"{len(revs)} latest revisions (autosaves left out):")
        for r in revs:
            f = inhalt.summary(r['content'])
            c = f['counts']
            self.stdout.write(f"  rev {r['id']:>6}  {r['modified_gmt'][:16]}  {wp.author_name(r['author_id']):<18} "
                              f"{c['heading']} h · {c['text']} t · {c['button']} b · {c['image']} img  "
                              f"{' | '.join(f['headings'][:3])}")
