#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# LinkedIn Dashboard – User-Einladung einrichten
# Einfach im Projektordner (neben manage.py) ausführen:
#   bash deploy_user_invite.sh
# ─────────────────────────────────────────────────────────────────

echo "🚀 Starte Deployment..."

# ── 1. settings.py ───────────────────────────────────────────────
cat > dashboard/settings.py << 'EOF'
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = ["django.contrib.admin","django.contrib.auth","django.contrib.contenttypes",
    "django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles","core","posts_posted",
    'collectives',
]
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

# ── E-MAIL ────────────────────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.hosteurope.de")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "LinkedIn Dashboard <noreply@octotrial.com>")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8000")
EOF
echo "✅ dashboard/settings.py geschrieben"

# ── 2. urls.py ───────────────────────────────────────────────────
cat > dashboard/urls.py << 'EOF'
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", core_views.home_view, name='home'),
    path("data/upload/", core_views.upload_view, name='upload'),
    path("data/import/", core_views.analyze_view, name='analyze'),
    path("data/delete/<str:filename>/", core_views.delete_file_view, name='delete_file'),
    path("data/posts/", include("posts_posted.urls")),
    path("collectives/", include("collectives.urls")),
    path("users/", core_views.user_list, name='user_list'),
    path("users/new/", core_views.user_create, name='user_create'),
    path("users/<int:user_id>/delete/", core_views.user_delete, name='user_delete'),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
    path("change-password/", auth_views.PasswordChangeView.as_view(
        template_name="core/change_password.html", success_url="/"), name="change_password"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
EOF
echo "✅ dashboard/urls.py geschrieben"

# ── 3. views.py ──────────────────────────────────────────────────
cat > core/views.py << 'EOF'
import os
import shutil
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from .forms import UploadFileForm
from .utils import analyze_file, import_to_db

UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'uploads')
ARCHIVE_DIR = os.path.join(settings.MEDIA_ROOT, 'uploads', 'archive')
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

def is_staff(user):
    return user.is_staff

def home_view(request):
    return render(request, 'core/home.html')

@login_required
def upload_view(request):
    if request.method == 'POST':
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']
            file_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
            with open(file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            messages.success(request, f'✅ File "{uploaded_file.name}" uploaded successfully!')
            return redirect('upload')
    else:
        form = UploadFileForm()
    files = []
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                files.append({'name': filename, 'size': f"{file_size / 1024:.1f} KB", 'path': file_path})
    return render(request, 'core/upload.html', {'form': form, 'files': files})

@login_required
def analyze_view(request):
    results = []
    success_count = 0
    error_count = 0
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path) and not filename.startswith('.'):
                file_type = analyze_file(file_path)
                if file_type:
                    success = import_to_db(file_path, file_type)
                    if success:
                        archive_path = os.path.join(ARCHIVE_DIR, filename)
                        shutil.move(file_path, archive_path)
                        results.append({'file': filename, 'type': file_type, 'status': '✅ Imported & archived'})
                        success_count += 1
                    else:
                        results.append({'file': filename, 'type': file_type, 'status': '❌ Import failed'})
                        error_count += 1
                else:
                    results.append({'file': filename, 'type': 'Unknown', 'status': '⚠️ Type not recognized'})
                    error_count += 1
    messages.info(request, f'✅ {success_count} imported | ❌ {error_count} failed')
    return render(request, 'core/analyze.html', {'results': results, 'success_count': success_count, 'error_count': error_count})

@login_required
def delete_file_view(request, filename):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        messages.success(request, f'🗑️ File "{filename}" deleted successfully!')
    else:
        messages.error(request, f'❌ File "{filename}" not found!')
    return redirect('upload')

@login_required
@user_passes_test(is_staff)
def user_list(request):
    users = User.objects.all().order_by('username')
    return render(request, 'core/user_list.html', {'users': users})

