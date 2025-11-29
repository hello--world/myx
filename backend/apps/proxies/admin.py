from django.contrib import admin
from .models import Proxy


@admin.register(Proxy)
class ProxyAdmin(admin.ModelAdmin):
    list_display = ['name', 'server', 'protocol', 'port', 'status', 'created_at']
    list_filter = ['protocol', 'status', 'created_at']
    search_fields = ['name', 'server__name']

