import uuid
from django.db import models
from django.conf import settings


class Subscription(models.Model):
    """订阅模型"""
    FORMAT_CHOICES = [
        ('v2ray', 'V2Ray'),
        ('clash', 'Clash'),
    ]

    name = models.CharField(max_length=100, verbose_name='订阅名称')
    token = models.UUIDField(default=uuid.uuid4, unique=True, verbose_name='订阅Token')
    format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default='v2ray', verbose_name='订阅格式')
    enabled = models.BooleanField(default=True, verbose_name='启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='创建者')

    class Meta:
        verbose_name = '订阅'
        verbose_name_plural = '订阅'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.format})"

