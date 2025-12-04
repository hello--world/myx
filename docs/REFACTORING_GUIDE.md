# Agent安装和升级重构指南

## 📋 重构概述

本次重构统一了Agent的安装和升级流程，遵循架构设计原则：
- **Agent完全无状态**，服务器主动管理
- **统一使用Ansible playbook**（SSH本地执行或Agent远程执行）
- **Service层封装业务逻辑**，View层只负责HTTP请求处理
- **Agent自升级使用独立进程**（systemd-run），失败自动回滚

---

## 🏗️ 新增架构组件

### 1. Service层（业务逻辑层）

#### `backend/apps/agents/services/`

| 文件 | 职责 | 主要方法 |
|------|------|---------|
| `agent_service.py` | Agent管理服务 | `create_or_get_agent()`<br>`send_command()`<br>`stop_agent()` / `start_agent()`<br>`check_agent_status()` |
| `certificate_service.py` | 证书管理服务 | `generate_certificate()`<br>`regenerate_agent_certificate()`<br>`upload_certificate_to_agent()` |
| `upgrade_service.py` | Agent升级服务 | `upgrade_via_agent()`<br>`upgrade_via_ssh()`<br>`upload_agent_files()` |

#### `backend/apps/deployments/services/`

| 文件 | 职责 | 主要方法 |
|------|------|---------|
| `ansible_executor.py` | Ansible执行器 | `execute_playbook()`<br>`_execute_via_ssh()`<br>`_execute_via_agent()` |
| `deployment_service.py` | 部署管理服务 | `install_agent()`<br>`wait_for_agent_startup()`<br>`deploy_service()` |

### 2. Ansible Playbooks（统一部署脚本）

#### `deployment-tool/playbooks/`

| Playbook | 用途 | 执行方式 |
|----------|------|---------|
| `install_agent.yml` | Agent初始安装 | SSH方式（本地执行） |
| `upgrade_agent.yml` | Agent自升级 | Agent方式（RPC调用） |
| `deploy_xray.yml` | Xray宿主机部署 | SSH或Agent |
| `deploy_xray_docker.yml` | Xray Docker部署 | SSH或Agent |
| `deploy_caddy.yml` | Caddy部署 | SSH或Agent |

---

## 🔄 架构对比

### **重构前（旧架构）**

```
┌─────────────────────────────────────────┐
│              View Layer                  │
│  - 100+行业务逻辑                        │
│  - Bash heredoc脚本生成                 │
│  - 直接操作SSH/命令队列                 │
│  - 大量重复代码                          │
└─────────────────────────────────────────┘
              ↓ 直接调用
┌─────────────────────────────────────────┐
│  Bash脚本（tasks.py 618-774行）        │
│  + Python脚本（agent_deployer.py）     │
│  + 特殊的upgrade脚本（views.py）        │
└─────────────────────────────────────────┘
```

**问题**：
- ❌ View层业务逻辑过重
- ❌ 部署方式不统一（Bash/Python/特殊脚本）
- ❌ 代码重复（RPC端口生成、Token生成等）
- ❌ 难以维护和测试

### **重构后（新架构）**

```
┌─────────────────────────────────────────┐
│              View Layer                  │
│  - 接收HTTP请求                          │
│  - 参数验证                              │
│  - 调用Service层                         │
│  - 返回HTTP响应                          │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│            Service Layer                 │
│  - AgentService                          │
│  - CertificateService                    │
│  - AgentUpgradeService                   │
│  - DeploymentService                     │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│          AnsibleExecutor                 │
│  - execute_via_ssh()                     │
│  - execute_via_agent()                   │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│       Ansible Playbooks (统一)          │
│  - install_agent.yml                     │
│  - upgrade_agent.yml                     │
│  - deploy_xray.yml                       │
│  - deploy_caddy.yml                      │
└─────────────────────────────────────────┘
```

**优势**：
- ✅ 清晰的分层架构
- ✅ 统一使用Ansible（SSH和Agent逻辑一致）
- ✅ 代码复用，易于维护
- ✅ 便于单元测试
- ✅ 符合架构设计原则

