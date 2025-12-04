# Cloudflare DNS 自动配置设计方案

## 1. 功能概述

### 1.1 核心功能
- **Cloudflare API 集成**：通过 Cloudflare API 管理 DNS 记录
- **Agent 访问地址自动配置**：为每个 Agent 自动创建 DNS 记录
- **双 DNS 记录策略**：创建两个 DNS 记录（有代理/无代理）
- **Caddyfile 自动证书申请**：基于 DNS 记录自动配置 Caddyfile 并申请 Let's Encrypt 证书

### 1.2 使用场景
1. 部署 Agent 时，自动创建 DNS 记录指向服务器 IP
2. 提供两个访问方式：
   - **有代理（Proxied）**：通过 Cloudflare CDN，隐藏真实 IP，提供 DDoS 保护
   - **无代理（DNS Only）**：直接指向服务器 IP，用于需要真实 IP 的场景
3. 自动更新 Caddyfile，配置域名和自动 HTTPS
4. 自动申请和管理 SSL 证书

## 2. 数据模型设计

### 2.1 CloudflareAccount 模型
存储 Cloudflare API 凭证（支持多账户）

```python
class CloudflareAccount(models.Model):
    """Cloudflare 账户模型"""
    name = models.CharField(max_length=100, verbose_name='账户名称')
    api_token = models.CharField(max_length=255, verbose_name='API Token', help_text='Cloudflare API Token（推荐）')
    # 或者使用 Global API Key + Email（不推荐，但兼容）
    api_key = models.CharField(max_length=255, blank=True, null=True, verbose_name='Global API Key')
    api_email = models.CharField(max_length=255, blank=True, null=True, verbose_name='API Email')
    
    # 账户信息（从 API 获取）
    account_id = models.CharField(max_length=100, blank=True, null=True, verbose_name='账户ID')
    account_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='账户名称')
    
    # 状态
    is_active = models.BooleanField(default=True, verbose_name='启用')
    last_check = models.DateTimeField(null=True, blank=True, verbose_name='最后检查时间')
    last_check_status = models.CharField(max_length=20, blank=True, null=True, verbose_name='最后检查状态')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
```

### 2.2 CloudflareZone 模型
存储 Cloudflare 管理的域名（Zone）

```python
class CloudflareZone(models.Model):
    """Cloudflare Zone（域名）模型"""
    account = models.ForeignKey(CloudflareAccount, on_delete=models.CASCADE, related_name='zones')
    zone_id = models.CharField(max_length=100, unique=True, verbose_name='Zone ID')
    zone_name = models.CharField(max_length=255, verbose_name='域名', help_text='例如: example.com')
    
    # 状态
    status = models.CharField(max_length=50, blank=True, null=True, verbose_name='状态')
    is_active = models.BooleanField(default=True, verbose_name='启用')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 2.3 SubdomainWord 模型
存储常用的子域名词库（如 www、chat、api 等）

```python
class SubdomainWord(models.Model):
    """子域名词库模型"""
    word = models.CharField(max_length=50, unique=True, verbose_name='子域名词', 
                           help_text='例如: www, chat, api, mail 等')
    category = models.CharField(max_length=50, blank=True, null=True, verbose_name='分类', 
                                help_text='例如: common, service, app 等')
    is_active = models.BooleanField(default=True, verbose_name='启用', 
                                   help_text='是否在随机生成时使用')
    usage_count = models.IntegerField(default=0, verbose_name='使用次数', 
                                     help_text='记录该词被使用的次数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='创建者')
    
    class Meta:
        verbose_name = '子域名词'
        verbose_name_plural = '子域名词'
        ordering = ['-usage_count', 'word']
    
    def __str__(self):
        return self.word
```

### 2.4 CloudflareDNSRecord 模型
存储 DNS 记录信息

```python
class CloudflareDNSRecord(models.Model):
    """Cloudflare DNS 记录模型"""
    RECORD_TYPE_CHOICES = [
        ('A', 'A'),
        ('AAAA', 'AAAA'),
        ('CNAME', 'CNAME'),
    ]
    
    zone = models.ForeignKey(CloudflareZone, on_delete=models.CASCADE, related_name='dns_records')
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='cloudflare_dns_records', null=True, blank=True)
    agent = models.OneToOneField(Agent, on_delete=models.CASCADE, related_name='cloudflare_dns_record', null=True, blank=True)
    
    # DNS 记录信息
    record_id = models.CharField(max_length=100, unique=True, verbose_name='记录ID')
    record_type = models.CharField(max_length=10, choices=RECORD_TYPE_CHOICES, verbose_name='记录类型')
    name = models.CharField(max_length=255, verbose_name='记录名称', help_text='例如: agent1.example.com')
    content = models.CharField(max_length=255, verbose_name='记录内容', help_text='IP 地址或 CNAME 目标')
    ttl = models.IntegerField(default=1, verbose_name='TTL', help_text='1 = 自动，其他值表示秒数')
    proxied = models.BooleanField(default=False, verbose_name='启用代理', help_text='是否通过 Cloudflare CDN')
    
    # 用途标识
    purpose = models.CharField(max_length=50, blank=True, null=True, verbose_name='用途', 
                               help_text='例如: agent_proxied, agent_direct, proxy_domain')
    
    # 状态
    is_active = models.BooleanField(default=True, verbose_name='启用')
    last_sync = models.DateTimeField(null=True, blank=True, verbose_name='最后同步时间')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    
    class Meta:
        unique_together = [['zone', 'name', 'record_type', 'proxied']]
