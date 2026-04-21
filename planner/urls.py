from django.urls import path
from . import views

app_name = 'planner'
urlpatterns = [
    path('', views.planner_view, name='planner'),
    path('api/post/', views.api_planner_post, name='api_post'),
    path('api/topic/', views.api_planner_topic, name='api_topic'),
    path('api/idea/', views.api_planner_idea, name='api_idea'),
    path('api/image/<int:post_id>/', views.api_planner_image, name='api_image'),
]