---

## 📝 使用示例

### 1. 安装Agent（通过DeploymentService）

```python
from apps.deployments.services import DeploymentService

# 创建部署任务
deployment = Deployment.objects.create(
    name=f"安装Agent - {server.name}",
    server=server,
    deployment_type='agent',
    status='running',
    created_by=user
)

# 调用Service安装Agent
success, message = DeploymentService.install_agent(
    server=server,
    deployment=deployment,
    user=user
)

if success:
    # 等待Agent启动
    agent = DeploymentService.wait_for_agent_startup(
        server=server,
        timeout=60,
        deployment=deployment
    )
```

### 2. Agent自升级（通过AgentUpgradeService）

```python
from apps.agents.services.upgrade_service import AgentUpgradeService

# Agent在线：通过Agent自升级
if agent.status == 'online':
    success, message = AgentUpgradeService.upgrade_via_agent(
        agent=agent,
        deployment=deployment,
        user=request.user
    )
else:
    # Agent离线：通过SSH升级
    success, message = AgentUpgradeService.upgrade_via_ssh(
        server=agent.server,
        deployment=deployment,
        user=request.user
    )
```

### 3. 部署Xray/Caddy（通过DeploymentService）

```python
from apps.deployments.services import DeploymentService

# 部署Xray（自动选择SSH或Agent方式）
success, message = DeploymentService.deploy_service(
    server=server,
    service_type='xray',
    deployment_target='docker',  # 'host' 或 'docker'
    deployment=deployment,
    user=request.user
)
```

### 4. 更新证书（通过CertificateService）

```python
from apps.agents.services import CertificateService

# 重新生成证书
success, message = CertificateService.regenerate_agent_certificate(
    agent=agent,
    verify_ssl=False,
    user=request.user
)
```

### 5. 执行命令（通过AgentService）

```python
from apps.agents.services import AgentService

# 发送命令
cmd = AgentService.send_command(
    agent=agent,
    command='systemctl',
    args=['restart', 'myx-agent'],
    timeout=30,
    user=request.user
)
```

---

## 🚀 迁移步骤

### 阶段1：测试新Service层（不影响现有功能）

1. **保留现有代码不动**
2. **测试新的Service方法**：
   ```python
   # 在Django shell中测试
   from apps.agents.services import AgentService
   from apps.servers.models import Server

   server = Server.objects.first()
   agent = AgentService.create_or_get_agent(server)
   print(f"Agent创建成功: {agent.token}")
   ```

3. **测试AnsibleExecutor**：
   ```python
   from apps.deployments.services.ansible_executor import AnsibleExecutor

   executor = AnsibleExecutor(server)
   success, output = executor.execute_playbook(
       playbook_name='install_agent.yml',
       extra_vars={'agent_token': agent.token, ...},
       method='ssh'
   )
   ```

### 阶段2：逐步替换View层调用

1. **替换简单方法**（如send_command, stop, start）：
   ```python
   # 旧代码
   from .command_queue import CommandQueue
   cmd = CommandQueue.add_command(agent, command, args, timeout)

   # 新代码
   from .services import AgentService
   cmd = AgentService.send_command(agent, command, args, timeout, user)
   ```

2. **替换复杂方法**（如redeploy, update_certificate）：
   - 参考 `views_refactored.py` 中的示例
   - 将整个方法体替换为Service调用

3. **逐个替换并测试**，确保功能正常

### 阶段3：清理旧代码

1. **删除旧的Bash脚本生成逻辑**（tasks.py:618-774）
2. **删除View中的业务逻辑**
3. **删除重复的工具函数**（RPC端口生成、Token生成等）
4. **更新agent_deployer.py**，改为调用DeploymentService

### 阶段4：优化部署工具同步

当前`deployment_tool.py`的`check_deployment_tool_version()`总是返回False（第113-117行）。

