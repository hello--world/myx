# Cloudflare Agent 域名自动配置与证书管理设计方案

## 1. 功能概述

### 1.1 核心功能
- **自动域名匹配**：在添加代理服务时，自动从 Cloudflare Zone 中匹配一个可用域名（使用 `agent-随机10个字符`、`agent-随机10个字符` 等格式）
- **DNS 记录自动创建**：在 Cloudflare DNS 中自动创建 A 记录，启用代理（Proxied）
- **Agent 连接地址更新**：Agent 部署成功后，自动更新 Agent 连接地址为分配的域名
- **证书自动管理**：
  - **有代理（Proxied）**：使用 Cloudflare 源证书（Origin Certificate），通过 API 申请并下载存储
  - **无代理（DNS Only）**：使用 Caddy 自动申请 Let's Encrypt 证书
- **Caddyfile 自动配置**：根据代理状态自动生成和更新 Caddyfile 配置

### 1.2 使用场景
1. 用户创建代理服务时，系统自动：
   - 从已配置的 Cloudflare Zone 中选择一个域名
   - 生成子域名（如 `agent-<x-10>.example.com`）
   - 在 Cloudflare DNS 中创建 A 记录（启用代理）
   - 申请 Cloudflare 源证书并存储
   - 更新 Caddyfile 配置
   - 更新 Agent 连接地址

2. 对于不需要 Cloudflare 代理的场景：
   - 创建 DNS Only 记录
   - 使用 Caddy 自动申请 Let's Encrypt 证书

## 2. Cloudflare 源证书（Origin Certificate）说明

### 2.1 什么是源证书
- **定义**：由 Cloudflare 签发的免费 TLS 证书，用于 Cloudflare 与源服务器之间的加密
- **特点**：
  - 仅对 Cloudflare 与源服务器之间的连接有效
  - 不适用于客户端直接访问源服务器
  - 免费，无数量限制
  - 有效期通常为 15 年
  - 支持通配符域名

### 2.2 使用场景
- **适用**：通过 Cloudflare CDN 代理的流量（Proxied = True）
- **不适用**：客户端直接访问源服务器（需要 Let's Encrypt 或其他公共 CA 证书）

### 2.3 API 接口
- **申请证书**：`POST /certificates`（需要 API Token）
- **下载证书**：`GET /certificates/{id}`（获取证书和私钥）
- **证书格式**：PEM 格式（包含证书和私钥）

## 3. 数据模型设计

### 3.1 Proxy 模型扩展
在 `Proxy` 模型中添加域名和证书相关字段：

```python
class Proxy(models.Model):
    # ... 现有字段 ...
    
    # Cloudflare 域名配置
    cloudflare_zone = models.ForeignKey(
        'settings.CloudflareZone', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name='Cloudflare Zone',
        help_text='使用的 Cloudflare 域名'
    )
    agent_domain = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        verbose_name='Agent 域名',
        help_text='自动分配的域名，如 agent-随机10个字符.example.com'
    )
    dns_record = models.OneToOneField(
        'settings.CloudflareDNSRecord',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proxy',
        verbose_name='DNS 记录',
        help_text='关联的 Cloudflare DNS 记录'
    )
    
    # 证书配置
    use_cloudflare_cert = models.BooleanField(
        default=False,
        verbose_name='使用 Cloudflare 源证书',
        help_text='是否使用 Cloudflare 源证书（仅适用于代理模式）'
    )
    cloudflare_cert_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Cloudflare 证书 ID',
        help_text='Cloudflare 源证书 ID'
    )
    certificate_path = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='证书路径',
        help_text='证书文件在服务器上的路径'
    )
    private_key_path = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='私钥路径',
        help_text='私钥文件在服务器上的路径'
    )
```

### 3.2 CloudflareOriginCertificate 模型（新增）
用于存储 Cloudflare 源证书信息：

