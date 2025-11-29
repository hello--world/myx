#!/bin/bash
# 启动Django后端服务器（使用uv管理依赖）

# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 检查是否安装了uv
if ! command -v uv &> /dev/null; then
    echo "错误: 未安装 uv。请先安装: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 在项目根目录使用uv同步依赖
echo "正在同步依赖..."

# 如果网络有问题，可以尝试使用国内镜像源
# 取消下面的注释来使用清华镜像
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 使用 --no-install-project 跳过项目本身的安装（Django项目不需要）
uv sync --no-install-project

# 切换到backend目录并使用uv运行Django命令
cd backend
echo "正在创建数据库迁移..."
uv run python manage.py makemigrations
echo "正在运行数据库迁移..."
uv run python manage.py migrate

# 检查是否存在管理员账号，如果不存在则创建默认账号
echo "检查管理员账号..."
if ! uv run python manage.py shell -c "from apps.accounts.models import User; exit(0 if User.objects.filter(is_superuser=True).exists() else 1)" 2>/dev/null; then
    echo "未检测到管理员账号，创建默认管理员账号..."
    uv run python create_default_user.py
fi

echo "启动Django开发服务器..."
uv run python manage.py runserver

