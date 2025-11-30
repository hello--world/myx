from rest_framework import serializers
from .models import AppSettings


class AppSettingsSerializer(serializers.ModelSerializer):
    """应用设置序列化器"""
    
    class Meta:
        model = AppSettings
        fields = ['site_title', 'site_subtitle', 'updated_at']
        read_only_fields = ['updated_at']

