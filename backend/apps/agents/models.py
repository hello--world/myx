import uuid
from django.db import models
from django.conf import settings
from apps.servers.models import Server


class Agent(models.Model):
    """Agent 模型"""
    STATUS_CHOICES = [
        ('online', '在线'),
        ('offline', '离线'),
        ('error', '错误'),
    ]

    server = models.OneToOneField(Server, on_delete=models.CASCADE, related_name='agent', verbose_name='服务器')
    token = models.UUIDField(default=uuid.uuid4, unique=True, verbose_name='Agent Token')
    secret_key = models.CharField(max_length=64, verbose_name='加密密钥')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', verbose_name='状态')
    version = models.CharField(max_length=50, blank=True, null=True, verbose_name='Agent版本')
    last_heartbeat = models.DateTimeField(null=True, blank=True, verbose_name='最后心跳时间')
    registered_at = models.DateTimeField(auto_now_add=True, verbose_name='注册时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = 'Agent'
        verbose_name_plural = 'Agent'
        ordering = ['-registered_at']

    def __str__(self):
        return f"Agent for {self.server.name}"


class AgentCommand(models.Model):
    """Agent命令队列"""
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('running', '执行中'),
        ('success', '成功'),
        ('failed', '失败'),
    ]

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='commands', verbose_name='Agent')
    command = models.CharField(max_length=255, verbose_name='命令')
    args = models.JSONField(default=list, verbose_name='参数')
    timeout = models.IntegerField(default=300, verbose_name='超时时间（秒）')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    result = models.TextField(blank=True, null=True, verbose_name='执行结果')
    error = models.TextField(blank=True, null=True, verbose_name='错误信息')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')

    class Meta:
        verbose_name = 'Agent命令'
        verbose_name_plural = 'Agent命令'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.command} ({self.status})"