```python
class CloudflareOriginCertificate(models.Model):
    """Cloudflare 源证书模型"""
    account = models.ForeignKey(
        'settings.CloudflareAccount',
        on_delete=models.CASCADE,
        related_name='origin_certificates',
        verbose_name='Cloudflare 账户'
    )
    zone = models.ForeignKey(
        'settings.CloudflareZone',
        on_delete=models.CASCADE,
        related_name='origin_certificates',
        verbose_name='Zone'
    )
    
    # 证书信息
    cert_id = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='证书 ID',
        help_text='Cloudflare 证书 ID'
    )
    hostnames = models.JSONField(
        default=list,
        verbose_name='域名列表',
        help_text='证书覆盖的域名列表'
    )
    certificate = models.TextField(
        verbose_name='证书内容',
        help_text='PEM 格式的证书内容'
    )
    private_key = models.TextField(
        verbose_name='私钥内容',
        help_text='PEM 格式的私钥内容'
    )
    
    # 状态
    is_active = models.BooleanField(
        default=True,
        verbose_name='启用'
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='过期时间'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='创建者'
    )
    
    class Meta:
        verbose_name = 'Cloudflare 源证书'
        verbose_name_plural = 'Cloudflare 源证书'
        ordering = ['-created_at']
```

### 3.3 Server 模型扩展
在 `Server` 模型中添加 Agent 域名字段（如果还没有）：

```python
class Server(models.Model):
    # ... 现有字段 ...
    
    # Agent 域名（用于连接）
    agent_domain = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='Agent 域名',
        help_text='Agent 连接使用的域名（如 agent-随机10个字符.example.com）'
    )
```

## 4. Cloudflare API 客户端扩展

### 4.1 源证书管理方法
在 `backend/apps/settings/cloudflare_client.py` 中添加：

```python
def create_origin_certificate(
    zone_id: str,
    hostnames: list,
    api_token: str = None,
    api_key: str = None,
    api_email: str = None,
    validity_days: int = 5475  # 15 年
) -> dict:
    """
    创建 Cloudflare 源证书
    
    Args:
        zone_id: Zone ID
        hostnames: 域名列表，支持通配符（如 ['*.example.com', 'example.com']）
        api_token: API Token（推荐）
        api_key: Global API Key（备选）
        api_email: API Email（备选）
        validity_days: 有效期（天数，默认 15 年）
    
    Returns:
        包含证书 ID、证书内容、私钥的字典
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    data = {
        'hostnames': hostnames,
        'requested_validity': validity_days
    }
    
    response = requests.post(
        f'https://api.cloudflare.com/client/v4/certificates',
        headers=headers,
        json=data,
        timeout=30
    )
    
    if response.status_code != 201:
        error_msg = response.json().get('errors', [{}])[0].get('message', 'Unknown error')
        raise CloudflareAPIError(f'创建源证书失败: {error_msg}')
    
    result = response.json().get('result', {})
    return {
        'id': result.get('id'),
        'certificate': result.get('certificate'),
        'private_key': result.get('private_key'),
        'hostnames': result.get('hostnames', []),
        'expires_on': result.get('expires_on')
    }


def get_origin_certificate(
    cert_id: str,
    api_token: str = None,
    api_key: str = None,
    api_email: str = None
) -> dict:
    """
    获取 Cloudflare 源证书详情
    
    Args:
        cert_id: 证书 ID
        api_token: API Token（推荐）
        api_key: Global API Key（备选）
        api_email: API Email（备选）
    
    Returns:
        证书信息字典
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    response = requests.get(
        f'https://api.cloudflare.com/client/v4/certificates/{cert_id}',
        headers=headers,
        timeout=30
    )
    
    if response.status_code != 200:
        error_msg = response.json().get('errors', [{}])[0].get('message', 'Unknown error')
        raise CloudflareAPIError(f'获取源证书失败: {error_msg}')
    
    result = response.json().get('result', {})
    return {
        'id': result.get('id'),
        'certificate': result.get('certificate'),
        'private_key': result.get('private_key'),
        'hostnames': result.get('hostnames', []),
        'expires_on': result.get('expires_on')
    }


def list_origin_certificates(
    api_token: str = None,
    api_key: str = None,
    api_email: str = None
) -> list:
    """
    列出所有源证书
    
    Returns:
        证书列表
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    response = requests.get(
        'https://api.cloudflare.com/client/v4/certificates',
        headers=headers,
        timeout=30
    )
    
    if response.status_code != 200:
        error_msg = response.json().get('errors', [{}])[0].get('message', 'Unknown error')
        raise CloudflareAPIError(f'列出源证书失败: {error_msg}')
    
    return response.json().get('result', [])


def revoke_origin_certificate(
    cert_id: str,
    api_token: str = None,
    api_key: str = None,
    api_email: str = None
) -> bool:
    """
    撤销 Cloudflare 源证书
    
    Returns:
        是否成功
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    response = requests.delete(
        f'https://api.cloudflare.com/client/v4/certificates/{cert_id}',
        headers=headers,
        timeout=30
    )
    
    return response.status_code == 204
```