**优化建议**：
```python
# backend/apps/deployments/deployment_tool.py:107-119

def check_deployment_tool_version(agent: Agent, force_sync: bool = False) -> bool:
    # ... 现有逻辑 ...

    # 检查playbooks的hash
    current_playbooks_hash = get_playbooks_hash()
    if current_playbooks_hash:
        # 如果Agent有hash记录且匹配，则不需要同步
        if agent.deployment_tool_playbooks_hash == current_playbooks_hash:
            logger.info(f"Agent {agent.id} playbooks版本一致，无需同步")
            return True
        else:
            logger.info(f"Agent {agent.id} playbooks版本不一致，需要同步")
            return False

    return True
```

**需要添加字段**：
```python
# backend/apps/agents/models.py

class Agent(models.Model):
    # ... 现有字段 ...
    deployment_tool_playbooks_hash = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        verbose_name='部署工具Playbooks哈希'
    )
```

---

## ✅ 重构成果总结

### 已完成

- ✅ 创建Service层目录结构
- ✅ 创建AnsibleExecutor统一执行Ansible
- ✅ 创建install_agent.yml替代Bash脚本
- ✅ 创建upgrade_agent.yml实现自升级（含失败回滚）
- ✅ 创建AgentService管理Agent
- ✅ 创建CertificateService管理证书
- ✅ 创建AgentUpgradeService实现升级逻辑
- ✅ 创建DeploymentService封装部署逻辑
- ✅ 创建View重构示例（views_refactored.py）

### 待完成（后续工作）

1. **替换现有View**：
   - 将`agents/views.py`中的业务逻辑替换为Service调用
   - 参考`views_refactored.py`中的示例

2. **更新tasks.py**：
   - 将`install_agent_via_ssh()`改为调用`DeploymentService.install_agent()`
   - 删除Bash heredoc脚本生成逻辑

3. **更新agent_deployer.py**：
   - 将`deploy_via_agent()`改为调用`DeploymentService.deploy_service()`

4. **优化部署工具同步**：
   - 实现真正的按需同步（参考上面的优化建议）
   - 添加`deployment_tool_playbooks_hash`字段

5. **添加单元测试**：
   - 测试Service层方法
   - 测试AnsibleExecutor
   - 测试Playbook执行

6. **更新文档**：
   - API文档
   - 部署文档
   - 故障排查文档

---

## 🔧 测试建议

### 1. 测试Agent安装

```bash
# 在Django shell中
python manage.py shell

from apps.servers.models import Server
from apps.deployments.models import Deployment
from apps.deployments.services import DeploymentService
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.first()
server = Server.objects.first()

deployment = Deployment.objects.create(
    name="测试Agent安装",
    server=server,
    deployment_type='agent',
    status='running',
    created_by=user
)

success, message = DeploymentService.install_agent(server, deployment, user)
print(f"结果: {success}, 消息: {message}")
print(f"日志:\n{deployment.log}")
```

### 2. 测试Agent升级

```bash
from apps.agents.models import Agent
from apps.agents.services.upgrade_service import AgentUpgradeService

agent = Agent.objects.first()
success, message = AgentUpgradeService.upgrade_via_agent(agent, None, user)
print(f"结果: {success}, 消息: {message}")
```

### 3. 测试Ansible执行器

```bash
from apps.deployments.services.ansible_executor import AnsibleExecutor

executor = AnsibleExecutor(server)
success, output = executor.execute_playbook(
    playbook_name='install_agent.yml',
    extra_vars={'agent_token': 'test-token', ...},
    method='ssh',
    timeout=600
)
print(f"结果: {success}\n输出:\n{output}")
```

---

## 📚 参考文档

- [架构文档](ARCHITECTURE.md) - 整体架构设计原则
- [Agent设计](ARCHITECTURE.md#21-agent-端deployment-toolagent) - Agent无状态设计
- [Ansible文档](https://docs.ansible.com/) - Ansible playbook语法

---

**最后更新**: 2025-01-05
**重构版本**: v1.0
**状态**: ✅ Service层和Playbooks已完成，待集成到现有代码
