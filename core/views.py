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
import xlrd

@login_required
def home(request):
    return render(request, "core/home.html")

@login_required
def upload_data(request):
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
    log = []
    
    # Handle file upload
    if request.method == "POST" and request.GET.get('action') == 'upload':
        os.makedirs(upload_dir, exist_ok=True)
        uploaded_count = 0
        for f in request.FILES.getlist('files'):
            path = os.path.join(upload_dir, f.name)
            with open(path, 'wb+') as destination:
                for chunk in f.chunks():
                    destination.write(chunk)
            uploaded_count += 1
        messages.success(request, f"✅ {uploaded_count} file(s) uploaded successfully!")
        return redirect("upload_data")
    
    # Handle import
    if request.method == "POST" and request.GET.get('action') == 'import':
        if not os.path.exists(upload_dir):
            messages.warning(request, "No files to import.")
            return redirect("upload_data")
        
        files = [f for f in os.listdir(upload_dir) if os.path.isfile(os.path.join(upload_dir, f))]
        
        if not files:
            messages.warning(request, "Upload folder is empty.")
            return redirect("upload_data")
        
        log.append(f"📋 {len(files)} file(s) found in uploads/")
        log.append("")
        
        processed = 0
        errors = 0
        
        for fname in files:
            fpath = os.path.join(upload_dir, fname)
            log.append(f"🔍 Analyzing: {fname}")
            
            # Determine file type
            file_type = analyze_file_type(fpath)
            
            if file_type == 'unknown':
                log.append(f"   ⚠️  Type could not be determined (columns don't match any known format)")
                errors += 1
                continue
            elif file_type.startswith('error'):
                log.append(f"   ❌ Error reading file: {file_type}")
                errors += 1
                continue
            
            # Target folder
            target_dir = os.path.join(settings.MEDIA_ROOT, 'linkedin_data', file_type)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, fname)
            
            # Move file
            try:
                shutil.move(fpath, target_path)
                log.append(f"   ✅ Type: {file_type} → moved to linkedin_data/{file_type}/")
                log.append(f"   📊 Importing to database... (TODO: call import script)")
                processed += 1
            except Exception as e:
                log.append(f"   ❌ Error moving file: {str(e)}")
                errors += 1
            
            log.append("")
        
        log.append("=" * 60)
        log.append(f"✅ Successfully processed: {processed}")
        if errors > 0:
            log.append(f"❌ Errors: {errors}")
        
        messages.success(request, f"Import completed: {processed} file(s) processed, {errors} errors")
    
    # List uploaded files
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
    
    return render(request, "core/upload.html", {"files": files, "log": log})

def analyze_file_type(filepath):
    """Analyzes Excel file and determines type based on columns"""
    try:
        # Try .xlsx first
        if filepath.endswith('.xlsx'):
            wb = openpyxl.load_workbook(filepath, read_only=True)
            sheet = wb.active
            headers = [cell.value.lower() if cell.value else '' for cell in sheet[1]]
            wb.close()
        # Try .xls (old format)
        elif filepath.endswith('.xls'):
            wb = xlrd.open_workbook(filepath)
            sheet = wb.sheet_by_index(0)
            headers = [str(cell.value).lower() if cell.value else '' for cell in sheet.row(0)]
        else:
            return 'unknown'
        
        # Competitor file?
        if 'competitor_name' in headers or 'competitor' in headers:
            return 'competitors'
        
        # Followers file?
        if 'followers_total' in headers or 'followers' in headers:
            return 'followers'
        
        # Visitors file?
        if 'page_views' in headers or 'visitors' in headers:
            return 'visitors'
        
        # Content/Posts file?
        if 'post_id' in headers or 'impressions' in headers or 'post_title' in headers:
            return 'content'
        
        return 'unknown'
    except Exception as e:
        return f'error: {str(e)}'

@login_required
def user_list(request):
    if not request.user.is_superuser:
        messages.error(request, "Only admins can manage users.")
        return redirect("home")
    users = User.objects.all().order_by("username")
    return render(request, "core/user_list.html", {"users": users})

@login_required
def user_create(request):
    if not request.user.is_superuser:
        messages.error(request, "Permission denied.")
        return redirect("home")
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.is_superuser = form.cleaned_data.get("is_superuser", False)
            user.is_staff = user.is_superuser
            user.save()
            messages.success(request, f"User {user.username} created!")
            return redirect("user_list")
    else:
        form = CreateUserForm()
    return render(request, "core/user_form.html", {"form": form, "title": "Create new user"})

@login_required
def user_edit(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Permission denied.")
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
            messages.success(request, f"User {user.username} updated!")
            return redirect("user_list")
    else:
        form = EditUserForm(instance=user, initial={"is_superuser": user.is_superuser})
    return render(request, "core/user_form.html", {"form": form, "title": f"Edit user: {user.username}", "edit_user": user})

@login_required
def user_delete(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Permission denied.")
        return redirect("home")
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot delete yourself!")
        return redirect("user_list")
    if request.method == "POST":
        username = user.username
        user.delete()
        messages.success(request, f"User {username} deleted.")
        return redirect("user_list")
    return render(request, "core/user_confirm_delete.html", {"del_user": user})

@login_required
def change_password(request):
    if request.method == "POST":
        form = ChangeOwnPasswordForm(request.POST)
        if form.is_valid():
            if not request.user.check_password(form.cleaned_data["current_password"]):
                messages.error(request, "Current password is incorrect!")
            else:
                request.user.set_password(form.cleaned_data["new_password"])
                request.user.save()
                messages.success(request, "Password changed! Please log in again.")
                return redirect("login")
    else:
        form = ChangeOwnPasswordForm()
    return render(request, "core/change_password.html", {"form": form})
