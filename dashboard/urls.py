from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),

    # Home
    path("", core_views.home_view, name='home'),

    # Data URLs
    path("data/upload/", core_views.upload_view, name='upload'),
    path("data/import/", core_views.analyze_view, name='analyze'),
    path("data/delete/<str:filename>/", core_views.delete_file_view, name='delete_file'),
    path("data/posts/", include("posts_posted.urls")),

    # Collectives
    path("collectives/", include("collectives.urls")),

    # User-Verwaltung
    path("users/", include("core.urls")),

    # Auth URLs
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
