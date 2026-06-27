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
    # Folders
    path('folder/create/',                views.folder_create,  name='folder_create'),
    path('folder/rename/<int:folder_id>/', views.folder_rename, name='folder_rename'),
    path('folder/delete/<int:folder_id>/', views.folder_delete, name='folder_delete'),
    path('item/move/',                    views.item_move,      name='item_move'),
    path('item/studio-info/<int:item_id>/', views.item_studio_info, name='item_studio_info'),
    # Image Studio
    path('studio/',                       views.studio_view,            name='studio'),
    path('studio/link-video/',            views.studio_link_video,      name='studio_link_video'),
    path('studio/templates/',             views.studio_templates_view,  name='studio_templates'),
    path('studio/template/upload/',       views.studio_template_upload, name='studio_template_upload'),
    path('studio/template/delete/<int:tpl_id>/', views.studio_template_delete, name='studio_template_delete'),
    path('studio/template/colors/<int:tpl_id>/', views.studio_template_colors, name='studio_template_colors'),
    path('studio/template/image/<int:tpl_id>/',  views.studio_template_image,  name='studio_template_image'),
    path('studio/save/',                  views.studio_save,            name='studio_save'),
    path('studio/save-video/',            views.studio_save_video,      name='studio_save_video'),
    path('studio/api/templates/',         views.studio_api_templates,   name='studio_api_templates'),
    path('studio/api/library/',           views.studio_api_library,     name='studio_api_library'),
    path('studio/api/saved/',             views.studio_api_saved,       name='studio_api_saved'),
    path('studio/api/post-image/<int:post_id>/', views.studio_api_post_image, name='studio_api_post_image'),
    path('studio/drawio/save/',                  views.studio_drawio_save,          name='studio_drawio_save'),
    path('studio/brand-colors/save/',            views.studio_brand_colors_save,    name='studio_brand_colors_save'),
    # Video-Vorlagen
    path('studio/flowcharts/',            views.studio_flowcharts_view, name='studio_flowcharts'),
    path('studio/nc-image/',                             views.studio_nc_image_proxy,         name='studio_nc_image_proxy'),
    path('studio/video-template/save/',                 views.studio_video_template_save,    name='studio_video_template_save'),
    path('studio/video-template/list/',                 views.studio_video_template_list,    name='studio_video_template_list'),
    path('studio/video-template/load/<int:tpl_id>/',    views.studio_video_template_load,    name='studio_video_template_load'),
    path('studio/video-template/delete/<int:tpl_id>/',  views.studio_video_template_delete,  name='studio_video_template_delete'),
    path('studio/video-template/preview/<int:tpl_id>/', views.studio_video_template_preview, name='studio_video_template_preview'),
    # Shared Assets (geteilter Bilderpool)
    path('studio/api/shared-assets/',        views.studio_shared_assets_list,   name='studio_shared_assets_list'),
    path('studio/api/shared-assets/upload/', views.studio_shared_assets_upload, name='studio_shared_assets_upload'),
    path('studio/api/shared-assets/delete/', views.studio_shared_assets_delete, name='studio_shared_assets_delete'),
]
