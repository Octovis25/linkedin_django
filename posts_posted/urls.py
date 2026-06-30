from django.urls import path
from . import views

app_name = "posts_posted"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("buffer/", views.buffer_post_list, name="buffer_list"),
    path("buffer/toggle-repost/", views.buffer_toggle_repost, name="buffer_toggle_repost"),
    path("fill-images/", views.buffer_fill_images, name="buffer_fill_images"),
    path("add/", views.post_add, name="add"),
    path("<int:pk>/edit/", views.post_edit, name="edit"),
    path("<int:pk>/delete/", views.post_delete, name="delete"),
    path("<int:pk>/image/", views.post_image_proxy, name="image_proxy"),
    path("<int:pk>/delete-image/", views.post_delete_image, name="delete_image"),
]