## 5. 核心功能实现

### 5.1 自动域名匹配和 DNS 记录创建

**实现逻辑**：

```python
def auto_setup_proxy_domain(proxy: Proxy, zone: CloudflareZone = None, subdomain: str = None) -> dict:
    """
    为代理自动设置域名和 DNS 记录
    
    Args:
        proxy: Proxy 实例
        zone: Cloudflare Zone（如果不提供，从服务器配置中获取）
        subdomain: 子域名前缀（如 'agent-随机10个字符'），如果不提供则自动生成
    
    Returns:
        包含域名、DNS 记录、证书信息的字典
    """
    server = proxy.server
    
    # 1. 获取或选择 Zone
    if not zone:
        # 从服务器配置中获取，或选择第一个可用的 Zone
        zone = get_default_zone_for_server(server)
        if not zone:
            raise ValueError('未找到可用的 Cloudflare Zone')
    
    # 2. 生成子域名
    if not subdomain:
        # 使用 agent-随机10个字符, agent-2 格式
        subdomain = generate_agent_subdomain(zone, proxy)
    
    domain = f"{subdomain}.{zone.zone_name}"
    
    # 3. 获取服务器 IP
    server_ip = get_server_ipv4(server)
    if not server_ip:
        raise ValueError('服务器 IP 地址未配置')
    
    # 4. 创建 DNS 记录（启用代理）
    account = zone.account
    dns_record = create_dns_record_via_api(
        zone_id=zone.zone_id,
        record_type='A',
        name=subdomain,
        content=server_ip,
        proxied=True,  # 启用代理
        api_token=account.api_token,
        api_key=account.api_key,
        api_email=account.api_email
    )
    
    # 5. 保存 DNS 记录到数据库
    from apps.settings.models import CloudflareDNSRecord
    dns_record_obj, created = CloudflareDNSRecord.objects.update_or_create(
        record_id=dns_record['id'],
        zone=zone,
        defaults={
            'record_type': 'A',
            'name': subdomain,
            'content': server_ip,
            'ttl': 1,  # 自动
            'proxied': True,
            'purpose': 'agent_proxied',
            'is_active': True,
            'last_sync': timezone.now(),
            'created_by': proxy.created_by
        }
    )
    
    # 6. 更新 Proxy 模型
    proxy.cloudflare_zone = zone
    proxy.agent_domain = domain
    proxy.dns_record = dns_record_obj
    proxy.use_cloudflare_cert = True  # 使用 Cloudflare 源证书
    proxy.save()
    
    # 7. 更新 Server 模型的 Agent 连接地址
    server.agent_domain = domain
    server.agent_connect_host = domain
    server.agent_connect_port = get_agent_web_port(server)  # 通常是 8443
    server.save()
    
    return {
        'domain': domain,
        'dns_record': dns_record_obj,
        'zone': zone
    }


def generate_agent_subdomain(zone: CloudflareZone, proxy: Proxy) -> str:
    """
    生成 Agent 子域名（agent-随机10个字符 格式）
    
    Args:
        zone: Cloudflare Zone
        proxy: Proxy 实例（用于排除已使用的域名）
    
    Returns:
        可用的子域名前缀（如 'agent-abc123xyz4'）
    """
    import random
    import string
    from apps.settings.models import CloudflareDNSRecord
    
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
    import time
    timestamp_suffix = str(int(time.time()))[-10:]  # 使用时间戳的后10位
    return f'agent-{timestamp_suffix}'
```

