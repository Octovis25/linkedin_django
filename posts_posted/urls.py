from django.urls import path
from . import views

app_name = "posts_posted"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("add/", views.post_add, name="add"),
    path("<int:pk>/edit/", views.post_edit, name="edit"),
    path("<int:pk>/delete/", views.post_delete, name="delete"),
    path("<int:pk>/image/", views.post_image_proxy, name="image_proxy"),
    path("<int:pk>/delete-image/", views.post_delete_image, name="delete_image"),
]
