from django.urls import path
from . import views

app_name = "posts_posted"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("add/", views.post_add, name="add"),
    path("<path:pk>/edit/", views.post_edit, name="edit"),
    path("<path:pk>/delete/", views.post_delete, name="delete"),
]
