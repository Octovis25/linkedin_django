"""Statistics → OJ analysis: patterns in Ortrud's own posts.

Everything is computed on each page view from what is stored: the Buffer
numbers per post (buffer_metrics) and the LinkedIn profile export
(oj_export). With about ten posts a year most findings are hints, not proof,
so each one carries a verdict:

    solid   enough data, and the effect is large or merely descriptive
    hint    points one way, but few posts or p between 0.01 and 0.1
    few     too few posts to say anything yet

The thresholds are deliberately plain (counts and one exact binomial test);
there is no model fitting here - see clicks_model.py for that kind of work on
the company page.
"""
import math
import re
from collections import OrderedDict
from datetime import date, timedelta
from statistics import mean, median

from . import buffer_metrics as bm

WINDOW = 4            # day of the post + 3 days after it
YOUNG_DAYS = 7        # posts younger than this are still collecting
MIN_TESTED = 30       # from this many posts the factor table gets tested

CONFERENCE = re.compile(r'acdm|phuse|pcmg|conference|konferenz|congress|kongress|summit|assembly|'
                        r'single day event|\bsde\b|webinar|\bevent\b|meeting', re.I)
ACHIEVEMENT = re.compile(r'credential|certificat|zertifikat|earned|award|graduat', re.I)


def post_type(text):
    if CONFERENCE.search(text or ''):
        return 'Conference'
    if ACHIEVEMENT.search(text or ''):
        return 'Achievement'
    return 'Topic'


def binom_two_sided(x, n, p):
    """Exact two-sided binomial test (sum of all outcomes no likelier than x)."""
    if n == 0 or p <= 0 or p >= 1:
        return 1.0
    pmf = [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]
    cut = pmf[x] * (1 + 1e-9)
    return min(1.0, sum(v for v in pmf if v <= cut))


def _hour_berlin(sent_at):
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(sent_at).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return dt.astimezone(bm.BERLIN).hour if dt.tzinfo else dt.hour


def _verdict(n_needed_ok, p=None):
    if not n_needed_ok:
        return 'few'
    if p is None:
        return 'solid'
    return 'solid' if p < 0.01 else 'hint' if p < 0.1 else 'none'


