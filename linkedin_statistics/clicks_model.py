"""Count models for the Clicks tab - plain numpy, no scipy or statsmodels.

The question the tab answers: does a post get more clicks because more people
saw it, or because its content did unusually well for that reach?

So every comparison starts from a model that already knows the reach
(log impressions) and the posting date, and asks what one more factor adds:
video, topic, hook type, post length.

Why a negative-binomial model
-----------------------------
Clicks are small counts (median about 3) that scatter far more than a Poisson
model allows (dispersion about 3-4 here). A Poisson model would call almost
every factor "significant". The negative binomial (NB2, variance
mu + alpha * mu^2) carries that extra scatter in alpha, which is estimated
from the data by profiling the likelihood.

The "explained" bars use the Poisson deviance, because it is the familiar
share-of-variation number and does not move with alpha. The tests (p values,
AIC) all come from the negative binomial.

Checked against statsmodels 0.15 on the 80 posts of 03.10.2026, see
``_tests/clicks_model_test.py``.
"""
import math

import numpy as np

# Below this many posts the models say nothing useful.
MIN_POSTS = 15
# A topic or hook type needs this many posts for its own parameter.
MIN_GROUP = 3


# ── distributions ────────────────────────────────────────────────────────────

def chi2_sf(x, df):
    """P(X > x) for a chi-square distribution with df degrees of freedom."""
    if x <= 0:
        return 1.0
    return _gamma_q(df / 2.0, x / 2.0)


def _gamma_q(a, x):
    """Regularised upper incomplete gamma function Q(a, x)."""
    if x < a + 1.0:
        # series for P, then Q = 1 - P
        term = total = 1.0 / a
        n = a
        for _ in range(500):
            n += 1.0
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        return max(0.0, 1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a)))
    # continued fraction (Lentz)
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        step = d * c
        h *= step
        if abs(step - 1.0) < 1e-14:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def normal_p(z):
    """Two-sided p value of a z statistic."""
    return math.erfc(abs(z) / math.sqrt(2.0))


_lgamma = np.frompyfunc(math.lgamma, 1, 1)


def _lg(v):
    return _lgamma(v).astype(float)


# ── fitting ──────────────────────────────────────────────────────────────────

def _irls(y, X, alpha, iters=100):
    """Coefficients of a log-link GLM; alpha = 0 is Poisson, > 0 is NB2."""
    eta = np.log(y + 0.5)
    beta = np.linalg.lstsq(X, eta, rcond=None)[0]
    for _ in range(iters):
        eta = np.clip(X @ beta, -30, 30)
        mu = np.exp(eta)
        w = mu / (1.0 + alpha * mu)
        z = eta + (y - mu) / mu
        XtW = X.T * w
        new = np.linalg.solve(XtW @ X, XtW @ z)
        if np.max(np.abs(new - beta)) < 1e-10:
            beta = new
            break
        beta = new
    mu = np.exp(np.clip(X @ beta, -30, 30))
    return beta, mu


def _nb_loglik(y, mu, alpha):
    r = 1.0 / alpha
    return float(np.sum(_lg(y + r) - _lg(np.full_like(y, r)) - _lg(y + 1.0)
                        + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu))))


def nb_fit(y, X):
    """Negative-binomial fit with alpha estimated by profile likelihood.

    Returns dict: beta, se, mu, alpha, llf, aic (k counts alpha as well).
    """
    y = np.asarray(y, float)
    X = np.asarray(X, float)

    def neg(log_a):
        a = math.exp(log_a)
        _, mu = _irls(y, X, a)
        return -_nb_loglik(y, mu, a)

    # golden-section search on log(alpha)
    lo, hi = math.log(1e-4), math.log(20.0)
    g = (math.sqrt(5) - 1) / 2
    c, d = hi - g * (hi - lo), lo + g * (hi - lo)
    fc, fd = neg(c), neg(d)
    for _ in range(80):
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - g * (hi - lo)
            fc = neg(c)
        else:
            lo, c, fc = c, d, fd
            d = lo + g * (hi - lo)
            fd = neg(d)
        if hi - lo < 1e-7:
            break
    alpha = math.exp((lo + hi) / 2)
    beta, mu = _irls(y, X, alpha)
    w = mu / (1.0 + alpha * mu)
    cov = np.linalg.inv((X.T * w) @ X)
    llf = _nb_loglik(y, mu, alpha)
    k = X.shape[1] + 1
    return {'beta': beta, 'se': np.sqrt(np.diag(cov)), 'mu': mu, 'alpha': alpha,
            'llf': llf, 'aic': 2 * k - 2 * llf, 'k': k}


def poisson_deviance(y, X):
    y = np.asarray(y, float)
    _, mu = _irls(y, np.asarray(X, float), 0.0)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return float(2 * np.sum(t - (y - mu)))


def lr_test(small, big):
    """Likelihood-ratio test of a nested pair of nb_fit results."""
    stat = max(0.0, 2 * (big['llf'] - small['llf']))
    df = big['k'] - small['k']
    return {'stat': stat, 'df': df, 'p': chi2_sf(stat, df) if df > 0 else 1.0}


def evidence(p):
    """Words for a p value - the page never shows a bare 'significant'."""
    if p is None:
        return 'weak'
    if p < 0.05:
        return 'clear'
    if p < 0.15:
        return 'moderate'
    return 'weak'


# ── the analysis for the tab ─────────────────────────────────────────────────

