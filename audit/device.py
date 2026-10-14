"""Where a sign-in came from: browser, system and address.

Kept short on purpose - "Chrome on Windows", not the whole user-agent string,
which is mostly noise. The address is the first one in X-Forwarded-For,
because on Render every request arrives through its proxy.
"""


def client_ip(request):
    if request is None:
        return ''
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()[:45]
    return (request.META.get('REMOTE_ADDR') or '')[:45]


def browser_and_system(user_agent):
    ua = user_agent or ''
    if not ua:
        return ''
    if 'Edg/' in ua:
        browser = 'Edge'
    elif 'OPR/' in ua or 'Opera' in ua:
        browser = 'Opera'
    elif 'Firefox/' in ua:
        browser = 'Firefox'
    elif 'Chrome/' in ua or 'CriOS/' in ua:
        browser = 'Chrome'
    elif 'Safari/' in ua:
        browser = 'Safari'
    elif 'python-requests' in ua or 'curl/' in ua:
        browser = 'Script'
    else:
        browser = 'Other browser'
    if 'iPhone' in ua or 'iPad' in ua:
        system = 'iPhone/iPad'
    elif 'Android' in ua:
        system = 'Android'
    elif 'Windows' in ua:
        system = 'Windows'
    elif 'Mac OS X' in ua or 'Macintosh' in ua:
        system = 'Mac'
    elif 'Linux' in ua:
        system = 'Linux'
    else:
        system = ''
    return '%s on %s' % (browser, system) if system else browser


def describe(request):
    """{'device': 'Chrome on Windows', 'ip': '…'} - empty values left out."""
    if request is None:
        return {}
    out = {'device': browser_and_system(request.META.get('HTTP_USER_AGENT', '')),
           'ip': client_ip(request)}
    return {k: v for k, v in out.items() if v}
