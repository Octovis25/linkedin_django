from django.urls import path
from . import stat_clicks, stat_oj, stat_views
app_name = 'linkedin_statistics'
urlpatterns = [
    path('',                          stat_views.overview,       name='overview'),
    path('timeline/',                 stat_views.timeline,       name='timeline'),
    path('timeline/<str:post_id>/',   stat_views.timeline_detail,name='timeline_detail'),
    path('posts/',                    stat_views.posts,          name='posts'),
    path('post-image/<str:post_id>/', stat_views.post_image,    name='post_image'),
    path('video/',                   stat_views.video_comparison, name='video'),
    path('clicks/',                  stat_clicks.clicks,        name='clicks'),
    path('clicks/topic/',            stat_clicks.clicks_topic,  name='clicks_topic'),
    path('oj/',                      stat_oj.oj,                name='oj'),
    path('oj/analysis/',             stat_oj.oj_analysis,       name='oj_analysis'),
    path('oj/post/<str:buffer_post_id>/', stat_oj.oj_post,      name='oj_post'),
    path('oj/upload/',               stat_oj.oj_upload,         name='oj_upload'),
    path('oj/fetch/',                stat_oj.oj_fetch,          name='oj_fetch'),
]
