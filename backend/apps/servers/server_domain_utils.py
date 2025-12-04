"""
服务器 Agent 域名自动配置工具
"""
import random
import string
import time
import logging
from typing import Optional, Dict, Any
from django.utils import timezone

from apps.servers.models import Server
from apps.agents.models import Agent
from apps.settings.models import CloudflareZone, CloudflareDNSRecord
from apps.settings.cloudflare_client import (
    create_dns_record,
    CloudflareAPIError
)

logger = logging.getLogger(__name__)


def generate_agent_subdomain_for_server(zone: CloudflareZone, server: Server) -> str:
    """
    为服务器生成 Agent 子域名（agent-随机10个字符 格式）
    
    Args:
        zone: Cloudflare Zone
        server: Server 实例
    
    Returns:
        可用的子域名前缀（如 'agent-abc123xyz4'）
    """
    # 获取该 Zone 中已使用的 agent-* 子域名
    existing_records = CloudflareDNSRecord.objects.filter(
        zone=zone,
        name__startswith='agent-'
    ).values_list('name', flat=True)
    
    # 提取已使用的随机字符串部分
    used_suffixes = set()
    for name in existing_records:
        # 提取 agent-xxx 中的 xxx 部分
        parts = name.split('-', 1)
        if len(parts) == 2 and parts[0] == 'agent':
            used_suffixes.add(parts[1])
    
    # 生成随机10个字符（小写字母和数字）
    max_attempts = 100
    for _ in range(max_attempts):
        # 生成10个随机字符（小写字母和数字）
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        candidate = f'agent-{random_suffix}'
        
        if candidate not in used_suffixes:
            return candidate
    
    # 如果100次尝试都冲突（极不可能），使用时间戳作为后缀
    timestamp_suffix = str(int(time.time()))[-10:]  # 使用时间戳的后10位
    return f'agent-{timestamp_suffix}'


def get_server_ipv4(server: Server) -> Optional[str]:
    """
    获取服务器的 IPv4 地址
    
    Args:
        server: Server 实例
    
    Returns:
        IPv4 地址，如果未配置则返回 None
    """
    # 从 host 字段中提取 IP（如果 host 是 IP 地址）
    host = server.host.strip()
    
    # 简单的 IP 地址验证
    import re
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, host):
        return host
    
    # 如果不是 IP，尝试解析（这里简化处理，实际可能需要 DNS 查询）
    # 暂时返回 None，让调用方处理
    return None


def get_default_zone_for_server(server: Server) -> Optional[CloudflareZone]:
    """
    获取服务器的默认 Cloudflare Zone
    
    Args:
        server: Server 实例
    
    Returns:
        CloudflareZone 实例，如果未找到则返回 None
    """
    # 优先查找已激活的 Zone
    zones = CloudflareZone.objects.filter(is_active=True).order_by('-created_at')
    
    if zones.exists():
        return zones.first()
    
    return None


def auto_setup_server_agent_domain(
    server: Server,
    zone: Optional[CloudflareZone] = None,
    subdomain: Optional[str] = None,
    auto_setup: bool = True
) -> Dict[str, Any]:
    """
    为服务器的 Agent 自动设置域名和 DNS 记录
    
    Args:
        server: Server 实例
        zone: Cloudflare Zone（如果不提供，从配置中获取）
        subdomain: 子域名前缀（如 'agent-abc123xyz4'），如果不提供则自动生成
        auto_setup: 是否自动配置（如果为 False，只检查不配置）
    
    Returns:
        包含域名、DNS 记录信息的字典
    """
    # 如果服务器已经有域名，直接返回
    if server.agent_connect_host and server.agent_connect_host != server.host:
        # 检查域名是否有效（不是 IP 地址）
        import re
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(ip_pattern, server.agent_connect_host):
            logger.info(f'服务器 {server.name} 已有域名: {server.agent_connect_host}')
            return {
                'success': True,
                'domain': server.agent_connect_host,
                'message': '服务器已有域名配置',
                'skipped': True
            }
    
    # 如果不需要自动配置，返回提示
    if not auto_setup:
        return {
            'success': False,
            'message': '未启用自动配置域名',
            'skipped': True
        }
    
    # 1. 获取或选择 Zone
    if not zone:
        zone = get_default_zone_for_server(server)
        if not zone:
            logger.warning(f'服务器 {server.name} 未找到可用的 Cloudflare Zone')
            return {
                'success': False,
                'error': '未找到可用的 Cloudflare Zone',
                'message': '请先在 Cloudflare DNS 管理中配置 Zone'
            }
    
    # 2. 生成子域名
    if not subdomain:
        subdomain = generate_agent_subdomain_for_server(zone, server)
    
    domain = f"{subdomain}.{zone.zone_name}"
    
    # 3. 获取服务器 IP
    server_ip = get_server_ipv4(server)
    if not server_ip:
        logger.warning(f'服务器 {server.name} IP 地址未配置或无法解析')
        return {
            'success': False,
            'error': '服务器 IP 地址未配置',
            'message': '请确保服务器 host 字段是有效的 IP 地址'
        }
    
    # 4. 创建 DNS 记录（启用代理）
    account = zone.account
    try:
        dns_record_data = create_dns_record(
            zone_id=zone.zone_id,
            record_type='A',
            name=subdomain,
            content=server_ip,
            api_token=account.api_token,
            api_key=account.api_key,
            api_email=account.api_email,
            ttl=1,  # 自动
            proxied=True  # 启用代理
        )
    except CloudflareAPIError as e:
        logger.error(f'创建 DNS 记录失败: {str(e)}')
        return {
            'success': False,
            'error': f'创建 DNS 记录失败: {str(e)}',
            'message': 'DNS 记录创建失败，请检查 Cloudflare API 配置'
        }
    
    # 5. 保存 DNS 记录到数据库
    dns_record_obj, created = CloudflareDNSRecord.objects.update_or_create(
        record_id=dns_record_data['id'],
        zone=zone,
        defaults={
            'record_type': 'A',
            'name': subdomain,
            'content': server_ip,
            'ttl': 1,  # 自动
            'proxied': True,
            'is_active': True,
        }
    )
    
    # 6. 更新 Server 模型的 Agent 连接地址
    try:
        agent = Agent.objects.get(server=server)
        agent_port = agent.web_service_port
    except Agent.DoesNotExist:
        agent_port = 8443  # 默认端口
    
    server.agent_connect_host = domain
    server.agent_connect_port = agent_port
    server.save()
    
    logger.info(f'服务器 {server.name} Agent 域名配置成功: {domain}')
    
    return {
        'success': True,
        'domain': domain,
        'dns_record': dns_record_obj,
        'zone': zone,
        'message': f'Agent 域名配置成功: {domain}'
    }

