"""Tracking links for LinkedIn posts (October 2026).

Every link from a LinkedIn post to octotrial.com gets the same parameters, so
Web Analytics can tell which post brought a visit:

    utm_source=linkedin
    utm_medium=organic_social
    utm_campaign=<stable campaign id>       default "linkedin_posts"
    utm_content=post-<planner id>           the post, stable for its lifetime
    utm_term=company_page | personal_profile   which LinkedIn channel posted it

Values a link already carries are kept; nothing is added twice. Links to other
sites are left alone.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SOURCE = "linkedin"
MEDIUM = "organic_social"
CAMPAIGN = "linkedin_posts"
CHANNELS = {False: "company_page", True: "personal_profile"}
HOSTS = ("octotrial.com", "www.octotrial.com")

# A URL inside text or HTML: up to white space, a quote or an angle bracket.
URL = re.compile(r"""https?://[^\s"'<>]+""", re.I)


def is_site_link(url):
    try:
        return (urlsplit(url).hostname or "").lower() in HOSTS
    except ValueError:
        return False


def content_for(post_id):
    return f"post-{int(post_id)}"


def tag(url, post_id, personal=False, campaign=CAMPAIGN):
    """The link with the convention's parameters; existing UTM values win."""
    if not is_site_link(url):
        return url
    # A full stop or bracket at the end belongs to the sentence, not the link.
    tail = ""
    while url and url[-1] in ".,;:!?)]":
        tail = url[-1] + tail
        url = url[:-1]
    teile = urlsplit(url)
    paare = parse_qsl(teile.query, keep_blank_values=True)
    vorhanden = {k.lower() for k, _ in paare}
    wanted = [("utm_source", SOURCE), ("utm_medium", MEDIUM), ("utm_campaign", campaign),
              ("utm_content", content_for(post_id)), ("utm_term", CHANNELS[bool(personal)])]
    paare += [(k, v) for k, v in wanted if k not in vorhanden]
    # HTML text carries "&amp;" between parameters; keep the form it came in.
    query = urlencode(paare, safe="-_.~")
    return urlunsplit((teile.scheme, teile.netloc, teile.path or "/", query, teile.fragment)) + tail


def tag_text(text, post_id, personal=False, campaign=CAMPAIGN):
    """Tag every octotrial.com link in a post text (plain or HTML).

    Returns (new text, [(old link, new link)]) - only the links that changed.
    """
    changes = []

    def replace(m):
        old = m.group(0)
        raw = old.replace("&amp;", "&")
        new = tag(raw, post_id, personal, campaign)
        if new == raw:
            return old
        if "&amp;" in old:
            new = new.replace("&", "&amp;")
        if (old, new) not in changes:      # href and link text: one link, not two
            changes.append((old, new))
        return new

    return URL.sub(replace, text or ""), changes
