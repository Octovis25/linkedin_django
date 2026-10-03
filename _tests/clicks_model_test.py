"""Tests for the Clicks tab: count models and topic rules.

    python _tests/clicks_model_test.py

No Django, no database. The reference values come from statsmodels 0.15
(NegativeBinomial with estimated alpha, Poisson GLM) on the 80 posts of
03.10.2026 - the numbers in claude/klick-analyse-2026-10-03.md.
"""
import datetime
import importlib.util
import os
import sys
import types

import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)


def laden(name):
    pfad = os.path.join(WURZEL, 'linkedin_statistics', name + '.py')
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# clicks_topics imports django.db.connection only for its table helpers
dj = types.ModuleType('django'); djdb = types.ModuleType('django.db'); djdb.connection = None
sys.modules.setdefault('django', dj); sys.modules.setdefault('django.db', djdb)
cm = laden('clicks_model')
ct = laden('clicks_topics')

# impressions, clicks, date, video, topic, hook, length of (LinkedIn + Buffer) text, post type
POSTS = [
    (33, 0, '2026-09-29', 0, 'EV', 's', 1350, 'company'),
    (36, 0, '2026-09-28', 1, 'SQ', 's', 1150, 'company'),
    (68, 5, '2026-09-21', 1, 'DM', 's', 800, 'company'),
    (80, 0, '2026-09-17', 0, 'EV', 's', 1380, 'short'),
    (62, 1, '2026-09-11', 0, 'EV', 's', 1130, 'short'),
    (131, 3, '2026-08-10', 0, 'SV', 's', 1320, 'company'),
    (116, 1, '2026-07-31', 1, 'DM', 's', 660, 'short'),
    (57, 0, '2026-07-22', 0, 'EV', 's', 1100, 'company'),
    (88, 8, '2026-07-21', 1, 'OV', 's', 1000, 'company'),
    (121, 1, '2026-07-13', 0, 'DM', 's', 1030, 'company'),
    (44, 0, '2026-07-06', 0, 'OV', 'w', 1490, 'company'),
    (58, 1, '2026-07-03', 0, 'DM', 'q', 750, 'short'),
    (18, 1, '2026-06-29', 0, 'OV', 's', 1290, 'company'),
    (18, 0, '2026-06-26', 0, 'SD', 's', 1200, 'short'),
    (41, 3, '2026-06-22', 1, 'DM', 's', 620, 'company'),
    (31, 0, '2026-06-19', 0, 'ST', 'w', 450, 'short'),
    (20, 0, '2026-06-15', 1, 'SQ', 's', 1810, 'company'),
    (23, 1, '2026-06-12', 1, 'DM', 's', 710, 'short'),
    (52, 0, '2026-06-08', 0, 'SV', 'w', 950, 'company'),
    (78, 0, '2026-06-08', 0, 'SV', 'w', 960, 'company'),
    (56, 12, '2026-06-05', 1, 'DM', 's', 280, 'company'),
    (101, 0, '2026-06-05', 0, 'DM', 's', 610, 'company'),
    (70, 2, '2026-06-01', 0, 'DM', 's', 1330, 'company'),
    (44, 1, '2026-05-29', 0, 'ST', 's', 830, 'short'),
    (43, 6, '2026-05-25', 1, 'OV', 's', 1740, 'company'),
    (54, 6, '2026-05-18', 0, 'OV', 's', 2120, 'company'),
    (45, 1, '2026-05-15', 0, 'ST', 's', 960, 'short'),
    (104, 3, '2026-05-11', 1, 'SD', 's', 1400, 'company'),
    (69, 0, '2026-05-04', 0, 'SQ', 's', 1380, 'company'),
    (111, 1, '2026-04-27', 0, 'OV', 's', 1260, 'company'),
    (129, 10, '2026-04-24', 0, 'OT', 's', 450, 'short'),
    (84, 4, '2026-04-20', 1, 'SQ', 's', 1500, 'company'),
    (149, 4, '2026-04-13', 0, 'OV', 'w', 1290, 'company'),
    (52, 0, '2026-04-07', 0, 'EV', 's', 870, 'short'),
    (69, 6, '2026-04-03', 0, 'DM', 'w', 480, 'short'),
    (90, 4, '2026-03-30', 1, 'EV', 's', 860, 'company'),
    (61, 0, '2026-03-20', 0, 'OT', 'q', 430, 'short'),
    (102, 6, '2026-03-16', 1, 'SD', 's', 1230, 'company'),
    (141, 6, '2026-03-13', 0, 'DM', 's', 520, 'short'),
    (96, 10, '2026-03-09', 0, 'SV', 's', 1520, 'company'),
    (84, 2, '2026-03-06', 0, 'ST', 's', 330, 'short'),
    (163, 0, '2026-03-02', 0, 'DM', 's', 1240, 'company'),
    (140, 0, '2026-02-23', 0, 'DM', 's', 1830, 'company'),
    (211, 4, '2026-02-23', 0, 'DM', 's', 2050, 'company'),
    (145, 2, '2026-02-23', 0, 'DM', 's', 2640, 'company'),
    (318, 14, '2026-02-23', 0, 'DM', 's', 2690, 'company'),
    (139, 4, '2026-02-20', 0, 'ST', 's', 340, 'short'),
    (200, 0, '2026-02-13', 0, 'DM', 's', 340, 'short'),
    (123, 8, '2026-02-10', 0, 'DM', 's', 3060, 'company'),
    (172, 6, '2026-02-06', 0, 'DM', 'w', 320, 'short'),
    (197, 8, '2026-01-30', 0, 'ST', 's', 1660, 'short'),
    (241, 8, '2026-01-26', 0, 'ST', 's', 1970, 'company'),
    (119, 0, '2026-01-23', 0, 'DM', 's', 420, 'short'),
    (173, 5, '2026-01-19', 0, 'SD', 's', 1900, 'company'),
    (150, 3, '2026-01-16', 0, 'DM', 's', 290, 'short'),
    (110, 2, '2026-01-12', 1, 'SV', 'w', 1410, 'company'),
    (109, 3, '2026-01-09', 0, 'OT', 's', 1160, 'company'),
    (87, 2, '2026-01-02', 1, 'EV', 'q', 530, 'company'),
    (70, 2, '2025-12-22', 1, 'EV', 's', 730, 'company'),
    (39, 1, '2025-12-19', 1, 'EV', 'n', 1080, 'company'),
    (70, 17, '2025-12-15', 0, 'SQ', 'n', 750, 'company'),
    (53, 2, '2025-12-12', 1, 'EV', 'n', 840, 'company'),
    (53, 1, '2025-12-08', 1, 'OT', 's', 480, 'company'),
    (75, 5, '2025-12-05', 1, 'EV', 'n', 680, 'company'),
    (68, 4, '2025-12-02', 0, 'OT', 's', 580, 'company'),
    (77, 9, '2025-11-28', 1, 'EV', 'n', 1070, 'company'),
    (175, 12, '2025-11-24', 1, 'DM', 's', 650, 'company'),
    (90, 4, '2025-11-18', 1, 'SV', 's', 800, 'company'),
    (103, 10, '2025-11-10', 1, 'SV', 's', 990, 'company'),
    (83, 7, '2025-11-06', 1, 'SV', 'w', 870, 'company'),
    (118, 12, '2025-10-30', 1, 'EV', 'w', 560, 'company'),
    (115, 7, '2025-10-24', 0, 'ST', 's', 150, 'company'),
    (187, 14, '2025-10-17', 1, 'OT', 's', 130, 'company'),
    (129, 8, '2025-10-10', 1, 'OT', 's', 150, 'company'),
    (69, 8, '2025-10-02', 0, 'OV', 's', 150, 'company'),
    (170, 10, '2025-09-26', 0, 'DM', 'q', 150, 'company'),
    (184, 1, '2025-09-19', 0, 'OT', 's', 150, 'company'),
    (184, 3, '2025-09-12', 0, 'OT', 's', 140, 'company'),
    (259, 17, '2025-08-19', 0, 'SQ', 'q', 150, 'company'),
    (315, 19, '2025-06-03', 0, 'OT', 's', 180, 'company')
]
KEYS = ['DM', 'SQ', 'OV', 'SD', 'ST', 'SV', 'EV', 'OT']

