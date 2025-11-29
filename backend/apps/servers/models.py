from django.db import models
from django.conf import settings
try:
    from django_cryptography.fields import encrypt
except ImportError:
    # 如果django-cryptography不可用，使用普通字段
    def encrypt(field):
        return field


class Server(models.Model):
    """服务器模型"""
    STATUS_CHOICES = [
        ('active', '活跃'),
        ('inactive', '不活跃'),
        ('error', '错误'),
    ]

    CONNECTION_METHOD_CHOICES = [
        ('ssh', 'SSH'),
        ('agent', 'Agent'),
    ]

    DEPLOYMENT_TARGET_CHOICES = [
        ('host', '宿主机'),
        ('docker', 'Docker'),
    ]

    name = models.CharField(max_length=100, verbose_name='服务器名称')
    host = models.CharField(max_length=255, verbose_name='主机地址')
    port = models.IntegerField(default=22, verbose_name='SSH端口')
    username = models.CharField(max_length=100, verbose_name='SSH用户名')
    password = encrypt(models.CharField(max_length=255, blank=True, null=True, verbose_name='SSH密码'))
    private_key = encrypt(models.TextField(blank=True, null=True, verbose_name='SSH私钥'))
    connection_method = models.CharField(max_length=20, choices=CONNECTION_METHOD_CHOICES, default='ssh', verbose_name='连接方式')
    deployment_target = models.CharField(max_length=20, choices=DEPLOYMENT_TARGET_CHOICES, default='host', verbose_name='部署目标')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='inactive', verbose_name='状态')
    last_check = models.DateTimeField(null=True, blank=True, verbose_name='最后检查时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='创建者')

    class Meta:
        verbose_name = '服务器'
        verbose_name_plural = '服务器'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.host})"

