"""Which operations does Buffer's GraphQL API show to our key? (07.11.2026)

Looking for a way to make Buffer fetch a post's numbers again (refresh,
sync, metrics, insights). Read only: an introspection query, nothing is
changed and no refresh is started. The key is never printed.

    python manage.py buffer_schema           # names that look relevant
    python manage.py buffer_schema --all     # every query and mutation
"""
import re

from django.core.management.base import BaseCommand, CommandError

from linkedin_statistics import buffer_metrics as bm

QUERY = """query Ops {
  __schema {
    queryType { fields { name description } }
    mutationType { fields { name description } }
  }
}"""
LOOK_FOR = re.compile(r'refresh|sync|metric|insight|analytic|stat|fetch|update', re.I)


class Command(BaseCommand):
    help = "Lists Buffer GraphQL queries and mutations (introspection, read only)."

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='list every operation, not only the relevant ones')

    def handle(self, *args, **opts):
        from planner.views import _buffer_graphql
        token = bm.superuser_buffer()['token']
        if not token:
            raise CommandError('No Buffer key saved under API Connect.')
        try:
            data = _buffer_graphql(token, QUERY)['data']['__schema']
        except Exception as e:
            raise CommandError(f'Buffer did not answer the introspection: {str(e)[:300]}')
        for kind in ('mutationType', 'queryType'):
            fields = (data.get(kind) or {}).get('fields') or []
            shown = [f for f in fields if opts['all'] or LOOK_FOR.search(f['name'] + ' ' + (f.get('description') or ''))]
            self.stdout.write(f"\n{'Mutations' if kind == 'mutationType' else 'Queries'}: {len(fields)} in all, {len(shown)} shown")
            for f in shown:
                desc = re.sub(r'\s+', ' ', f.get('description') or '').strip()
                self.stdout.write(f"  {f['name']}" + (f" – {desc[:120]}" if desc else ''))
