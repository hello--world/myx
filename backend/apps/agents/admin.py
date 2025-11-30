from django.contrib import admin
from .models import Agent, AgentCommand, CommandTemplate

@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ['id', 'server', 'token', 'status', 'created_at', 'last_heartbeat']
    list_filter = ['status', 'created_at']
    readonly_fields = ['token', 'created_at']
    search_fields = ['server__name', 'server__host', 'token']

@admin.register(AgentCommand)
class AgentCommandAdmin(admin.ModelAdmin):
    list_display = ['id', 'agent', 'command', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    readonly_fields = ['created_at', 'started_at', 'completed_at']
    search_fields = ['command', 'agent__server__name']

@admin.register(CommandTemplate)
class CommandTemplateAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'command', 'created_by', 'created_at']
    list_filter = ['created_at']
    readonly_fields = ['created_at', 'updated_at']
    search_fields = ['name', 'command', 'description']
