"""Who may open the audit trail: only the owner.

Two conditions, both needed: superuser, and the user name in
AUDIT_TRAIL_VIEWERS (environment variable, comma-separated, default
"ortrud"). Being a superuser alone is not enough - a second superuser added
later would otherwise see everything automatically.
"""
import os


def viewers():
    raw = os.getenv('AUDIT_TRAIL_VIEWERS', 'ortrud')
    return {name.strip().lower() for name in raw.split(',') if name.strip()}


def may_view(user):
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser
                and user.get_username().lower() in viewers())


def audit_link(request):
    """Context processor: shows the menu entry only to the owner."""
    return {'audit_visible': may_view(getattr(request, 'user', None))}