```

### 2.4 Server 模型扩展
在 Server 模型中添加 Cloudflare 相关字段

```python
# 在 Server 模型中添加
cloudflare_zone = models.ForeignKey(CloudflareZone, on_delete=models.SET_NULL, null=True, blank=True, 
                                     verbose_name='Cloudflare Zone', help_text='用于此服务器的 Cloudflare 域名')
agent_domain_proxied = models.CharField(max_length=255, blank=True, null=True, 
                                       verbose_name='Agent 域名（代理）', help_text='通过 Cloudflare CDN 的域名')
agent_domain_direct = models.CharField(max_length=255, blank=True, null=True, 
                                       verbose_name='Agent 域名（直连）', help_text='直连服务器的域名')
```

## 3. Cloudflare API 客户端设计

### 3.1 文件结构
```
backend/
  utils/
    cloudflare/
      __init__.py
      client.py          # Cloudflare API 客户端
      dns.py             # DNS 记录管理
      zones.py           # Zone 管理
      exceptions.py      # 自定义异常
```

### 3.2 CloudflareClient 类设计

```python
class CloudflareClient:
    """Cloudflare API 客户端"""
    
    def __init__(self, account: CloudflareAccount):
        self.account = account
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = self._build_headers()
    
    def _build_headers(self):
        """构建请求头"""
        headers = {"Content-Type": "application/json"}
        if self.account.api_token:
            headers["Authorization"] = f"Bearer {self.account.api_token}"
        elif self.account.api_key and self.account.api_email:
            headers["X-Auth-Key"] = self.account.api_key
            headers["X-Auth-Email"] = self.account.api_email
        return headers
    
    def _request(self, method, endpoint, **kwargs):
        """发送 API 请求"""
        # 实现请求逻辑，包含错误处理
        pass
    
    # Zone 相关方法
    def list_zones(self):
        """列出所有 Zone"""
        pass
    
    def get_zone(self, zone_id):
        """获取 Zone 信息"""
        pass
    
    # DNS 记录相关方法
    def list_dns_records(self, zone_id, **filters):
        """列出 DNS 记录"""
        pass
    
    def create_dns_record(self, zone_id, record_type, name, content, ttl=1, proxied=False):
        """创建 DNS 记录"""
        pass
    
    def update_dns_record(self, zone_id, record_id, **updates):
        """更新 DNS 记录"""
        pass
    
    def delete_dns_record(self, zone_id, record_id):
        """删除 DNS 记录"""
        pass
