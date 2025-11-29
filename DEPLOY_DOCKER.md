# Docker 容器部署指南

本项目支持通过 GitHub Actions 自动构建 Docker 镜像，并推送到 GitHub Container Registry (ghcr.io)。

## 自动构建流程

### 1. 推送代码到 GitHub

当代码推送到 `main` 或 `master` 分支时，GitHub Actions 会自动：

- ✅ 构建 Agent Docker 镜像
- ✅ 构建 Backend Docker 镜像  
- ✅ 构建 Frontend Docker 镜像
- ✅ 推送到 `ghcr.io/<owner>/<repo>/<service>:latest`

### 2. 创建 Release

创建 GitHub Release 时，会自动构建并标记版本：

```bash
# 镜像标签示例
ghcr.io/your-username/myx/agent:v1.0.0
ghcr.io/your-username/myx/backend:v1.0.0
ghcr.io/your-username/myx/frontend:v1.0.0
```

## 使用 Docker Compose 部署

### 开发环境

```bash
# 设置环境变量
export GITHUB_REPO="your-username/myx"
export SECRET_KEY="your-secret-key"

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 生产环境

```bash
# 使用生产配置
docker-compose -f docker-compose.prod.yml up -d

# 需要设置的环境变量
export GITHUB_REPO="your-username/myx"
export SECRET_KEY="your-production-secret-key"
export DATABASE_URL="postgresql://user:pass@host/db"  # 可选，使用 PostgreSQL
export ALLOWED_HOSTS="your-domain.com"
```

## 单独使用 Docker 镜像

### Agent

```bash
# 拉取镜像
docker pull ghcr.io/your-username/myx/agent:latest

# 运行 Agent（首次需要注册）
docker run -d \
  --name myx-agent \
  -e SERVER_TOKEN="your-server-id" \
  -e API_URL="http://your-backend:8000/api/agents" \
  -v /etc/myx-agent:/etc/myx-agent \
  ghcr.io/your-username/myx/agent:latest
```

### Backend

```bash
# 拉取镜像
docker pull ghcr.io/your-username/myx/backend:latest

# 运行 Backend
docker run -d \
  --name myx-backend \
  -p 8000:8000 \
  -e SECRET_KEY="your-secret-key" \
  -e GITHUB_REPO="your-username/myx" \
  -v ./db.sqlite3:/app/db.sqlite3 \
  ghcr.io/your-username/myx/backend:latest
```

### Frontend

```bash
# 拉取镜像
docker pull ghcr.io/your-username/myx/frontend:latest

# 运行 Frontend
docker run -d \
  --name myx-frontend \
  -p 80:80 \
  -e VITE_API_URL="http://your-backend:8000/api" \
  ghcr.io/your-username/myx/frontend:latest
```

## 镜像访问权限

### 公开仓库

如果 GitHub 仓库是公开的，镜像会自动公开，任何人都可以拉取。

### 私有仓库

如果仓库是私有的，需要配置访问权限：

1. 在 GitHub 仓库页面，点击 "Packages"
2. 找到对应的包（如 `myx/agent`）
3. 点击 "Package settings"
4. 在 "Manage access" 中配置访问权限

### 使用私有镜像

```bash
# 登录到 GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# 拉取私有镜像
docker pull ghcr.io/your-username/myx/agent:latest
```

## 多平台支持

所有镜像都支持多平台构建：
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM64)

Docker 会自动选择匹配的镜像。

## 健康检查

Backend 容器包含健康检查端点：

```bash
# 检查健康状态
curl http://localhost:8000/api/health/

# 响应
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "service": "myx-backend"
}
```

## 更新镜像

### 自动更新

每次推送代码到 main/master 分支，会自动构建新镜像并标记为 `latest`。

### 手动更新

```bash
# 拉取最新镜像
docker-compose pull

# 重启服务
docker-compose up -d
```

## 故障排除

### 问题：无法拉取镜像

**原因：** 镜像未公开或权限不足

**解决：**
1. 检查仓库是否为公开
2. 检查 Package 访问权限
3. 使用 GitHub Token 登录

### 问题：构建失败

**检查：**
1. GitHub Actions 日志
2. Dockerfile 语法
3. 依赖是否正确

### 问题：容器无法启动

**检查：**
1. 环境变量是否正确
2. 端口是否被占用
3. 卷挂载路径是否正确
4. 查看容器日志：`docker logs <container-name>`

## 最佳实践

1. **使用版本标签**：生产环境使用具体版本号，不要使用 `latest`
2. **环境变量**：敏感信息使用环境变量，不要硬编码
3. **数据持久化**：使用 Docker volumes 持久化数据
4. **健康检查**：配置健康检查确保服务正常运行
5. **日志管理**：配置日志轮转和收集

