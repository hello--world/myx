from django.db import models
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model

User = get_user_model()


class AppSettings(models.Model):
    """应用设置模型（单例模式）"""
    site_title = models.CharField(max_length=200, default='MyX - 科学技术管理平台', verbose_name='网站标题')
    site_subtitle = models.CharField(max_length=200, blank=True, default='', verbose_name='网站副标题')
    site_icon = models.TextField(blank=True, default='', verbose_name='网站图标（SVG）')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '应用设置'
        verbose_name_plural = '应用设置'

    def __str__(self):
        return '应用设置'

    @classmethod
    def get_settings(cls):
        """获取设置（单例）"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        """确保只有一个设置实例"""
        self.pk = 1
        super().save(*args, **kwargs)


class SubdomainWord(models.Model):
    """子域名词库模型（用于 DNS 记录生成）"""
    word = models.CharField(max_length=50, unique=True, verbose_name='子域名词', 
                           help_text='例如: www, chat, api, mail 等')
    category = models.CharField(max_length=50, blank=True, null=True, verbose_name='分类', 
                                help_text='例如: common, service, app 等')
    is_active = models.BooleanField(default=True, verbose_name='启用', 
                                   help_text='是否在随机生成时使用')
    usage_count = models.IntegerField(default=0, verbose_name='使用次数', 
                                     help_text='记录该词被使用的次数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, 
                                   null=True, blank=True, verbose_name='创建者')

    class Meta:
        verbose_name = '子域名词'
        verbose_name_plural = '子域名词'
        ordering = ['-usage_count', 'word']

    def __str__(self):
        return self.word


class CloudflareAccount(models.Model):
    """Cloudflare 账户模型"""
    name = models.CharField(max_length=100, verbose_name='账户名称')
    api_token = models.CharField(max_length=255, blank=True, null=True, verbose_name='API Token', 
                                 help_text='Cloudflare API Token（推荐）')
    # 或者使用 Global API Key + Email（不推荐，但兼容）
    api_key = models.CharField(max_length=255, blank=True, null=True, verbose_name='Global API Key')
    api_email = models.CharField(max_length=255, blank=True, null=True, verbose_name='API Email')
    
    # 账户信息（从 API 获取）
    account_id = models.CharField(max_length=100, blank=True, null=True, verbose_name='账户ID')
    account_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='账户名称')
    
    # 状态
    is_active = models.BooleanField(default=True, verbose_name='启用')
    last_check = models.DateTimeField(null=True, blank=True, verbose_name='最后检查时间')
    last_check_status = models.CharField(max_length=20, blank=True, null=True, verbose_name='最后检查状态')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    
    class Meta:
        verbose_name = 'Cloudflare 账户'
        verbose_name_plural = 'Cloudflare 账户'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class CloudflareZone(models.Model):
    """Cloudflare Zone（域名）模型"""
    account = models.ForeignKey(CloudflareAccount, on_delete=models.CASCADE, related_name='zones', verbose_name='账户')
    zone_id = models.CharField(max_length=100, unique=True, verbose_name='Zone ID')
    zone_name = models.CharField(max_length=255, verbose_name='域名', help_text='例如: example.com')
    
    # 状态
    status = models.CharField(max_length=50, blank=True, null=True, verbose_name='状态')
    is_active = models.BooleanField(default=True, verbose_name='启用')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = 'Cloudflare Zone'
        verbose_name_plural = 'Cloudflare Zones'
        ordering = ['-created_at']
        unique_together = [['account', 'zone_id']]
    
    def __str__(self):
        return self.zone_name


class CloudflareDNSRecord(models.Model):
    """Cloudflare DNS 记录模型"""
    RECORD_TYPE_CHOICES = [
        ('A', 'A'),
        ('AAAA', 'AAAA'),
        ('CNAME', 'CNAME'),
        ('MX', 'MX'),
        ('TXT', 'TXT'),
        ('NS', 'NS'),
        ('SRV', 'SRV'),
    ]
    
    zone = models.ForeignKey(CloudflareZone, on_delete=models.CASCADE, related_name='dns_records', verbose_name='Zone')
    
    # DNS 记录信息
    record_id = models.CharField(max_length=100, unique=True, verbose_name='记录ID')
    record_type = models.CharField(max_length=10, choices=RECORD_TYPE_CHOICES, verbose_name='记录类型')
    name = models.CharField(max_length=255, verbose_name='记录名称', help_text='例如: agent1.example.com')
    content = models.CharField(max_length=255, verbose_name='记录内容', help_text='IP 地址或 CNAME 目标')
    ttl = models.IntegerField(default=1, verbose_name='TTL', help_text='1 = 自动，其他值表示秒数')
    proxied = models.BooleanField(default=False, verbose_name='启用代理', help_text='是否通过 Cloudflare CDN')
    
    # 状态
    is_active = models.BooleanField(default=True, verbose_name='启用')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = 'Cloudflare DNS 记录'
        verbose_name_plural = 'Cloudflare DNS 记录'
        ordering = ['-created_at']
        unique_together = [['zone', 'record_id']]
    
    def __str__(self):
        return f"{self.name} ({self.record_type})"

