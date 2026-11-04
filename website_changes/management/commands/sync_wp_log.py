"""Copies new revisions and uploads of octotrial.com into the website log.

    python manage.py sync_wp_log               # as long as it takes
    python manage.py sync_wp_log --budget 240  # stop after 240 s, the rest next time

Read only: only GET requests to WordPress. On 401/403 it stops at once.
"""
from django.core.management.base import BaseCommand, CommandError

from website_changes import log


class Command(BaseCommand):
    help = 'Copies new WordPress revisions and media uploads into the website log.'

    def add_arguments(self, parser):
        parser.add_argument('--budget', type=int, default=3600, help='seconds before it stops (default 3600)')

    def handle(self, *args, **opts):
        res = log.sync(budget_seconds=opts['budget'])
        if not res['ok']:
            raise CommandError(res['message'])
        self.stdout.write(res['message'])
