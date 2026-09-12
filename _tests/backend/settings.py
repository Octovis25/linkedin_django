"""Einstellungen NUR fuer den Testlauf.

Bewusst getrennt von den echten: keine Nextcloud-Zugangsdaten, keine
Produktionsdatenbank, kein Zugriff nach draussen. Die Tests sollen auf einem
beliebigen Rechner laufen und nichts anfassen, was jemandem gehoert.
"""
import os

import pymysql
pymysql.install_as_MySQLdb()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = 'nur-fuer-tests-nicht-geheim'
DEBUG = False
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'collectives',
    'media_library',
    'planner',
    'posts_posted',
]

MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = '_tests.backend.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [os.path.join(BASE_DIR, '_tests', 'backend')],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('PRUEF_DB', 'pruef_db'),
        'USER': os.environ.get('PRUEF_DB_USER', 'pruef'),
        'PASSWORD': os.environ.get('PRUEF_DB_PASS', 'pruef'),
        'HOST': os.environ.get('PRUEF_DB_HOST', '127.0.0.1'),
        'PORT': os.environ.get('PRUEF_DB_PORT', '3306'),
        'TEST': {'CHARSET': 'utf8mb4', 'COLLATION': 'utf8mb4_unicode_ci'},
    }
}

STATIC_URL = '/static/'
USE_TZ = False
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Nextcloud ist im Test nicht erreichbar und soll es auch nicht sein. Die Tests
# setzen die Zugriffe gezielt ausser Kraft; was sie vergessen, faellt hier auf
# leere Zugangsdaten zurueck und damit auf einen sauberen Fehlerweg.
for _schluessel in ('NEXTCLOUD_URL', 'NEXTCLOUD_USER', 'NEXTCLOUD_APP_PASSWORD'):
    os.environ.pop(_schluessel, None)
