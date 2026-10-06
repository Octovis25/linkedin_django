"""Send times: stored in UTC, shown in German time.

post_scheduled_at holds what we told Buffer, in UTC (compared with
UTC_TIMESTAMP()). Buffer's own due_at is UTC too ("...Z"). Both used to be
shown as they were - two hours early in summer (Ortrud, 06.10.2026).
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo('Europe/Berlin')


def berlin(wert):
    """A UTC moment as German time, or None.

    Takes a naive datetime (meant as UTC), an aware one, or an ISO string such
    as 2026-09-21T08:00:00.000Z."""
    if not wert:
        return None
    if isinstance(wert, str):
        try:
            wert = datetime.strptime(wert.strip()[:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return None
    if not isinstance(wert, datetime):
        return None
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert.astimezone(BERLIN)


def berlin_fmt(wert):
    """'14.10.2026 09:30' in German time, or ''."""
    zeit = berlin(wert)
    return zeit.strftime('%d.%m.%Y %H:%M') if zeit else ''
