from django.contrib import admin
from .models import LinkedinPostPosted
@admin.register(LinkedinPostPosted)
class LinkedinPostPostedAdmin(admin.ModelAdmin):
    list_display = ("post_id","post_date","post_link","created_at")
    list_filter = ("post_date",)
    search_fields = ("post_link","post_id")
    readonly_fields = ("post_id",)
