from django.contrib import admin
from .models import Deployment


@admin.register(Deployment)
class DeploymentAdmin(admin.ModelAdmin):
    list_display = ['name', 'server', 'deployment_type', 'status', 'created_at']
    list_filter = ['deployment_type', 'status', 'created_at']
    search_fields = ['name', 'server__name']

