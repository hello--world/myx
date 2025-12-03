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
    # Web服务配置
    web_service_port = models.IntegerField(default=8443, verbose_name='Web服务端口', help_text='Agent Web服务监听的端口')
    web_service_enabled = models.BooleanField(default=True, verbose_name='启用Web服务', help_text='是否启用Agent Web服务模式（新架构）')
    certificate_path = models.CharField(max_length=255, blank=True, null=True, verbose_name='证书路径', help_text='Agent Web服务使用的SSL证书路径')
    private_key_path = models.CharField(max_length=255, blank=True, null=True, verbose_name='私钥路径', help_text='Agent Web服务使用的SSL私钥路径')
    certificate_content = models.TextField(blank=True, null=True, verbose_name='证书内容', help_text='SSL证书内容（PEM格式），存储在服务器端')
    private_key_content = models.TextField(blank=True, null=True, verbose_name='私钥内容', help_text='SSL私钥内容（PEM格式），存储在服务器端')
    verify_ssl = models.BooleanField(default=False, verbose_name='验证SSL证书', help_text='是否验证Agent的SSL证书（默认False，因为使用自签名证书）')
    # JSON-RPC配置
    rpc_port = models.IntegerField(unique=True, verbose_name='RPC端口', help_text='Agent JSON-RPC服务端口（首次部署时确定，不可更改）')
    rpc_path = models.CharField(max_length=64, blank=True, verbose_name='RPC随机路径', help_text='RPC随机路径（用于路径混淆，保障安全，由服务器在部署时分配）')
    rpc_supported = models.BooleanField(default=False, verbose_name='支持JSON-RPC', help_text='Agent是否支持JSON-RPC协议')
    rpc_last_check = models.DateTimeField(null=True, blank=True, verbose_name='RPC支持检查时间', help_text='最后一次检查Agent是否支持JSON-RPC的时间')
    rpc_last_success = models.DateTimeField(null=True, blank=True, verbose_name='RPC最后成功时间', help_text='最后一次成功通过JSON-RPC连接的时间')
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