```

## 4. 核心功能实现

### 4.1 Agent DNS 记录自动创建

**触发时机**：
- Agent 部署成功后
- 手动触发（通过 API 或前端按钮）

**实现逻辑**：
```python
def generate_random_subdomain(zone: CloudflareZone, purpose: str = 'agent', use_dash: bool = False) -> str:
    """
    从词库中随机选择一个可用的子域名词，如果已被使用则自动添加数字后缀
    
    Args:
        zone: Cloudflare Zone
        purpose: 用途（'agent' 或 'proxy'）
        use_dash: 是否使用短横线分隔（www-0）还是直接拼接（www0）
    
    Returns:
        可用的子域名（不包含域名后缀），例如: 'www', 'www0', 'www-0', 'chat1' 等
    """
    from apps.settings.utils import get_random_subdomain_word
    
    # 获取该 Zone 中已使用的子域名
    existing_names = CloudflareDNSRecord.objects.filter(
        zone=zone
    ).values_list('name', flat=True)
    
    # 提取已使用的子域名前缀（去掉域名后缀）
    used_prefixes = set()
    zone_name = zone.zone_name
    for name in existing_names:
        if name.endswith(f'.{zone_name}') or name == zone_name:
            prefix = name.replace(f'.{zone_name}', '').replace(zone_name, '')
            if prefix:
                used_prefixes.add(prefix)
    
    # 从词库中随机选择（如果已被使用，会自动添加数字后缀）
    subdomain = get_random_subdomain_word(exclude_words=list(used_prefixes), use_dash=use_dash)
    
    if subdomain:
        return subdomain
    
    # 如果词库为空，使用后备方案
    from apps.settings.utils import get_subdomain_with_fallback
    fallback_prefix = 'agent' if purpose == 'agent' else 'proxy'
    return get_subdomain_with_fallback(
        exclude_words=list(used_prefixes),
        fallback_prefix=fallback_prefix,
        use_dash=use_dash
    )

def setup_agent_dns_records(agent: Agent, zone: CloudflareZone, subdomain: str = None):
    """
    为 Agent 创建 DNS 记录
    
    Args:
        agent: Agent 实例
        zone: Cloudflare Zone
        subdomain: 子域名前缀（如 'chat'），如果不提供则从词库随机生成
    """
    server = agent.server
    
    # 1. 生成子域名
    if not subdomain:
        subdomain = generate_random_subdomain(zone, purpose='agent')
    
    # 2. 获取服务器 IP（IPv4 和 IPv6）
    ipv4 = get_server_ipv4(server)
    ipv6 = get_server_ipv6(server)  # 可选
    
    # 3. 创建有代理的 DNS 记录（A 记录）
    proxied_domain = f"{subdomain}.{zone.zone_name}"
    proxied_record = create_dns_record(
        zone=zone,
        record_type='A',
        name=subdomain,
        content=ipv4,
        proxied=True,
        purpose='agent_proxied',
        agent=agent
    )
    
    # 4. 创建无代理的 DNS 记录（A 记录）
    direct_domain = f"{subdomain}-direct.{zone.zone_name}"
    direct_record = create_dns_record(
        zone=zone,
        record_type='A',
        name=f"{subdomain}-direct",
        content=ipv4,
        proxied=False,
        purpose='agent_direct',
        agent=agent
    )
    
    # 5. 更新 Server 和 Agent 模型
    server.agent_domain_proxied = proxied_domain
    server.agent_domain_direct = direct_domain
    server.agent_connect_host = proxied_domain  # 默认使用代理域名
    server.agent_connect_port = agent.web_service_port
    server.save()
    
    return {
        'proxied_domain': proxied_domain,
        'direct_domain': direct_domain,
        'proxied_record': proxied_record,
        'direct_record': direct_record
    }
```

### 4.2 Caddyfile 自动配置

**实现逻辑**：
```python
def configure_caddyfile_with_domain(proxy: Proxy, domain: str, auto_https: bool = True):
    """
    为代理配置 Caddyfile，使用域名并自动申请证书
    
    Args:
        proxy: Proxy 实例
        domain: 域名（例如: proxy1.example.com）
        auto_https: 是否自动申请 HTTPS 证书
    """
    server = proxy.server
    
    # 1. 读取现有 Caddyfile
    caddyfile_content = read_caddyfile(server)
    
    # 2. 生成新的配置块
    config_block = f"""
{domain} {{
    reverse_proxy localhost:{proxy.port}
"""
    
    if auto_https:
        # 使用 Caddy 自动 HTTPS（Let's Encrypt）
        config_block += """
    tls {
        on_demand
    }
"""
    else:
        # 使用手动上传的证书（如果存在）
        cert = get_certificate_for_domain(server, domain)
        if cert:
            config_block += f"""
    tls {cert.cert_path} {cert.key_path}
"""
    
    config_block += "}\n"
    
    # 3. 合并到现有 Caddyfile（避免重复）
    updated_content = merge_caddyfile_config(caddyfile_content, config_block)
    
    # 4. 保存并验证
    save_caddyfile(server, updated_content, validate=True)
    
    # 5. 重载 Caddy
    reload_caddy(server)
