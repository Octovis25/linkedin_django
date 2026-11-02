"""LinkedIn's own export of a personal profile ("Aggregate Analytics", .xlsx).

LinkedIn offers it under Analytics on the profile; Ortrud uploads it about once
a month. It brings what Buffer does not have: followers (total and new per
day), impressions and engagement per day for the whole profile, the top posts
of the period and the demographics of followers and readers.

The workbook comes in the language of the LinkedIn account (German sheet
names like "AUFFINDBARKEIT", English ones like "DISCOVERY"). The parser goes
by the position of the sheets and the shape of the rows, not by their names:

    0  discovery     period, impressions, members reached
    1  engagement    date | impressions | engagement      (one row per day)
    2  top posts     url | date | engagement || url | date | impressions
    3  followers     total on <date>; then date | new followers
    4  demographics of the followers   category | value | percent
    5  demographics of the readers     (same shape; older exports lack it)

Storage: four tables oj_export_*; days are upserted (a newer export wins),
top posts and demographics are replaced by the newest upload.
"""
import re
from datetime import date, datetime

from zoneinfo import ZoneInfo

from django.db import connection

BERLIN = ZoneInfo('Europe/Berlin')

CATEGORIES = {
    'unternehmen': 'company', 'companies': 'company', 'company': 'company',
    'standort': 'location', 'locations': 'location', 'location': 'location',
    'firmengröße': 'company_size', 'company size': 'company_size',
    'karrierestufe': 'seniority', 'seniority': 'seniority',
    'position': 'job_title', 'job titles': 'job_title', 'job title': 'job_title',
    'branche': 'industry', 'industries': 'industry', 'industry': 'industry',
}
CATEGORY_LABEL = {
    'industry': 'Industry', 'seniority': 'Seniority', 'location': 'Location',
    'job_title': 'Job title', 'company_size': 'Company size', 'company': 'Company',
}


class ExportError(ValueError):
    """The file is not a LinkedIn profile export we can read."""


# ── parsing ────────────────────────────────────────────────────────────────

