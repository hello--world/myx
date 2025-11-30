from django.db import models
from django.conf import settings
from apps.servers.models import Server


class Deployment(models.Model):
    """部署任务模型"""
    TYPE_CHOICES = [
        ('xray', 'Xray'),
        ('caddy', 'Caddy'),
        ('both', 'Xray + Caddy'),
        ('full', '一键部署 (Agent + Xray + Caddy)'),
        ('agent', 'Agent'),
    ]

    CONNECTION_METHOD_CHOICES = [
        ('ssh', 'SSH'),
        ('agent', 'Agent'),
    ]

    DEPLOYMENT_TARGET_CHOICES = [
        ('host', '宿主机'),
        ('docker', 'Docker'),
    ]

    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('running', '运行中'),
        ('success', '成功'),
        ('failed', '失败'),
    ]

    name = models.CharField(max_length=100, verbose_name='任务名称')
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='deployments', verbose_name='服务器')
    deployment_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='部署类型')
    connection_method = models.CharField(max_length=20, choices=CONNECTION_METHOD_CHOICES, blank=True, null=True, verbose_name='连接方式')
    deployment_target = models.CharField(max_length=20, choices=DEPLOYMENT_TARGET_CHOICES, blank=True, null=True, verbose_name='部署目标')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    log = models.TextField(blank=True, null=True, verbose_name='部署日志')
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='创建者')

    class Meta:
        verbose_name = '部署任务'
        verbose_name_plural = '部署任务'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.deployment_type})"