### 5.2 Cloudflare 源证书申请和存储

**实现逻辑**：

```python
def setup_cloudflare_origin_certificate(
    proxy: Proxy,
    domain: str,
    zone: CloudflareZone
) -> dict:
    """
    为代理申请并存储 Cloudflare 源证书
    
    Args:
        proxy: Proxy 实例
        domain: 域名（如 agent-随机10个字符.example.com）
        zone: Cloudflare Zone
    
    Returns:
        包含证书信息的字典
    """
    account = zone.account
    
    # 1. 检查是否已有可用的源证书（支持通配符）
    from apps.settings.models import CloudflareOriginCertificate
    wildcard_domain = f"*.{zone.zone_name}"
    
    # 查找支持该域名的证书（通配符或精确匹配）
    existing_cert = CloudflareOriginCertificate.objects.filter(
        zone=zone,
        is_active=True,
        hostnames__contains=[wildcard_domain]  # 支持通配符
    ).first()
    
    if existing_cert:
        # 使用现有证书
        cert_id = existing_cert.cert_id
        certificate = existing_cert.certificate
        private_key = existing_cert.private_key
    else:
        # 2. 申请新证书（使用通配符，支持该 Zone 下所有子域名）
        from apps.settings.cloudflare_client import create_origin_certificate
        
        cert_data = create_origin_certificate(
            zone_id=zone.zone_id,
            hostnames=[wildcard_domain, zone.zone_name],  # 支持 *.example.com 和 example.com
            api_token=account.api_token,
            api_key=account.api_key,
            api_email=account.api_email
        )
        
        cert_id = cert_data['id']
        certificate = cert_data['certificate']
        private_key = cert_data['private_key']
        
        # 3. 保存证书到数据库
        from datetime import datetime
        expires_at = None
        if cert_data.get('expires_on'):
            expires_at = datetime.fromisoformat(cert_data['expires_on'].replace('Z', '+00:00'))
        
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
    from apps.agents.models import Agent
    from apps.agents.utils import execute_script_via_agent
    
    agent = Agent.objects.get(server=server)
    
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
chown caddy:caddy {cert_path} {key_path}

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
        raise Exception(f'存储证书失败: {result.get("error", "Unknown error")}')
    
    return cert_path, key_path
```

### 5.3 Caddyfile 自动配置

**实现逻辑**：

```python
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


def update_caddyfile_with_proxy_config(
    proxy: Proxy,
    domain: str,
    use_cloudflare_cert: bool = True
) -> bool:
    """
    更新服务器的 Caddyfile，添加代理配置
    
    Args:
        proxy: Proxy 实例
        domain: 域名
        use_cloudflare_cert: 是否使用 Cloudflare 源证书
    
    Returns:
        是否成功
    """
    server = proxy.server
    
    # 1. 读取现有 Caddyfile
    from apps.agents.models import Agent
    from apps.agents.utils import execute_script_via_agent
    
    agent = Agent.objects.get(server=server)
    
    # 获取现有 Caddyfile 内容
    get_caddyfile_script = """#!/bin/bash
if [ -f /etc/caddy/Caddyfile ]; then
    cat /etc/caddy/Caddyfile
else
    echo ""
fi
"""
    
    result = execute_script_via_agent(agent, get_caddyfile_script, timeout=10)
    existing_content = result.get('output', '').strip()
    
    # 2. 生成新的配置块
    new_config = configure_caddyfile_for_proxy(proxy, domain, use_cloudflare_cert)
    
    # 3. 合并配置（避免重复）
    updated_content = merge_caddyfile_config(existing_content, new_config, domain)
    
    # 4. 保存并验证
    from apps.proxies.views import ProxyViewSet
    proxy_viewset = ProxyViewSet()
    proxy_viewset.request = type('Request', (), {'user': proxy.created_by})()
    
    response = proxy_viewset.update_caddyfile(
        request=type('Request', (), {
            'data': {'content': updated_content},
            'user': proxy.created_by
        }()),
        pk=proxy.id
    )
    
    return response.status_code == 200


def merge_caddyfile_config(existing_content: str, new_config: str, domain: str) -> str:
    """
    合并 Caddyfile 配置，避免重复域名
    
    Args:
        existing_content: 现有 Caddyfile 内容
        new_config: 新配置块
        domain: 域名（用于检查是否已存在）
    
    Returns:
        合并后的内容
    """
    # 检查是否已存在该域名的配置
    if domain in existing_content:
        # 替换现有配置
        import re
        pattern = rf'{re.escape(domain)}\s*\{{[^}}]*\}}'
        updated_content = re.sub(pattern, new_config, existing_content, flags=re.MULTILINE | re.DOTALL)
        return updated_content
    else:
        # 追加新配置
        if existing_content.strip():
            return f"{existing_content}\n\n{new_config}"
        else:
            return new_config
```