def _date(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    m = re.fullmatch(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', s)          # 13.3.2026
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)            # 3/13/2026
    if m:
        return date(int(m[3]), int(m[1]), int(m[2]))
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', s)                # 2026-03-13
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    return None


def _int(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r'[^\d]', '', str(v))
    return int(digits) if digits else None


def _pct(v):
    """'10 %', '10%', '< 1 %', 0.1 -> percent as number."""
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return float(v) * 100 if v <= 1 else float(v)
    s = str(v).replace('\xa0', ' ').strip()
    if s.startswith('<'):
        return 0.5
    m = re.search(r'\d+(?:[.,]\d+)?', s)
    return float(m.group(0).replace(',', '.')) if m else None


def _dates_in(text):
    found = re.findall(r'\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2}', str(text or ''))
    return [d for d in (_date(x) for x in found) if d]


def parse_workbook(fileobj):
    """Read the export into a plain dict. Raises ExportError if it does not fit."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(fileobj, read_only=True, data_only=True)
    except Exception as e:
        raise ExportError(f'Not an Excel file LinkedIn exported ({type(e).__name__}).')
    sheets = [list(ws.iter_rows(values_only=True)) for ws in wb.worksheets]
    if len(sheets) < 5:
        raise ExportError('The file has fewer sheets than a LinkedIn profile export.')

    out = {'sheet_names': [ws.title for ws in wb.worksheets]}

    # 0 discovery
    disc = [r for r in sheets[0] if r and any(c not in (None, '') for c in r)]
    if len(disc) < 3:
        raise ExportError('The first sheet does not show the period and impressions.')
    period = _dates_in(disc[0][1] if len(disc[0]) > 1 else '')
    if len(period) != 2:
        raise ExportError('The period could not be read from the first sheet.')
    out['period_from'], out['period_to'] = period
    out['impressions'] = _int(disc[1][1])
    out['members_reached'] = _int(disc[2][1])

    # 1 engagement per day
    days = {}
    for r in sheets[1][1:]:
        d = _date(r[0] if r else None)
        if d:
            days[d] = {'impressions': _int(r[1]) or 0, 'engagement': _int(r[2]) or 0, 'new_followers': 0}
    if not days:
        raise ExportError('The second sheet has no daily values.')

    # 3 followers
    fol = sheets[3]
    total_row = next((r for r in fol if r and r[0] and _dates_in(r[0])), None)
    out['followers_total'] = _int(total_row[1]) if total_row else None
    out['followers_date'] = _dates_in(total_row[0])[0] if total_row else None
    for r in fol:
        d = _date(r[0] if r else None)
        if d and len(r) > 1:
            days.setdefault(d, {'impressions': 0, 'engagement': 0, 'new_followers': 0})
            days[d]['new_followers'] = _int(r[1]) or 0
    out['days'] = days

    # 2 top posts: two blocks side by side
    top = {}
    for r in sheets[2]:
        r = list(r) + [None] * 7
        if r[0] and str(r[0]).startswith('http'):
            top.setdefault(r[0], {'posted': _date(r[1])})['engagement'] = _int(r[2])
        if r[4] and str(r[4]).startswith('http'):
            top.setdefault(r[4], {'posted': _date(r[5])})['impressions'] = _int(r[6])
    out['top'] = top

    # 4, 5 demographics
    def demo(rows):
        res = []
        for r in rows[1:]:
            if not r or not r[0] or len(r) < 3:
                continue
            key = CATEGORIES.get(str(r[0]).strip().lower(), str(r[0]).strip().lower()[:30])
            pct = _pct(r[2])
            if r[1] and pct is not None:
                res.append((key, str(r[1]).strip()[:200], pct))
        return res
    out['demo'] = {'audience': demo(sheets[4]), 'content': demo(sheets[5]) if len(sheets) > 5 else []}
    return out


# ── storage ────────────────────────────────────────────────────────────────

def ensure_tables():
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS oj_export_meta (
            id INT PRIMARY KEY, period_from DATE, period_to DATE,
            impressions INT, members_reached INT,
            followers_total INT, followers_date DATE,
            file_name VARCHAR(255), uploaded_at DATETIME)""")
        c.execute("""CREATE TABLE IF NOT EXISTS oj_export_daily (
            day DATE PRIMARY KEY, impressions INT DEFAULT 0,
            engagement INT DEFAULT 0, new_followers INT DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS oj_export_top (
            url VARCHAR(400) PRIMARY KEY, posted DATE,
            impressions INT NULL, engagement INT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS oj_export_demo (
            id INT AUTO_INCREMENT PRIMARY KEY, kind VARCHAR(10),
            category VARCHAR(30), value VARCHAR(200), pct DOUBLE)""")


