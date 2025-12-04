# Agent 系统文档

## 概述

MyX Agent 系统允许在目标服务器上安装轻量级 Agent 程序，通过加密通信执行部署任务，无需每次输入 SSH 密码。

## 架构

### 组件

1. **Python Agent** (`deployment-tool/agent/`): 运行在目标服务器上的轻量级代理程序
2. **Django API** (`backend/apps/agents/`): Agent 管理 API
3. **命令队列** (`backend/apps/agents/command_queue.py`): 命令队列管理器
4. **部署集成** (`backend/apps/deployments/agent_deployer.py`): Agent 部署逻辑

### 通信流程

```
控制中心 (Django)          Agent (Python)
     |                         |
     |---- 注册请求 ----------->|
     |<--- Token + Secret -----|
     |                         |
     |<---- 心跳 (30s) --------|
     |---- 心跳响应 ---------->|
     |                         |
     |---- 命令入队 ----------->|
     |<---- 轮询命令 (5s) ------|
     |---- 返回命令 ----------->|
     |                         |
     |<---- 执行结果 -----------|
     |---- 确认接收 ----------->|
```

## 功能特性

### 1. Agent 注册

- Agent 首次运行时，使用服务器 ID 向控制中心注册
- 控制中心返回 Agent Token 和加密密钥
- 配置保存到 `/etc/myx-agent/config.json`

### 2. 心跳机制

- Agent 每 30 秒发送一次心跳
- 控制中心更新 Agent 状态和最后心跳时间
- 超过 60 秒未收到心跳，标记为离线

### 3. 命令执行

- 控制中心将命令添加到队列
- Agent 每 5 秒轮询一次待执行命令
- Agent 执行命令并返回结果
- 支持超时控制（默认 300 秒）

### 4. 加密通信

- 使用 AES-256-GCM 加密
- 密钥通过 PBKDF2 派生
- Agent Token 用于身份验证

## 部署方式

### SSH 部署（传统方式）
- 使用 Ansible 通过 SSH 执行部署脚本
- 需要每次提供 SSH 密码或密钥

### Agent 部署（推荐）
- 在服务器上安装 Agent
- 通过 Agent 执行命令，无需 SSH 密码
- 支持加密通信

### Docker 部署（计划中）
- 在 Docker 容器中部署 Xray 和 Caddy
- 便于管理和隔离

## 使用指南

### 1. 安装 Agent（通过 Web 界面，推荐）

1. 登录 MyX 平台
2. 进入"服务器管理"页面
3. 添加服务器，选择"部署方式"为 "Agent"
4. 点击"安装Agent"按钮
5. 系统会自动通过 SSH 安装 Agent 到宿主机

### 2. 手动安装 Agent

```bash
# 1. 下载 Agent 文件
curl -L http://your-backend:8000/api/agents/files/main.py/ -o /opt/myx-agent/main.py
curl -L http://your-backend:8000/api/agents/files/requirements.txt/ -o /opt/myx-agent/requirements.txt

# 2. 安装依赖
pip3 install -r /opt/myx-agent/requirements.txt

# 3. 设置权限
chmod +x /opt/myx-agent/main.py

# 4. 首次注册（需要服务器ID）
python3 /opt/myx-agent/main.py --token <服务器ID> --api http://your-server:8000/api/agents
```

### 3. 配置系统服务

创建 `/etc/systemd/system/myx-agent.service`:

```ini
[Unit]
Description=MyX Agent (Python)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/myx-agent
ExecStart=/usr/bin/python3 /opt/myx-agent/main.py
Restart=always
RestartSec=10
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable myx-agent
sudo systemctl start myx-agent
```

### 4. 在 Web 界面使用

1. **添加服务器**：
   - 在"服务器管理"页面添加服务器
   - 选择"部署方式"为 "Agent"

2. **安装 Agent**：
   - 在服务器上运行 Agent 注册命令
   - Agent 会自动注册到控制中心

3. **创建部署任务**：
   - 在"部署任务"页面创建新任务
   - 选择"部署方式"为 "Agent"
   - 系统会通过 Agent 执行部署

## API 接口

### 注册

```http
POST /api/agents/register/
Content-Type: application/json

{
  "server_token": "服务器ID",
  "version": "1.0.0",
  "hostname": "server1",
  "os": "linux"
}
```

### 心跳

```http
POST /api/agents/heartbeat/
X-Agent-Token: <Agent Token>
Content-Type: application/json

{
  "status": "online",
  "version": "1.0.0"
}
```

### 轮询命令

```http
GET /api/agents/poll/
X-Agent-Token: <Agent Token>
```

### 提交执行结果

```http
POST /api/agents/commands/<command_id>/result/
X-Agent-Token: <Agent Token>
Content-Type: application/json

{
  "success": true,
  "stdout": "命令输出",
  "stderr": "错误输出",
  "error": "错误信息（如果有）"
}
```

## 安全考虑

1. **Token 认证**: 每个 Agent 有唯一的 Token
2. **加密通信**: 使用 AES-256-GCM 加密
3. **配置文件权限**: 配置文件权限设置为 600
4. **超时控制**: 命令执行有超时限制
5. **命令验证**: 只执行来自控制中心的命令

## 故障排查

### Agent 无法注册

1. 检查服务器 ID 是否正确
2. 检查 API 地址是否可访问
3. 检查网络连接

### Agent 显示离线

1. 检查 Agent 是否正在运行
2. 检查心跳是否正常发送
3. 检查网络连接

### 命令执行失败

1. 检查 Agent 日志
2. 检查命令是否正确
3. 检查服务器权限

## 未来改进

- [ ] WebSocket 实时通信（替代轮询）
- [ ] Docker 部署支持
- [ ] 命令执行日志持久化
- [ ] Agent 自动更新
- [ ] 多 Agent 负载均衡
- [ ] 命令执行历史记录

