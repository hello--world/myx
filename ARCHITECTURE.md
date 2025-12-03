# MyX 项目架构文档

## 1. 整体架构概述

MyX 是一个基于 Agent 的服务器管理和部署系统，采用**服务器主动、Agent 被动**的架构模式。

### 核心设计原则

1. **Agent 完全无状态**：Agent 不知道服务器的存在，不主动连接服务器
2. **服务器主动管理**：服务器主动连接 Agent，发送心跳和命令
3. **JSON-RPC 通信**：使用 JSON-RPC 2.0 协议进行双向通信
4. **配置由服务器分配**：Agent 的 Token 和 RPC 端口由服务器在部署时生成

## 2. 组件架构

### 2.1 Agent 端（deployment-tool/agent/）

#### 主要文件
- `main.py`: Agent 主程序，启动 JSON-RPC 服务器
- `rpc_server.py`: JSON-RPC 2.0 服务器实现
- `ansible_executor.py`: Ansible 执行器（使用 ansible-runner）
- `requirements.txt`: Python 依赖列表

**部署时上传的文件**：

**阶段1：Agent核心文件**（通过SSH SFTP上传到 `/opt/myx-agent/`）：
- `main.py`（必需）
- `requirements.txt`（必需）
- `rpc_server.py`（必需，main.py 导入）
- `ansible_executor.py`（必需，main.py 导入）
- 其他被 main.py 直接或间接导入的 Python 模块文件

**阶段2：部署工具目录**（Agent启动后，通过Agent命令上传到 `/opt/myx-deployment-tool/`）：
- **整个 `deployment-tool` 目录**打包为 tar.gz 上传
- 包含：
  - `playbooks/`：Ansible playbook 文件
    - `deploy_xray.yml`：Xray 部署 playbook
    - `deploy_xray_docker.yml`：Xray Docker 部署 playbook
    - `deploy_xray_config.yml`：Xray 配置部署 playbook
    - `deploy_caddy.yml`：Caddy 部署 playbook
  - `scripts/`：部署脚本
    - `deploy_xray.py`：Xray 部署脚本
    - `deploy_caddy.py`：Caddy 部署脚本
    - `check_service.py`：服务检查脚本
    - `install_ansible.sh`：Ansible 安装脚本
  - `inventory/`：Ansible inventory 文件
    - `localhost.ini`：本地主机 inventory
  - `ansible.cfg`：Ansible 配置文件
  - `VERSION`：版本文件
- 通过 `sync_deployment_tool_to_agent()` 函数同步
- 用于执行实际的部署任务（Xray、Caddy等服务的安装和配置）

#### Agent 配置（/etc/myx-agent/config.json）
```json
{
    "agent_token": "服务器分配的Token",
    "secret_key": "服务器分配的加密密钥",
    "rpc_port": 24351,  // 服务器分配的RPC端口（首次启动时确定，不可更改）
    "rpc_path": "a3f8b9c2d1e4"  // 服务器分配的随机RPC路径（用于路径混淆，保障安全）
}
```

#### Agent 行为
- **启动时**：
  1. 读取配置文件（`/etc/myx-agent/config.json`）
  2. 从配置文件读取 `rpc_port`（**必须由服务器在部署时指定，Agent不会自己生成**）
  3. 如果 `rpc_port` 不存在，启动失败并报错（端口必须由服务器分配）
  4. 启动 JSON-RPC 服务器（HTTPS，使用自签名证书，端口=配置文件中的rpc_port）
  5. **被动等待**服务器连接

- **运行时**：
  - 不主动连接服务器
  - 不主动发送心跳
  - 不主动轮询命令
  - 只响应服务器的 JSON-RPC 请求

#### JSON-RPC 方法（Agent 提供）
- **端点路径**：`/{rpc_path}/rpc`（`rpc_path` 由服务器在部署时分配，每个Agent不同）
- `health_check()`: 健康检查
- `heartbeat()`: 接收服务器心跳
- `get_status()`: 获取 Agent 状态
- `execute_command(command, args, timeout, command_id)`: 执行系统命令
  - **立即执行**：命令立即开始执行，不等待
  - **异步执行**：命令在后台执行，日志存储在本地缓冲区
  - **立即返回**：返回 `{status: 'running', command_id: ...}`，不等待命令完成
  - **日志获取**：服务器通过 `get_command_log` 主动获取日志
