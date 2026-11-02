"""Ortrud's LinkedIn contacts (Connections.csv from LinkedIn's data archive).

LinkedIn → Settings → Data privacy → Get a copy of your data. The archive is a
.zip with many files (messages among them); only Connections.csv is read, and
of each contact only the day of connecting, the company and the job title are
kept - no names, no profile links, no e-mail addresses (Ortrud, 01.11.2026).

Field and level are read from the job title with plain word lists; a title like
"Senior Manager" says nothing about the field and lands under "Not clear from
the title".
"""
import csv
import io
import re
import zipfile
from datetime import date, datetime

from django.db import connection


class ContactsError(ValueError):
    """The file is not a LinkedIn archive / Connections.csv we can read."""


FIELDS = [
    ('Recruiting / HR', r'recruit|talent|headhunt|human resources|\bhr\b|personal'),
    ('Biostatistics / programming', r'biostat|statist|programm|\bsas\b|biometr|data scien'),
    ('Data management', r'data manag|\bcdm\b|clinical data|\bedc\b'),
    ('Clinical / quality', r'clinical|\bcra\b|trial|study|medical|regulat|pharmacovig|safety|\bqa\b|quality|gcp'),
    ('Sales / BD', r'sales|business develop|account|marketing|growth|client'),
    ('Consulting', r'consult|advisor|freelanc|berater'),
    ('IT / software', r'engineer|developer|software|\bit\b|cloud|architect'),
]
LEVELS = [
    ('Founder / C-level', r'ceo|founder|gründer|owner|inhaber|geschäftsführ|managing director|president|chief|\bcoo\b|\bcto\b|\bcfo\b|board'),
    ('Director / head', r'director|head|\bvp\b|vice president|leitung|principal'),
    ('Manager / lead', r'manager|lead|leader'),
    ('Senior / expert', r'senior|expert|specialist|consult|scientist|statistician|programmer'),
]


def field_of(title):
    t = (title or '').lower()
    if not t:
        return '(no job title)'
    return next((name for name, rx in FIELDS if re.search(rx, t)), 'Not clear from the title')


def level_of(title):
    t = (title or '').lower()
    if not t:
        return '(no job title)'
    return next((name for name, rx in LEVELS if re.search(rx, t)), 'Other')


def _date(s):
    s = (s or '').strip()
    for fmt in ('%d %b %Y', '%d %B %Y', '%d.%m.%Y', '%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def read_connections(fileobj, name=''):
    """[(date, company, position)] from a LinkedIn .zip or a Connections.csv."""
    raw = fileobj.read()
    if name.lower().endswith('.zip') or raw[:2] == b'PK':
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise ContactsError('The .zip file could not be opened.')
        member = next((n for n in z.namelist() if n.rsplit('/', 1)[-1].lower() == 'connections.csv'), None)
        if not member:
            raise ContactsError('The archive has no Connections.csv – request the larger archive (it contains the contacts).')
        raw = z.read(member)
    text = raw.decode('utf-8-sig', errors='replace')
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith('First Name')), None)
    if start is None:
        raise ContactsError('No contact list found (the header “First Name, Last Name, …” is missing).')
    out = []
    for row in csv.DictReader(io.StringIO('\n'.join(lines[start:]))):
        d = _date(row.get('Connected On'))
        if d:
            out.append((d, (row.get('Company') or '').strip()[:200], (row.get('Position') or '').strip()[:300]))
    if not out:
        raise ContactsError('The contact list is empty.')
    return out


def ensure_table():
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS oj_contacts (
            id INT AUTO_INCREMENT PRIMARY KEY, connected_on DATE,
            company VARCHAR(200), position VARCHAR(300),
            field VARCHAR(60), level VARCHAR(60), KEY idx_connected (connected_on))""")


def store(rows):
    """Replace the stored list with this one (the archive always has all contacts)."""
    ensure_table()
    with connection.cursor() as c:
        c.execute("DELETE FROM oj_contacts")
        for d, company, position in rows:
            c.execute("""INSERT INTO oj_contacts (connected_on, company, position, field, level)
                         VALUES (%s,%s,%s,%s,%s)""", [d, company, position, field_of(position), level_of(position)])


def listing():
    """[[iso date, field, level, company]] oldest first."""
    ensure_table()
    with connection.cursor() as c:
        c.execute("SELECT connected_on, field, level, company FROM oj_contacts ORDER BY connected_on, id")
        return [[d.isoformat(), f or '', l or '', co or ''] for d, f, l, co in c.fetchall()]
