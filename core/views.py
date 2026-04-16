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

UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'linkedin_data')
ARCHIVE_DIR = os.path.join(settings.MEDIA_ROOT, 'linkedin_data', 'archive')
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
            messages.success(request, f'File "{uploaded_file.name}" uploaded successfully!')
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
                    stats = import_to_db(file_path, file_type)
                    if stats:
                        archive_path = os.path.join(ARCHIVE_DIR, filename)
                        shutil.move(file_path, archive_path)
                        results.append({'file': filename, 'type': file_type, 'status': 'ok', 'stats': stats if isinstance(stats, list) else []})
                        success_count += 1
                    else:
                        results.append({'file': filename, 'type': file_type, 'status': 'error', 'stats': []})
                        error_count += 1
                else:
                    results.append({'file': filename, 'type': 'Unknown', 'status': 'Type not recognized'})
                    error_count += 1
    messages.info(request, f'{success_count} imported | {error_count} failed')
    return render(request, 'core/analyze.html', {'results': results, 'success_count': success_count, 'error_count': error_count})

@login_required
def delete_file_view(request, filename):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        messages.success(request, f'File "{filename}" deleted successfully!')
    else:
        messages.error(request, f'File "{filename}" not found!')
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
            messages.error(request, 'E-Mail-Adresse ist Pflichtfeld.')
            return render(request, 'core/user_create.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Ein User mit dieser E-Mail existiert bereits.')
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
            messages.success(request, f'User "{username}" angelegt - Einladungsmail an {email} gesendet.')
        except Exception as e:
            messages.warning(request, f'User "{username}" angelegt, aber E-Mail fehlgeschlagen: {e}')

        return redirect('user_list')
    return render(request, 'core/user_create.html')

@login_required
@user_passes_test(is_staff)
def user_delete(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user == request.user:
        messages.error(request, 'Du kannst dich nicht selbst loeschen.')
        return redirect('user_list')
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'User "{username}" wurde geloescht.')
        return redirect('user_list')
    return render(request, 'core/user_confirm_delete.html', {'target_user': user})

from django.contrib.auth import logout as auth_logout

def custom_logout(request):
    auth_logout(request)
    return redirect('/login/')
