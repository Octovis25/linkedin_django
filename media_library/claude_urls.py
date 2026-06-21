from django.urls import path
from . import claude_api

urlpatterns = [
    path('status/',                    claude_api.api_status,         name='claude_status'),
    path('images/',                    claude_api.list_images,        name='claude_images'),
    path('images/upload/',             claude_api.upload_image,       name='claude_upload'),
    path('posts/',                     claude_api.list_posts,         name='claude_posts'),
    path('posts/<int:post_id>/',       claude_api.get_post,           name='claude_post'),
    path('posts/<int:post_id>/update/', claude_api.update_post_text,  name='claude_post_update'),
    path('templates/',                 claude_api.list_templates,     name='claude_templates'),
    path('aufgaben/',                  claude_api.list_aufgaben,      name='claude_aufgaben'),
    path('aufgaben/<int:aufgabe_id>/update/', claude_api.update_aufgabe, name='claude_aufgabe_update'),
]
