from django.urls import path
from . import views

app_name = 'assets'
urlpatterns = [
    path('', views.assets_view, name='library'),
    path('api/list/', views.assets_api_list, name='api_list'),
    path('api/upload/', views.assets_api_upload, name='api_upload'),
    path('api/delete/', views.assets_api_delete, name='api_delete'),
    path('api/move/', views.assets_api_move, name='api_move'),
    path('api/rename/', views.assets_api_rename, name='api_rename'),
    path('api/meta/', views.assets_api_update_meta, name='api_meta'),
    path('api/favorite/', views.assets_api_toggle_favorite, name='api_favorite'),
    path('api/tags/', views.assets_api_tags, name='api_tags'),
    path('api/create-folder/', views.assets_api_create_folder, name='api_create_folder'),
    path('api/setup/', views.assets_api_setup, name='api_setup'),
    path('image/', views.assets_image_proxy, name='image_proxy'),
]
