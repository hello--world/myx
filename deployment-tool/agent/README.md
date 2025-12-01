# MyX Agent - Python版本

Python版本的MyX Agent，与Go版本功能完全兼容，支持实时上报。

## 特性

- ✅ 与Go版本API完全兼容
- ✅ 实时上报命令执行输出（每2秒）
- ✅ 支持推送和拉取两种心跳模式
- ✅ 自动重试机制
- ✅ 配置文件管理
- ✅ systemd服务支持
- ✅ **仅支持宿主机安装**（不支持Docker容器）

## 安装方式

**重要说明：** Agent 仅支持在宿主机上安装运行，不支持 Docker 容器部署。Agent 需要在宿主机上执行部署任务和管理服务，因此必须直接运行在宿主机上。

### 方式一：通过Web界面自动安装（推荐）

1. 在 MyX 平台的"服务器管理"页面添加服务器
2. 选择"部署方式"为 "Agent"
3. 点击"安装Agent"按钮
4. 系统会自动通过SSH安装Agent到宿主机

### 方式二：手动安装

### 1. 安装依赖

```bash
pip3 install -r requirements.txt
```

### 2. 注册Agent

```bash
python3 main.py --token <server_token> --api <api_url>
```

例如：
```bash
python3 main.py --token 123 --api http://your-server.com:8000/api/agents
```

### 3. 运行Agent

```bash
python3 main.py
```

## 配置

配置文件默认位置：`/etc/myx-agent/config.json`

配置文件格式：
```json
{
  "server_token": "服务器Token",
  "secret_key": "加密密钥",
  "api_url": "http://your-server.com:8000/api/agents",
  "agent_token": "Agent Token",
  "heartbeat_mode": "push",
  "heartbeat_min_interval": 30,
  "heartbeat_max_interval": 300,
  "poll_min_interval": 5,
  "poll_max_interval": 60
}
```

## systemd服务

创建systemd服务文件：`/etc/systemd/system/myx-agent.service`

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
systemctl daemon-reload
systemctl enable myx-agent
systemctl start myx-agent
```

## 与Go版本的差异

- Python版本更容易更新和调试
- 代码更易读，便于维护
- 实时上报机制相同
- API完全兼容

## 日志

日志文件：`/var/log/myx-agent.log`

查看日志：
```bash
tail -f /var/log/myx-agent.log
```

## 故障排除

1. **无法连接服务器**
   - 检查网络连接
   - 检查API地址是否正确
   - 检查防火墙设置

2. **注册失败**
   - 检查server_token是否正确
   - 检查服务器是否在线
   - 查看日志文件

3. **命令执行失败**
   - 检查Agent是否有执行权限
   - 检查命令路径是否正确
   - 查看日志文件


