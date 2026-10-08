from django.urls import path

from . import views

app_name = 'tutorials'

urlpatterns = [
    path('', views.tutorials_view, name='index'),
    path('api/film/', views.api_film, name='api_film'),
    path('api/film/<int:film_id>/', views.api_film_get, name='api_film_get'),
    path('api/step/', views.api_step, name='api_step'),
    path('api/upload/', views.api_upload, name='api_upload'),
    path('api/video/', views.api_video, name='api_video'),
    path('api/tts/', views.api_tts, name='api_tts'),
]
