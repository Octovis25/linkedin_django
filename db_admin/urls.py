from django.urls import path
from . import views

urlpatterns = [
    path("",                  views.db_index,  name="db_admin_index"),
    path("sql/",              views.db_sql,    name="db_admin_sql"),
    path("<str:table_name>/", views.db_table,  name="db_admin_table"),
]
