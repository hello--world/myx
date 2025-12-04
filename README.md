# MyX - 科学技术管理平台

一个基于 Agent 架构的服务器管理和部署系统，采用**服务器主动、Agent 被动**的设计模式。支持通过 Agent 自动化部署和管理 Xray、Caddy 等服务，提供代理订阅管理和节点监控功能。

## 功能特性

- 🖥️ **服务器管理**: 通过SSH连接信息管理多台服务器，自动安装和升级Agent
- 🤖 **Agent架构**: 基于无状态Agent设计，服务器主动管理，Agent被动响应
- 🚀 **自动化部署**: 通过Agent使用Ansible自动部署Xray和Caddy
- 🔗 **代理节点管理**: 支持VLESS、VMess、Trojan、Shadowsocks等多种协议
- 📡 **订阅管理**: 支持Base64和Clash格式的订阅链接
- 📝 **Caddyfile管理**: 可视化编辑和管理Caddy配置文件，支持证书管理
- 🔒 **安全认证**: Token验证 + HTTPS通信 + 随机RPC路径（路径混淆）
- 📊 **实时监控**: 查看部署任务状态、Agent状态和实时日志
- 💓 **心跳机制**: 服务器主动发送心跳，实时监控Agent在线状态

## 技术栈

### 后端
- Django 4.2.7
- Django REST Framework
- JSON-RPC 2.0 (Agent通信协议)
- Ansible (自动化部署)
- Paramiko (SSH连接)
- Flask (Agent端JSON-RPC服务器)
- uv (Python包管理)

### 前端
- Vue.js 3
- Element Plus
- Vue Router
- Pinia
- Axios
- CodeMirror (代码编辑器)

## 项目结构

```
MyX/
├── backend/                 # Django后端（服务器端）
│   ├── config/             # Django配置
│   ├── apps/               # 应用模块
│   │   ├── accounts/       # 用户认证
│   │   ├── servers/        # 服务器管理
│   │   ├── agents/         # Agent管理（心跳、RPC客户端、命令队列）
│   │   ├── proxies/        # 代理节点管理（含Caddyfile和证书管理）
│   │   ├── subscriptions/  # 订阅管理
│   │   ├── deployments/    # 部署任务管理
│   │   └── logs/           # 日志中心
│   └── utils/              # 工具函数
├── deployment-tool/        # 部署工具（通过Agent上传到目标服务器）
│   ├── agent/              # Agent核心文件
│   │   ├── main.py         # Agent主程序
│   │   ├── rpc_server.py   # JSON-RPC服务器
│   │   └── ansible_executor.py  # Ansible执行器
│   ├── playbooks/          # Ansible playbooks
│   └── scripts/            # 部署脚本
├── frontend/               # Vue.js前端
│   └── src/
│       ├── views/          # 页面组件
│       ├── components/     # 公共组件
│       ├── api/            # API调用
│       └── router/         # 路由配置
├── pyproject.toml          # Python项目配置（uv使用）
└── requirements.txt        # Python依赖（兼容传统pip）
```

## 安装和运行

### 安装 uv

首先安装 `uv`（如果尚未安装）：

```bash
# macOS 和 Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或使用 pip
pip install uv
```

### 后端设置

#### 方式一：使用 uv（推荐）

1. 安装依赖：

```bash
# 在项目根目录
uv sync --no-install-project
```

> **注意**: 使用 `--no-install-project` 选项是因为这是一个 Django 应用项目，不需要将项目本身作为包安装，只需要安装依赖即可。

如果遇到网络连接问题，可以配置使用国内镜像源：

```bash
# 使用环境变量设置镜像源（临时）
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
uv sync --no-install-project

# 或者使用阿里云镜像
# export UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

2. 配置环境变量（可选）：

从 `.env.example` 复制并创建 `.env` 文件：

```bash
cp .env.example .env
```

然后编辑 `.env` 文件，根据你的实际情况修改配置：

```env
SECRET_KEY=your-secret-key-here
DEBUG=True

# 允许访问的主机列表（逗号分隔，追加到默认值）
# 默认值已包含: localhost, 127.0.0.1
# 设置此变量会追加到默认值后面，而不是替换
ALLOWED_HOSTS=your-domain.com,192.168.1.100

