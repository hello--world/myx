from rest_framework import serializers
from .models import AppSettings, SubdomainWord, CloudflareAccount, CloudflareZone, CloudflareDNSRecord


class AppSettingsSerializer(serializers.ModelSerializer):
    """应用设置序列化器"""
    
    class Meta:
        model = AppSettings
        fields = ['site_title', 'site_subtitle', 'site_icon', 'updated_at']
        read_only_fields = ['updated_at']


class SubdomainWordSerializer(serializers.ModelSerializer):
    """子域名词序列化器"""
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = SubdomainWord
        fields = ['id', 'word', 'category', 'is_active', 'usage_count', 
                 'created_at', 'updated_at', 'created_by', 'created_by_username']
        read_only_fields = ['usage_count', 'created_at', 'updated_at', 'created_by']
    
    def create(self, validated_data):
        """创建时自动设置创建者"""
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class CloudflareAccountSerializer(serializers.ModelSerializer):
    """Cloudflare 账户序列化器"""
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = CloudflareAccount
        fields = ['id', 'name', 'api_token', 'api_key', 'api_email', 
                 'account_id', 'account_name', 'is_active', 
                 'last_check', 'last_check_status',
                 'created_at', 'updated_at', 'created_by', 'created_by_username']
        read_only_fields = ['account_name', 'last_check', 'last_check_status',
                          'created_at', 'updated_at', 'created_by']
    
    def create(self, validated_data):
        """创建时自动设置创建者"""
        validated_data['created_by'] = self.context['request'].user
        # 清理 API Token 和 Key（去除首尾空格和换行符）
        if 'api_token' in validated_data and validated_data['api_token']:
            validated_data['api_token'] = validated_data['api_token'].strip()
        if 'api_key' in validated_data and validated_data['api_key']:
            validated_data['api_key'] = validated_data['api_key'].strip()
        if 'api_email' in validated_data and validated_data['api_email']:
            validated_data['api_email'] = validated_data['api_email'].strip()
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """更新时清理 API Token 和 Key"""
        # 清理 API Token 和 Key（去除首尾空格和换行符）
        if 'api_token' in validated_data and validated_data['api_token']:
            validated_data['api_token'] = validated_data['api_token'].strip()
        if 'api_key' in validated_data and validated_data['api_key']:
            validated_data['api_key'] = validated_data['api_key'].strip()
        if 'api_email' in validated_data and validated_data['api_email']:
            validated_data['api_email'] = validated_data['api_email'].strip()
        return super().update(instance, validated_data)


class CloudflareZoneSerializer(serializers.ModelSerializer):
    """Cloudflare Zone 序列化器"""
    account_name = serializers.CharField(source='account.name', read_only=True)
    
    class Meta:
        model = CloudflareZone
        fields = ['id', 'account', 'account_name', 'zone_id', 'zone_name', 
                 'status', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['zone_id', 'status', 'created_at', 'updated_at']


class CloudflareDNSRecordSerializer(serializers.ModelSerializer):
    """Cloudflare DNS 记录序列化器"""
    zone_name = serializers.CharField(source='zone.zone_name', read_only=True)
    
    class Meta:
        model = CloudflareDNSRecord
        fields = ['id', 'zone', 'zone_name', 'record_id', 'record_type', 
                 'name', 'content', 'ttl', 'proxied', 'is_active',
                 'created_at', 'updated_at']
        read_only_fields = ['record_id', 'created_at', 'updated_at']

