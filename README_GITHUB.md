# GitHub Actions 自动化构建指南

本项目已配置 GitHub Actions 来自动构建 Agent 和 Backend 的二进制文件及 Docker 镜像。

## 快速开始

### 1. 创建 GitHub 仓库

1. 在 GitHub 上创建新仓库（例如：`myx`）
2. 将代码推送到仓库：

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/hello--world/myx.git
git push -u origin main
```

### 2. 配置环境变量

在部署服务器上设置 GitHub 仓库地址：

```bash
export GITHUB_REPO="hello--world/myx"
```

或者在 `.env` 文件中：

```
GITHUB_REPO=hello--world/myx
```

### 3. 创建第一个 Release

1. 在 GitHub 仓库页面，点击 "Releases"
2. 点击 "Create a new release"
3. 填写版本号（如 `v1.0.0`）
4. 点击 "Publish release"
5. GitHub Actions 会自动构建并上传二进制文件

### 4. 验证构建

构建完成后，在 Release 页面可以看到：
- `myx-agent-linux-amd64`
- `myx-agent-linux-arm64`

## Workflows 说明

### Build Agent (`build-agent.yml`)

**功能：** 构建 Agent 二进制文件

**触发：**
- 推送到 main/master 分支（agent/ 目录有变更）
- 创建 Release
- 手动触发

**输出：**
- Artifacts: 构建的二进制文件
- Release: 自动上传到 GitHub Releases

### Docker Agent (`docker-agent.yml`)

**功能：** 构建 Agent Docker 镜像

**触发：** 同 Build Agent

**输出：**
- Docker 镜像: `ghcr.io/<owner>/<repo>/agent:latest`

**使用：**
```bash
docker pull ghcr.io/hello--world/myx/agent:latest
docker run -d --name myx-agent ghcr.io/hello--world/myx/agent:latest
```

### Docker Backend (`build-backend.yml`)

**功能：** 构建 Backend Docker 镜像

**触发：**
- 推送到 main/master 分支（backend/ 目录有变更）
- 创建 Release

**输出：**
- Docker 镜像: `ghcr.io/hello--world/myx/backend:latest`

**使用：**
```bash
docker pull ghcr.io/hello--world/myx/backend:latest
docker run -d -p 8000:8000 ghcr.io/hello--world/myx/backend:latest
```

## 部署脚本自动下载

部署脚本会自动从 GitHub Releases 下载 Agent 二进制文件：

1. 检测系统架构（amd64/arm64）
2. 从 `https://github.com/{GITHUB_REPO}/releases/latest/download/myx-agent-linux-{arch}` 下载
3. 上传到目标服务器并安装

**无需手动构建！**

## 故障排除

### 问题：下载失败 404

**原因：** GitHub Releases 中还没有二进制文件

**解决：**
1. 创建一个 Release（即使没有文件）
2. 等待 GitHub Actions 构建完成
3. 重新尝试部署

### 问题：Docker 镜像拉取失败

**原因：** 镜像未公开或权限不足

**解决：**
1. 在 GitHub 仓库设置中，将仓库设为公开
2. 或者在 Package 设置中配置访问权限

### 问题：构建失败

**检查：**
1. GitHub Actions 日志
2. Go 版本是否正确（需要 1.21+）
3. 依赖是否正确（`go mod tidy`）

## 手动构建（可选）

如果不想使用 GitHub Actions，也可以手动构建：

```bash
# 构建 Agent
cd agent
make all

# 构建 Docker 镜像
docker build -t myx-agent:latest -f agent/Dockerfile ./agent
docker build -t myx-backend:latest -f backend/Dockerfile ./backend
```

## 下一步

1. ✅ 创建 GitHub 仓库
2. ✅ 推送代码
3. ✅ 创建第一个 Release
4. ✅ 配置 `GITHUB_REPO` 环境变量
5. ✅ 开始部署！