def store(data, file_name=''):
    ensure_tables()
    with connection.cursor() as c:
        c.execute("DELETE FROM oj_export_meta")
        c.execute("""INSERT INTO oj_export_meta (id, period_from, period_to, impressions,
                         members_reached, followers_total, followers_date, file_name, uploaded_at)
                     VALUES (1,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  [data['period_from'], data['period_to'], data['impressions'],
                   data['members_reached'], data['followers_total'], data['followers_date'],
                   (file_name or '')[:255], datetime.now(BERLIN).replace(tzinfo=None)])
        for d, v in data['days'].items():
            c.execute("""INSERT INTO oj_export_daily (day, impressions, engagement, new_followers)
                         VALUES (%s,%s,%s,%s)
                         ON DUPLICATE KEY UPDATE impressions=VALUES(impressions),
                             engagement=VALUES(engagement), new_followers=VALUES(new_followers)""",
                      [d, v['impressions'], v['engagement'], v['new_followers']])
        c.execute("DELETE FROM oj_export_top")
        for url, v in data['top'].items():
            c.execute("INSERT INTO oj_export_top (url, posted, impressions, engagement) VALUES (%s,%s,%s,%s)",
                      [url[:400], v.get('posted'), v.get('impressions'), v.get('engagement')])
        c.execute("DELETE FROM oj_export_demo")
        for kind, rows in data['demo'].items():
            for cat, value, pct in rows:
                c.execute("INSERT INTO oj_export_demo (kind, category, value, pct) VALUES (%s,%s,%s,%s)",
                          [kind, cat, value, pct])


def _post_label(url):
    """'…/posts/ortrud-junker-wolf_acdm-clinicaltrials-share-7437…' -> '#acdm #clinicaltrials'."""
    slug = url.rsplit('/posts/', 1)[-1]
    slug = slug.split('_', 1)[1] if '_' in slug else slug
    slug = re.split(r'-(?:share|ugcPost|activity)-', slug)[0]
    if slug.startswith('ich-') or slug.startswith('i-'):
        return slug.replace('-', ' ')
    return ' '.join('#' + w for w in slug.split('-') if w)


def summary():
    """Everything the page shows from the export, or None before the first upload."""
    ensure_tables()
    with connection.cursor() as c:
        c.execute("""SELECT period_from, period_to, impressions, members_reached,
                            followers_total, followers_date, file_name, uploaded_at
                     FROM oj_export_meta WHERE id=1""")
        meta = c.fetchone()
        if not meta:
            return None
        p_from, p_to = meta[0], meta[1]
        c.execute("""SELECT DATE_FORMAT(day,'%%Y-%%m'), SUM(impressions), SUM(engagement), SUM(new_followers)
                     FROM oj_export_daily WHERE day BETWEEN %s AND %s
                     GROUP BY 1 ORDER BY 1""", [p_from, p_to])
        months = [{'month': r[0], 'impressions': int(r[1] or 0), 'engagement': int(r[2] or 0),
                   'new_followers': int(r[3] or 0)} for r in c.fetchall()]
        c.execute("""SELECT url, posted, impressions, engagement FROM oj_export_top
                     ORDER BY COALESCE(impressions,0) DESC, COALESCE(engagement,0) DESC""")
        top = [{'url': r[0], 'posted': r[1], 'impressions': r[2], 'engagement': r[3],
                'label': _post_label(r[0]),
                'rate': round(r[3] / r[2] * 100, 1) if r[2] and r[3] is not None else None}
               for r in c.fetchall() if not r[1] or not p_from or r[1] >= p_from]
        c.execute("SELECT kind, category, value, pct FROM oj_export_demo ORDER BY id")
        demo = {}
        for kind, cat, value, pct in c.fetchall():
            demo.setdefault(cat, {}).setdefault(value, {})[kind] = pct
    engagement = sum(m['engagement'] for m in months)
    new_followers = sum(m['new_followers'] for m in months)
    total = meta[4]
    growth = []
    if total is not None:
        running = total - new_followers
        for m in months:
            running += m['new_followers']
            growth.append(running)
    demo_rows = {}
    for cat, values in demo.items():
        rows = [{'value': v, 'audience': d.get('audience'), 'content': d.get('content')}
                for v, d in values.items()]
        rows.sort(key=lambda x: -max(x['audience'] or 0, x['content'] or 0))
        demo_rows[cat] = rows[:10]
    return {
        'period_from': p_from, 'period_to': p_to, 'impressions': meta[2],
        'members_reached': meta[3], 'followers_total': total, 'followers_date': meta[5],
        'file_name': meta[6], 'uploaded_at': meta[7],
        'engagement': engagement,
        'engagement_rate': round(engagement / meta[2] * 100, 1) if meta[2] else None,
        'new_followers': new_followers,
        'growth_pct': round(new_followers / (total - new_followers) * 100) if total and total > new_followers else None,
        'months': months, 'growth': growth, 'top': top,
        'demo': demo_rows,
        'demo_categories': [(k, CATEGORY_LABEL.get(k, k.title())) for k in
                            ['industry', 'seniority', 'location', 'job_title', 'company_size', 'company']
                            if k in demo_rows],
    }


def daily():
    """Every stored day as [iso date, impressions, engagement, new followers], oldest first."""
    ensure_tables()
    with connection.cursor() as c:
        c.execute("SELECT day, impressions, engagement, new_followers FROM oj_export_daily ORDER BY day")
        return [[d.isoformat(), int(i or 0), int(e or 0), int(f or 0)] for d, i, e, f in c.fetchall()]


def meta():
    """Facts about the newest upload, or None before the first one."""
    ensure_tables()
    with connection.cursor() as c:
        c.execute("""SELECT period_from, period_to, impressions, members_reached,
                            followers_total, followers_date, file_name, uploaded_at
                     FROM oj_export_meta WHERE id=1""")
        r = c.fetchone()
    if not r:
        return None
    return {'period_from': r[0], 'period_to': r[1], 'impressions': r[2], 'members_reached': r[3],
            'followers_total': r[4], 'followers_date': r[5], 'file_name': r[6], 'uploaded_at': r[7]}
