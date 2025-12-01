# MyX Release 说明

## Docker 容器使用

MyX 平台提供 Docker 容器镜像，方便快速部署 Backend 和 Frontend 服务。

### Docker 镜像地址

所有镜像托管在 GitHub Container Registry (ghcr.io)：

- **Backend**: `ghcr.io/hello--world/myx/backend:latest`
- **Frontend**: `ghcr.io/hello--world/myx/frontend:latest`

### 使用 Docker Compose 部署（推荐）

#### 1. 克隆仓库

```bash
git clone https://github.com/hello--world/myx.git
cd myx
```

#### 2. 配置环境变量

创建 `.env` 文件：

```bash
# GitHub仓库地址
GITHUB_REPO=hello--world/myx

# Django密钥（生产环境请使用强密码）
SECRET_KEY=your-secret-key-here

# 后端API地址（用于前端连接）
VITE_API_URL=http://localhost:8000/api

# 允许的主机（生产环境请设置实际域名）
ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com
```

#### 3. 启动服务

```bash
# 开发环境
docker-compose up -d

# 生产环境
docker-compose -f docker-compose.prod.yml up -d
```

#### 4. 访问服务

- **前端**: http://localhost
- **后端API**: http://localhost:8000/api

### 单独使用 Docker 镜像

#### Backend 服务

```bash
# 拉取镜像
docker pull ghcr.io/hello--world/myx/backend:latest

# 运行容器
docker run -d \
  --name myx-backend \
  -p 8000:8000 \
  -e SECRET_KEY="your-secret-key" \
  -e GITHUB_REPO="hello--world/myx" \
  -e ALLOWED_HOSTS="localhost,your-domain.com" \
  -v ./db.sqlite3:/app/db.sqlite3 \
  -v ./backend/media:/app/media \
  -v ./backend/staticfiles:/app/staticfiles \
  ghcr.io/hello--world/myx/backend:latest
```

#### Frontend 服务

```bash
# 拉取镜像
docker pull ghcr.io/hello--world/myx/frontend:latest

# 运行容器
docker run -d \
  --name myx-frontend \
  -p 80:80 \
  -e VITE_API_URL="http://your-backend:8000/api" \
  ghcr.io/hello--world/myx/frontend:latest
```

### 查看日志

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
```

### 停止服务

```bash
docker-compose down
```

## Python 直接安装（Agent）

**重要：** Agent 仅支持在宿主机上安装，不支持 Docker 容器部署。

### 方式一：通过 Web 界面自动安装（推荐）

1. 登录 MyX 平台
2. 进入"服务器管理"页面
3. 添加服务器，选择"部署方式"为 "Agent"
4. 点击"安装Agent"按钮
5. 系统会自动通过 SSH 安装 Agent 到宿主机

### 方式二：手动安装

#### 1. 下载 Agent 文件

从后端 API 下载 Agent 文件：

```bash
# 下载 main.py
curl -L http://your-backend:8000/api/agents/files/main.py/ -o /opt/myx-agent/main.py

# 下载 requirements.txt
curl -L http://your-backend:8000/api/agents/files/requirements.txt/ -o /opt/myx-agent/requirements.txt
```

#### 2. 安装依赖

```bash
# 安装 Python 依赖
pip3 install -r /opt/myx-agent/requirements.txt

# 或者使用系统包管理器
apt-get install -y python3-requests python3-urllib3  # Debian/Ubuntu
# 或
yum install -y python3-requests python3-urllib3      # CentOS/RHEL
```

#### 3. 设置权限

```bash
chmod +x /opt/myx-agent/main.py
```

#### 4. 注册 Agent

```bash
python3 /opt/myx-agent/main.py --token <server_id> --api http://your-backend:8000/api/agents
```

#### 5. 配置 systemd 服务

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

#### 6. 启动服务

```bash
systemctl daemon-reload
systemctl enable myx-agent
systemctl start myx-agent
```

#### 7. 查看状态

```bash
systemctl status myx-agent
journalctl -u myx-agent -f
```

## 版本说明

- **Backend/Frontend**: 支持 Docker 容器部署
- **Agent**: 仅支持宿主机安装，不支持 Docker 容器

## 故障排除

### Docker 相关问题

1. **镜像拉取失败**
   - 检查网络连接
   - 确认镜像地址正确
   - 检查 GitHub Container Registry 访问权限

2. **容器启动失败**
   - 检查环境变量配置
   - 查看容器日志：`docker logs myx-backend` 或 `docker logs myx-frontend`
   - 确认端口未被占用

### Agent 相关问题

1. **Agent 无法连接后端**
   - 检查网络连接
   - 确认 API 地址正确
   - 检查防火墙设置

2. **Agent 注册失败**
   - 检查 server_token 是否正确
   - 确认后端服务正常运行
   - 查看 Agent 日志：`journalctl -u myx-agent -f`

## 更多信息

- 项目地址: https://github.com/hello--world/myx
- 问题反馈: https://github.com/hello--world/myx/issues
- Docker 镜像: https://github.com/hello--world/myx/pkgs/container/myx

