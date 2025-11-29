# MyX - Xray代理管理平台

一个基于Django + Vue.js的中心化Xray代理管理平台，支持通过SSH自动化部署Xray和Caddy，提供代理订阅管理和节点监控功能。

## 功能特性

- 🖥️ **服务器管理**: 通过SSH连接信息管理多台服务器
- 🚀 **自动化部署**: 使用Ansible自动部署Xray和Caddy
- 🔗 **代理节点管理**: 支持VLESS、VMess等多种协议
- 📡 **订阅管理**: 支持V2Ray和Clash格式的订阅链接
- 🔒 **安全认证**: Django Session认证，保护敏感信息
- 📊 **实时监控**: 查看部署任务状态和日志

## 技术栈

### 后端
- Django 4.2.7
- Django REST Framework
- Ansible (自动化部署)
- Paramiko (SSH连接)
- uv (Python包管理)

### 前端
- Vue.js 3
- Element Plus
- Vue Router
- Pinia
- Axios

## 项目结构

```
MyX/
├── backend/                 # Django后端
│   ├── config/             # Django配置
│   ├── apps/               # 应用模块
│   │   ├── accounts/       # 用户认证
│   │   ├── servers/        # 服务器管理
│   │   ├── proxies/        # 代理节点管理
│   │   ├── subscriptions/  # 订阅管理
│   │   └── deployments/    # 部署任务管理
│   ├── ansible/            # Ansible playbooks
│   └── utils/              # 工具函数
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

创建 `.env` 文件：

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
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

## 使用说明

### 1. 添加服务器

在"服务器管理"页面添加服务器的SSH连接信息（IP、端口、用户名、密码或私钥）。

### 2. 测试连接

添加服务器后，可以点击"测试连接"按钮验证SSH连接是否正常。

### 3. 创建部署任务

在"部署任务"页面创建部署任务，选择要部署的服务器和部署类型（Xray、Caddy或两者）。

### 4. 添加代理节点

在"代理节点"页面添加代理节点配置，包括协议、端口、传输方式等。

### 5. 管理订阅

在"订阅管理"页面创建订阅链接，支持V2Ray和Clash格式。订阅链接会自动包含所有活跃的代理节点。

## 注意事项

1. **SSH安全**: 建议使用SSH密钥认证而不是密码
2. **Ansible要求**: 确保目标服务器已安装Python和必要的系统工具
3. **权限要求**: 部署Xray和Caddy需要sudo权限
4. **防火墙**: 确保目标服务器的防火墙允许SSH连接
5. **uv优势**: 使用uv可以更快地安装依赖，并且自动管理虚拟环境

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
