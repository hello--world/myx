from django.contrib import admin
from .models import AppSettings, SubdomainWord, CloudflareAccount


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    """应用设置管理"""
    list_display = ['site_title', 'site_subtitle', 'updated_at']
    
    def has_add_permission(self, request):
        """禁止添加（单例模式）"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """禁止删除（单例模式）"""
        return False


@admin.register(SubdomainWord)
class SubdomainWordAdmin(admin.ModelAdmin):
    """子域名词管理"""
    list_display = ['word', 'category', 'is_active', 'usage_count', 'created_at', 'created_by']
    list_filter = ['is_active', 'category', 'created_at']
    search_fields = ['word', 'category']
    readonly_fields = ['usage_count', 'created_at', 'updated_at']
    list_editable = ['is_active']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('word', 'category', 'is_active')
        }),
        ('统计信息', {
            'fields': ('usage_count', 'created_by', 'created_at', 'updated_at')
        }),
    )


@admin.register(CloudflareAccount)
class CloudflareAccountAdmin(admin.ModelAdmin):
    """Cloudflare 账户管理"""
    list_display = ['name', 'account_name', 'account_id', 'is_active', 'last_check_status', 'created_by', 'created_at']
    list_filter = ['is_active', 'last_check_status', 'created_at']
    search_fields = ['name', 'account_name', 'account_id', 'api_email']
    readonly_fields = ['account_id', 'account_name', 'last_check', 'last_check_status', 'created_at', 'updated_at']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'created_by')
        }),
        ('API 凭证', {
            'fields': ('api_token', 'api_key', 'api_email'),
            'description': '使用 API Token（推荐）或 Global API Key + Email'
        }),
        ('账户信息', {
            'fields': ('account_id', 'account_name'),
            'description': '从 Cloudflare API 自动获取'
        }),
        ('状态', {
            'fields': ('is_active', 'last_check', 'last_check_status')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at')
        }),
    )

