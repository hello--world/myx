"""
代理域名自动配置工具
"""
import random
import string
import time
import logging
from typing import Optional, Dict, Any
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.proxies.models import Proxy
from apps.servers.models import Server
from apps.agents.models import Agent
from apps.settings.models import CloudflareZone, CloudflareDNSRecord, CloudflareOriginCertificate, CloudflareAccount
from apps.settings.cloudflare_client import (
    create_dns_record,
    create_origin_certificate,
    CloudflareAPIError
)
from apps.agents.utils import execute_script_via_agent

logger = logging.getLogger(__name__)


def generate_agent_subdomain(zone: CloudflareZone, proxy: Proxy) -> str:
    """
    生成 Agent 子域名（agent-随机10个字符 格式）
    
    Args:
        zone: Cloudflare Zone
        proxy: Proxy 实例（用于排除已使用的域名）
    
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


def get_agent_web_port(server: Server) -> int:
    """
    获取 Agent Web 服务端口
    
    Args:
        server: Server 实例
    
    Returns:
        Agent Web 服务端口（默认 8443）
    """
    try:
        agent = Agent.objects.get(server=server)
        return agent.web_service_port
    except Agent.DoesNotExist:
        return 8443  # 默认端口


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


def auto_setup_proxy_domain(
    proxy: Proxy,
    zone: Optional[CloudflareZone] = None,
    subdomain: Optional[str] = None
) -> Dict[str, Any]:
    """
    为代理自动设置域名和 DNS 记录
    
    Args:
        proxy: Proxy 实例
        zone: Cloudflare Zone（如果不提供，从服务器配置中获取）
        subdomain: 子域名前缀（如 'agent-abc123xyz4'），如果不提供则自动生成
    
    Returns:
        包含域名、DNS 记录、证书信息的字典
    """
    server = proxy.server
    
    # 1. 获取或选择 Zone
    if not zone:
        zone = get_default_zone_for_server(server)
        if not zone:
            raise ValueError('未找到可用的 Cloudflare Zone')
    
    # 2. 生成子域名
    if not subdomain:
        subdomain = generate_agent_subdomain(zone, proxy)
    
    domain = f"{subdomain}.{zone.zone_name}"
    
    # 3. 获取服务器 IP
    server_ip = get_server_ipv4(server)
    if not server_ip:
        raise ValueError('服务器 IP 地址未配置')
    
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
        raise
    
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
    
    # 6. 更新 Proxy 模型
    proxy.cloudflare_zone = zone
    proxy.agent_domain = domain
    proxy.dns_record = dns_record_obj
    proxy.use_cloudflare_cert = True  # 使用 Cloudflare 源证书
    proxy.save()
    
    # 7. 更新 Server 模型的 Agent 连接地址
    server.agent_connect_host = domain
    server.agent_connect_port = get_agent_web_port(server)  # 通常是 8443
    server.save()
    
    return {
        'domain': domain,
        'dns_record': dns_record_obj,
        'zone': zone
    }


def setup_cloudflare_origin_certificate(
    proxy: Proxy,
    domain: str,
    zone: CloudflareZone
) -> Dict[str, Any]:
    """
    为代理申请并存储 Cloudflare 源证书
    
    Args:
        proxy: Proxy 实例
        domain: 域名（如 agent-abc123xyz4.example.com）
        zone: Cloudflare Zone
    
    Returns:
        包含证书信息的字典
    """
    account = zone.account
    
    # 1. 检查是否已有可用的源证书（支持通配符）
    wildcard_domain = f"*.{zone.zone_name}"
    
    # 查找支持该域名的证书（通配符或精确匹配）
    existing_cert = CloudflareOriginCertificate.objects.filter(
        zone=zone,
        is_active=True
    ).first()
    
    # 检查现有证书是否支持通配符域名
    if existing_cert and wildcard_domain in existing_cert.hostnames:
        # 使用现有证书
        cert_id = existing_cert.cert_id
        certificate = existing_cert.certificate
        private_key = existing_cert.private_key
        logger.info(f'使用现有源证书: {cert_id[:8]}...')
    else:
        # 2. 申请新证书（使用通配符，支持该 Zone 下所有子域名）
        try:
            cert_data = create_origin_certificate(
                hostnames=[wildcard_domain, zone.zone_name],  # 支持 *.example.com 和 example.com
                api_token=account.api_token,
                api_key=account.api_key,
                api_email=account.api_email
            )
        except CloudflareAPIError as e:
            logger.error(f'申请源证书失败: {str(e)}')
            raise
        
        cert_id = cert_data['id']
        certificate = cert_data['certificate']
        private_key = cert_data['private_key']
        
        # 3. 保存证书到数据库
        expires_at = None
        if cert_data.get('expires_on'):
            expires_at = parse_datetime(cert_data['expires_on'].replace('Z', '+00:00'))
        
        existing_cert = CloudflareOriginCertificate.objects.create(
            account=account,
            zone=zone,
            cert_id=cert_id,
            hostnames=cert_data['hostnames'],
            certificate=certificate,
            private_key=private_key,
            expires_at=expires_at,
            is_active=True,
            created_by=proxy.created_by
        )
        logger.info(f'创建新源证书: {cert_id[:8]}...')
    
    # 4. 将证书存储到服务器
    cert_path, key_path = store_certificate_on_server(
        server=proxy.server,
        domain=domain,
        certificate=certificate,
        private_key=private_key
    )
    
    # 5. 更新 Proxy 模型
    proxy.cloudflare_cert_id = cert_id
    proxy.certificate_path = cert_path
    proxy.private_key_path = key_path
    proxy.save()
    
    return {
        'cert_id': cert_id,
        'cert_path': cert_path,
        'key_path': key_path,
        'certificate': existing_cert
    }


def store_certificate_on_server(
    server: Server,
    domain: str,
    certificate: str,
    private_key: str
) -> tuple:
    """
    将证书存储到服务器上
    
    Args:
        server: Server 实例
        domain: 域名
        certificate: 证书内容（PEM 格式）
        private_key: 私钥内容（PEM 格式）
    
    Returns:
        (cert_path, key_path) 元组
    """
    # 证书存储路径：/etc/caddy/certs/{domain}/
    cert_dir = f'/etc/caddy/certs/{domain}'
    cert_path = f'{cert_dir}/cert.pem'
    key_path = f'{cert_dir}/key.pem'
    
    # 通过 Agent 执行脚本存储证书
    try:
        agent = Agent.objects.get(server=server)
    except Agent.DoesNotExist:
        raise ValueError('服务器未安装 Agent')
    
    store_script = f"""#!/bin/bash
