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
    """The start page is Create Posts (07.11.2026). The old "All Posts" list
    is gone: its numbers are under Statistics → Timeline, and the one status
    that mattered, "Event", is set there."""
    if not request.user.is_authenticated:
        return redirect("/login/")
    return redirect("/planner/")

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
                        try:
                            shutil.move(file_path, archive_path)
                        except Exception as mv_err:
                            print(f"Move error: {mv_err}")
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
def upload_import_view(request):
    import shutil
    files = []
    results = []
    
    if os.path.exists(UPLOAD_DIR):
        for filename in sorted(os.listdir(UPLOAD_DIR)):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path) and not filename.startswith('.'):
                file_size = os.path.getsize(file_path)
                file_type = analyze_file(file_path)
                files.append({
                    'name': filename,
                    'size': f"{file_size / 1024:.1f} KB",
                    'type': file_type or 'Unknown',
                })

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'upload':
            uploaded_file = request.FILES.get('file')
            if uploaded_file:
                upload_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
                if os.path.exists(upload_path):
                    messages.warning(request, f'File "{uploaded_file.name}" is already waiting to be imported!')
                    return redirect('upload_import')
                with open(upload_path, 'wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                messages.success(request, f'File "{uploaded_file.name}" uploaded successfully!')
                return redirect('upload_import')
        
        elif action == 'import':
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
                                # The file can already be gone: two import
                                # clicks race each other and the first move
                                # wins. That is not a failure - the import
                                # itself went through. Crashing here threw a
                                # FileNotFoundError over a finished import.
                                os.makedirs(ARCHIVE_DIR, exist_ok=True)
                                try:
                                    shutil.move(file_path, archive_path)
                                except (FileNotFoundError, shutil.Error) as mv_err:
                                    print(f"Move skipped for {filename}: {mv_err}")
                                results.append({
                                    'file': filename,
                                    'type': file_type,
                                    'status': 'ok',
                                    'stats': stats if isinstance(stats, list) else []
                                })
                                success_count += 1
                            else:
                                results.append({'file': filename, 'type': file_type, 'status': 'error', 'stats': []})
                                error_count += 1
                        else:
                            results.append({'file': filename, 'type': 'Unknown', 'status': 'unrecognized', 'stats': []})
                            error_count += 1

            # AUTOMATISCH nach dem Import: erst Buffer-Posts frisch holen,
            # dann fehlende Post-Bilder/Daten aus Buffer befuellen.
            if success_count > 0:
                try:
                    from django.core.management import call_command
                    call_command('fetch_buffer_posts')
                except Exception as _e:
                    print('Auto-fetch_buffer_posts (Upload) fehlgeschlagen:', _e)
                try:
                    from posts_posted.views import fill_missing_post_images
                    filled, checked, img_err, dates_filled = fill_missing_post_images()
                    if filled:
                        messages.success(request, f'{filled} missing post image(s) auto-filled from Buffer.')
                    if dates_filled:
                        messages.success(request, f'{dates_filled} missing post date(s) auto-filled from Buffer.')
                except Exception as _e:
                    print('Auto-Bild/Datum-Befuellen fehlgeschlagen:', _e)

            # Dateiliste nach Import aktualisieren
            files = []
            if os.path.exists(UPLOAD_DIR):
                for filename in sorted(os.listdir(UPLOAD_DIR)):
                    file_path = os.path.join(UPLOAD_DIR, filename)
                    if os.path.isfile(file_path) and not filename.startswith('.'):
                        file_size = os.path.getsize(file_path)
                        file_type = analyze_file(file_path)
                        files.append({
                            'name': filename,
                            'size': f"{file_size / 1024:.1f} KB",
                            'type': file_type or 'Unknown',
                        })

    return render(request, 'core/upload_import.html', {
        'files': files,
        'results': results,
    })

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
            messages.error(request, 'Email address is required.')
            return render(request, 'core/user_create.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'A user with this email already exists.')
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

        # Link fuer die E-Mail: auf Render liefert LIVE_URL (=RENDER_EXTERNAL_URL)
        # automatisch die Live-Adresse; lokal faellt es auf DASHBOARD_URL zurueck.
        dashboard_url = (getattr(settings, 'LIVE_URL', '')
                         or getattr(settings, 'DASHBOARD_URL', '')
                         or 'http://localhost:8000').rstrip('/')
        subject = 'Your access to the LinkedIn Dashboard'
        body = f"""Hi {first_name or username},

you have been invited to the Octotrial LinkedIn Dashboard.

Your login details:
  URL:       {dashboard_url}
  Username:  {username}
  Password:  {password}

Please change your password after your first login at:
{dashboard_url}/change-password/

Best regards
Your Octotrial team
"""
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
            messages.success(request, f'User "{username}" created – invitation email sent to {email}.')
        except Exception as e:
            messages.warning(request, f'User "{username}" created, but email failed: {e}')

        return redirect('user_list')
    return render(request, 'core/user_create.html')

@login_required
@user_passes_test(is_staff)
def user_delete(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user == request.user:
        messages.error(request, 'You cannot delete yourself.')
        return redirect('user_list')
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'User "{username}" has been deleted.')
        return redirect('user_list')
    return render(request, 'core/user_confirm_delete.html', {'target_user': user})

@login_required
@user_passes_test(is_staff)
def user_toggle_active(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user == request.user:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('user_list')
    if request.method == 'POST':
        user.is_active = not user.is_active
        user.save()
        status = 'activated' if user.is_active else 'deactivated'
        messages.success(request, f'User "{user.username}" was {status}.')
    return redirect('user_list')


from django.contrib.auth import logout as auth_logout

def custom_logout(request):
    auth_logout(request)
    return redirect('/login/')


@login_required
def api_post_category(request):
    from django.http import JsonResponse
    from django.db import connection
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        post_id = data.get('post_id')
        category = data.get('category')
        with connection.cursor() as c:
            c.execute("UPDATE linkedin_posts_posted SET category=%s WHERE post_id=%s", [category, post_id])
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_post_comment(request):
    from django.http import JsonResponse
    from django.db import connection
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        post_id = data.get('post_id')
        comment = data.get('comment')
        with connection.cursor() as c:
            c.execute("UPDATE linkedin_posts_posted SET comment=%s WHERE post_id=%s", [comment, post_id])
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


@login_required
def api_categories(request):
    from django.http import JsonResponse
    from django.db import connection
    if request.method == 'GET':
        with connection.cursor() as c:
            c.execute("SELECT id, name, color FROM linkedin_post_categories ORDER BY name")
            cats = [{'id': r[0], 'name': r[1], 'color': r[2]} for r in c.fetchall()]
        return JsonResponse({'categories': cats})
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        action = data.get('action')
        with connection.cursor() as c:
            if action == 'add':
                c.execute("INSERT INTO linkedin_post_categories (name, color) VALUES (%s, %s)",
                         [data.get('name'), data.get('color', 'gray')])
            elif action == 'delete':
                c.execute("DELETE FROM linkedin_post_categories WHERE id=%s", [data.get('id')])
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)