ok = fehl = 0


def pruef(name, bedingung, info=''):
    global ok, fehl
    if bedingung:
        ok += 1
    else:
        fehl += 1
        print('FEHL', name, info)


def nah(name, wert, soll, tol):
    pruef(name, wert is not None and abs(wert - soll) <= tol, f'{wert} statt {soll} (±{tol})')


def posts(rows=POSTS):
    return [dict(imp=a, clicks=b, date=datetime.date.fromisoformat(c), video=bool(d), topic=e,
                 hook=f, length=g if g >= 500 else None, format=h) for a, b, c, d, e, f, g, h in rows]


# 1 chi-square tail against scipy.stats.chi2.sf
for x, df, soll in [(9.5888, 7, 0.21309756511940314), (6.1332, 1, 0.013266653826308072),
                    (2.494, 3, 0.47637639366394413), (30, 2, 3.0590232050182594e-07),
                    (0.001, 5, 0.9999999983185123), (0.0, 3, 1.0)]:
    nah(f'chi2_sf({x},{df})', cm.chi2_sf(x, df), soll, 1e-9 + soll * 1e-9)

# 2 the analysis of 03.10.2026
r = cm.analyse(posts(), KEYS)
pruef('result there', r is not None)
nah('n', r['n'], 80, 0)
nah('alpha', r['alpha'], 0.5617, 0.002)
nah('explained imp', r['explained']['imp'], 0.2509, 0.001)
nah('explained + date', r['explained']['date'], 0.3530, 0.001)
nah('explained + video', r['explained']['video'], 0.3927, 0.001)
nah('explained + topic', r['explained']['topic'], 0.4568, 0.001)
nah('R² log-log', r['scatter']['r2'], 0.2417, 0.001)
nah('video factor', r['video']['factor'], 1.7532, 0.005)
nah('video LR p', r['video']['p'], 0.01327, 0.0005)
nah('per month', r['date']['per_month'], 0.9028, 0.002)
nah('topic LR p', r['topic']['p'], 0.2131, 0.002)
nah('topic df', r['topic']['df'], 7, 0)
nah('hook LR p', r['hook']['p'], 0.4763, 0.002)
nah('length LR p', r['length']['p'], 0.5070, 0.002)
nah('length n', r['length']['n'], 59, 0)
nah('AIC + date', r['aic']['date'], 392.02, 0.05)
nah('AIC + video', r['aic']['video'], 387.88, 0.05)
nah('AIC + topic', r['aic']['topic'], 392.30, 0.05)
pt = {t['key']: t for t in r['topic']['per_topic']}
nah('DM expected', pt['DM']['expected'], 96.8, 0.2)
nah('EV pct', pt['EV']['pct'], -29, 1)
pruef('EV range below 0', pt['EV']['hi'] < 0, pt['EV'])
pruef('DM range spans 0', pt['DM']['lo'] < 0 < pt['DM']['hi'], pt['DM'])
pruef('expected per post', len(r['expected']) == 80 and all(e > 0 for e in r['expected']))
pruef('evidence words', [cm.evidence(p) for p in (0.01, 0.1, 0.3, None)] == ['clear', 'moderate', 'weak', 'weak'])

