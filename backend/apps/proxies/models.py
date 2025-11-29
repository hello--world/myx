import uuid
import json
from django.db import models
from django.conf import settings as django_settings
from apps.servers.models import Server


class Proxy(models.Model):
    """代理节点模型（参考 xray-ui 设计，使用 JSON 存储复杂配置）"""
    PROTOCOL_CHOICES = [
        ('vless', 'VLESS'),
        ('vmess', 'VMess'),
        ('trojan', 'Trojan'),
        ('shadowsocks', 'Shadowsocks'),
    ]

    # 基础字段
    name = models.CharField(max_length=100, verbose_name='节点名称')
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='proxies', verbose_name='服务器')
    remark = models.TextField(blank=True, null=True, verbose_name='备注')
    enable = models.BooleanField(default=True, verbose_name='启用')
    
    # 流量统计
    up = models.BigIntegerField(default=0, verbose_name='上传流量（字节）')
    down = models.BigIntegerField(default=0, verbose_name='下载流量（字节）')
    total = models.BigIntegerField(default=0, verbose_name='总流量限制（字节），0表示不限制')
    expiry_time = models.BigIntegerField(default=0, verbose_name='到期时间（时间戳），0表示永不到期')
    
    # Xray 配置字段（参考 xray-ui 的 Inbound 模型）
    listen = models.CharField(max_length=50, blank=True, default='', verbose_name='监听IP，留空使用默认')
    port = models.IntegerField(verbose_name='端口', unique=True)
    protocol = models.CharField(max_length=20, choices=PROTOCOL_CHOICES, verbose_name='协议')
    settings = models.TextField(default='{}', verbose_name='协议设置（JSON字符串）')  # 存储完整的 settings JSON
    stream_settings = models.TextField(default='{}', verbose_name='传输设置（JSON字符串）')  # 存储完整的 streamSettings JSON
    tag = models.CharField(max_length=100, unique=True, blank=True, null=True, verbose_name='标签')
    sniffing = models.TextField(default='{}', verbose_name='嗅探设置（JSON字符串）')
    
    # 状态和部署
    status = models.CharField(max_length=20, default='active', verbose_name='状态')
    deployment_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', '待部署'),
            ('running', '部署中'),
            ('success', '部署成功'),
            ('failed', '部署失败'),
        ],
        default='pending',
        verbose_name='部署状态'
    )
    deployment_log = models.TextField(blank=True, null=True, verbose_name='部署日志')
    deployed_at = models.DateTimeField(null=True, blank=True, verbose_name='部署时间')
    
    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='创建者')

    class Meta:
        verbose_name = '代理节点'
        verbose_name_plural = '代理节点'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.protocol})"
    
    def get_settings_dict(self):
        """获取 settings 字典"""
        try:
            return json.loads(self.settings) if self.settings else {}
        except:
            return {}
    
    def get_stream_settings_dict(self):
        """获取 streamSettings 字典"""
        try:
            return json.loads(self.stream_settings) if self.stream_settings else {}
        except:
            return {}
    
    def get_sniffing_dict(self):
        """获取 sniffing 字典"""
        try:
            return json.loads(self.sniffing) if self.sniffing else {}
        except:
            return {}