@login_required
@user_passes_test(is_staff)
def user_create(request):
    if request.method == 'POST':
        first_name  = request.POST.get('first_name', '').strip()
        last_name   = request.POST.get('last_name', '').strip()
        email       = request.POST.get('email', '').strip()
        is_staff_cb = request.POST.get('is_staff') == 'on'

        if not email:
            messages.error(request, '❌ E-Mail-Adresse ist Pflichtfeld.')
            return render(request, 'core/user_create.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, '❌ Ein User mit dieser E-Mail existiert bereits.')
            return render(request, 'core/user_create.html')

        username = email.split('@')[0]
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        password = get_random_string(12)
        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=first_name, last_name=last_name, is_staff=is_staff_cb,
        )

        dashboard_url = getattr(settings, 'DASHBOARD_URL', 'http://localhost:8000')
        subject = 'Dein Zugang zum LinkedIn Dashboard'
        body = f"""Hallo {first_name or username},

du wurdest zum LinkedIn Dashboard von Octotrial eingeladen.

Deine Zugangsdaten:
  URL:       {dashboard_url}
  Username:  {username}
  Passwort:  {password}

Bitte aendere dein Passwort nach dem ersten Login unter:
{dashboard_url}/change-password/

Viele Gruesse
Dein Octotrial-Team
"""
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
            messages.success(request, f'✅ User "{username}" angelegt – Einladungsmail an {email} gesendet.')
        except Exception as e:
            messages.warning(request, f'✅ User "{username}" angelegt, aber E-Mail fehlgeschlagen: {e}')

        return redirect('user_list')
    return render(request, 'core/user_create.html')

@login_required
@user_passes_test(is_staff)
def user_delete(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user == request.user:
        messages.error(request, '❌ Du kannst dich nicht selbst löschen.')
        return redirect('user_list')
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'🗑️ User "{username}" wurde gelöscht.')
        return redirect('user_list')
    return render(request, 'core/user_confirm_delete.html', {'target_user': user})
EOF
echo "✅ core/views.py geschrieben"

# ── 4. Templates ─────────────────────────────────────────────────
mkdir -p core/templates/core

cat > core/templates/core/user_list.html << 'EOF'
{% extends "core/base.html" %}
{% block title %}User-Verwaltung{% endblock %}
{% block content %}
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
  <h1>👥 User-Verwaltung</h1>
  <a href="/users/new/" class="btn btn-primary">+ Neuen User einladen</a>
</div>
<table>
  <thead>
    <tr>
      <th>Name</th><th>Username</th><th>E-Mail</th><th>Rolle</th><th>Aktiv</th><th>Aktionen</th>
    </tr>
  </thead>
  <tbody>
    {% for u in users %}
    <tr>
      <td>{{ u.get_full_name|default:"–" }}</td>
      <td>{{ u.username }}</td>
      <td>{{ u.email|default:"–" }}</td>
      <td>{% if u.is_superuser %}🔴 Superuser{% elif u.is_staff %}🟡 Staff{% else %}🟢 User{% endif %}</td>
      <td>{% if u.is_active %}✅{% else %}❌{% endif %}</td>
      <td>
        {% if u != request.user %}
        <form method="post" action="/users/{{ u.id }}/delete/" style="display:inline;"
              onsubmit="return confirm('User {{ u.username }} wirklich löschen?')">
          {% csrf_token %}
          <button type="submit" class="btn btn-danger btn-sm">Löschen</button>
        </form>
        {% else %}
        <span style="color:#aaa; font-size:0.85rem;">Du selbst</span>
        {% endif %}
      </td>
    </tr>
    {% empty %}
    <tr><td colspan="6" style="text-align:center; color:#aaa;">Keine User gefunden.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
EOF
echo "✅ core/templates/core/user_list.html geschrieben"