# CORS 允许的源（逗号分隔，追加到默认值）
# 默认值已包含: http://localhost:5173, http://localhost:3000, http://127.0.0.1:5173, http://127.0.0.1:3000
# 设置此变量会追加到默认值后面，而不是替换
CORS_ALLOWED_ORIGINS=https://your-domain.com

# CSRF 信任的源（逗号分隔，追加到默认值）
# 默认值已包含: http://localhost:5173, http://localhost:3000, http://127.0.0.1:5173, http://127.0.0.1:3000
# 设置此变量会追加到默认值后面，而不是替换
CSRF_TRUSTED_ORIGINS=https://your-domain.com

# Agent 配置（重要！）
# 如果部署到远程服务器，Agent 需要能够访问后端 API
# 方式1: 直接设置完整的 API URL
AGENT_API_URL=http://your-server-ip:8000/api/agents

# 方式2: 设置后端主机地址（推荐）
# 系统会自动构建 API URL: http://{BACKEND_HOST}:8000/api/agents
BACKEND_HOST=your-server-ip-or-domain.com

# GitHub Repository（用于下载 Agent 二进制文件）
GITHUB_REPO=hello--world/myx

# Agent 心跳和轮询间隔配置（秒）
# 心跳间隔：Agent 向服务器发送心跳的随机间隔范围
AGENT_HEARTBEAT_MIN_INTERVAL=30
AGENT_HEARTBEAT_MAX_INTERVAL=300

# 轮询间隔：Agent 轮询服务器获取命令的随机间隔范围
AGENT_POLL_MIN_INTERVAL=5
AGENT_POLL_MAX_INTERVAL=60

# ============================================
# 前端配置（Vite）
# ============================================

# Vite 允许的主机列表（逗号分隔）
# 用于解决 "Blocked request. This host is not allowed" 错误
VITE_ALLOWED_HOSTS=your-domain.com
```

3. 运行数据库迁移：

```bash
cd backend
uv run python manage.py makemigrations
uv run python manage.py migrate
```

4. 创建超级用户：

```bash
uv run python manage.py createsuperuser
```

5. 启动开发服务器：

```bash
# 使用启动脚本（推荐）
./start_backend.sh

# 或手动启动
cd backend
uv run python manage.py runserver
```

#### 方式二：使用传统 pip

1. 创建虚拟环境并安装依赖：

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r ../requirements.txt
```

2. 运行数据库迁移：

```bash
python manage.py makemigrations
python manage.py migrate
```

3. 创建超级用户：

```bash
python manage.py createsuperuser
```

4. 启动开发服务器：

```bash
python manage.py runserver
```

### 前端设置

1. 安装依赖：

```bash
cd frontend
npm install
```

2. 启动开发服务器：

```bash
npm run dev
```

访问 http://localhost:5173 查看前端界面。

### Docker 部署（推荐生产环境）

项目提供了 Docker 和 Docker Compose 配置，方便快速部署。

> **注意**：项目目前不提供预构建的 Docker 镜像，需要本地构建。

#### 使用 Docker Compose

1. 配置环境变量：

```bash
cp .env.example .env
# 编辑 .env 文件，设置必要的配置
```

2. 修改 `docker-compose.yml`：

由于没有预构建镜像，需要修改 `docker-compose.yml`，将 `image` 改为 `build`：

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    # image: ghcr.io/hello--world/myx/backend:latest  # 注释掉这行
    # ... 其他配置

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    # image: ghcr.io/hello--world/myx/frontend:latest  # 注释掉这行
    # ... 其他配置
