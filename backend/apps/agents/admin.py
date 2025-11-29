from django.contrib import admin
from .models import Agent


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ['server', 'status', 'version', 'last_heartbeat', 'registered_at']
    list_filter = ['status', 'registered_at']
    search_fields = ['server__name', 'server__host', 'token']
    readonly_fields = ['token', 'secret_key', 'registered_at', 'updated_at']

