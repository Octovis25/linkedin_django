import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = ["django.contrib.admin","django.contrib.auth","django.contrib.contenttypes",
    "django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles","core","posts_posted"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware","django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware","django.contrib.messages.middleware.MessageMiddleware"]
ROOT_URLCONF = "dashboard.urls"
TEMPLATES = [{"BACKEND":"django.template.backends.django.DjangoTemplates","DIRS":[],"APP_DIRS":True,
    "OPTIONS":{"context_processors":["django.template.context_processors.debug","django.template.context_processors.request",
    "django.contrib.auth.context_processors.auth","django.contrib.messages.context_processors.messages"]}}]
DATABASES = {"default":{"ENGINE":"django.db.backends.mysql",
    "HOST":os.getenv("MYSQL_HOST","wp687.webpack.hosteurope.de"),
    "PORT":os.getenv("MYSQL_PORT","3306"),
    "NAME":os.getenv("MYSQL_DATABASE","db1105422-linkedin"),
    "USER":os.getenv("MYSQL_USER","db1105422-link"),
    "PASSWORD":os.getenv("MYSQL_PASSWORD","linkedin_2026"),
    "OPTIONS":{"charset":"utf8mb4","init_command":"SET sql_mode='STRICT_TRANS_TABLES'"}}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