# 3 posts without impressions are left out, too few posts give no result
mehr = POSTS + [(0, 0, '2026-10-02', 0, 'DM', 's', 0, 'short')]
nah('zero impressions left out', cm.analyse(posts(mehr), KEYS)['n'], 80, 0)
pruef('too few posts', cm.analyse(posts(POSTS[:10]), KEYS) is None)

# 4 a real topic effect must be found (the test can say yes, not only no)
rng = np.random.default_rng(3)
kunst = []
for i, (a, b, c, d, e, f, g, h) in enumerate(POSTS):
    mu = np.exp(-2.6 + 0.9 * np.log(a)) * (3.0 if e == 'OV' else 1.0) * (0.35 if e == 'EV' else 1.0)
    kunst.append((a, int(rng.poisson(mu)), c, d, e, f, g, h))
rk = cm.analyse(posts(kunst), KEYS)
pruef('strong topic effect detected', rk['topic']['p'] < 0.01, rk['topic']['p'])
ptk = {t['key']: t for t in rk['topic']['per_topic']}
pruef('OV above expected', ptk['OV']['lo'] > 0, ptk['OV'])

# 4b events stay out; a hook type with a single post gets no parameter of its own
rest, ev = ct.split_events(posts())
pruef('events split off', len(ev) == 13 and len(rest) == 67 and all(p['topic'] != 'EV' for p in rest))
ohne = cm.analyse(rest, [k for k in KEYS if k != 'EV'])
nah('without events n', ohne['n'], 67, 0)
pruef('no EV circle', all(t['key'] != 'EV' for t in ohne['topic']['per_topic']))
# only one "number" hook is left without the Advent posts: it must not count as an effect
pruef('single-post hook merged', ohne['hook']['p'] > 0.2, ohne['hook']['p'])
nah('without events topic p', ohne['topic']['p'], 0.64, 0.03)
nah('short vs company factor', ohne['format']['factor'], 0.764, 0.01)
nah('short vs company p', ohne['format']['p'], 0.353, 0.01)
nah('short posts', ohne['format']['n_short'], 18, 0)
nur_company = [dict(p, format='company') for p in rest]
pruef('no format factor without short posts', cm.analyse(nur_company, KEYS)['format'] is None)

