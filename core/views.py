import os
import shutil
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings
from .forms import CreateUserForm, EditUserForm, ChangeOwnPasswordForm
import openpyxl

@login_required
def home(request):
    return render(request, "core/home.html")

@login_required
def upload_data(request):
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
    
    if request.method == "POST" and request.FILES.getlist('files'):
        os.makedirs(upload_dir, exist_ok=True)
        uploaded_count = 0
        for f in request.FILES.getlist('files'):
            path = os.path.join(upload_dir, f.name)
            with open(path, 'wb+') as destination:
                for chunk in f.chunks():
                    destination.write(chunk)
            uploaded_count += 1
        messages.success(request, f"✅ {uploaded_count} Datei(en) erfolgreich hochgeladen!")
        return redirect("upload_data")
    
    # Liste der hochgeladenen Dateien
    files = []
    if os.path.exists(upload_dir):
        for fname in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, fname)
            if os.path.isfile(fpath):
                files.append({
                    'name': fname,
                    'size': os.path.getsize(fpath),
                    'date': datetime.fromtimestamp(os.path.getmtime(fpath))
                })
    files.sort(key=lambda x: x['date'], reverse=True)
    
    return render(request, "core/upload.html", {"files": files})

def analyze_file_type(filepath):
    """Analysiert Excel-Datei und bestimmt den Typ anhand der Spalten"""
    try:
        wb = openpyxl.load_workbook(filepath, read_only=True)
        sheet = wb.active
        headers = [cell.value.lower() if cell.value else '' for cell in sheet[1]]
        wb.close()
        
        # Competitor-Datei?
        if 'competitor_name' in headers or 'competitor' in headers:
            return 'competitors'
        
        # Followers-Datei?
        if 'followers_total' in headers or 'followers' in headers:
            return 'followers'
        
        # Visitors-Datei?
        if 'page_views' in headers or 'visitors' in headers:
            return 'visitors'
        
        # Content/Posts-Datei?
        if 'post_id' in headers or 'impressions' in headers or 'post_title' in headers:
            return 'content'
        
        return 'unknown'
    except Exception as e:
        return f'error: {str(e)}'

@login_required
def import_run(request):
    log = []
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
    
    if request.method == "POST":
        if not os.path.exists(upload_dir):
            messages.warning(request, "Keine Dateien zum Importieren vorhanden.")
            return redirect("import_run")
        
        files = [f for f in os.listdir(upload_dir) if os.path.isfile(os.path.join(upload_dir, f))]
        
        if not files:
            messages.warning(request, "Upload-Ordner ist leer.")
            return redirect("import_run")
        
        log.append(f"📋 {len(files)} Datei(en) gefunden in uploads/")
        log.append("")
        
        processed = 0
        errors = 0
        
        for fname in files:
            fpath = os.path.join(upload_dir, fname)
            log.append(f"🔍 Analysiere: {fname}")
            
            # Datei-Typ bestimmen
            file_type = analyze_file_type(fpath)
            
            if file_type == 'unknown':
                log.append(f"   ⚠️  Typ konnte nicht bestimmt werden (Spalten passen zu keinem bekannten Format)")
                errors += 1
                continue
            elif file_type.startswith('error'):
                log.append(f"   ❌ Fehler beim Lesen: {file_type}")
                errors += 1
                continue
            
            # Ziel-Ordner
            target_dir = os.path.join(settings.MEDIA_ROOT, 'linkedin_data', file_type)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, fname)
            
            # Verschieben
            try:
                shutil.move(fpath, target_path)
                log.append(f"   ✅ Typ: {file_type} → verschoben nach linkedin_data/{file_type}/")
                log.append(f"   📊 Import in Datenbank... (TODO: Import-Skript aufrufen)")
                processed += 1
            except Exception as e:
                log.append(f"   ❌ Fehler beim Verschieben: {str(e)}")
                errors += 1
            
            log.append("")
        
        log.append("=" * 60)
        log.append(f"✅ Erfolgreich verarbeitet: {processed}")
        if errors > 0:
            log.append(f"❌ Fehler: {errors}")
        
        messages.success(request, f"Import abgeschlossen: {processed} Datei(en) verarbeitet, {errors} Fehler")
    
    return render(request, "core/import_run.html", {"log": log})

@login_required
def user_list(request):
    if not request.user.is_superuser:
        messages.error(request, "Nur Admins koennen User verwalten.")
        return redirect("home")
    users = User.objects.all().order_by("username")
    return render(request, "core/user_list.html", {"users": users})

@login_required
def user_create(request):
    if not request.user.is_superuser:
        messages.error(request, "Keine Berechtigung.")
        return redirect("home")
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.is_superuser = form.cleaned_data.get("is_superuser", False)
            user.is_staff = user.is_superuser
            user.save()
            messages.success(request, f"User {user.username} angelegt!")
            return redirect("user_list")
    else:
        form = CreateUserForm()
    return render(request, "core/user_form.html", {"form": form, "title": "Neuen User anlegen"})

@login_required
def user_edit(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Keine Berechtigung.")
        return redirect("home")
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = EditUserForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_superuser = form.cleaned_data.get("is_superuser", False)
            user.is_staff = user.is_superuser
            pw = form.cleaned_data.get("new_password")
            if pw:
                user.set_password(pw)
            user.save()
            messages.success(request, f"User {user.username} aktualisiert!")
            return redirect("user_list")
    else:
        form = EditUserForm(instance=user, initial={"is_superuser": user.is_superuser})
    return render(request, "core/user_form.html", {"form": form, "title": f"User bearbeiten: {user.username}", "edit_user": user})

@login_required
def user_delete(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Keine Berechtigung.")
        return redirect("home")
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "Du kannst dich nicht selbst loeschen!")
        return redirect("user_list")
    if request.method == "POST":
        username = user.username
        user.delete()
        messages.success(request, f"User {username} geloescht.")
        return redirect("user_list")
    return render(request, "core/user_confirm_delete.html", {"del_user": user})

@login_required
def change_password(request):
    if request.method == "POST":
        form = ChangeOwnPasswordForm(request.POST)
        if form.is_valid():
            if not request.user.check_password(form.cleaned_data["current_password"]):
                messages.error(request, "Aktuelles Passwort ist falsch!")
            else:
                request.user.set_password(form.cleaned_data["new_password"])
                request.user.save()
                messages.success(request, "Passwort geaendert! Bitte neu einloggen.")
                return redirect("login")
    else:
        form = ChangeOwnPasswordForm()
    return render(request, "core/change_password.html", {"form": form})
