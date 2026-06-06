from django.urls import path
from . import views

app_name = 'media_library'
urlpatterns = [
    path('',                      views.library_view,   name='library'),
    path('upload/',               views.library_upload, name='upload'),
    path('image/<int:item_id>/',  views.library_image,  name='image'),
    path('edit/<int:item_id>/',   views.library_edit,   name='edit'),
    path('delete/<int:item_id>/', views.library_delete, name='delete'),
    path('api/',                  views.library_api,    name='api'),
]
