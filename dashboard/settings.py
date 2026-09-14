import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Fehler-Tracebacks in die Server-Konsole (Render-Logs) schreiben, auch bei DEBUG=False.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"v": {"format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "v"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20MB for Studio canvas images

# Sessions: lange Gültigkeit + gleitende Verlängerung bei Aktivität,
# damit man nicht ständig ausgeloggt wird (auch nach Server-Neustarts).
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30          # 30 Tage
SESSION_SAVE_EVERY_REQUEST = True               # bei jeder Anfrage verlängern
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "posts_posted",
    "collectives",
    "linkedin_statistics",
    "planner",
    "db_admin",
    "media_library",
    "assets",
    "matomo",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "dashboard.middleware.NoCacheStaticInDebug",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "dashboard.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "core.context.live_adresse",
        "media_library.context_processors.brand_colors",
    ]}
}]

# ── Database: TLS towards Host Europe ───────────────────────────────────────
# From 15 September 2026 Host Europe rejects unencrypted external MySQL
# connections. Note what the driver did BEFORE this block existed: libmysql
# defaults to ssl_mode=PREFERRED, so the connection was most likely already
# encrypted - but nothing was verified, and PREFERRED falls back to plain text
# without a word if the handshake fails. Encrypted, unverified and not
# guaranteed is not the same as compliant.
#
# VERIFY_IDENTITY checks two things: the certificate chain against the CA
# bundle, and that the certificate really belongs to the host we dialled. The
# second half is why MYSQL_HOST must be the hostname (wpXXXXXXX.server-he.de):
# a certificate carries the name, not the IP address, so an IP is rejected -
# this was measured, not assumed.
#
# No certificate of our own has to be deployed: Host Europe uses publicly
# trusted authorities, which are in the system bundle.
MYSQL_SSL_MODE = os.getenv("MYSQL_SSL_MODE", "VERIFY_IDENTITY").upper()

# Where the system keeps its CA bundle. MYSQL_SSL_CA overrides it.
CA_BUENDEL = (
    "/etc/ssl/certs/ca-certificates.crt",    # Debian/Ubuntu - and Render
    "/etc/pki/tls/certs/ca-bundle.crt",      # RHEL/Fedora
    "/etc/ssl/cert.pem",                     # Alpine, macOS
)


def _ca_pfad():
    gesetzt = os.getenv("MYSQL_SSL_CA")
    if gesetzt:
        return gesetzt
    for pfad in CA_BUENDEL:
        if os.path.exists(pfad):
            return pfad
    # Windows keeps no bundle in the file system. certifi ships one and
    # arrives with requests, so a development machine needs no
    # configuration of its own - without this, Django would refuse to
    # start there.
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


_mysql_optionen = {
    "charset": "utf8mb4",
    "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
}

if MYSQL_SSL_MODE == "DISABLED":
    # Pass it on, so the name tells the truth: without this the driver would
    # fall back to its own default PREFERRED and encrypt opportunistically -
    # "DISABLED" would then mean the opposite of what it says.
    _mysql_optionen["ssl_mode"] = "DISABLED"
else:
    _ca = _ca_pfad()
    if not _ca:
        # Deliberately loud. Carrying on without a CA would mean carrying on
        # unverified - and that is the state we are leaving behind here.
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            "No CA bundle found for the MySQL TLS connection. Looked in: %s. "
            "Set MYSQL_SSL_CA to the bundle, or MYSQL_SSL_MODE=DISABLED for a "
            "local database without certificates." % ", ".join(CA_BUENDEL))
    _mysql_optionen["ssl_mode"] = MYSQL_SSL_MODE
    _mysql_optionen["ssl"] = {"ca": _ca}

DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql",
    "HOST": os.getenv("MYSQL_HOST"),
    "PORT": os.getenv("MYSQL_PORT", "3306"),
    "NAME": os.getenv("MYSQL_DATABASE"),
    "USER": os.getenv("MYSQL_USER"),
    "PASSWORD": os.getenv("MYSQL_PASSWORD"),
    "OPTIONS": _mysql_optionen,
}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Produktion: komprimierte, gehashte Dateien via WhiteNoise.
# Entwicklung: Quelldateien direkt ausliefern, sonst erscheinen CSS/JS-Änderungen
# erst nach 'collectstatic' (das war die Ursache für "keine Änderung").
if DEBUG:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
else:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "contact@octotrial.com")

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8000")

LINKEDIN_CLIENT_ID     = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
CSRF_TRUSTED_ORIGINS = [
    "https://linkedin-django-wd7a.onrender.com",
    "https://*.onrender.com",
]

# ── Matomo (Web-Statistik) ──────────────────────────────────────────────
# Matomo laeuft als WordPress-Plugin auf octotrial.com. Der Token hat die Form
# "<wp-benutzer>:<anwendungspasswort>" und gehoert NUR in die .env bzw. auf
# Render unter Environment - niemals ins Repository.
# Basis-Adresse der WordPress-Seite. Der Client haengt /wp-json/matomo/v1/ an
# und meldet sich per Anwendungspasswort (HTTP Basic) an.
MATOMO_URL = os.getenv("MATOMO_URL", "https://octotrial.com")
MATOMO_SITE_ID = os.getenv("MATOMO_SITE_ID", "1")
MATOMO_TOKEN = os.getenv("MATOMO_TOKEN", "")
MATOMO_CACHE_SECONDS = int(os.getenv("MATOMO_CACHE_SECONDS", "900"))  # Live-Ansicht 15 min
# Adresse der Live-Instanz für den Link im Kopfbereich. Render setzt
# RENDER_EXTERNAL_URL von selbst; lokal kommt DASHBOARD_URL aus der .env.
LIVE_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("DASHBOARD_URL", "")

# Ziele für den Goals-Reiter. Sie werden aus Matomos Besuchsprotokoll
# abgeleitet - in Matomo selbst muss nichts eingerichtet werden, und die
# Auswertung gilt rückwirkend. None = die Voreinstellung aus matomo/views.py.
#   art: seite | titel | mailto | download | outlink | tiefe | dauer
# MATOMO_ZIELE = [
#     {"name": "Contact page reached", "art": "seite", "muster": "/kontakt",
#      "beschreibung": "visited a page whose address contains /kontakt"},
# ]
MATOMO_ZIELE = None

MATOMO_SPRACHE = "en"   # Sprache der Spaltentitel, die Matomo mitliefert
MATOMO_TIMEOUT = 30