```

### 4.3 代理域名自动配置

**实现逻辑**：
```python
def setup_proxy_domain(proxy: Proxy, zone: CloudflareZone, subdomain: str = None):
    """
    为代理创建域名并配置 Caddyfile
    
    Args:
        proxy: Proxy 实例
        zone: Cloudflare Zone
        subdomain: 子域名前缀，如果不提供则从词库随机生成
    """
    server = proxy.server
    
    # 1. 生成子域名
    if not subdomain:
        subdomain = generate_random_subdomain(zone, purpose='proxy')
    
    domain = f"{subdomain}.{zone.zone_name}"
    
    # 2. 创建 DNS 记录（有代理）
    dns_record = create_dns_record(
        zone=zone,
        record_type='A',
        name=subdomain,
        content=get_server_ipv4(server),
        proxied=True,  # 代理流量通过 Cloudflare
        purpose='proxy_domain',
        server=server
    )
    
    # 3. 配置 Caddyfile
    configure_caddyfile_with_domain(proxy, domain, auto_https=True)
    
    # 4. 等待 DNS 传播和证书申请（可选，异步处理）
    # 可以添加一个后台任务来检查证书申请状态
    
    return {
        'domain': domain,
        'dns_record': dns_record
    }
```

## 5. API 端点设计

### 5.1 Cloudflare 账户管理
```
GET    /api/cloudflare/accounts/          # 列出账户
POST   /api/cloudflare/accounts/          # 创建账户
GET    /api/cloudflare/accounts/{id}/    # 获取账户详情
PUT    /api/cloudflare/accounts/{id}/    # 更新账户
DELETE /api/cloudflare/accounts/{id}/    # 删除账户
POST   /api/cloudflare/accounts/{id}/test/  # 测试账户连接
```

### 5.2 Zone 管理
```
GET    /api/cloudflare/zones/             # 列出 Zone
POST   /api/cloudflare/zones/sync/        # 从 Cloudflare 同步 Zone
GET    /api/cloudflare/zones/{id}/       # 获取 Zone 详情
```

### 5.3 DNS 记录管理
```
GET    /api/cloudflare/dns-records/      # 列出 DNS 记录
POST   /api/cloudflare/dns-records/      # 创建 DNS 记录
PUT    /api/cloudflare/dns-records/{id}/ # 更新 DNS 记录
DELETE /api/cloudflare/dns-records/{id}/ # 删除 DNS 记录
```

### 5.4 子域名词库管理
```
GET    /api/subdomain-words/             # 列出所有子域名词
POST   /api/subdomain-words/              # 添加子域名词
PUT    /api/subdomain-words/{id}/         # 更新子域名词
DELETE /api/subdomain-words/{id}/         # 删除子域名词
POST   /api/subdomain-words/batch-add/   # 批量添加子域名词
```

### 5.5 Agent DNS 自动配置
```
POST   /api/agents/{id}/setup-dns/       # 为 Agent 创建 DNS 记录
DELETE /api/agents/{id}/dns-records/     # 删除 Agent 的 DNS 记录
```

### 5.6 代理域名配置
```
POST   /api/proxies/{id}/setup-domain/   # 为代理创建域名并配置 Caddyfile
```

## 6. 前端界面设计

### 6.1 子域名词库管理页面
- 词库列表（表格，显示词、分类、使用次数、状态）
- 添加/编辑词表单
- 批量添加功能（支持导入常用词）
- 启用/禁用开关
- 使用统计（按使用次数排序）

### 6.2 Cloudflare 账户管理页面
- 账户列表（表格）
- 添加/编辑账户表单
- 测试连接按钮
- Zone 同步按钮

### 6.3 DNS 记录管理页面
- DNS 记录列表（表格，显示域名、类型、内容、代理状态等）
- 创建/编辑 DNS 记录表单
- 批量操作（启用/禁用代理）

### 6.4 Agent 配置页面增强
- 在 Agent 详情页添加 "配置 DNS" 按钮
- 显示当前 DNS 记录状态
- 显示两个域名（代理/直连）
- 子域名选择（可从词库选择或手动输入）

### 6.5 代理配置页面增强
- 在代理详情页添加 "配置域名" 按钮
- 显示当前域名
- 显示 Caddyfile 配置状态
- 子域名选择（可从词库选择或手动输入）

## 7. 工作流程

### 7.1 Agent 部署后自动配置 DNS
```
1. Agent 部署成功
2. 检查服务器是否配置了 Cloudflare Zone
3. 如果配置了，自动创建两个 DNS 记录（代理/直连）
4. 更新 Server 模型的 agent_connect_host
5. 通知用户配置完成
```

### 7.2 代理域名配置流程
```
1. 用户点击 "配置域名" 按钮
2. 选择 Cloudflare Zone 和子域名
3. 系统创建 DNS 记录（A 记录，启用代理）
4. 自动更新 Caddyfile，添加域名配置
5. Caddy 自动申请 Let's Encrypt 证书
6. 重载 Caddy 配置
7. 等待 DNS 传播（通常几分钟）
8. 证书申请完成（通常几分钟到几十分钟）
```

## 8. 错误处理和重试机制

### 8.1 API 错误处理
- Cloudflare API 限流处理（429 错误）
- 网络错误重试（指数退避）
- 认证失败处理

### 8.2 DNS 传播等待
- 创建 DNS 记录后，等待 DNS 传播
- 提供检查 DNS 解析状态的 API
- 前端显示等待状态

### 8.3 证书申请监控
- 监控 Caddy 证书申请状态
- 如果申请失败，记录错误并通知用户
- 支持手动重试

## 9. 安全考虑

### 9.1 API 凭证存储
- 使用加密字段存储 API Token/Key
- 不在日志中记录完整凭证
- 支持凭证轮换

### 9.2 权限控制
- 只有管理员可以管理 Cloudflare 账户
- 普通用户只能查看和使用已配置的域名

### 9.3 操作审计
- 记录所有 DNS 记录创建/更新/删除操作
- 记录证书申请和配置变更

## 10. 实施步骤

### 阶段 1：基础架构
1. 创建数据模型（SubdomainWord, CloudflareAccount, CloudflareZone, CloudflareDNSRecord）
2. 实现 Cloudflare API 客户端
3. 创建数据库迁移
4. 初始化默认子域名词库（www, api, chat, mail, app, service, node, proxy, agent 等）

### 阶段 2：子域名词库和 DNS 记录管理
1. 实现子域名词库的 CRUD 操作（包括批量添加）
2. 实现随机子域名生成逻辑
3. 实现 DNS 记录的 CRUD 操作
4. 实现 Zone 同步功能
5. 创建 API 端点

### 阶段 3：Agent DNS 自动配置
1. 实现 Agent DNS 记录自动创建（使用词库随机生成）
2. 集成到 Agent 部署流程
3. 前端界面开发（包括词库管理页面）

### 阶段 4：代理域名配置
1. 实现代理域名自动配置
2. 实现 Caddyfile 自动更新
3. 证书申请状态监控

### 阶段 5：测试和优化
1. 端到端测试
2. 错误处理完善
3. 性能优化
4. 文档编写

## 11. 依赖和配置

### 11.1 Python 依赖
```python
# requirements.txt
requests>=2.31.0  # Cloudflare API 调用
```

### 11.2 环境变量
```env
# Cloudflare API 配置（可选，也可以在数据库中配置）
CLOUDFLARE_API_TOKEN=your-api-token
CLOUDFLARE_API_KEY=your-api-key
CLOUDFLARE_API_EMAIL=your-email
```

### 11.3 Caddy 配置要求
- Caddy 需要能够访问 80 和 443 端口（用于 Let's Encrypt 验证）
- 确保防火墙规则允许这些端口

## 12. 注意事项

1. **DNS 传播时间**：DNS 记录创建后，可能需要几分钟到几小时才能全球生效
2. **证书申请时间**：Let's Encrypt 证书申请通常需要几分钟，首次申请可能需要更长时间
3. **Cloudflare 代理限制**：启用代理后，某些端口可能被限制，需要确保 Agent 使用的端口在 Cloudflare 允许的范围内
4. **API 限流**：Cloudflare API 有速率限制，需要实现适当的重试和限流处理
5. **IPv6 支持**：如果需要 IPv6，需要创建 AAAA 记录

