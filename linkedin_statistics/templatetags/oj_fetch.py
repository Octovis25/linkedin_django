"""A short note at the top of the page when the hourly Buffer fetch has
stopped or failed - for a superuser, at most once a day per browser
session (07.11.2026: "zeig sie mindestens täglich"). After a login the
session is new, so the note comes on the first page after logging in, and
again on the first page of every following day while the problem lasts."""
from django import template
from django.utils.html import format_html

register = template.Library()

SESSION_KEY = 'oj_fetch_note_day'


def due_note(request):
    """The note if one is due for this request, else ''. Marks the day."""
    user = getattr(request, 'user', None)
    session = getattr(request, 'session', None)
    if session is None or not getattr(user, 'is_superuser', False):
        return ''
    try:
        from .. import buffer_metrics as bm
        today = bm.today_berlin().isoformat()
        if session.get(SESSION_KEY) == today:
            return ''
        session[SESSION_KEY] = today
        return bm.fetch_problem()
    except Exception:
        return ''              # a page never fails because of this note


@register.simple_tag(takes_context=True)
def oj_fetch_note(context):
    text = due_note(context.get('request'))
    if not text:
        return ''
    return format_html('<div class="messages"><div class="alert alert-warning">{}</div></div>', text)
