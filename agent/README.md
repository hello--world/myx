# MyX Agent

MyX Agent 是一个用 Go 开发的轻量级代理程序，用于在目标服务器上执行部署任务和管理操作。

## 功能特性

- 🔐 **加密通信**: 使用 AES-256-GCM 加密所有通信
- 💓 **心跳机制**: 定期发送心跳保持连接
- 📡 **命令执行**: 接收并执行来自控制中心的命令
- 🚀 **自动注册**: 首次运行自动注册到控制中心
- 🔄 **状态同步**: 实时同步执行状态和日志

## 安装

### 编译

```bash
cd agent
go mod download
go build -o myx-agent main.go
```

### 首次注册

```bash
./myx-agent -token <服务器ID> -api http://your-server:8000/api/agents
```

首次运行会：
1. 向控制中心注册
2. 获取 Agent Token 和加密密钥
3. 保存配置文件到 `/etc/myx-agent/config.json`

### 运行 Agent

```bash
# 使用配置文件运行
./myx-agent

# 或指定配置文件路径
./myx-agent -config /path/to/config.json
```

## 系统服务

### systemd 服务文件

创建 `/etc/systemd/system/myx-agent.service`:

```ini
[Unit]
Description=MyX Agent
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/myx-agent
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl enable myx-agent
sudo systemctl start myx-agent
sudo systemctl status myx-agent
```

## 配置

配置文件位于 `/etc/myx-agent/config.json`:

```json
{
  "ServerToken": "服务器ID",
  "SecretKey": "加密密钥",
  "APIURL": "http://your-server:8000/api/agents",
  "AgentToken": "Agent Token"
}
```

## 通信协议

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

## 安全

- 所有通信使用 AES-256-GCM 加密
- Agent Token 用于身份验证
- 配置文件权限设置为 600（仅所有者可读）

## 许可证

MIT License

