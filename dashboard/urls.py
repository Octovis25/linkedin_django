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
    path("users/add/", core_views.user_add, name='user_add'),
    path("users/<int:pk>/edit/", core_views.user_edit, name='user_edit'),
    path("users/<int:pk>/delete/", core_views.user_delete, name='user_delete'),
    path("change-password/", core_views.change_password, name='change_password'),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