cat > core/templates/core/user_create.html << 'EOF'
{% extends "core/base.html" %}
{% block title %}Neuen User einladen{% endblock %}
{% block content %}
<h1>✉️ Neuen User einladen</h1>
<p style="margin-bottom:1.5rem; color:#555;">Der neue User bekommt automatisch eine E-Mail mit seinen Zugangsdaten.</p>
<div class="card" style="max-width:500px;">
  <form method="post">
    {% csrf_token %}
    <div class="form-group">
      <label>Vorname</label>
      <input type="text" name="first_name" placeholder="z.B. Anna" />
    </div>
    <div class="form-group">
      <label>Nachname</label>
      <input type="text" name="last_name" placeholder="z.B. Müller" />
    </div>
    <div class="form-group">
      <label>E-Mail-Adresse *</label>
      <input type="text" name="email" placeholder="anna.mueller@beispiel.de" required />
    </div>
    <div class="form-group" style="display:flex; align-items:center; gap:0.5rem;">
      <input type="checkbox" name="is_staff" id="is_staff" style="width:auto;" />
      <label for="is_staff" style="margin:0;">Staff-Rechte (kann andere User verwalten)</label>
    </div>
    <div style="display:flex; gap:1rem; margin-top:1.5rem;">
      <button type="submit" class="btn btn-primary">✉️ Einladen & E-Mail senden</button>
      <a href="/users/" class="btn btn-secondary">Abbrechen</a>
    </div>
  </form>
</div>
{% endblock %}
EOF
echo "✅ core/templates/core/user_create.html geschrieben"

