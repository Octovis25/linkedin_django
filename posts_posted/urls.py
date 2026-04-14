from django.urls import path
from . import views

app_name = 'posts_posted'

urlpatterns = [
    path('', views.post_list, name='list'),
    path('<path:pk>/edit/', views.post_edit, name='edit'),
    path('<path:pk>/image/', views.post_image_proxy, name='image_proxy'),
]
