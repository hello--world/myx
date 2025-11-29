# GitHub Actions Workflows

本项目使用 GitHub Actions 自动构建和发布 Agent 和 Backend 的二进制文件和 Docker 镜像。

## Workflows

### 1. Build Agent (`build-agent.yml`)

自动构建 Agent 的二进制文件，支持多平台：
- Linux amd64
- Linux arm64

**触发条件：**
- 推送到 main/master 分支（agent/ 目录有变更）
- 创建 Release
- 手动触发

**输出：**
- 构建的二进制文件作为 Artifacts
- Release 时自动上传到 GitHub Releases

### 2. Build Agent Docker Image (`docker-agent.yml`)

构建 Agent 的 Docker 镜像并推送到 GitHub Container Registry。

**触发条件：**
- 推送到 main/master 分支（agent/ 目录或 Dockerfile 有变更）
- 创建 Release
- 手动触发

**输出：**
- Docker 镜像推送到 `ghcr.io/<owner>/<repo>/agent`
- 支持多平台：linux/amd64, linux/arm64

### 3. Build Backend Docker Image (`build-backend.yml`)

构建 Backend 的 Docker 镜像并推送到 GitHub Container Registry。

**触发条件：**
- 推送到 main/master 分支（backend/ 目录或 Dockerfile 有变更）
- 创建 Release
- 手动触发

**输出：**
- Docker 镜像推送到 `ghcr.io/<owner>/<repo>/backend`
- 支持多平台：linux/amd64, linux/arm64

### 4. Release (`release.yml`)

当创建 GitHub Release 时，自动构建并上传二进制文件到 Release。

## 使用方法

### 1. 设置 GitHub 仓库

1. 在 GitHub 上创建新仓库
2. 推送代码到仓库
3. GitHub Actions 会自动运行

### 2. 创建 Release

1. 在 GitHub 仓库页面，点击 "Releases"
2. 点击 "Create a new release"
3. 填写版本号（如 `v1.0.0`）和描述
4. 点击 "Publish release"
5. GitHub Actions 会自动构建并上传二进制文件

### 3. 下载二进制文件

二进制文件会出现在 Release 页面，可以直接下载：
- `myx-agent-linux-amd64`
- `myx-agent-linux-arm64`

### 4. 使用 Docker 镜像

```bash
# 拉取 Agent 镜像
docker pull ghcr.io/<owner>/<repo>/agent:latest

# 拉取 Backend 镜像
docker pull ghcr.io/<owner>/<repo>/backend:latest
```

### 5. 配置部署脚本

在部署脚本中，设置环境变量指定 GitHub 仓库：

```bash
export GITHUB_REPO="your-username/myx"
```

或者在 Django settings 中配置：

```python
GITHUB_REPO = os.getenv('GITHUB_REPO', 'your-username/myx')
```

## 注意事项

1. **首次使用**：需要先创建一个 Release 才能下载二进制文件
2. **权限**：确保 GitHub Actions 有写入权限（默认已启用）
3. **Docker 镜像**：首次推送需要公开仓库或配置访问权限
4. **环境变量**：部署脚本需要设置 `GITHUB_REPO` 环境变量

