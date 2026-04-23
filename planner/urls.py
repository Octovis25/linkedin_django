from django.urls import path
from . import views

app_name = 'planner'
urlpatterns = [
    path('', views.planner_view, name='planner'),
    path('pipeline/', views.pipeline_view, name='pipeline'),
    path('ready/', views.ready_view, name='ready'),
    path('scheduled/', views.scheduled_view, name='scheduled'),
    path('archive/', views.archive_view, name='archive'),
    path('api/post/', views.api_post, name='api_post'),
    path('api/series/', views.api_series, name='api_series'),
    path('api/topic/', views.api_topic, name='api_topic'),
    path('api/idea/', views.api_idea, name='api_idea'),
    path('api/image/<int:post_id>/', views.api_image, name='api_image'),
]