# ── 5. base.html ─────────────────────────────────────────────────
cat > core/templates/core/base.html << 'EOF'
{% load static %}
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}LinkedIn Dashboard{% endblock %}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --octo-petrol:      #008591;
      --octo-turquoise:   #61CEBC;
      --octo-orange:      #F56E28;
      --octo-dark-petrol: #005F68;
      --octo-text:        #161616;
      --octo-white:       #FFFFFF;
      --octo-light-gray:  #F9F7F0;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Roboto', Arial, sans-serif; background-color: var(--octo-white); color: var(--octo-text); line-height: 1.4; font-size: 14px; }
    header { background-color: var(--octo-white); border-bottom: 2px solid var(--octo-petrol); padding: 0.5rem 1.5rem; }
    .header-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
    .logo { height: 40px; }
    .user-section { display: flex; gap: 1.5rem; align-items: center; font-size: 14px; }
    .user-info { color: var(--octo-dark-petrol); font-weight: 500; }
    .user-section a { color: var(--octo-petrol); text-decoration: none; font-weight: 500; transition: color 0.3s; }
    .user-section a:hover { color: var(--octo-orange); }
    nav { display: flex; gap: 0; border-bottom: 2px solid var(--octo-light-gray); }
    nav a { color: var(--octo-petrol); text-decoration: none; font-weight: 500; padding: 0.5rem 1rem; border-bottom: 3px solid transparent; transition: all 0.3s; }
    nav a:hover, nav a.active { color: var(--octo-orange); border-bottom-color: var(--octo-orange); }
    .sub-nav { display: flex; gap: 0; background: var(--octo-light-gray); padding: 0 1.5rem; }
    .sub-nav a { color: var(--octo-dark-petrol); padding: 0.4rem 1rem; font-size: 0.9rem; text-decoration: none; border-bottom: 2px solid transparent; }
    .sub-nav a:hover, .sub-nav a.active { color: var(--octo-orange); border-bottom-color: var(--octo-orange); }
    main { max-width: 1400px; margin: 1rem auto; padding: 0 1.5rem; }
    h1, h2, h3 { color: var(--octo-petrol); margin-bottom: 0.75rem; font-size: 1.3rem; }
    h2 { font-size: 1.1rem; }
    .btn { display: inline-block; padding: 0.4rem 1rem; border: none; border-radius: 6px; font-size: 0.9rem; font-weight: 500; cursor: pointer; text-decoration: none; transition: all 0.3s; }
    .btn-primary { background-color: var(--octo-petrol); color: var(--octo-white); }
    .btn-primary:hover { background-color: var(--octo-dark-petrol); }
    .btn-secondary { background-color: var(--octo-orange); color: var(--octo-white); }
    .btn-secondary:hover { background-color: #d55a1f; }
    .btn-danger { background-color: #dc3545; color: var(--octo-white); }
    .btn-danger:hover { background-color: #c82333; }
    .btn-sm { padding: 0.3rem 0.75rem; font-size: 0.85rem; }
    table { width: 100%; border-collapse: collapse; background-color: var(--octo-white); box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 6px; overflow: hidden; font-size: 0.9rem; }
    thead { background-color: var(--octo-petrol); color: var(--octo-white); }
    th, td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--octo-light-gray); }
    tr:hover { background-color: var(--octo-light-gray); }
    .form-group { margin-bottom: 1rem; }
    label { display: block; color: var(--octo-petrol); font-weight: 500; margin-bottom: 0.3rem; font-size: 0.9rem; }
    input[type="text"], input[type="url"], input[type="date"], input[type="file"], input[type="datetime-local"], input[type="password"], select { width: 100%; padding: 0.5rem; border: 2px solid var(--octo-light-gray); border-radius: 6px; font-size: 0.9rem; transition: border-color 0.3s; }
    input:focus, select:focus { outline: none; border-color: var(--octo-orange); }
    .messages { margin: 0.75rem 0; }
    .alert { padding: 0.75rem; border-radius: 6px; margin-bottom: 0.75rem; font-size: 0.9rem; }
    .alert-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .alert-error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .alert-info { background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
    .card { background-color: var(--octo-white); border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); padding: 1.25rem; margin-bottom: 1.25rem; }
    a { color: var(--octo-petrol); transition: color 0.3s; }
    a:hover { color: var(--octo-orange); }
    footer { background-color: var(--octo-light-gray); color: var(--octo-text); text-align: center; padding: 0.75rem; margin-top: 2rem; border-top: 2px solid var(--octo-petrol); font-size: 0.85rem; }
  </style>
</head>
<body>
<header>
  <div class="header-top">
    <a href="/"><img src="{% static 'images/octovis_logo--1-.png' %}" alt="Octovis Logo" class="logo" /></a>
    <div class="user-section">
      {% if user.is_authenticated %}
        {% if user.is_staff %}<a href="/users/">User-Verwaltung</a>{% endif %}
        <span class="user-info">{{ user.get_full_name|default:user.username }}</span>
        <a href="/change-password/">Passwort ändern</a>
        <a href="/logout/">Logout</a>
      {% else %}
        <a href="/login/">Login</a>
      {% endif %}
    </div>
  </div>
  <nav>
    <a href="/" {% if request.path == '/' %}class="active"{% endif %}>Dashboard</a>
    <a href="/data/posts/" {% if '/data/' in request.path %}class="active"{% endif %}>Data</a>
    <a href="/collectives/" {% if '/collectives/' in request.path %}class="active"{% endif %}>Collectives</a>
  </nav>
  {% if '/data/' in request.path %}
  <div class="sub-nav">
    <a href="/data/posts/" {% if request.path == '/data/posts/' %}class="active"{% endif %}>Posts Posted</a>
    <a href="/data/upload/" {% if request.path == '/data/upload/' %}class="active"{% endif %}>Upload Data</a>
  </div>
  {% endif %}
</header>
<main>
  {% if messages %}
  <div class="messages">
    {% for message in messages %}
    <div class="alert alert-{{ message.tags }}">{{ message }}</div>
    {% endfor %}
  </div>
  {% endif %}
  {% block content %}{% endblock %}
</main>
<footer>© 2026 Octotrial | LinkedIn Dashboard</footer>
{% block extra_js %}{% endblock %}
</body>
</html>
EOF
echo "✅ core/templates/core/base.html geschrieben"

# ── 6. .env – E-Mail ergänzen (nur wenn noch nicht vorhanden) ─────
if ! grep -q "EMAIL_HOST" .env 2>/dev/null; then
  cat >> .env << 'EOF'

# E-Mail-Konfiguration
EMAIL_HOST=smtp.hosteurope.de
EMAIL_PORT=587
EMAIL_HOST_USER=noreply@octotrial.com
EMAIL_HOST_PASSWORD=DEIN_MAIL_PASSWORT
DEFAULT_FROM_EMAIL=LinkedIn Dashboard <noreply@octotrial.com>
DASHBOARD_URL=https://deine-dashboard-url.de
EOF
  echo "✅ .env ergänzt – bitte EMAIL_HOST_PASSWORD und DASHBOARD_URL eintragen!"
else
  echo "ℹ️  .env bereits vorhanden – bitte manuell prüfen"
fi

echo ""
echo "✅ Fertig! Jetzt ausführen:"
echo "   python manage.py migrate"
echo "   python manage.py runserver"
