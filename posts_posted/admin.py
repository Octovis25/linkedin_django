from django.contrib import admin
from .models import LinkedinPostPosted

@admin.register(LinkedinPostPosted)
class LinkedinPostPostedAdmin(admin.ModelAdmin):
    list_display = ['post_id', 'post_date', 'post_image']
    search_fields = ['post_id']
    list_filter = ['post_date']
