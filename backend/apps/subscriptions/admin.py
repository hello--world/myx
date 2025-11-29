from django.contrib import admin
from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['name', 'format', 'token', 'enabled', 'created_at']
    list_filter = ['format', 'enabled', 'created_at']
    search_fields = ['name', 'token']