- `get_command_log(command_id, offset)`: 获取命令执行日志（服务器主动调用，用于实时日志流式传输）
  - `command_id`：命令ID
  - `offset`：已读取的字节数（用于增量获取，避免重复）
  - 返回：`{log_data, log_type, new_offset, is_final, result}`
    - `log_data`：日志内容（stdout 和 stderr 的增量数据）
    - `log_type`：日志类型（'stdout' 或 'stderr'）
    - `new_offset`：新的偏移量（用于下次调用）
    - `is_final`：是否为最后一条日志（命令执行完成）
    - `result`：如果 `is_final=True`，包含最终结果（success, stdout, stderr, return_code）
- `execute_ansible(playbook, extra_vars, timeout)`: 执行 Ansible playbook
- `get_port()`: 获取 RPC 端口

### 2.2 服务器端（backend/apps/）

#### 核心模块

**agents/**
- `models.py`: Agent 数据模型
  - `Agent`: 存储 Agent 信息（Token、RPC端口、支持状态等）
  - `AgentCommand`: 命令执行记录
- `rpc_client.py`: JSON-RPC 客户端（连接 Agent）
- `command_queue.py`: 命令队列管理
- `heartbeat_scheduler.py`: 心跳调度器（服务器主动发送心跳）
- `scheduler.py`: 心跳调度器启动逻辑（Django App 启动时自动启动）
- `rpc_support.py`: RPC 服务可用性检查（用于等待 Agent 启动）
- `apps.py`: Django App 配置（启动心跳调度器）

**deployments/**
- `tasks.py`: 部署任务
  - `install_agent_via_ssh()`: 通过 SSH 安装 Agent
  - `wait_for_agent_startup()`: 等待 Agent 启动并检查 RPC 服务是否可用
- `agent_deployer.py`: Agent 部署器

**servers/**
- `models.py`: 服务器数据模型
- `views.py`: 服务器管理视图

## 3. 通信流程

### 3.1 Agent 部署流程

```
1. 用户通过 Web 界面添加服务器（提供 SSH 凭证）
   ↓
2. 服务器端创建 Agent 记录
   - 生成 agent_token（随机字符串）
   - 生成 secret_key（加密密钥）
   - 生成 rpc_port（随机端口，8000-65535，排除常用端口，检查数据库确保唯一）
   - 生成 rpc_path（随机路径字符串，16-32字符，用于路径混淆，保障安全）
   ↓
3. 通过 SSH 连接目标服务器
   - 服务器通过SSH检查目标服务器端口可用性（可选，但建议）
   ↓
4. 上传 Agent 核心文件（通过SSH SFTP上传到 `/opt/myx-agent/`）
   - main.py（Agent主程序）
   - requirements.txt（Python依赖列表）
   - rpc_server.py（JSON-RPC服务器实现）
   - ansible_executor.py（Ansible执行器）
   - 其他被 main.py 直接或间接导入的 Python 模块文件
   ↓
5. 创建配置文件（/etc/myx-agent/config.json）
   - 写入 agent_token（服务器分配）
   - 写入 secret_key（服务器分配）
   - 写入 rpc_port（**服务器分配，Agent必须使用此端口，不可更改**）
   - 写入 rpc_path（**服务器分配，Agent必须使用此路径，不可更改**）
   ↓
6. 创建 systemd 服务（myx-agent.service）
   ↓
7. 启动 systemd 服务
   ↓
8. Agent 启动，读取配置文件
   ↓
9. Agent 启动 JSON-RPC 服务器（HTTPS，端口=rpc_port，路径=/{rpc_path}/rpc）
   ↓
10. 服务器端等待 Agent 启动
    - 每 3 秒检查一次 Agent RPC 服务是否可用
    - 每 10 秒输出进度日志
    - 使用完整路径 `https://agent_ip:rpc_port/{rpc_path}/rpc` 进行连接
    - 超时时间：30-120 秒（根据调用场景）
    - **如果超时或 RPC 不可用，触发 Agent 重新安装**
   ↓
11. Agent 启动成功，RPC 服务可用
   ↓
12. 同步部署工具目录到 Agent（可选，按需同步）
    - 通过 Agent 命令执行 `sync_deployment_tool_to_agent()`
    - 将整个 `deployment-tool` 目录打包为 tar.gz
    - 上传到 Agent 端的 `/opt/myx-deployment-tool/` 目录
    - 包含：playbooks/、scripts/、inventory/、ansible.cfg、VERSION 等
    - 用于后续的部署任务执行（Xray、Caddy等服务的安装和配置）
```

### 3.2 心跳机制

**服务器主动发送心跳**（随机间隔 + 重试机制）

```
1. Django App 启动时（apps.py.ready()），自动启动心跳调度器（后台线程）
   ↓
2. heartbeat_scheduler.check_all_agents_heartbeat() 定期运行
   ↓
3. 遍历所有 Agent（随机顺序，避免同时检查）
   ↓
4. 对每个 Agent（带重试机制）：
   - 尝试连接 Agent 的 RPC 端口（最多重试 3 次）
   - 重试策略：指数退避（1秒、2秒、4秒）
   - 调用 heartbeat() JSON-RPC 方法
   - 获取 Agent 状态（get_status()）
   - 更新 Agent 的 last_heartbeat、status、version 等
   - 如果所有重试都失败，标记 Agent 为 offline
   ↓
5. 等待随机时间（20-60 秒，可配置）
   ↓
6. 重复步骤 2-5
```

**启动机制**：
- Django App (`apps/agents/apps.py`) 的 `ready()` 方法中启动
- 使用独立的后台线程运行
- 应用启动时自动开始，无需手动启动

**心跳间隔**：
- 最小间隔：20 秒（AGENT_HEARTBEAT_MIN_INTERVAL）
- 最大间隔：60 秒（AGENT_HEARTBEAT_MAX_INTERVAL）
- 实际间隔：随机值（min_interval 到 max_interval）

**心跳重试机制**：
- **重试次数**：最多 3 次
- **重试间隔**：指数退避策略
  - 第 1 次重试：等待 1 秒
  - 第 2 次重试：等待 2 秒
  - 第 3 次重试：等待 4 秒
- **重试条件**：
  - 网络连接失败（ConnectionError, Timeout）
  - JSON-RPC 调用失败（非认证错误）
  - 临时性错误（5xx 错误、SSL 握手失败等）
- **不重试的情况**：
  - 认证失败（401 Unauthorized）- 立即标记为 offline
  - 配置错误（400 Bad Request）- 立即标记为 offline
- **失败处理**：
  - 所有重试都失败后，标记 Agent 为 `offline`
  - 记录失败日志，包含失败原因和重试次数
  - 下次心跳周期继续尝试（不会因为一次失败就永久标记为离线）

### 3.3 命令执行流程

```
1. 服务器端需要执行命令
   ↓
2. CommandQueue.add_command()
   - 创建 AgentCommand 记录（status='running'）
   - 立即开始执行，不等待
   ↓
3. 使用 AgentRPCClient 连接 Agent（带重试机制）
   - **所有 Agent 都必须支持 RPC**（如果不支持，触发重新安装）
   - 构建完整 URL：`https://agent_ip:rpc_port/{rpc_path}/rpc`
   - **立即调用** execute_command() JSON-RPC 方法（最多重试 3 次）
   - 重试策略：指数退避（1秒、2秒、4秒）
   - 传递：command, args, timeout, command_id
   - **如果 RPC 不可用或连接失败**：触发 Agent 重新安装
   ↓
4. Agent 立即执行命令（带流式日志）
   - **立即启动命令执行**（subprocess.Popen）
   - **实时读取 stdout/stderr**（后台线程，逐行或逐块读取）
   - **日志存储在本地缓冲区**（内存中，按 command_id 索引）
   - **立即返回**：返回 `{status: 'running', command_id: ...}`，不等待命令完成
   - 命令执行完成后，最终结果也存储在缓冲区
   ↓
5. 服务器端主动获取日志和结果
   - **启动日志轮询任务**：每1秒调用一次 `get_command_log` JSON-RPC 方法
   - **增量获取日志**：使用 `offset` 参数避免重复获取
   - **实时更新 `AgentCommand.result`**：追加模式（`append=True`）
   - **实时推送日志到前端**：前端可以立即看到命令输出（如同本地终端执行）
   - **接收最终结果**：当 `is_final=True` 时，更新 `AgentCommand` 记录
   - status = 'success' 或 'failed'
   - 保存完整的 stdout, stderr, return_code
   ↓
6. 前端实时显示日志（如同本地终端）
   - 通过轮询 `AgentCommand.result` 或 WebSocket 实时获取日志
   - **命令一开始执行，前端立即开始显示输出**
   - 实时显示命令执行进度和输出（逐行显示）
   - 命令完成后显示最终结果和状态
   ↓
7. 完成
```

**注意**：
- 命令是**立即执行**的，不等待，执行过程中日志存储在 Agent 本地缓冲区
- **日志是流式传输的**，服务器每1秒主动获取一次，用户可以实时查看（如同在本地终端执行命令）
- 前端可以实时看到命令输出，不需要等待命令完成
- **所有 Agent 都必须支持 RPC**：如果 RPC 不可用或连接失败，系统会自动触发 Agent 重新安装

**日志流式传输**（当前架构要求）：
- **实现方式**：服务器主动轮询（符合 Agent 无状态设计）
  - Agent 端：命令执行时实时读取 stdout/stderr，存储在本地内存缓冲区（按 command_id 索引）
  - 服务器端：每1秒调用一次 `get_command_log` JSON-RPC 方法，获取增量日志，实时更新 `AgentCommand.result`（增量追加，`append=True`）
  - 前端：通过轮询 `AgentCommand.result` 或 WebSocket 实时获取并显示日志
- **JSON-RPC 方法**：
  - `get_command_log(command_id, offset)`：服务器主动调用，获取命令日志
    - `command_id`：命令ID
    - `offset`：已读取的字节数（用于增量获取，避免重复）
    - 返回：`{log_data, log_type, new_offset, is_final, result}`
      - `log_data`：日志内容（stdout 和 stderr 的增量数据）
      - `log_type`：日志类型（'stdout' 或 'stderr'）
      - `new_offset`：新的偏移量（用于下次调用）
      - `is_final`：是否为最后一条日志（命令执行完成）
      - `result`：如果 `is_final=True`，包含最终结果（success, stdout, stderr, return_code）
- **工作流程**：
  1. Agent **立即启动命令执行**（subprocess.Popen），不等待
  2. Agent 启动后台线程**实时读取 stdout/stderr**（逐行或逐块读取），存储在本地缓冲区
  3. 服务器端**启动日志轮询任务**（后台线程），每1秒调用一次 `get_command_log`
  4. Agent **返回增量日志**（从 `offset` 开始的新数据）
  5. 服务器端**立即更新 `AgentCommand.result`**（追加模式）
  6. 前端**立即通过轮询或 WebSocket 获取并显示日志**（如同本地终端，实时逐行显示）
  7. 命令执行完成后，Agent 在缓冲区标记 `completed=True`，服务器获取到 `is_final=True` 时更新最终状态
- **优势**：
  - 符合 Agent 无状态设计（Agent 不主动推送，只被动响应）
  - 用户可以实时看到命令执行进度
  - 长时间运行的命令不会让用户等待
  - 更好的用户体验
  - 便于问题排查（可以实时看到错误信息）

**命令执行重试机制**：
- **重试次数**：最多 3 次
- **重试间隔**：指数退避策略
  - 第 1 次重试：等待 1 秒
  - 第 2 次重试：等待 2 秒
  - 第 3 次重试：等待 4 秒
- **重试条件**：
  - 网络连接失败（ConnectionError, Timeout）
  - JSON-RPC 调用失败（非认证错误）
  - 临时性错误（5xx 错误、SSL 握手失败等）
  - Agent 暂时不可用（但 Agent 已部署且应该支持 RPC）
- **不重试的情况**：
  - 认证失败（401 Unauthorized）- 立即标记命令为 failed
  - 命令执行超时（Agent 返回超时错误）- 立即标记命令为 failed
  - 命令执行失败（Agent 返回 success=false）- 不重试，直接标记为 failed
- **失败处理**：
  - 所有重试都失败后，标记命令为 `failed`
  - 记录失败日志，包含失败原因和重试次数
  - 如果连续失败，触发 Agent 重新安装（所有 Agent 都必须支持 RPC）
- **超时处理**：
  - 每次重试都有独立的超时时间（默认 30 秒）
  - 如果命令执行超时（由 Agent 返回），不进行重试
  - 总重试时间 = 重试次数 × (重试间隔 + 超时时间)

### 3.4 Ansible 执行流程

```
1. 服务器端需要执行 Ansible playbook
   ↓
2. 通过 AgentRPCClient 调用 execute_ansible()
   - 传递：playbook 路径、extra_vars、timeout
   ↓
3. Agent 端使用 ansible-runner 执行 playbook
   - 返回执行结果
   ↓
4. 服务器端接收结果
```

## 4. 数据模型

### 4.1 Agent 模型

```python
class Agent(models.Model):
    server = OneToOneField(Server)  # 关联的服务器
    token = CharField()  # Agent Token（服务器分配）
    secret_key = CharField()  # 加密密钥（服务器分配）
    status = CharField()  # 'online' | 'offline'
    rpc_port = IntegerField(unique=True)  # RPC端口（服务器分配，不可更改）
    rpc_path = CharField()  # RPC随机路径（服务器分配，用于路径混淆，保障安全）
    rpc_supported = BooleanField()  # 是否支持JSON-RPC
    rpc_last_check = DateTimeField()  # 最后检查时间
    rpc_last_success = DateTimeField()  # 最后成功时间
    last_heartbeat = DateTimeField()  # 最后心跳时间
    # ... 其他字段
```

### 4.2 AgentCommand 模型

```python
class AgentCommand(models.Model):
    agent = ForeignKey(Agent)
    command = CharField()  # 命令
    args = JSONField()  # 参数列表
    status = CharField()  # 'pending' | 'running' | 'success' | 'failed'
    result = TextField()  # stdout（Base64编码）
    error = TextField()  # stderr（Base64编码）
    exit_code = IntegerField()  # 退出码
    # ... 时间戳字段
```

## 5. 安全机制

### 5.1 身份验证

- **Token 验证**：服务器连接 Agent 时，在 HTTP Header 中传递 `X-Agent-Token`
- **Agent 验证**：Agent 的 JSON-RPC 服务器验证 Token 是否匹配配置文件中的 `agent_token`

### 5.2 通信加密

- **HTTPS**：Agent 的 JSON-RPC 服务器使用 HTTPS（自签名证书）
- **证书生成**：Agent 首次启动时自动生成自签名证书
  - 证书路径：`/etc/myx-agent/ssl/agent.crt`
  - 私钥路径：`/etc/myx-agent/ssl/agent.key`

### 5.3 RPC 路径安全（路径混淆）

- **随机路径**：每个 Agent 的 JSON-RPC 端点使用随机路径，格式为：`/随机path/rpc`
  - 例如：`/a3f8b9c2d1e4/rpc`、`/x7k2m9p4q6/rpc`
  - 路径在部署时由服务器生成（随机字符串，长度建议 16-32 字符）
  - 路径写入 Agent 配置文件：`/etc/myx-agent/config.json` 的 `rpc_path` 字段
  - 路径存储在服务器端 Agent 模型的 `rpc_path` 字段中
- **安全优势**：
  - 防止路径扫描攻击
  - 即使知道 Agent 的 IP 和端口，不知道随机路径也无法访问
  - 每个 Agent 的路径都不同，即使一个路径泄露也不影响其他 Agent
- **实现要求**：
  - Agent 端：根据配置文件中的 `rpc_path` 动态注册路由（如：`@app.route('/{rpc_path}/rpc')`）
  - 服务器端：使用 Agent 记录中的 `rpc_path` 构建完整 URL（如：`https://agent_ip:port/{rpc_path}/rpc`）
  - 如果配置文件中没有 `rpc_path`，Agent 启动失败（与 `rpc_port` 一样，必须由服务器分配）

### 5.4 配置安全

- 配置文件权限：`600`（仅 root 可读）
- Secret Key：用于未来可能的加密通信

## 6. 错误处理和容错

### 6.1 Agent 启动失败

- 部署时：`wait_for_agent_startup()` 会等待并检查
- 超时后：标记部署失败，记录错误日志

### 6.2 RPC 连接失败

- **心跳失败**：
  - 使用重试机制（最多 3 次，指数退避）
  - 所有重试都失败后，标记 Agent 为 `offline`
  - 下次心跳周期继续尝试（不会永久标记为离线）
- **命令执行失败**：
  - 使用重试机制（最多 3 次，指数退避）
  - 所有重试都失败后，标记命令为 `failed`
  - 记录失败日志，包含重试次数和失败原因

### 6.3 网络问题

- **连接超时**：
  - 心跳：每次调用超时时间 30 秒
  - 命令执行：每次调用超时时间 30 秒（命令本身的 timeout 由参数指定）
- **重试机制**：
  - 心跳：指数退避（1秒、2秒、4秒），最多 3 次
  - 命令执行：指数退避（1秒、2秒、4秒），最多 3 次
  - 心跳调度器会定期重试（每个心跳周期都会尝试）

### 6.4 重试策略总结

**通用重试策略**：
- **重试次数**：3 次
- **重试间隔**：指数退避（1秒、2秒、4秒）
- **总重试时间**：最多 7 秒（1+2+4）+ 每次调用的超时时间

**适用场景**：
- ✅ 网络连接失败（ConnectionError）
- ✅ 请求超时（Timeout）
- ✅ 临时性服务器错误（5xx）
- ✅ SSL 握手失败（临时性）
- ❌ 认证失败（401）- 不重试
- ❌ 请求格式错误（400）- 不重试
- ❌ 命令执行失败（Agent 返回 success=false）- 不重试
- ❌ 命令执行超时（Agent 返回超时）- 不重试

**重试日志**：
- 记录每次重试的详细信息（重试次数、失败原因、等待时间）
- 所有重试都失败后，记录最终失败原因
- 便于问题排查和性能分析

## 7. 关键配置

### 7.1 服务器端配置（Django settings）

```python
AGENT_HEARTBEAT_MIN_INTERVAL = 20  # 心跳最小间隔（秒）
AGENT_HEARTBEAT_MAX_INTERVAL = 60  # 心跳最大间隔（秒）
AGENT_RPC_RETRY_MAX_ATTEMPTS = 3  # RPC调用最大重试次数（默认3次）
AGENT_RPC_RETRY_BASE_DELAY = 1  # 重试基础延迟（秒，指数退避的基数）
AGENT_RPC_TIMEOUT = 30  # RPC调用超时时间（秒）
```

### 7.2 Agent 端配置

- 配置文件：`/etc/myx-agent/config.json`
  - **重要**：`rpc_port` 和 `rpc_path` 必须由服务器在部署时指定，Agent不会自己生成
  - 如果配置文件中缺少 `rpc_port` 或 `rpc_path`，Agent启动会失败
  - `rpc_path` 用于路径混淆，保障安全（每个Agent的路径都不同）
- 证书目录：`/etc/myx-agent/ssl/`
- 工作目录：`/opt/myx-agent/`

## 8. 部署流程总结

### 8.1 首次部署

1. 用户添加服务器（SSH 凭证）
2. 服务器创建 Agent 记录（生成 Token 和 RPC 端口）
3. 通过 SSH 安装 Agent
4. Agent 启动，服务器等待并验证
5. 部署完成

### 8.2 Agent 重新部署

1. 用户触发重新部署
2. 通过 SSH 更新 Agent 文件
3. 重启 systemd 服务
4. Agent 重新启动（使用相同的 RPC 端口）
5. 服务器验证 Agent 状态

## 9. 架构特点

### 9.1 优势

1. **Agent 无状态**：Agent 不需要知道服务器地址，配置简单
2. **服务器主动管理**：服务器完全控制通信时机
3. **安全性高**：HTTPS + Token 验证
4. **可扩展**：JSON-RPC 协议易于扩展新方法

### 9.2 限制

1. **Agent 必须可被服务器访问**：服务器需要能连接到 Agent 的 RPC 端口
2. **防火墙配置**：需要确保 Agent 的 RPC 端口可访问
3. **命令执行**：命令立即执行，执行过程中实时推送日志（如同本地终端执行，可以实时查看输出）

## 10. 未来可能的改进

1. **异步命令执行**：支持长时间运行的命令，通过 WebSocket 实时返回结果
2. **命令队列**：Agent 端维护命令队列，支持批量执行
3. **多服务器管理**：支持 Agent 连接多个服务器（如果需要）
4. **WebSocket 日志传输**：使用 WebSocket 替代 JSON-RPC 轮询，实现更高效的实时日志传输

---

**最后更新**：2025-01-03
**架构版本**：v2.0（无状态 Agent + JSON-RPC）

