import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings
from .forms import CreateUserForm, EditUserForm, ChangeOwnPasswordForm

@login_required
def home(request):
    return render(request, "core/home.html")

@login_required
def upload_data(request):
    uploaded_files = []
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
    
    if request.method == "POST" and request.FILES.getlist('files'):
        os.makedirs(upload_dir, exist_ok=True)
        for f in request.FILES.getlist('files'):
            path = os.path.join(upload_dir, f.name)
            with open(path, 'wb+') as destination:
                for chunk in f.chunks():
                    destination.write(chunk)
            uploaded_files.append(f.name)
        messages.success(request, f"{len(uploaded_files)} Datei(en) hochgeladen!")
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
                    'date': os.path.getmtime(fpath)
                })
    
    return render(request, "core/upload.html", {"files": files})

@login_required
def import_run(request):
    log = []
    if request.method == "POST":
        # Hier später orchestrate_imports.py aufrufen
        log.append("Import gestartet...")
        log.append("TODO: orchestrate_imports.py integrieren")
        messages.info(request, "Import-Funktion wird noch implementiert.")
    
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