set -e

# 创建证书目录
mkdir -p {cert_dir}

# 设置权限
chmod 700 {cert_dir}

# 写入证书
cat > {cert_path} << 'CERT_EOF'
{certificate}
CERT_EOF

# 写入私钥
cat > {key_path} << 'KEY_EOF'
{private_key}
KEY_EOF

# 设置文件权限
chmod 600 {cert_path} {key_path}
chown caddy:caddy {cert_path} {key_path} 2>/dev/null || chown root:root {cert_path} {key_path}

echo "证书已存储: {cert_path}"
echo "私钥已存储: {key_path}"
"""
    
    result = execute_script_via_agent(
        agent,
        store_script,
        timeout=30,
        script_name='store_certificate.sh'
    )
    
    if result.get('status') != 'success':
        error_msg = result.get('error', 'Unknown error')
        raise Exception(f'存储证书失败: {error_msg}')
    
    return cert_path, key_path


def configure_caddyfile_for_proxy(
    proxy: Proxy,
    domain: str,
    use_cloudflare_cert: bool = True
) -> str:
    """
    为代理配置 Caddyfile
    
    Args:
        proxy: Proxy 实例
        domain: 域名
        use_cloudflare_cert: 是否使用 Cloudflare 源证书（True）或 Let's Encrypt（False）
    
    Returns:
        生成的 Caddyfile 配置块
    """
    if use_cloudflare_cert and proxy.certificate_path and proxy.private_key_path:
        # 使用 Cloudflare 源证书
        config = f"""{domain} {{
    tls {proxy.certificate_path} {proxy.private_key_path}
    reverse_proxy localhost:{proxy.port}
}}"""
    else:
        # 使用 Caddy 自动申请 Let's Encrypt 证书
        config = f"""{domain} {{
    tls {{
        on_demand
    }}
    reverse_proxy localhost:{proxy.port}
}}"""
    
    return config


def auto_setup_proxy_with_domain(proxy: Proxy, zone: Optional[CloudflareZone] = None) -> Dict[str, Any]:
    """
    为代理自动设置域名、DNS 记录、证书和 Caddyfile
    
    完整流程：
    1. 自动匹配域名（agent-随机10个字符 格式）
    2. 创建 Cloudflare DNS 记录（启用代理）
    3. 申请 Cloudflare 源证书
    4. 存储证书到服务器
    5. 更新 Caddyfile
    6. 更新 Agent 连接地址
    
    Args:
        proxy: Proxy 实例
        zone: Cloudflare Zone（可选）
    
    Returns:
        包含所有配置信息的字典
    """
    try:
        # 1. 自动设置域名和 DNS 记录
        domain_info = auto_setup_proxy_domain(proxy, zone)
        domain = domain_info['domain']
        zone = domain_info['zone']
        
        # 2. 申请并存储 Cloudflare 源证书
        cert_info = setup_cloudflare_origin_certificate(proxy, domain, zone)
        
        # 3. 更新 Caddyfile（这里只生成配置，实际更新需要通过 API）
        caddyfile_config = configure_caddyfile_for_proxy(
            proxy,
            domain,
            use_cloudflare_cert=True
        )
        
        return {
            'success': True,
            'domain': domain,
            'dns_record': domain_info['dns_record'],
            'certificate': cert_info,
            'caddyfile_config': caddyfile_config,
            'message': '域名和证书配置成功'
        }
        
    except Exception as e:
        logger.error(f'自动配置代理域名失败: {str(e)}', exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'message': f'自动配置失败: {str(e)}'
        }