def analyse(posts, topic_keys, seed=7, n_boot=2000):
    """posts: list of dicts with imp, clicks, date (datetime.date), video
    (bool), topic (key), hook (key), length (int or None = no full text).

    Posts without impressions are left out (no reach, nothing to explain).
    Returns None when there are too few posts.
    """
    P = [p for p in posts if (p.get('imp') or 0) > 0]
    n = len(P)
    if n < MIN_POSTS:
        return None
    y = np.array([p['clicks'] for p in P], float)
    imp = np.array([p['imp'] for p in P], float)
    t0 = min(p['date'] for p in P)
    month = np.array([(p['date'] - t0).days / 30.4 for p in P])
    vid = np.array([1.0 if p['video'] else 0.0 for p in P])
    one = np.ones(n)
    lim = np.log(imp)

    def dummies(values, keys):
        # A group needs MIN_GROUP posts to get its own parameter. A single
        # "5 Reasons ..." post would otherwise make "numbers in the hook" look
        # like a strong effect - it is one post, not a pattern. Small groups
        # count with the reference group.
        present = [k for k in keys if values.count(k) >= MIN_GROUP]
        if len(present) < 2:
            return np.zeros((n, 0)), present
        ref = max(present, key=values.count)   # largest group is the reference
        cols = [k for k in present if k != ref]
        return np.array([[1.0 if v == k else 0.0 for k in cols] for v in values]), present

    topics = [p['topic'] for p in P]
    hooks = [p['hook'] for p in P]
    D_topic, topics_present = dummies(topics, topic_keys)
    D_hook, _ = dummies(hooks, ['s', 'q', 'n', 'w'])

    X_imp = np.c_[one, lim]
    X_date = np.c_[one, lim, month]
    X_vid = np.c_[one, lim, month, vid]
    X_top = np.c_[X_vid, D_topic]
    X_hook = np.c_[X_vid, D_hook]

    m_date, m_vid = nb_fit(y, X_date), nb_fit(y, X_vid)
    m_top = nb_fit(y, X_top) if D_topic.shape[1] else None
    m_hook = nb_fit(y, X_hook) if D_hook.shape[1] else None

    null_dev = poisson_deviance(y, one[:, None])

    def share(X):
        return 1 - poisson_deviance(y, X) / null_dev if null_dev > 0 else 0.0

    explained = {'imp': share(X_imp), 'date': share(X_date), 'video': share(X_vid),
                 'topic': share(X_top) if m_top else share(X_vid)}

    lr_video = lr_test(m_date, m_vid)
    lr_topic = lr_test(m_vid, m_top) if m_top else None
    lr_hook = lr_test(m_vid, m_hook) if m_hook else None

    # length: only posts whose full text is known
    idx = [i for i, p in enumerate(P) if p.get('length')]
    lr_len = None
    if len(idx) >= MIN_POSTS:
        ln = np.log(np.array([P[i]['length'] for i in idx], float))
        a = nb_fit(y[idx], X_vid[idx])
        b = nb_fit(y[idx], np.c_[X_vid[idx], ln])
        lr_len = lr_test(a, b)
        lr_len['n'] = len(idx)

    # reach on its own, log-log (clicks + 1), for the scatter line and R²
    ly = np.log(y + 1.0)
    slope, intercept = np.polyfit(lim, ly, 1)
    r2 = float(np.corrcoef(lim, ly)[0, 1] ** 2)

    b, se = m_vid['beta'], m_vid['se']
    expected = m_vid['mu']

    # topic: observed vs expected, 95 % range by bootstrapping the posts
    rng = np.random.default_rng(seed)
    per_topic = []
    for k in topic_keys:
        ii = np.array([i for i, t in enumerate(topics) if t == k])
        if not len(ii):
            continue
        O, E = float(y[ii].sum()), float(expected[ii].sum())
        draws = rng.choice(ii, size=(n_boot, len(ii)))
        ratios = y[draws].sum(axis=1) / expected[draws].sum(axis=1)
        lo, hi = np.percentile(ratios, [2.5, 97.5])
        per_topic.append({'key': k, 'n': int(len(ii)), 'clicks': int(O), 'expected': round(E, 1),
                          'pct': round((O / E - 1) * 100) if E else 0,
                          'lo': round((lo - 1) * 100), 'hi': round((hi - 1) * 100)})

    return {
        'n': n, 'clicks': int(y.sum()), 'impressions': int(imp.sum()),
        'first': t0, 'last': max(p['date'] for p in P),
        'alpha': m_vid['alpha'],
        'scatter': {'slope': float(slope), 'intercept': float(intercept), 'r2': r2,
                    'double': float(2 ** b[1])},
        'explained': explained,
        'date': {'per_month': float(math.exp(b[2])), 'p': normal_p(b[2] / se[2])},
        'video': {'factor': float(math.exp(b[3])),
                  'lo': float(math.exp(b[3] - 1.96 * se[3])), 'hi': float(math.exp(b[3] + 1.96 * se[3])),
                  'p': lr_video['p'], 'n': int(vid.sum())},
        'aic': {'date': m_date['aic'], 'video': m_vid['aic'], 'topic': m_top['aic'] if m_top else None},
        'topic': {'p': lr_topic['p'] if lr_topic else None, 'df': lr_topic['df'] if lr_topic else 0,
                  'groups': len(topics_present), 'per_topic': per_topic},
        'hook': {'p': lr_hook['p'] if lr_hook else None},
        'length': lr_len,
        'expected': [float(e) for e in expected],
        'posts': P,
    }