### 5.4 完整流程集成

**在代理创建/部署时自动执行**：

```python
def auto_setup_proxy_with_domain(proxy: Proxy, zone: CloudflareZone = None) -> dict:
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
        
        # 3. 更新 Caddyfile
        update_caddyfile_with_proxy_config(
            proxy,
            domain,
            use_cloudflare_cert=True
        )
        
        # 4. 重载 Caddy（如果需要）
        # reload_caddy(proxy.server)
        
        return {
            'success': True,
            'domain': domain,
            'dns_record': domain_info['dns_record'],
            'certificate': cert_info,
            'message': '域名和证书配置成功'
        }
        
    except Exception as e:
        logger.error(f'自动配置代理域名失败: {str(e)}', exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'message': f'自动配置失败: {str(e)}'
        }
```

## 6. API 端点设计

### 6.1 代理域名自动配置
```
POST   /api/proxies/{id}/setup-domain/     # 为代理自动设置域名
POST   /api/proxies/{id}/setup-domain-manual/  # 手动指定域名
DELETE /api/proxies/{id}/domain/           # 删除代理的域名和 DNS 记录
```

### 6.2 Cloudflare 源证书管理
```
GET    /api/settings/cloudflare/origin-certificates/     # 列出源证书
POST   /api/settings/cloudflare/origin-certificates/     # 申请新证书
GET    /api/settings/cloudflare/origin-certificates/{id}/ # 获取证书详情
DELETE /api/settings/cloudflare/origin-certificates/{id}/ # 撤销证书
```

### 6.3 证书存储管理
```
POST   /api/proxies/{id}/certificates/store/  # 存储证书到服务器
GET    /api/proxies/{id}/certificates/        # 获取代理的证书信息
```

## 7. 前端界面设计

### 7.1 代理创建/编辑页面增强
- **域名自动配置选项**：
  - 复选框："自动配置 Cloudflare 域名"
  - Zone 选择下拉框（如果启用自动配置）
  - 子域名输入框（可选，留空则自动生成）
  
- **显示信息**：
  - 当前分配的域名
  - DNS 记录状态
  - 证书状态
  - Agent 连接地址

### 7.2 Cloudflare 源证书管理页面
- 证书列表（表格）
- 申请新证书按钮
- 证书详情（域名列表、过期时间）
- 撤销证书功能

## 8. 工作流程

### 8.1 代理创建时自动配置流程
```
1. 用户创建代理
2. 如果启用了"自动配置 Cloudflare 域名"：
   a. 选择或自动选择 Cloudflare Zone
   b. 生成子域名（agent-随机10个字符, agent-2...）
   c. 创建 Cloudflare DNS 记录（A 记录，启用代理）
   d. 申请 Cloudflare 源证书（通配符证书）
   e. 存储证书到服务器
   f. 更新 Caddyfile
   g. 更新 Agent 连接地址
3. 代理部署成功后，使用新域名连接
```