def analyse(posts, company_posts, daily, followers_total, today=None, contacts=None):
    """posts / company_posts: lists from buffer_metrics.posts_with_latest().
    daily: oj_export.daily() rows [iso, impressions, engagement, new followers]."""
    today = today or bm.today_berlin()
    year_ago = today - timedelta(days=365)
    days = {date.fromisoformat(r[0]): r for r in daily}
    first_day = min(days) if days else year_ago
    mine = [p for p in posts if p['date'] and p['date'] >= max(first_day, year_ago)
            and p['m'].get('impressions') is not None]
    post_days = sorted({p['date'] for p in mine})
    out = {'n_posts': len(mine), 'has_export': bool(days), 'findings': []}
    F = out['findings']

    # 1 · lifetime of a post (profile impressions per day around each post)
    if days and post_days:
        window = {d + timedelta(k) for d in post_days for k in range(WINDOW)}
        ev = []
        for k in range(11):
            vals = [days[d + timedelta(k)][1] for d in post_days if d + timedelta(k) in days]
            ev.append(round(mean(vals), 1) if vals else 0)
        base = [r[1] for d, r in days.items() if d not in window]
        total = sum(r[1] for r in days.values())
        in_win = sum(r[1] for d, r in days.items() if d in window)
        baseline = round(mean(base), 1) if base else 0
        # Days until two thirds of the extra reach (above a normal day) are in.
        extra = [max(0, v - baseline) for v in ev]
        run, n_days = 0, len(extra)
        for k, v in enumerate(extra):
            run += v
            if sum(extra) and run >= sum(extra) * 2 / 3:
                n_days = k + 1
                break
        F.append({'key': 'lifetime', 'title': ('Two thirds of a post’s reach come on the day itself' if n_days == 1 else
                            f'Two thirds of a post’s reach come in the first {n_days} days'),
                  'verdict': _verdict(len(post_days) >= 5),
                  'basis': f'{len(post_days)} posts, {len(days)} days',
                  'text': (f'On the day of a post your profile gets on average <b>{ev[0]:.0f}</b> impressions, '
                           f'the next day <b>{ev[1]:.0f}</b>; without a post it is <b>{baseline:g}</b> a day. '
                           f'<b>{round(in_win / total * 100) if total else 0} %</b> of all impressions came in the '
                           f'{WINDOW} days after a post.'),
                  'so': 'Reach comes almost only from new posts – a steady rhythm counts more than a perfect single post.',
                  'chart': {'kind': 'event', 'values': ev, 'baseline': baseline}})

    # 2 · posts and followers
    if days and post_days:
        window = {d + timedelta(k) for d in post_days for k in range(WINDOW)}
        win_days = [d for d in days if d in window]
        other_days = [d for d in days if d not in window]
        f_win = sum(days[d][3] for d in win_days)
        f_all = sum(r[3] for r in days.values())
        r_win = f_win / len(win_days) if win_days else 0
        r_oth = (f_all - f_win) / len(other_days) if other_days else 0
        p = binom_two_sided(f_win, f_all, len(win_days) / len(days)) if f_all else 1.0
        months = OrderedDict()
        for d in sorted(days):
            months[d.strftime('%Y-%m')] = months.get(d.strftime('%Y-%m'), 0) + days[d][3]
        top = sorted(months.items(), key=lambda kv: -kv[1])[:2]
        verdict = _verdict(f_all >= 30 and len(post_days) >= 5, p)
        F.append({'key': 'followers', 'title': 'Posts bring followers' + (' – a little' if verdict != 'none' else '? No clear effect'),
                  'verdict': verdict,
                  'basis': f'p = {p:.2f}' if p >= 0.01 else 'p < 0.01',
                  'text': (f'In the {WINDOW} days after a post: <b>{r_win:.2f}</b> new followers per day, '
                           f'otherwise <b>{r_oth:.2f}</b>{f" – about <b>{r_win / r_oth:.1f}×</b>" if r_oth else ""}. '
                           f'But only <b>{f_win} of {f_all}</b> new followers came in those days. '
                           f'The biggest months: ' + ', '.join(f'<b>{_month(k)} (+{v})</b>' for k, v in top) + '.'),
                  'so': 'Most followers come from elsewhere – meeting people, conferences, connection requests. Posts help a little on top.',
                  'chart': {'kind': 'pair', 'labels': [f'{WINDOW} days after a post', 'all other days'],
                            'values': [round(r_win, 2), round(r_oth, 2)]}})

    # 2b · followers and contacts (Connections.csv)
    if days and contacts:
        lo, hi = min(days).isoformat(), max(days).isoformat()
        new_c = [c for c in contacts if lo <= c[0] <= hi]
        f_all = sum(r[3] for r in days.values())
        if new_c and f_all:
            months = OrderedDict()
            for c in new_c:
                months[c[0][:7]] = months.get(c[0][:7], 0) + 1
            top = sorted(months.items(), key=lambda kv: -kv[1])[:2]
            levels = OrderedDict()
            for c in new_c:
                if c[2] not in ('Other', '(no job title)', ''):
                    levels[c[2]] = levels.get(c[2], 0) + 1
            lv = sorted(levels.items(), key=lambda kv: -kv[1])[:2]
            share = len(new_c) / f_all
            chart_months = OrderedDict((d.strftime('%Y-%m'), [0, 0]) for d in sorted(days))
            for d, r in days.items():
                chart_months[d.strftime('%Y-%m')][0] += r[3]
            for c in new_c:
                if c[0][:7] in chart_months:
                    chart_months[c[0][:7]][1] += 1
            F.append({'key': 'contacts',
                      'title': 'Your followers grow through contacts' if share >= 0.6 else 'Contacts and followers',
                      'verdict': 'solid' if len(new_c) >= 30 else 'hint',
                      'basis': f'{len(new_c)} contacts, {f_all} followers',
                      'text': (f'In the export period you gained <b>{f_all}</b> followers and <b>{len(new_c)}</b> new contacts – '
                               f'about <b>{round(share * 100)} %</b>. Today: {len(contacts)} contacts'
                               + (f', {followers_total} followers' if followers_total else '') + '. '
                               f'Most new contacts: ' + ', '.join(f'<b>{_month(k)} (+{v})</b>' for k, v in top)
                               + ('. Among them most often: ' + ', '.join(f'{k.lower()} ({v})' for k, v in lv) if lv else '') + '.'),
                      'so': 'Your reach grows with your network – connecting after a conference, with a short personal note, is what moves the follower number.' if share >= 0.6 else '',
                      'chart': {'kind': 'months2', 'labels': list(chart_months),
                                'followers': [v[0] for v in chart_months.values()],
                                'contacts': [v[1] for v in chart_months.values()]}})

    # 3 · types of posts
    if mine:
        rows = []
        for p in sorted(mine, key=lambda p: p['date']):
            t = post_type(p['text'])
            age = (today - p['date']).days
            rows.append({'label': f"{p['date']:%d.%m.} {p['title'][:34]}", 'type': t,
                         'impressions': p['m'].get('impressions') or 0, 'young': age < YOUNG_DAYS})
        groups = OrderedDict()
        for r in rows:
            if not r['young']:
                groups.setdefault(r['type'], []).append(r['impressions'])
        parts = [f'{t}: median <b>{median(v):.0f}</b> ({len(v)} post{"s" if len(v) != 1 else ""})' for t, v in groups.items()]
        young = [r for r in rows if r['young']]
        ok = len(groups) >= 2 and all(len(v) >= 3 for v in groups.values())
        best = max(groups.items(), key=lambda kv: median(kv[1]))[0] if groups else None
        F.append({'key': 'types', 'title': f'{best} posts do best' if best and len(groups) > 1 else 'Types of posts',
                  'verdict': 'hint' if ok else 'few',
                  'basis': ' vs '.join(f'{len(v)}' for v in groups.values()) + ' posts',
                  'text': ' · '.join(parts) + (f'. {len(young)} post{"s are" if len(young) != 1 else " is"} younger than a week and left out.' if young else '.'),
                  'so': 'Types come from words in the text (conference names, “credential” …); posts younger than a week are still collecting and not compared.',
                  'chart': {'kind': 'bars', 'rows': rows, 'height': max(180, 26 * len(rows) + 60)}})

    # 4 · profile vs company page
    def _avg(ps):
        v = [p['m'].get('impressions') for p in ps if p['date'] and year_ago <= p['date'] <= today - timedelta(days=YOUNG_DAYS)
             and p['m'].get('impressions') is not None]
        return (round(mean(v)), len(v)) if v else (None, 0)
    a_me, n_me = _avg(posts)
    a_co, n_co = _avg(company_posts)
    if a_me and a_co:
        F.append({'key': 'company', 'title': 'Your profile reaches more than the company page' if a_me > a_co else 'The company page reaches more than your profile',
                  'verdict': _verdict(n_me >= 5 and n_co >= 10),
                  'basis': f'{n_me} vs {n_co} posts',
                  'text': (f'Per post, your profile gets about <b>{a_me}</b> impressions, the company page about '
                           f'<b>{a_co}</b> – <b>{a_me / a_co:.1f}×</b>. Both from Buffer, last 12 months, posts older than a week.'),
                  'so': 'A company post you share with a sentence of your own reaches far more people than the post alone.' if a_me > a_co else '',
                  'chart': {'kind': 'pair', 'labels': ['Your profile', 'Company page'], 'values': [a_me, a_co], 'horizontal': True}})

    # 5 · months without posts
    if days:
        m = OrderedDict()
        for d in sorted(days):
            k = d.strftime('%Y-%m')
            e = m.setdefault(k, {'month': k, 'impressions': 0, 'followers': 0, 'posts': 0, 'days': 0})
            e['days'] += 1
            e['impressions'] += days[d][1]
            e['followers'] += days[d][3]
        for d in post_days:
            k = d.strftime('%Y-%m')
            if k in m:
                m[k]['posts'] += 1
        # Months the export covers only in part (the current one) are left out of the comparison.
        full = [e for e in m.values() if e['days'] >= 20]
        silent = [e for e in full if not e['posts']]
        busy = [e for e in full if e['posts']]
        F.append({'key': 'months', 'title': 'Months without posts are silent' if silent else 'You posted every month',
                  'verdict': 'solid',
                  'basis': f'{len(m)} months',
                  'text': (f'{len(silent)} month{"s" if len(silent) != 1 else ""} without a post '
                           f'({", ".join(_month(e["month"]) for e in silent)}): Ø <b>{mean(e["impressions"] for e in silent):.0f}</b> impressions. '
                           f'Months with posts: Ø <b>{mean(e["impressions"] for e in busy):.0f}</b>.') if silent and busy else '',
                  'so': '',
                  'chart': {'kind': 'months', 'months': list(m.values())}})

    # 6 · factors - listed, tested only with enough posts
    if mine:
        am = [p for p in mine if (_hour_berlin(p['sent_at']) or 0) < 12]
        pm = [p for p in mine if (_hour_berlin(p['sent_at']) or 0) >= 12]
        wd = OrderedDict()
        for p in sorted(mine, key=lambda p: p['date'].weekday()):
            wd[p['date'].strftime('%a')] = wd.get(p['date'].strftime('%a'), 0) + 1
        lengths = [len(p['text']) for p in mine if p['text']]
        tags = [p['text'].count('#') for p in mine if p['text']]
        vids = [p for p in mine if p['m'].get('views')]
        imp = lambda ps: f'Ø {mean(p["m"]["impressions"] for p in ps):.0f}' if ps else '–'
        F.append({'key': 'factors', 'title': 'Time of day, weekday, length, hashtags',
                  'verdict': 'few' if len(mine) < MIN_TESTED else 'hint',
                  'basis': f'{len(mine)} posts',
                  'text': '',
                  'so': f'These rows fill in by themselves. From about {MIN_TESTED} posts it is worth testing them.',
                  'table': [
                      ['Time of day', f'Before noon {len(am)} posts, {imp(am)} · afternoon/evening {len(pm)} posts, {imp(pm)}', len(mine)],
                      ['Weekday', ' · '.join(f'{k} {v}' for k, v in wd.items()), len(mine)],
                      ['Length', f'{min(lengths)} – {max(lengths)} characters' if lengths else '–', len(lengths)],
                      ['Hashtags', f'{min(tags)} – {max(tags)} per post' if tags else '–', len(tags)],
                      ['Video', f'{len(vids)} video posts, {imp(vids)} · without video {imp([p for p in mine if p not in vids])}', len(mine)],
                  ]})
    return out


def _month(key):
    y, m = key.split('-')
    return date(int(y), int(m), 1).strftime('%b %y')