```

3. 构建并启动所有服务：

```bash
docker-compose build
docker-compose up -d
```

4. 运行数据库迁移：

```bash
docker-compose exec backend uv run python manage.py migrate
```

5. 创建超级用户：

```bash
docker-compose exec backend uv run python manage.py createsuperuser
```

6. 访问应用：

- 前端：http://localhost:80（Docker Compose 中配置的端口）
- 后端API：http://localhost:8000
- 管理后台：http://localhost:8000/admin/

#### 单独构建和运行

**后端**：

```bash
cd backend
docker build -t myx-backend .
docker run -d -p 8000:8000 --env-file ../.env myx-backend
```

**前端**：

```bash
cd frontend
docker build -t myx-frontend .
docker run -d -p 80:80 myx-frontend
```

#### 生产环境部署

使用 `docker-compose.prod.yml` 进行生产环境部署（同样需要修改为使用 `build` 而不是 `image`）：

```bash
# 修改 docker-compose.prod.yml 后
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d
```

## 架构说明

### 核心设计原则

1. **Agent 完全无状态**：Agent 不知道服务器的存在，不主动连接服务器
2. **服务器主动管理**：服务器主动连接 Agent，发送心跳和命令
3. **JSON-RPC 通信**：使用 JSON-RPC 2.0 协议进行双向通信
4. **配置由服务器分配**：Agent 的 Token、RPC 端口和随机路径由服务器在部署时生成

### Agent 部署流程

1. 用户添加服务器（提供SSH凭证）
2. 服务器生成 Agent Token、RPC 端口和随机路径
3. 通过SSH上传Agent核心文件到目标服务器
4. Agent启动JSON-RPC服务器（HTTPS，使用自签名证书）
5. 服务器主动连接Agent，验证RPC服务可用性
6. 部署完成，服务器开始发送心跳监控Agent状态

### 通信机制

- **心跳机制**：服务器每20-60秒（随机间隔）主动向Agent发送心跳
- **命令执行**：服务器通过JSON-RPC调用Agent执行命令，实时获取日志
- **安全机制**：Token验证 + HTTPS + 随机RPC路径（路径混淆）

详细架构说明请参考 [ARCHITECTURE.md](./ARCHITECTURE.md)

## 使用说明

### 1. 添加服务器

在"服务器管理"页面添加服务器的SSH连接信息（IP、端口、用户名、密码或私钥）。系统会自动生成服务器名称（基于IP地理位置）。

### 2. 安装Agent

添加服务器后，点击"安装Agent"按钮。系统会：
- 通过SSH上传Agent文件
- 自动生成Token和RPC端口
- 启动Agent服务
- 验证Agent连接

### 3. 管理代理节点

在"代理节点"页面添加代理节点配置，包括协议（VLESS、VMess、Trojan、Shadowsocks）、端口、传输方式等。配置会自动部署到服务器。

### 4. 管理Caddyfile

在"Caddyfile"页面可视化编辑Caddy配置文件，支持：
- 语法高亮
- 配置验证
- 证书管理（自动解析Caddyfile中的证书，支持手动上传）
- 一键重载Caddy服务

### 5. 管理订阅

在"订阅管理"页面创建订阅链接，支持Base64和Clash格式。订阅链接会自动包含所有活跃的代理节点。

### 6. 查看日志

在"日志中心"页面查看系统日志、部署日志、Agent日志等，支持按类型、级别、服务器筛选。

## 注意事项

1. **SSH安全**: 建议使用SSH密钥认证而不是密码
2. **Ansible要求**: 确保目标服务器已安装Python和必要的系统工具
3. **权限要求**: 部署Xray和Caddy需要sudo权限
4. **防火墙**: 
   - 确保目标服务器的防火墙允许SSH连接
   - Agent的RPC端口（随机分配，8000-65535）需要能被服务器访问
5. **uv优势**: 使用uv可以更快地安装依赖，并且自动管理虚拟环境
6. **Agent通信**: 
   - Agent使用HTTPS通信（自签名证书），服务器默认不验证证书
   - 每个Agent使用随机RPC路径，增强安全性
   - 服务器主动连接Agent，Agent不主动连接服务器
7. **网络要求**:
   - 目标服务器需要能够访问GitHub（下载Python依赖）
   - 服务器需要能够访问目标服务器的Agent RPC端口

## 开发

### 后端API文档

启动Django服务器后，访问 http://localhost:8000/admin/ 查看Django管理后台。

### 前端开发

前端使用Vite作为构建工具，支持热重载。

### uv 常用命令

```bash
# 同步依赖（安装/更新）
uv sync

# 添加新依赖
uv add package-name

# 添加开发依赖
uv add --dev package-name

# 运行Python命令
uv run python manage.py <command>

# 运行Python脚本
uv run python script.py
```

## 许可证

本项目采用 MIT 许可证。
