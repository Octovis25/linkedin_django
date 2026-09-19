from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from core import views as core_views


class RememberLoginView(auth_views.LoginView):
    """Login mit „Angemeldet bleiben": an = 30 Tage, aus = Logout beim Browser-Schließen."""
    template_name = "core/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.POST.get('remember'):
            self.request.session.set_expiry(60 * 60 * 24 * 30)   # 30 Tage
        else:
            self.request.session.set_expiry(0)                    # bis Browser zu
        return response

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", core_views.home_view, name='home'),
    path("data/upload/", core_views.upload_import_view, name='upload_import'),
    path("data/upload-old/", core_views.upload_view, name='upload'),
    path("data/import/", core_views.analyze_view, name='analyze'),
    path("data/delete/<str:filename>/", core_views.delete_file_view, name='delete_file'),
    path("data/posts/", include("posts_posted.urls")),
    path("collectives/", include("collectives.urls")),
    path("planner/", include("planner.urls")),
    path("statistics/", include("linkedin_statistics.stat_urls")),  # Statistics module
    path("webstats/", include("matomo.urls", namespace="matomo")),  # Matomo Web-Statistik
    path("users/", core_views.user_list, name='user_list'),
    path("users/new/", core_views.user_create, name='user_create'),
    path("users/<int:user_id>/delete/", core_views.user_delete, name='user_delete'),
    path("users/<int:user_id>/toggle-active/", core_views.user_toggle_active, name='user_toggle_active'),
    path("login/", RememberLoginView.as_view(), name="login"),
    path("logout/", core_views.custom_logout, name="logout"),
    path("api/post-category/", core_views.api_post_category, name='api_post_category'),
    path("api/post-comment/", core_views.api_post_comment, name='api_post_comment'),
    path("api/categories/", core_views.api_categories, name='api_categories'),
    path("library/", include("media_library.urls")),
    path("assets/", include("assets.urls")),
    # Claude API (nur Bilder + Texte, API-Key geschützt)
    path("api/claude/", include("media_library.claude_urls")),
    path("db-admin/", include("db_admin.urls")),
    path("change-password/", auth_views.PasswordChangeView.as_view(
        template_name="core/change_password.html", success_url="/"), name="change_password"),

    # Forgotten password: Django's own four-step flow, with our own pages. The
    # mail goes out over the same SMTP settings the invitation mail already
    # uses. Whether an address exists here is deliberately never revealed -
    # every request answers the same way.
    path("password-reset/", auth_views.PasswordResetView.as_view(
        template_name="core/password_reset.html",
        email_template_name="core/password_reset_email.txt",
        subject_template_name="core/password_reset_subject.txt",
        success_url="/password-reset/sent/"), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(
        template_name="core/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="core/password_reset_confirm.html",
        success_url="/reset/done/"), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="core/password_reset_complete.html"), name="password_reset_complete"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
