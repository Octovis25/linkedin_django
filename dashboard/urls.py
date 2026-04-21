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
    path("planner/", include("planner.urls")),
    path("statistics/", include("linkedin_statistics.stat_urls")),  # Statistics module
    path("users/", core_views.user_list, name='user_list'),
    path("users/new/", core_views.user_create, name='user_create'),
    path("users/<int:user_id>/delete/", core_views.user_delete, name='user_delete'),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", core_views.custom_logout, name="logout"),
    path("api/post-category/", core_views.api_post_category, name='api_post_category'),
    path("api/post-comment/", core_views.api_post_comment, name='api_post_comment'),
    path("api/categories/", core_views.api_categories, name='api_categories'),
    path("change-password/", auth_views.PasswordChangeView.as_view(
        template_name="core/change_password.html", success_url="/"), name="change_password"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
