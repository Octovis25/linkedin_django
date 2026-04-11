from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("passwort/", views.change_password, name="change_password"),
    path("users/", views.user_list, name="user_list"),
    path("users/neu/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
]
