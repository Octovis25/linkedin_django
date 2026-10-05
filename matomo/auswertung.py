"""One evaluation for every Web Analytics view (October 2026).

Before this module, some views counted the filtered visit log and others
Matomo's finished reports - with excluded places, previews and automation in
some numbers and not in others. Now every view built from the visit log goes
through `evaluate()`: one period, one set of exclusions, one classification.

What this module does NOT do: guess. A missing referrer stays "unknown", a
missing time measurement stays "not measured", and a visit is never linked to
a LinkedIn post because it happened shortly after one.

Pure functions, no database and no network - the views hand in the raw visits
and the lists (excluded places, own visitor IDs, WordPress posts).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

TIMEZONE = "Europe/Berlin"
TZ = ZoneInfo(TIMEZONE)

SITE_HOSTS = ("octotrial.com", "www.octotrial.com")

# Pages that present an offer, and the contact page (paths as on octotrial.com,
# checked 05.10.2026 against WordPress). Settings MATOMO_OFFER_PAGES /
# MATOMO_CONTACT_PAGES replace them.
OFFER_PAGES = ("/services/", "/lean-oversight/", "/octosop/", "/clinical-trial-conduct/")
CONTACT_PAGES = ("/contact-page/",)

# ── Sources ──────────────────────────────────────────────────────────────

SEARCH = "Search engine"
LINKEDIN = "LinkedIn"
WEBSITE = "Other website"
AI = "AI assistant"
UNKNOWN = "Unknown source / direct access"
SOURCES = (LINKEDIN, SEARCH, AI, WEBSITE, UNKNOWN)

UNKNOWN_EXPLAINED = (
    "No referrer was passed on. The visit may come from a typed or saved address, "
    "a bookmark, an app (the LinkedIn app sends none) or a link that withholds the "
    "referrer. It is not assigned to LinkedIn by timing.")

LINKEDIN_HOSTS = ("linkedin.com", "lnkd.in", "linkedin.android", "com.linkedin.android")

# The UTM convention for links in LinkedIn posts (see planner/utm.py).
UTM_SOURCE = "linkedin"
UTM_MEDIUM = "organic_social"
POST_CONTENT = re.compile(r"^(?:post[-_]?)?(\d{1,7})$", re.I)

# ── Classification ───────────────────────────────────────────────────────

HUMAN = "human"
AUTOMATION = "automation"
UNCLEAR = "unclear"
OWN = "own"
CLASSES = {
    HUMAN: "Probably human",
    AUTOMATION: "Probably automated",
    UNCLEAR: "Unclear",
    OWN: "Confirmed own / test visit",
}

READING_GAP = 3        # seconds between two pageviews that look like reading
FAST_GAP = 1           # every gap at most this long: faster than anyone reads

RULES = [
    ("Own device", "The visitor ID is on the list of own / test devices "
                   "(marked by hand in the visit details).", OWN),
    ("Headless browser", "Matomo reports a headless browser (e.g. “Headless Chrome”) - "
                         "a browser without a screen, used by scripts.", AUTOMATION),
    ("Too fast for reading", f"Two or more pages, every page left after at most "
                             f"{FAST_GAP} s.", AUTOMATION),
    ("Reading time", f"Two or more pages with at least {READING_GAP} s between two of them.",
     HUMAN),
    ("Interaction", "A click on an outgoing link, an email or phone link, a download, "
                    "an event or a goal.", HUMAN),
    ("Otherwise", "No automation signal and no human signal - for example one page "
                  "without measurable time. 0 seconds alone is not proof of a bot, "
                  "several pages alone are not proof of a person.", UNCLEAR),
]

# ── Previews and other editing views ─────────────────────────────────────

PREVIEW_PARAMS = ("preview", "preview_id", "preview_nonce", "elementor-preview",
                  "elementor_library", "render_mode")

PAGE_NOT_FOUND = re.compile(r"page not found|seite nicht gefunden|\b404\b", re.I)


# ── Small helpers ────────────────────────────────────────────────────────

def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _first(raw, *names):
    for n in names:
        v = raw.get(n)
        if v not in (None, "", "Unknown", "unknown", "-"):
            return v
    return None


def path_of(url):
    """'/services/' from 'https://octotrial.com/services?x=1#top'."""
    if not url:
        return ""
    p = urlsplit(str(url)).path or "/"
    last = p.rsplit("/", 1)[-1]
    if not p.endswith("/") and "." not in last:
        p += "/"
    return p


def query_of(url):
    try:
        return dict(parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=True))
    except ValueError:
        return {}


def is_preview(url):
    """WordPress or Elementor preview: needs a login, so never an audience view."""
    q = query_of(url)
    return any(k in q for k in PREVIEW_PARAMS)


def clean_title(title):
    """'Lessons learned - Octotrial' -> 'Lessons learned'."""
    t = " ".join(str(title or "").split())
    t = re.sub(r"\s+[|\-–—]\s+Octotrial\b.*$", "", t)
    return t


def host_of(url):
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def to_local(timestamp):
    """UTC epoch seconds -> aware datetime in Europe/Berlin, or None."""
    ts = _int(timestamp, None)
    if not ts:
        return None
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).astimezone(TZ)


def duration_text(sec):
    if sec is None:
        return "not measured"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d} min" if sec >= 60 else f"{sec} s"


# ── Places ───────────────────────────────────────────────────────────────

def place_key(city):
    """Comparison form of a city: case, spaces and a district in brackets ignored.

    Matomo writes some places with a district: 'Wasserburg am Inn (Gabersee)'.
    The rule 'Wasserburg am Inn' covers it; the district is kept in the data.
    """
    s = " ".join(str(city or "").split()).casefold()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    return s


def place_rule_for(city, rules):
    """The rule (as written in the list) that covers this city, or None."""
    key = place_key(city)
    if not key:
        return None
    for r in rules:
        if place_key(r) == key:
            return r
    return None


# ── Pages: article, page, overview … ─────────────────────────────────────

PAGE = "page"
ARTICLE = "article"
OVERVIEW = "overview"
NOT_FOUND = "not found"
OTHER = "other"

OVERVIEW_PREFIXES = ("/category/", "/tag/", "/series/", "/author/", "/page/",
                     "/insights/category/", "/insights/tag/", "/insights/series/",
                     "/insights/page/", "/insights/author/")


def _slug(path):
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else ""


@dataclass
class Catalogue:
    """What kind of page an address is - from WordPress, not from guessing.

    posts:  [{'link', 'titel', 'slug'}]  published WordPress posts
    pages:  [{'link', 'titel'}]          published WordPress pages
    manual: paths entered in the portal as "counts as article"
    """
    posts: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    manual: list = field(default_factory=list)
    wordpress_ok: bool = True

    def __post_init__(self):
        self.page_paths = {path_of(p.get("link")) for p in self.pages if p.get("link")}
        self.articles = {}          # key -> {'titel', 'link', 'addresses': set()}
        self.by_slug = {}
        for p in self.posts:
            path = path_of(p.get("link"))
            slug = p.get("slug") or _slug(path)
            if not path or not slug:
                continue
            self.articles[slug] = {"titel": p.get("titel") or "", "link": path,
                                   "addresses": set(), "published": True}
            self.by_slug[slug] = slug
        self.manual_paths = {path_of(m) for m in self.manual if m}
        for m in self.manual_paths:
            slug = _slug(m)
            if slug and slug not in self.articles:
                self.articles[slug] = {"titel": "", "link": m, "addresses": set(),
                                       "published": False}
                self.by_slug[slug] = slug

    def classify(self, path, title=""):
        """(kind, article key or '', reason)."""
        if not path:
            return OTHER, "", "no address"
        if path == "/":
            return PAGE, "", "home page"
        if PAGE_NOT_FOUND.search(title or ""):
            return NOT_FOUND, "", "the page answered “not found”"
        if path == "/insights/":
            return OVERVIEW, "", "blog overview"
        if path.startswith(OVERVIEW_PREFIXES):
            return OVERVIEW, "", "category, series, tag or author overview"
        if path in self.page_paths:
            return PAGE, "", "WordPress page"
        slug = _slug(path)
        key = self.by_slug.get(slug)
        if key is None:
            # WordPress adds "-2" when a slug is taken; the same article, saved twice.
            base = re.sub(r"-\d+$", "", slug)
            if base != slug:
                key = self.by_slug.get(base)
        if key is not None:
            art = self.articles[key]
            if path in self.manual_paths and not art["published"]:
                return ARTICLE, key, "entered as article in the portal"
            if path == art["link"]:
                return ARTICLE, key, "WordPress post"
            return ARTICLE, key, f"earlier address of the WordPress post {art['link']}"
        return OTHER, "", ("not a published WordPress post or page"
                           if self.wordpress_ok else "WordPress list not available")

    def article_title(self, key, fallback=""):
        a = self.articles.get(key) or {}
        return a.get("titel") or fallback or key


# ── One visit ────────────────────────────────────────────────────────────

@dataclass
class Settings:
    places: list = field(default_factory=list)       # location rule (cities)
    own_ids: set = field(default_factory=set)        # visitor IDs marked as own
    offer_pages: tuple = OFFER_PAGES
    contact_pages: tuple = CONTACT_PAGES
    linkedin_campaigns: tuple = ()                   # campaign names used for LinkedIn links


def _source(raw, entry_query, settings):
    """(source group, evidence text, utm dict, campaign, post id)."""
    rtype = str(raw.get("referrerType") or "").lower()
    rname = str(raw.get("referrerName") or "")
    rkey = str(raw.get("referrerKeyword") or "")
    rurl = str(raw.get("referrerUrl") or "")
    rhost = host_of(rurl)

    utm = {k[4:]: v for k, v in entry_query.items() if k.startswith(("utm_", "mtm_")) and v}
    # Matomo's campaign plugin delivers the parts as visit fields
    for k, name in (("source", "campaignSource"), ("medium", "campaignMedium"),
                    ("campaign", "campaignName"), ("content", "campaignContent"),
                    ("term", "campaignKeyword")):
        if raw.get(name) and k not in utm:
            utm[k] = str(raw[name])
    if rtype == "campaign":
        utm.setdefault("campaign", rname)
        if rkey:
            utm.setdefault("term", rkey)

    campaign = utm.get("campaign", "")
    post_id = None
    m = POST_CONTENT.match(str(utm.get("content") or "").strip())
    if m:
        post_id = int(m.group(1))

    def evidence_utm():
        parts = [f"utm_{k}={utm[k]}" for k in ("source", "medium", "campaign", "content", "term")
                 if utm.get(k)]
        return "UTM: " + ", ".join(parts)

    linkedin_campaign = campaign and (
        campaign.lower() in {c.lower() for c in settings.linkedin_campaigns}
        or "linkedin" in campaign.lower())
    if utm and (str(utm.get("source", "")).lower() == UTM_SOURCE or linkedin_campaign
                or (post_id is not None and not utm.get("source"))):
        return LINKEDIN, evidence_utm(), utm, campaign, post_id
    if rhost.endswith(LINKEDIN_HOSTS) or "linkedin" in rname.lower():
        return LINKEDIN, f"Referrer: {rhost or rname}", utm, campaign, post_id
    if utm:
        return WEBSITE if utm.get("source") else UNKNOWN, evidence_utm(), utm, campaign, post_id
    if rtype == "search":
        return SEARCH, f"Referrer: {rname or rhost}" + (f" ({rhost})" if rhost and rname else ""), \
            utm, campaign, post_id
    if rtype == "ai":
        return AI, f"Referrer: {rname or rhost}", utm, campaign, post_id
    if rtype in ("website", "social"):
        return WEBSITE, f"Referrer: {rhost or rname}", utm, campaign, post_id
    if rhost and rhost in SITE_HOSTS:
        return UNKNOWN, ("Referrer is octotrial.com itself: a new visit that started from an "
                         "open page (e.g. after 30 minutes); where the person first came from "
                         "is not known."), utm, campaign, post_id
    return UNKNOWN, "No referrer", utm, campaign, post_id


def prepare(raw, catalogue, settings):
    """One raw Matomo visit -> the dict every view works with."""
    actions = [a for a in (raw.get("actionDetails") or []) if isinstance(a, dict)]
    first_ts = _int(raw.get("firstActionTimestamp") or raw.get("serverTimestamp"), None)
    local = to_local(first_ts)
    if local is None and raw.get("serverDate"):
        # Without a timestamp: Matomo's site date. Marked, not converted.
        try:
            local = dt.datetime.fromisoformat(str(raw["serverDate"])[:10]).replace(tzinfo=TZ)
        except ValueError:
            local = None

    pageviews, steps = [], []
    for a in actions:
        typ = str(a.get("type") or "action").lower()
        url = str(a.get("url") or "")
        ts = _int(a.get("timestamp"), None)
        step = {"typ": typ, "url": url, "ts": ts,
                "zeit_lokal": to_local(ts).strftime("%H:%M:%S") if ts else ""}
        if typ == "action":
            path = path_of(url)
            title = clean_title(a.get("pageTitle") or "")
            kind, key, why = catalogue.classify(path, title)
            preview = is_preview(url)
            if preview:
                kind, why = "preview", "WordPress / Elementor preview (needs a login)"
            step.update(pfad=path, titel=title or path, art=kind, artikel=key,
                        grund=why, vorschau=preview,
                        time_raw=_int(a.get("timeSpent"), None))
            pageviews.append(step)
        else:
            label = " / ".join(str(a[k]) for k in ("eventCategory", "eventAction", "eventName")
                               if a.get(k)) or str(a.get("pageTitle") or a.get("title") or "")
            step.update(pfad=url, titel=label, art=typ, artikel="", grund="",
                        vorschau=False, time_raw=None)
        steps.append(step)

    # Time on a page: Matomo measures it up to the next pageview. The last page
    # has no end - its 0 is "not measured", unless a heartbeat delivered a value.
    for i, p in enumerate(pageviews):
        last = i == len(pageviews) - 1
        t = p.pop("time_raw")
        p["zeit"] = None if (t is None or (last and t == 0)) else t
        p["zeit_text"] = duration_text(p["zeit"])
    for s in steps:
        s.pop("time_raw", None)

    gaps = []
    for a, b in zip(pageviews, pageviews[1:]):
        if a["ts"] and b["ts"]:
            gaps.append(b["ts"] - a["ts"])
        elif a["zeit"] is not None:
            gaps.append(a["zeit"])

    entry = pageviews[0] if pageviews else None
    entry_query = query_of(entry["url"]) if entry else {}
    source, evidence, utm, campaign, post_id = _source(raw, entry_query, settings)

    browser = _first(raw, "browserName", "browser") or "unknown"
    city = _first(raw, "city", "cityName") or "unknown"
    interactions = [s for s in steps if s["typ"] in ("outlink", "download", "event", "goal")]
    contact_actions = [s for s in steps if s["typ"] in ("outlink", "action")
                       and s["url"].lower().startswith(("mailto:", "tel:"))]
    contact_actions += [s for s in steps if s["typ"] == "event"
                        and re.search(r"contact|kontakt|form", s["titel"] + s["url"], re.I)]
    goals = raw.get("goalConversions")
    if _int(goals) > 0:
        interactions.append({"typ": "goal"})

    measured_pages = [p for p in pageviews if not p["vorschau"]]
    duration = _int(raw.get("visitDuration"), 0)
    visit = {
        "id": str(raw.get("idVisit") or ""),
        "besucher": str(raw.get("visitorId") or ""),
        "lokal": local,
        "datum": local.date().isoformat() if local else "unknown",
        "datum_de": local.strftime("%d.%m.%Y") if local else "unknown",
        "uhrzeit": local.strftime("%H:%M") if local else "",
        "stunde": local.strftime("%H:00") if local else "unknown",
        "wochentag": local.strftime("%A") if local else "unknown",
        "sortier": first_ts or 0,
        "seiten": pageviews,
        "schritte": steps,
        "aufrufe": len(measured_pages),
        "vorschau_aufrufe": len(pageviews) - len(measured_pages),
        # Matomo's visit duration runs from the first to the last pageview; with
        # one page there is nothing to measure.
        "dauer_sek": duration if len(pageviews) >= 2 else None,
        "dauer_text": (f"≥ {duration_text(duration)}" if len(pageviews) >= 2
                       else "not measured (1 page)"),
        "luecken": gaps,
        "wiederkehrend": str(raw.get("visitorType") or "").lower() == "returning",
        "besuch_nr": _int(raw.get("visitCount"), 0),
        "quelle": source,
        "beleg": evidence,
        "utm": utm,
        "kampagne": campaign,
        "post_id": post_id,
        "einstieg": entry,
        "stadt": city,
        "land": _first(raw, "country", "countryName") or "unknown",
        "geraet": _first(raw, "deviceType", "deviceTypeName") or "unknown",
        "browser": browser,
        "system": _first(raw, "operatingSystemName", "operatingSystem") or "unknown",
        "sprache": _first(raw, "languageCode", "language") or "unknown",
        "interaktionen": len(interactions),
        "kontaktaktionen": len(contact_actions),
        "angebot": any(p["pfad"] in settings.offer_pages for p in measured_pages),
        "kontaktseite": any(p["pfad"] in settings.contact_pages for p in measured_pages),
    }
    _classify(visit, settings)
    visit["klasse_name"] = CLASSES[visit["klasse"]]
    _exclusions(visit, settings)
    return visit


def _classify(v, settings):
    reasons, automation, human = [], [], []
    if v["besucher"] and v["besucher"] in settings.own_ids:
        v["klasse"] = OWN
        v["gruende"] = ["Visitor ID is on the list of own / test devices"]
        return
    if "headless" in v["browser"].lower():
        automation.append(f"headless browser ({v['browser']})")
    gaps = v["luecken"]
    if len(v["seiten"]) >= 2 and gaps and all(g <= FAST_GAP for g in gaps):
        automation.append(f"{len(v['seiten'])} pages, each left after ≤ {FAST_GAP} s")
    if any(g >= READING_GAP for g in gaps):
        human.append(f"reading time between pages (up to {max(gaps)} s)")
    if v["interaktionen"]:
        human.append(f"{v['interaktionen']} interaction{'s' if v['interaktionen'] > 1 else ''}"
                     " (link, download, event or goal)")
    if automation:
        v["klasse"] = AUTOMATION
        reasons = ["Automation signal: " + "; ".join(automation)]
        if human:
            reasons.append("also seen: " + "; ".join(human))
    elif human:
        v["klasse"] = HUMAN
        reasons = ["Human signal: " + "; ".join(human)]
    else:
        v["klasse"] = UNCLEAR
        if len(v["seiten"]) <= 1:
            reasons = ["One page, time not measurable, no interaction"]
        else:
            reasons = ["Several pages, but no reading time between them and no interaction"]
    v["gruende"] = reasons


def _exclusions(v, settings):
    v["ausschluesse"] = []
    rule = place_rule_for(v["stadt"], settings.places)
    v["ortsregel"] = rule
    if rule:
        v["ausschluesse"].append(f"location rule “{rule}”"
                                 + (f" (Matomo: {v['stadt']})" if place_key(v["stadt"]) and
                                    v["stadt"].casefold() != rule.casefold() else ""))
    v["bearbeitung"] = v["vorschau_aufrufe"] > 0
    if v["bearbeitung"]:
        v["ausschluesse"].append("possible internal editing visit (preview opened)")
    if v["klasse"] == OWN:
        v["ausschluesse"].append("confirmed own / test visit")


# ── The whole period ─────────────────────────────────────────────────────

SCOPES = {
    "human": ("Probably human", (HUMAN,)),
    "human_unclear": ("Probably human + unclear", (HUMAN, UNCLEAR)),
}


@dataclass
class Evaluation:
    all: list
    audience: list
    scope: str
    von: dt.date
    bis: dt.date
    counted_places: bool = True
    truncated: bool = False

    def excluded(self):
        ids = {id(v) for v in self.audience}
        return [v for v in self.all if id(v) not in ids]

    def counts(self):
        c = {k: 0 for k in CLASSES}
        for v in self.all:
            c[v["klasse"]] += 1
        return c


def normalise_raw(raw):
    """Matomo returns {date: [visits]} for several days, a list for one."""
    if isinstance(raw, dict):
        flat = []
        for value in raw.values():
            if isinstance(value, list):
                flat.extend(value)
        raw = flat
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def evaluate(raw_visits, von, bis, catalogue, settings, scope="human",
             count_places=False, truncated=False):
    """Prepare, classify and filter - the single source for all log-based views.

    von/bis are dates in Europe/Berlin. Matomo stores days in the site's time
    zone (UTC here), so the caller fetches one day more at the start and the
    visits are cut here by their local date.
    """
    if scope not in SCOPES:
        scope = "human"
    visits = []
    for raw in normalise_raw(raw_visits):
        v = prepare(raw, catalogue, settings)
        if v["datum"] != "unknown" and not (von.isoformat() <= v["datum"] <= bis.isoformat()):
            continue
        visits.append(v)
    visits.sort(key=lambda v: v["sortier"], reverse=True)

    allowed = SCOPES[scope][1]
    audience = []
    for v in visits:
        if v["klasse"] not in allowed or v["bearbeitung"]:
            v["im_publikum"] = False
            continue
        if v["ortsregel"] and not count_places:
            v["im_publikum"] = False
            continue
        v["im_publikum"] = True
        audience.append(v)
    return Evaluation(all=visits, audience=audience, scope=scope, von=von, bis=bis,
                      counted_places=count_places, truncated=truncated)


# ── Analyses ─────────────────────────────────────────────────────────────

def share(n, total):
    return {"n": n, "von": total, "pct": round(100 * n / total) if total else None}


def kpis(ev):
    a = ev.audience
    return {
        "besuche": len(a),
        "besucher_ids": len({v["besucher"] for v in a if v["besucher"]}),
        "aufrufe": sum(v["aufrufe"] for v in a),
        "angebot": share(sum(1 for v in a if v["angebot"]), len(a)),
        "kontaktseite": share(sum(1 for v in a if v["kontaktseite"]), len(a)),
        "kontaktaktionen": share(sum(1 for v in a if v["kontaktaktionen"]), len(a)),
    }


def by_source(visits):
    """Analysis 1: source and what happened next, one row per source."""
    rows = []
    for name in SOURCES + ("Total",):
        vs = visits if name == "Total" else [v for v in visits if v["quelle"] == name]
        if not vs and name != "Total":
            continue
        n = len(vs)
        rows.append({
            "quelle": name,
            "besuche": n,
            "ids": len({v["besucher"] for v in vs if v["besucher"]}),
            "mehrere": share(sum(1 for v in vs if v["aufrufe"] >= 2), n),
            "angebot": share(sum(1 for v in vs if v["angebot"]), n),
            "kontaktseite": share(sum(1 for v in vs if v["kontaktseite"]), n),
            "kontaktaktionen": share(sum(1 for v in vs if v["kontaktaktionen"]), n),
            "summe": name == "Total",
        })
    return rows


def by_article(visits, catalogue, settings):
    """Analysis 2: every article, who read it, where from, and what came next."""
    arts = {}

    def entry(key, title):
        a = arts.get(key)
        if a is None:
            a = arts[key] = {
                "key": key, "titel": catalogue.article_title(key, title),
                "link": (catalogue.articles.get(key) or {}).get("link", ""),
                "ids": set(), "aufrufe": 0, "einstiege": 0, "besuche": 0,
                "quellen": dict.fromkeys(SOURCES, 0), "adressen": {},
                "weiter": {}, "ende": 0, "spaeter_angebot": 0, "spaeter_kontakt": 0,
                "zeiten": [], "published": (catalogue.articles.get(key) or {}).get("published", False),
            }
        return a

    for key, art in catalogue.articles.items():
        entry(key, art["titel"])

    for v in visits:
        pages = [p for p in v["seiten"] if not p["vorschau"]]
        seen = set()
        for i, p in enumerate(pages):
            if p["art"] != ARTICLE:
                continue
            a = entry(p["artikel"], p["titel"])
            a["aufrufe"] += 1
            a["adressen"][p["pfad"]] = a["adressen"].get(p["pfad"], 0) + 1
            if p["zeit"] is not None:
                a["zeiten"].append(p["zeit"])
            if i == 0:
                a["einstiege"] += 1
            if v["besucher"]:
                a["ids"].add(v["besucher"])
            nxt = pages[i + 1] if i + 1 < len(pages) else None
            if nxt is None:
                a["ende"] += 1
            elif nxt["pfad"] != p["pfad"]:
                label = nxt["titel"] or nxt["pfad"]
                a["weiter"][label] = a["weiter"].get(label, 0) + 1
            if p["artikel"] in seen:
                continue
            seen.add(p["artikel"])
            a["besuche"] += 1
            a["quellen"][v["quelle"]] += 1
            later = pages[i + 1:]
            if any(q["pfad"] in settings.offer_pages for q in later):
                a["spaeter_angebot"] += 1
            if any(q["pfad"] in settings.contact_pages for q in later):
                a["spaeter_kontakt"] += 1

    rows = []
    for a in arts.values():
        z = a["zeiten"]
        rows.append({
            "key": a["key"], "titel": a["titel"], "link": a["link"],
            "published": a["published"],
            "ids": len(a["ids"]), "aufrufe": a["aufrufe"], "einstiege": a["einstiege"],
            "besuche": a["besuche"],
            "quellen": [(q, n) for q, n in a["quellen"].items() if n],
            "adressen": sorted(a["adressen"].items(), key=lambda x: -x[1]),
            "weiter": sorted(a["weiter"].items(), key=lambda x: (-x[1], x[0])),
            "ende": a["ende"],
            "angebot": share(a["spaeter_angebot"], a["besuche"]),
            "kontakt": share(a["spaeter_kontakt"], a["besuche"]),
            "zeit": round(sum(z) / len(z)) if z else None,
            "zeit_text": duration_text(round(sum(z) / len(z))) if z else "not measured",
            "messungen": len(z),
        })
    rows.sort(key=lambda r: (-r["ids"], -r["aufrufe"], r["titel"].lower()))
    return rows


def overviews_and_unassigned(visits, catalogue):
    """Blog overviews (index, categories, series) and addresses WordPress no
    longer knows - shown apart from the articles, never mixed into them."""
    over, other = {}, {}
    for v in visits:
        for p in v["seiten"]:
            if p["vorschau"]:
                continue
            target = over if p["art"] == OVERVIEW else other if p["art"] in (OTHER, NOT_FOUND) else None
            if target is None:
                continue
            e = target.setdefault(p["pfad"], {"pfad": p["pfad"], "titel": p["titel"],
                                              "art": p["art"], "grund": p["grund"],
                                              "aufrufe": 0, "ids": set()})
            e["aufrufe"] += 1
            if v["besucher"]:
                e["ids"].add(v["besucher"])
    def done(d):
        rows = [dict(e, ids=len(e["ids"])) for e in d.values()]
        rows.sort(key=lambda r: (-r["aufrufe"], r["pfad"]))
        return rows
    return done(over), done(other)


def by_post(visits, posts=None):
    """Analysis 3: website visits per LinkedIn post, from UTM only.

    posts: {planner id: {'titel', 'datum', 'kanal'}} - for readable rows.
    Visits from LinkedIn without a post ID are one row of their own.
    """
    posts = posts or {}
    groups = {}
    for v in visits:
        if v["quelle"] != LINKEDIN:
            continue
        key = v["post_id"] if v["post_id"] is not None else "none"
        groups.setdefault(key, []).append(v)
    rows = []
    for key, vs in groups.items():
        info = posts.get(key, {}) if key != "none" else {}
        n = len(vs)
        rows.append({
            "post_id": None if key == "none" else key,
            "titel": info.get("titel") or ("LinkedIn without post ID" if key == "none"
                                           else f"Post #{key} (not in the planner)"),
            "datum": info.get("datum") or "",
            "kanal": info.get("kanal") or "",
            "kampagnen": sorted({v["kampagne"] for v in vs if v["kampagne"]}),
            "begriffe": sorted({v["utm"].get("term", "") for v in vs if v["utm"].get("term")}),
            "besuche": n,
            "ids": len({v["besucher"] for v in vs if v["besucher"]}),
            "angebot": share(sum(1 for v in vs if v["angebot"]), n),
            "kontaktseite": share(sum(1 for v in vs if v["kontaktseite"]), n),
            "kontaktaktionen": share(sum(1 for v in vs if v["kontaktaktionen"]), n),
        })
    rows.sort(key=lambda r: (r["post_id"] is None, -(r["post_id"] or 0)))
    return rows


def frequencies(visits, fields, titles):
    """Diagnostics: counts of one or more fields, per class."""
    if isinstance(fields, str):
        fields = (fields,)
    table = {}
    for v in visits:
        key = tuple(str(v.get(f) or "unknown") for f in fields)
        row = table.setdefault(key, dict.fromkeys(CLASSES, 0))
        row[v["klasse"]] += 1
    rows = [list(k) + [c[HUMAN], c[UNCLEAR], c[AUTOMATION], c[OWN], sum(c.values())]
            for k, c in table.items()]
    rows.sort(key=lambda r: (-r[-1], str(r[0])))
    return {"spalten": list(titles) + ["Human", "Unclear", "Automated", "Own", "Total"],
            "zeilen": rows}


def monthly_ids(visits, months):
    """Distinct visitor IDs per month - never summed across months."""
    out = []
    for m in months:
        ids = {v["besucher"] for v in visits if v["datum"][:7] == m and v["besucher"]}
        back = {v["besucher"] for v in visits if v["datum"][:7] == m and v["besucher"]
                and v["wiederkehrend"]}
        out.append({"monat": m, "ids": len(ids), "wieder": len(back)})
    return out


def place_variants(visits, rules):
    """For the exclusion list: which Matomo spellings each rule caught."""
    out = {r: {} for r in rules}
    for v in visits:
        r = v.get("ortsregel")
        if r:
            out[r][v["stadt"]] = out[r].get(v["stadt"], 0) + 1
    return [{"regel": r, "varianten": sorted(out[r].items())} for r in rules]
