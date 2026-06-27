from django.urls import path
from . import stat_views
app_name = 'linkedin_statistics'
urlpatterns = [
    path('',                          stat_views.overview,       name='overview'),
    path('timeline/',                 stat_views.timeline,       name='timeline'),
    path('buffer-timeline/',          stat_views.buffer_timeline, name='buffer_timeline'),
    path('timeline/<str:post_id>/',   stat_views.timeline_detail,name='timeline_detail'),
    path('posts/',                    stat_views.posts,          name='posts'),
    path('post-image/<str:post_id>/', stat_views.post_image,    name='post_image'),
    path('video/',                   stat_views.video_comparison, name='video'),
]
