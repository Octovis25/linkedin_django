"""When the posts went out: weekday × time of day, impressions per post.

For the heatmap on OJ analysis (Ortrud, 05.11.2026: "ob man da was
erkennen kann, dabei geht es um die Gesamtimpressionen"). Buffer gives the
sending time to the second (sent_at, UTC); it is counted in Berlin time.
The value of a post is its impressions so far (the newest numbers).

A field with fewer than MIN_POSTS posts gets no colour: one strong post
must not look like a good time slot. The text says how much can be read
from it - with nearly all posts in the same slot, nothing.
"""
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo('Europe/Berlin')
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
# (from hour, to hour, label) in Berlin time; the night wraps round midnight.
BLOCKS = [(6, 9, '06–09'), (9, 11, '09–11'), (11, 13, '11–13'), (13, 16, '13–16'),
          (16, 19, '16–19'), (19, 23, '19–23'), (23, 6, '23–06')]
MIN_POSTS = 3
CLEAR_RATIO = 1.3          # best median at least 30 % above the weakest -> a hint


def _block(hour):
    for i, (a, b, _) in enumerate(BLOCKS):
        if (a <= hour < b) if a < b else (hour >= a or hour < b):
            return i
    return None


def _sent(text):
    try:
        dt = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt.astimezone(BERLIN) if dt.tzinfo else None


def heatmap(posts):
    """posts: list from buffer_metrics.posts_with_latest(). Returns
    {'days', 'blocks', 'cells': {'d,b': [impressions, ...]}, 'n', 'summary'}.
    Posts without a sending time or without impressions are left out."""
    cells = {}
    for p in posts:
        imp = (p.get('m') or {}).get('impressions')
        at = _sent(p.get('sent_at') or '')
        if not imp or at is None:          # 0 = a repost or a failed post
            continue
        key = f'{at.weekday()},{_block(at.hour)}'
        cells.setdefault(key, []).append(int(round(float(imp))))
    n = sum(len(v) for v in cells.values())
    return {'days': DAYS, 'blocks': [b[2] for b in BLOCKS], 'cells': cells, 'n': n,
            'min_posts': MIN_POSTS, 'summary': summary(cells, n)}


def _name(key):
    d, b = (int(x) for x in key.split(','))
    return f'{DAYS[d]} {BLOCKS[b][2]}'


def summary(cells, n):
    """verdict (solid/hint/none/few) and plain sentences for the card."""
    if not n:
        return {'verdict': 'few', 'lines': ['No posts with numbers yet.'], 'so': ''}
    used = sorted(cells, key=lambda k: -len(cells[k]))
    top2 = sum(len(cells[k]) for k in used[:2])
    lines = []
    if len(used) == 1:
        lines.append(f'{n} posts, all on {_name(used[0])} (Berlin time).')
    else:
        lines.append(f'{n} posts. {top2} of them went out on {_name(used[0])} and {_name(used[1])} (Berlin time).')
    enough = [k for k in used if len(cells[k]) >= MIN_POSTS]
    if enough:
        lines.append('Median impressions per post: ' + ', '.join(
            f'{_name(k)} {int(statistics.median(cells[k]) + .5)} ({len(cells[k])} posts)' for k in enough[:5]) + '.')
    if len(enough) < 2:
        verdict = 'few'
        lines.append(f'Fewer than two fields have {MIN_POSTS} posts or more – too few to compare times.')
    else:
        big = [k for k in enough if len(cells[k]) >= 5] or enough
        if len(big) < 2:
            big = enough
        meds = {k: statistics.median(cells[k]) for k in big}
        best, worst = max(meds, key=meds.get), min(meds, key=meds.get)
        if meds[worst] and meds[best] / meds[worst] >= CLEAR_RATIO:
            verdict = 'hint'
            lines.append(f'{_name(best)} does better than {_name(worst)} – a hint, not proof: '
                         'topic and month changed as well.')
        else:
            verdict = 'none'
            lines.append('No clear difference between these times.')
    so = ''
    if top2 / n >= 0.7:
        so = ('The time of posting hardly changed, so it cannot explain much yet. To learn more, post at '
              'other times now and then – e.g. Tuesday or Thursday, or after 13:00.')
    elif verdict == 'few':
        so = f'About {MIN_POSTS} posts per field are needed before a pattern can show.'
    return {'verdict': verdict, 'lines': lines, 'so': so}
