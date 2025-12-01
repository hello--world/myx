from django.db import models
from django.conf import settings


class Agent(models.Model):
    """Agent模型"""
    STATUS_CHOICES = [
        ('online', '在线'),
        ('offline', '离线'),
    ]

    HEARTBEAT_MODE_CHOICES = [
        ('push', '推送模式'),
        ('pull', '拉取模式'),
    ]

    server = models.OneToOneField('servers.Server', on_delete=models.CASCADE, related_name='agent', verbose_name='服务器')
    token = models.CharField(max_length=64, unique=True, verbose_name='Token')
    secret_key = models.CharField(max_length=255, blank=True, null=True, verbose_name='加密密钥', help_text='用于Agent通信加密的密钥')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', verbose_name='状态')
    version = models.CharField(max_length=50, blank=True, null=True, verbose_name='版本')
    deployment_tool_version = models.CharField(max_length=50, blank=True, null=True, verbose_name='部署工具版本', help_text='Agent端部署工具的版本号')
    last_heartbeat = models.DateTimeField(null=True, blank=True, verbose_name='最后心跳时间')
    heartbeat_mode = models.CharField(max_length=10, choices=HEARTBEAT_MODE_CHOICES, default='push', verbose_name='心跳模式')
    last_check = models.DateTimeField(null=True, blank=True, verbose_name='最后检查时间（拉取模式）')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = 'Agent'
        verbose_name_plural = 'Agent'
        ordering = ['-created_at']

    def __str__(self):
        return f"Agent-{self.server.name}"


class AgentCommand(models.Model):
    """Agent命令模型"""
    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('running', '执行中'),
        ('success', '成功'),
        ('failed', '失败'),
    ]

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='commands', verbose_name='Agent')
    command = models.CharField(max_length=255, verbose_name='命令')
    args = models.JSONField(default=list, blank=True, verbose_name='参数')
    timeout = models.IntegerField(default=300, verbose_name='超时时间（秒）')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    result = models.TextField(blank=True, null=True, verbose_name='执行结果')
    error = models.TextField(blank=True, null=True, verbose_name='错误信息')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = 'Agent命令'
        verbose_name_plural = 'Agent命令'
        ordering = ['-created_at']


class CommandTemplate(models.Model):
    """命令模板模型"""
    name = models.CharField(max_length=100, verbose_name='模板名称')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    command = models.CharField(max_length=255, verbose_name='命令')
    args = models.JSONField(default=list, blank=True, verbose_name='参数')
    timeout = models.IntegerField(default=300, verbose_name='超时时间（秒）')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '命令模板'
        verbose_name_plural = '命令模板'
        ordering = ['-created_at']

    def __str__(self):
        return self.name
