"""Matomo visits shaped like octotrial.com's real log (checked 05.10.2026).

Invented visitors, real patterns: the location rule with a district in
brackets, WordPress and Elementor previews, Headless Chrome opening two pages
in three seconds, single 0-second hits from data-centre towns, an article under
its old and its new address, an article WordPress no longer has, a category
page that answers "not found", and a visit through a LinkedIn tracking link.

Times are UTC epoch seconds, as Matomo delivers them; the site's own day is UTC.
"""
import datetime as dt

UTC = dt.timezone.utc
SITE = "https://octotrial.com"

POSTS = [
    {"link": SITE + "/insights/clinical-data-management-lifecycle/", "titel": "Clinical data management lifecycle", "slug": "clinical-data-management-lifecycle", "datum": "2026-09-27"},
    {"link": SITE + "/insights/lessons-learned/", "titel": "Lessons learned in clinical trials", "slug": "lessons-learned", "datum": "2026-09-09"},
    {"link": SITE + "/insights/sop-quality-in-clinical-trials/", "titel": "SOP quality in clinical trials", "slug": "sop-quality-in-clinical-trials", "datum": "2026-09-30"},
]
PAGES = [{"link": SITE + p, "titel": t, "slug": ""} for p, t in [
    ("/", "Home"), ("/services/", "Services"), ("/lean-oversight/", "Trial Oversight with OctOver"),
    ("/octosop/", "OctoSOP"), ("/about-us/", "About us"), ("/contact-page/", "Contact"),
    ("/insights/", "Insights"), ("/clinical-trial-conduct/", "Clinical trial conduct"),
    ("/legal-notice/", "Legal notice"), ("/privacy-policy/", "Privacy policy")]]


def ts(text):
    """'2026-09-10 08:00' (UTC) -> epoch seconds."""
    return int(dt.datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp())


def visit(vid, start, pages, city="Munich", country="Germany", browser="Chrome",
          rtype="direct", rname="", rurl="", rkey="", returning=False, extra=(), idv=None):
    """pages: [(path or url, title, seconds until the next action)]."""
    t0 = ts(start)
    t = t0
    acts = []
    for i, (p, title, sec) in enumerate(pages):
        url = p if p.startswith(("http", "mailto:", "tel:")) else SITE + p
        acts.append({"type": "action", "url": url, "pageTitle": title + " - Octotrial",
                     "timeSpent": sec if i < len(pages) - 1 else 0, "timestamp": t})
        t += sec
    for typ, url, after in extra:
        acts.append({"type": typ, "url": url, "pageTitle": "", "timestamp": t0 + after})
    acts.sort(key=lambda a: a["timestamp"])
    dauer = (acts[-1]["timestamp"] - t0) if len([a for a in acts if a["type"] == "action"]) > 1 else 0
    return {
        "idVisit": idv or abs(hash((vid, start))) % 10**6, "visitorId": vid,
        "firstActionTimestamp": t0, "serverTimestamp": t, "serverDate": start[:10],
        "serverTimePretty": start[11:] + ":00", "visitDuration": dauer,
        "actions": len(acts), "visitorType": "returning" if returning else "new",
        "visitCount": 2 if returning else 1,
        "referrerType": rtype, "referrerName": rname, "referrerUrl": rurl, "referrerKeyword": rkey,
        "city": city, "country": country, "browserName": browser,
        "operatingSystemName": "Windows", "languageCode": "de-de", "deviceType": "Desktop",
        "actionDetails": acts, "events": 0, "goalConversions": 0,
    }


def log():
    return [
        # Google -> article -> services -> contact page (a reader who goes on)
        visit("a1", "2026-09-10 08:00", [("/insights/lessons-learned/", "Lessons learned", 95),
                                          ("/services/", "Services", 40), ("/contact-page/", "Contact", 0)],
              rtype="search", rname="Google", rurl="https://www.google.com/"),
        # the same article under its old address; then the visit ends there
        visit("a2", "2026-09-12 14:30", [("/about-us/", "About us", 20), ("/lessons-learned/", "Lessons learned", 0)],
              city="Hamburg"),
        # LinkedIn tracking link: Matomo core keeps utm_content in the URL and
        # stores utm_campaign / utm_term as campaign name and keyword
        visit("l1", "2026-09-15 06:30", [("/insights/clinical-data-management-lifecycle/?utm_content=post-152", "Clinical data management lifecycle", 120),
                                          ("/lean-oversight/", "Trial Oversight with OctOver", 0)],
              rtype="campaign", rname="linkedin_posts", rkey="company_page", city="Berlin",
              extra=[("outlink", "mailto:contact@octotrial.com", 150)]),
        # an article WordPress no longer has, read for a while, then a 404 category
        visit("a3", "2026-09-16 09:00", [("/why-ai-in-clinical-trials-still-needs-human-judgment/", "Why AI in Clinical Trials Still Needs Human Judgment", 60),
                                          ("/category/general/", "Page not found", 0)], city="Vienna", country="Austria"),
        # blog overview and a series page
        visit("a4", "2026-09-17 10:00", [("/insights/", "Insights", 15), ("/series/ai-in-clinical-trials-practical-support-not-magic/", "AI in Clinical Trials", 10),
                                          ("/insights/clinical-data-management-lifecycle/", "Clinical data management lifecycle", 0)],
              rtype="ai", rname="ChatGPT", rurl="https://chatgpt.com/"),
        # one page, 0 seconds, no referrer: could be anyone
        visit("u1", "2026-09-18 03:12", [("/", "Clinical trial oversight", 0)], city="Boardman", country="United States"),
        visit("u2", "2026-09-18 03:40", [("/", "Clinical trial oversight", 0)], city="Council Bluffs", country="United States"),
        # Headless Chrome: two pages, three seconds
        visit("h1", "2026-09-19 22:01", [("/", "Clinical trial oversight", 3), ("/about-us/", "About us", 0)],
              city="Ashburn", country="United States", browser="Headless Chrome"),
        # five pages, each left after a second
        visit("f1", "2026-09-20 01:00", [("/", "Home", 1), ("/services/", "Services", 1), ("/about-us/", "About us", 1),
                                          ("/octosop/", "OctoSOP", 1), ("/contact-page/", "Contact", 0)],
              city="Frankfurt am Main"),
        # own town, written with the district
        visit("o1", "2026-09-21 07:00", [("/", "Clinical trial oversight", 30), ("/services/", "Services", 0)],
              city="Wasserburg am Inn (Gabersee)", returning=True),
        visit("o2", "2026-09-22 07:00", [("/", "Clinical trial oversight", 30), ("/services/", "Services", 0)],
              city="Herzogenaurach", returning=True),
        # an editing session: preview, then the live page
        visit("e1", "2026-09-23 12:00", [("/?p=2200&preview=true", "Draft", 40), ("/insights/clinical-data-management-lifecycle/", "Clinical data management lifecycle", 0)],
              city="Nuremberg"),
        visit("e2", "2026-09-24 12:00", [("/about-us/?elementor-preview=17&ver=1", "About us", 0)], city="Nuremberg"),
        # around midnight: 22:30 UTC on 30.09. is already 01.10. in Berlin
        visit("m1", "2026-09-30 22:30", [("/", "Home", 30), ("/services/", "Services", 0)], city="Leipzig"),
        # referrer spam
        visit("s1", "2026-09-25 05:00", [("/", "Home", 0)], rtype="website", rname="www.webdig.asia",
              rurl="https://www.webdig.asia/", city="Singapore", country="Singapore"),
    ]