# 5 topic rules
pruef('event in first line', ct.suggest('', '4th Advent – The results are in!') == 'EV')
pruef('world day', ct.suggest('', 'World Patient Safety Day – patient safety first') == 'EV')
pruef('category Event', ct.suggest('anything about queries', '', 'Event') == 'EV')
pruef('SOP text', ct.suggest('Our SOP review and the audit trail. Procedures matter.') == 'SQ')
pruef('data management', ct.suggest('Clean data, fewer queries, a solid eCRF.') == 'DM')
pruef('hashtags ignored', ct.suggest('Nice day. #DataManagement #SOP #Oversight') == 'OT')
pruef('nothing found', ct.suggest('Hello and thank you.') == 'OT')
pruef('hook question', ct.hook_type('Settled into the new guideline yet? Let us talk') == 'q')
pruef('hook number', ct.hook_type('5 Reasons Why SOPs Matter') == 'n')
pruef('hook we', ct.hook_type('We work as if we were part of your team') == 'w')
pruef('hook statement', ct.hook_type('Clean data stays quiet.') == 's')
pruef('start list: 80 posts, known topics', len(ct.start_list()) == 80 and set(ct.start_list().values()) <= set(KEYS))
manual = {'7510724625836961793': 'DM'}
pruef('manual beats list', ct.resolve('7510724625836961793', '', '', '', manual) == ('DM', 'manual'))
pruef('list beats rules', ct.resolve('7510724625836961793', 'SOP', '', '', {}) == ('EV', 'checked'))
pruef('rules for new posts', ct.resolve('1', 'Our SOP audit', '', '', {}) == ('SQ', 'auto'))
pid = '7510247250753740800'   # SOP management video, 28.09.2026
pruef('format list: 80 posts, 21 short', len(ct.start_formats()) == 80 and list(ct.start_formats().values()).count('short') == 21)
pruef('format manual beats planner', ct.resolve_format(pid, {pid: 'short'}, {pid: 'company'}) == ('short', 'manual'))
pruef('format planner beats list', ct.resolve_format(pid, {}, {pid: 'short'}) == ('short', 'planner'))
pruef('format from list', ct.resolve_format(pid, {}, {}) == ('company', 'suggested'))
pruef('format unknown', ct.resolve_format('1', {}, {}) == ('', ''))

print(f'{ok} ok, {fehl} FEHL')
sys.exit(1 if fehl else 0)
