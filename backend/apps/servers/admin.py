from django.contrib import admin
from .models import Server


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ['name', 'host', 'port', 'username', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'host', 'username']

