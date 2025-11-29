# GitHub Actions Workflows 说明

## Workflow 触发说明

### 为什么会有多个 Workflow 运行？

当推送代码到 GitHub 时，可能会触发多个 workflow，原因如下：

1. **多个 workflow 监听相同的事件**：每个 workflow 都独立监听 push 事件
2. **路径匹配**：即使有 `paths` 限制，如果文件变化匹配多个 workflow，都会触发
3. **统一构建 workflow**：`docker-all.yml` 会构建所有镜像

### 当前 Workflow 配置

#### 自动触发的 Workflows

1. **`build-agent.yml`** - 构建 Agent 二进制文件
   - 触发：`agent/**` 目录变化
   - 输出：二进制文件（Artifacts）

2. **`docker-all.yml`** - 统一构建所有 Docker 镜像 ⭐ **主要 workflow**
   - 触发：`agent/**`, `backend/**`, `frontend/**` 目录变化
   - 输出：Agent、Backend、Frontend 三个 Docker 镜像
   - **这是推荐的 workflow，一次构建所有镜像**

#### 手动触发的 Workflows

以下 workflows 已改为只允许手动触发，避免重复构建：

- `docker-agent.yml` - 单独构建 Agent 镜像
- `build-backend.yml` - 单独构建 Backend 镜像  
- `docker-frontend.yml` - 单独构建 Frontend 镜像

#### Release Workflow

- **`release.yml`** - 创建 Release 时自动上传二进制文件

## 优化建议

### 方案 1：只使用 docker-all.yml（推荐）

当前配置已经优化：
- ✅ `docker-all.yml` 自动构建所有镜像
- ✅ 其他 Docker workflows 改为手动触发
- ✅ 避免重复构建

### 方案 2：完全禁用单独的 Docker workflows

如果不需要单独构建，可以删除：
- `.github/workflows/docker-agent.yml`
- `.github/workflows/build-backend.yml`
- `.github/workflows/docker-frontend.yml`

只保留 `docker-all.yml`。

## 镜像地址

所有镜像都推送到：`ghcr.io/hello--world/myx/<service>:latest`

- Agent: `ghcr.io/hello--world/myx/agent:latest`
- Backend: `ghcr.io/hello--world/myx/backend:latest`
- Frontend: `ghcr.io/hello--world/myx/frontend:latest`

## 使用示例

```bash
# 拉取所有镜像
docker pull ghcr.io/hello--world/myx/agent:latest
docker pull ghcr.io/hello--world/myx/backend:latest
docker pull ghcr.io/hello--world/myx/frontend:latest

# 或使用 docker-compose
export GITHUB_REPO="hello--world/myx"
docker-compose up -d
```

