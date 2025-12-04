# 推送到 GitHub 指南

GitHub 仓库已创建：https://github.com/hello--world/myx

代码已提交到本地，现在需要推送到 GitHub。请选择以下方式之一：

## 方式 1: 使用 GitHub CLI（推荐）

```bash
# 安装 GitHub CLI（如果未安装）
# macOS
brew install gh

# 登录 GitHub
gh auth login

# 推送代码
git push -u origin main
```

## 方式 2: 使用 Personal Access Token

1. 在 GitHub 创建 Personal Access Token：
   - 访问：https://github.com/settings/tokens
   - 点击 "Generate new token (classic)"
   - 选择权限：`repo`（完整仓库权限）
   - 复制生成的 token

2. 使用 token 推送：

```bash
# 使用 token 作为密码
git push -u origin main
# 用户名：hello--world
# 密码：粘贴你的 token
```

## 方式 3: 使用 SSH 密钥

1. 生成 SSH 密钥（如果还没有）：

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

2. 添加 SSH 密钥到 GitHub：
   - 复制公钥：`cat ~/.ssh/id_ed25519.pub`
   - 访问：https://github.com/settings/keys
   - 点击 "New SSH key"，粘贴公钥

3. 更改远程 URL 为 SSH：

```bash
git remote set-url origin git@github.com:hello--world/myx.git
git push -u origin main
```

## 方式 4: 使用 GitHub Desktop

1. 下载 GitHub Desktop：https://desktop.github.com/
2. 登录你的 GitHub 账号
3. 添加本地仓库
4. 点击 "Push origin"

## 验证推送

推送成功后，访问 https://github.com/hello--world/myx 查看代码。

GitHub Actions 会自动开始构建：
- Agent 二进制文件
- Docker 镜像（Agent、Backend、Frontend）

## 下一步

1. ✅ 推送代码到 GitHub
2. ✅ 等待 GitHub Actions 构建完成
3. ✅ 创建第一个 Release（v1.0.0）
4. ✅ 配置 `GITHUB_REPO=hello--world/myx` 环境变量
5. ✅ 开始使用！

