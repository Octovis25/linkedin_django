# LinkedIn Dashboard (Django) – Octotrial

## Setup (einmalig)

```powershell
cd linkedin_dashboard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate --run-syncdb
python manage.py createsuperuser
python manage.py runserver
```

Dann: http://127.0.0.1:8000/

## Rollen

| Rolle | Rechte |
|-------|--------|
| **Admin** (Superuser) | Alles + User anlegen/loeschen |
| **User** (Normal) | Post-Daten verwalten + eigenes Passwort |

## Features
- Post-Datum-Zuordnung (Hinzufuegen, Bearbeiten, Loeschen)
- post_id automatisch aus Link extrahiert
- Duplikat-Schutz
- Auto-Sync post_date in linkedin_posts
- User-Verwaltung (nur Admins)
- Passwort aendern (alle)
- Octotrial Design
