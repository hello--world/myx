# GitHub Actions Workflows

## 工作流说明

### 主要工作流

1. **`build-agent.yml`** - 构建 Agent 二进制文件
   - **触发条件**：
     - Push 到 `main`/`master` 分支（仅当 `agent/**` 路径变化时）
     - 创建 GitHub Release
     - 手动触发 (`workflow_dispatch`)
   - **功能**：
     - 构建多平台 Agent 二进制文件（Linux/macOS, AMD64/ARM64）
     - 自动上传到 GitHub Release（`latest` 标签或 release 标签）

2. **`docker-all.yml`** - 构建所有 Docker 镜像
   - **触发条件**：
     - Push 到 `main`/`master` 分支（当 agent/backend/frontend 路径变化时）
     - 创建 GitHub Release
     - 手动触发 (`workflow_dispatch`)
   - **功能**：
     - 并行构建 Agent、Backend、Frontend 的 Docker 镜像
     - 支持多平台（linux/amd64, linux/arm64）
     - 推送到 GitHub Container Registry (ghcr.io)

### 单独构建工作流（仅手动触发）

以下工作流已被 `docker-all.yml` 替代，仅保留用于单独构建特定镜像：

- **`docker-agent.yml`** - 单独构建 Agent Docker 镜像
- **`build-backend.yml`** - 单独构建 Backend Docker 镜像
- **`docker-frontend.yml`** - 单独构建 Frontend Docker 镜像

这些工作流默认只允许手动触发 (`workflow_dispatch`)，避免与 `docker-all.yml` 重复构建。

## 工作流关系

```
创建 Release
    ├── build-agent.yml (构建二进制文件并上传到 Release)
    └── docker-all.yml (构建所有 Docker 镜像)

Push 到 main/master
    ├── build-agent.yml (如果 agent/** 变化)
    └── docker-all.yml (如果 agent/backend/frontend/** 变化)
```

## 注意事项

- `build-agent.yml` 和 `docker-all.yml` 都会在创建 release 时触发
- `build-agent.yml` 负责构建二进制文件并上传到 Release
- `docker-all.yml` 负责构建 Docker 镜像并推送到容器仓库
- 两者不冲突，各自负责不同的构建产物