### 8.2 证书申请流程
```
1. 检查是否已有可用的通配符证书
2. 如果有，直接使用
3. 如果没有，申请新证书：
   a. 调用 Cloudflare API 申请证书
   b. 保存证书到数据库
   c. 存储证书文件到服务器
   d. 更新 Proxy 模型的证书路径
```

### 8.3 Caddyfile 更新流程
```
1. 读取现有 Caddyfile
2. 生成新的配置块（包含域名、证书路径、反向代理）
3. 检查是否已存在该域名配置
4. 如果存在，替换；如果不存在，追加
5. 验证配置
6. 保存并重载 Caddy
```

## 9. 错误处理和重试机制

### 9.1 DNS 记录创建失败
- 重试 3 次（指数退避）
- 记录错误日志
- 通知用户

### 9.2 证书申请失败
- 检查 API Token 权限
- 检查域名是否在 Zone 中
- 记录详细错误信息

### 9.3 证书存储失败
- 检查服务器连接
- 检查目录权限
- 重试存储操作

### 9.4 Caddyfile 更新失败
- 验证配置语法
- 保留原配置
- 记录错误日志

## 10. 安全考虑

### 10.1 证书私钥安全
- 私钥存储在数据库中（加密字段）
- 服务器上文件权限设置为 600
- 不在日志中记录私钥内容

### 10.2 API Token 权限
- 需要以下权限：
  - Zone:Read
  - DNS:Edit
  - SSL and Certificates:Edit

### 10.3 证书访问控制
- 只有证书创建者和管理员可以查看证书
- 证书私钥仅对创建者可见

## 11. 实施步骤

### 阶段 1：数据模型和 API 扩展
1. 扩展 `Proxy` 模型（添加域名和证书字段）
2. 创建 `CloudflareOriginCertificate` 模型
3. 扩展 `Server` 模型（Agent 域名字段）
4. 创建数据库迁移

### 阶段 2：Cloudflare API 客户端扩展
1. 实现源证书申请 API
2. 实现源证书查询 API
3. 实现源证书撤销 API
4. 添加错误处理和重试机制

### 阶段 3：核心功能实现
1. 实现自动域名匹配逻辑
2. 实现 DNS 记录自动创建
3. 实现源证书申请和存储
4. 实现 Caddyfile 自动配置

### 阶段 4：API 端点实现
1. 实现代理域名配置 API
2. 实现源证书管理 API
3. 实现证书存储 API
4. 添加权限控制

### 阶段 5：前端界面开发
1. 代理创建/编辑页面增强
2. 源证书管理页面
3. 证书状态显示
4. 错误提示和日志显示

### 阶段 6：测试和优化
1. 端到端测试
2. 错误场景测试
3. 性能优化
4. 文档完善

## 12. 注意事项

1. **DNS 传播时间**：DNS 记录创建后，可能需要几分钟才能生效
2. **证书有效期**：Cloudflare 源证书有效期通常为 15 年，但仍需监控过期时间
3. **通配符证书**：一个通配符证书可以覆盖整个 Zone 的所有子域名，建议复用
4. **Caddy 重载**：更新 Caddyfile 后需要重载 Caddy 配置
5. **Agent 连接**：更新 Agent 连接地址后，需要等待 DNS 传播才能正常连接
6. **API 限流**：Cloudflare API 有速率限制，需要实现适当的重试机制
7. **证书存储路径**：建议使用统一的证书存储路径（如 `/etc/caddy/certs/{domain}/`）

## 13. 依赖和配置

### 13.1 Python 依赖
```python
# requirements.txt
requests>=2.31.0  # Cloudflare API 调用
```

### 13.2 环境变量
无需新增环境变量，使用现有的 Cloudflare API 配置。

### 13.3 Caddy 配置要求
- Caddy 需要能够访问证书文件
- 证书目录需要适当的权限（caddy 用户可读）
- 建议使用 `/etc/caddy/certs/` 作为证书存储根目录

