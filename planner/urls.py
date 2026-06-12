from django.urls import path
from . import views

app_name = 'planner'
urlpatterns = [
    path('', views.planner_view, name='planner'),
    path('draft/', views.draft_view, name='draft'),
    path('pipeline/', views.pipeline_view, name='pipeline'),
    path('ready/', views.ready_view, name='ready'),
    path('scheduled/', views.scheduled_view, name='scheduled'),
    path('archive/', views.archive_view, name='archive'),
    path('all/', views.all_view, name='all'),
    path('oj/', views.oj_view, name='oj'),
    path('api/post/', views.api_post, name='api_post'),
    path('api/series/', views.api_series, name='api_series'),
    path('api/topic/', views.api_topic, name='api_topic'),
    path('api/idea/', views.api_idea, name='api_idea'),
    path('api/image/<int:post_id>/', views.api_image, name='api_image'),
    path('image/<int:post_id>/', views.planner_image, name='planner_image'),
    path('api-connect/', views.api_connect_view, name='api_connect'),
    path('linkedin/auth/', views.linkedin_auth_start, name='linkedin_auth_start'),
    path('linkedin/callback/', views.linkedin_auth_callback, name='linkedin_auth_callback'),
    path('linkedin/disconnect/', views.linkedin_disconnect, name='linkedin_disconnect'),
    path('linkedin/post/<int:post_id>/', views.linkedin_do_post, name='linkedin_do_post'),
    path('api/buffer/profiles/', views.api_buffer_profiles, name='api_buffer_profiles'),
    path('public-image/<int:post_id>/<str:token>/', views.public_image, name='public_image'),
    path('temp-video/<int:post_id>/<str:token>/', views.temp_video, name='temp_video'),
    path('api/trigger-scheduled/', views.api_trigger_scheduled, name='api_trigger_scheduled'),
    path('linkedin/post-video/<int:post_id>/', views.linkedin_post_video, name='linkedin_post_video'),
    path('api/video/<int:post_id>/', views.api_video, name='api_video'),
    path('api/linkedin-diag/', views.linkedin_diag, name='linkedin_diag'),
]
