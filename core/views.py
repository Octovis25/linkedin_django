import os
import shutil
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from .forms import UploadFileForm
from .utils import analyze_file, import_to_db

UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'uploads')
ARCHIVE_DIR = os.path.join(settings.MEDIA_ROOT, 'uploads', 'archive')

# Create folders if not exists
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

@login_required
def upload_view(request):
    if request.method == 'POST':
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']
            file_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
            
            # Save file
            with open(file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            
            messages.success(request, f'✅ File "{uploaded_file.name}" uploaded successfully!')
            return redirect('upload')
    else:
        form = UploadFileForm()
    
    # List ALL files in uploads/ folder (exclude archive subfolder)
    files = []
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path):  # Only files, not folders
                file_size = os.path.getsize(file_path)
                files.append({
                    'name': filename,
                    'size': f"{file_size / 1024:.1f} KB",
                    'path': file_path
                })
    
    return render(request, 'core/upload.html', {
        'form': form,
        'files': files
    })

@login_required
def analyze_view(request):
    """Analyze uploaded files and import to database"""
    results = []
    success_count = 0
    error_count = 0
    
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path) and not filename.startswith('.'):
                # Analyze file
                file_type = analyze_file(file_path)
                
                if file_type:
                    # Import to database
                    success = import_to_db(file_path, file_type)
                    
                    if success:
                        # Move to archive
                        archive_path = os.path.join(ARCHIVE_DIR, filename)
                        shutil.move(file_path, archive_path)
                        results.append({
                            'file': filename,
                            'type': file_type,
                            'status': '✅ Imported & archived'
                        })
                        success_count += 1
                    else:
                        results.append({
                            'file': filename,
                            'type': file_type,
                            'status': '❌ Import failed - kept in uploads/'
                        })
                        error_count += 1
                else:
                    results.append({
                        'file': filename,
                        'type': 'Unknown',
                        'status': '⚠️ Type not recognized - kept in uploads/'
                    })
                    error_count += 1
    
    messages.info(request, f'✅ {success_count} imported | ❌ {error_count} failed')
    
    return render(request, 'core/analyze.html', {
        'results': results,
        'success_count': success_count,
        'error_count': error_count
    })

@login_required
def delete_file_view(request, filename):
    """Delete a file from uploads/ folder"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if os.path.exists(file_path):
        os.remove(file_path)
        messages.success(request, f'🗑️ File "{filename}" deleted successfully!')
    else:
        messages.error(request, f'❌ File "{filename}" not found!')
    
    return redirect('upload')

def home_view(request):
    return render(request, 'core/home.html')


# ─── User-Verwaltung ───────────────────────────────────────────────────────────

from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm, UserChangeForm
from django.http import HttpResponseForbidden

@login_required
def user_list(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Kein Zugriff.")
    users = User.objects.all().order_by('username')
    return render(request, 'core/user_list.html', {'users': users})

@login_required
def user_add(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Kein Zugriff.")
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Benutzer erfolgreich erstellt.')
        return redirect('user_list')
    return render(request, 'core/user_form.html', {'form': form, 'title': 'Benutzer hinzufügen'})

@login_required
def user_edit(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Kein Zugriff.")
    user = User.objects.get(pk=pk)
    form = UserChangeForm(request.POST or None, instance=user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Benutzer gespeichert.')
        return redirect('user_list')
    return render(request, 'core/user_form.html', {'form': form, 'title': 'Benutzer bearbeiten'})

@login_required
def user_delete(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Kein Zugriff.")
    user = User.objects.get(pk=pk)
    if request.method == 'POST':
        user.delete()
        messages.success(request, 'Benutzer gelöscht.')
        return redirect('user_list')
    return render(request, 'core/user_confirm_delete.html', {'user_obj': user})

@login_required
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Passwort erfolgreich geändert.')
        return redirect('home')
    return render(request, 'core/change_password.html', {'form': form})
