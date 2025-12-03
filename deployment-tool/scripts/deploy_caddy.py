#!/usr/bin/env python3
"""
Caddy 部署脚本（纯Python实现）
支持宿主机部署，自动安装、配置systemd服务
"""
import os
import sys
import subprocess
import urllib.request
from pathlib import Path


def log(message, level="INFO"):
    """打印日志"""
    print(f"[{level}] {message}", flush=True)


def run_command(cmd, shell=False, check=True, capture_output=True):
    """执行命令并返回结果"""
    try:
        if isinstance(cmd, str) and not shell:
            cmd = cmd.split()

        result = subprocess.run(
            cmd,
            shell=shell,
            check=check,
            capture_output=capture_output,
            text=True,
            timeout=300
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "命令执行超时"
    except Exception as e:
        return False, "", str(e)


def check_caddy_installed():
    """检查Caddy是否已安装"""
    caddy_paths = ['/usr/bin/caddy', '/usr/local/bin/caddy', '/opt/caddy/caddy']
    for path in caddy_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            log(f"发现Caddy: {path}")
            return True, path
    return False, None


def detect_os():
    """检测操作系统类型"""
    try:
        with open('/etc/os-release', 'r') as f:
            content = f.read().lower()

        if 'debian' in content or 'ubuntu' in content:
            return 'debian'
        elif 'centos' in content or 'rhel' in content or 'fedora' in content or 'rocky' in content or 'almalinux' in content:
            return 'rhel'
        else:
            log("未能识别的操作系统，尝试Debian方式安装", "WARNING")
            return 'debian'
    except Exception as e:
        log(f"检测操作系统失败: {e}, 默认使用Debian方式", "WARNING")
        return 'debian'


def install_caddy_debian():
    """在Debian/Ubuntu系统上安装Caddy"""
    log("在Debian/Ubuntu系统上安装Caddy...")

    # 安装依赖
    log("安装依赖包...")
    run_command(
        "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl",
        shell=True,
        check=False
    )

    # 添加GPG密钥
    log("添加Caddy GPG密钥...")
    success, _, _ = run_command(
        "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg",
        shell=True,
        check=False
    )
    if success:
        run_command("chmod 644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg", shell=True, check=False)

    # 添加仓库
    log("添加Caddy仓库...")
    run_command(
        "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list",
        shell=True,
        check=False
    )
    run_command("chmod 644 /etc/apt/sources.list.d/caddy-stable.list", shell=True, check=False)

    # 更新并安装Caddy
    log("更新包列表并安装Caddy...")
    run_command("apt-get update -qq", shell=True, check=False)
    success, stdout, stderr = run_command(
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy",
        shell=True,
        check=False
    )

    if not success:
        log(f"Caddy安装失败: {stderr}", "ERROR")
        return False

    log("Caddy安装成功")
    return True


def install_caddy_rhel():
    """在RHEL/CentOS/Fedora系统上安装Caddy"""
    log("在RHEL/CentOS/Fedora系统上安装Caddy...")

    # 检测包管理器
    if os.path.exists('/usr/bin/dnf'):
        pkg_mgr = 'dnf'
    else:
        pkg_mgr = 'yum'

    log(f"使用包管理器: {pkg_mgr}")

    # 安装dnf-plugins-core
    if pkg_mgr == 'dnf':
        run_command(f"{pkg_mgr} install -y -q dnf-plugins-core", shell=True, check=False)

    # 启用COPR仓库
    log("启用Caddy COPR仓库...")
    success, stdout, stderr = run_command(
        f"{pkg_mgr} copr enable -y @caddy/caddy",
        shell=True,
        check=False
    )

    # 安装Caddy
    log("安装Caddy...")
    success, stdout, stderr = run_command(
        f"{pkg_mgr} install -y -q caddy",
        shell=True,
        check=False
    )

    if not success:
        log(f"Caddy安装失败: {stderr}", "ERROR")
        return False

    log("Caddy安装成功")
    return True


def install_caddy():
    """安装Caddy"""
    os_type = detect_os()

    if os_type == 'debian':
        return install_caddy_debian()
    elif os_type == 'rhel':
        return install_caddy_rhel()
    else:
        log(f"不支持的操作系统类型: {os_type}", "ERROR")
        return False


def create_caddy_directories():
    """创建Caddy所需的目录"""
    log("创建Caddy目录...")

    directories = [
        '/etc/caddy',
        '/var/lib/caddy'
    ]

    for dir_path in directories:
        Path(dir_path).mkdir(parents=True, exist_ok=True, mode=0o755)
        log(f"目录已创建: {dir_path}")

    return True


def enable_service():
    """启用Caddy服务"""
    log("启用Caddy服务...")

    # 重新加载systemd
    run_command("systemctl daemon-reload", shell=True, check=False)

    # 启用并启动服务
    success, stdout, stderr = run_command("systemctl enable caddy", shell=True, check=False)

    if success:
        log("Caddy服务已启用")

        # 尝试启动服务
        success, stdout, stderr = run_command("systemctl start caddy", shell=True, check=False)
        if success:
            log("Caddy服务已启动")
        else:
            log(f"启动服务失败: {stderr}", "WARNING")

        return True
    else:
        log(f"启用服务失败: {stderr}", "WARNING")
        return False


def verify_installation():
    """验证安装结果"""
    log("验证安装...")

    # 检查二进制文件
    installed, caddy_path = check_caddy_installed()
    if not installed:
        log("Caddy二进制文件不存在", "ERROR")
        return False

    # 检查版本
    success, stdout, stderr = run_command([caddy_path, "version"], check=False)
    if success and stdout:
        version_line = stdout.strip()
        log(f"Caddy版本: {version_line}")

    # 检查服务
    success, stdout, stderr = run_command(
        "systemctl list-unit-files | grep caddy.service",
        shell=True,
        check=False
    )
    if success and 'caddy.service' in stdout:
        log("Caddy服务文件已注册")
    else:
        log("Caddy服务文件未找到", "WARNING")

    log("安装验证通过", "SUCCESS")
    return True


def main():
    """主函数"""
    log("=" * 50)
    log("开始部署Caddy (宿主机模式)")
    log("=" * 50)

    # 步骤1: 检查是否已安装
    installed, caddy_path = check_caddy_installed()
    if installed:
        log(f"Caddy已安装: {caddy_path}")
    else:
        # 步骤2: 安装Caddy
        if not install_caddy():
            log("Caddy安装失败", "ERROR")
            return 1

    # 步骤3: 创建所需目录
    if not create_caddy_directories():
        log("创建目录失败", "ERROR")
        return 1

    # 步骤4: 启用服务
    if not enable_service():
        log("启用服务失败", "WARNING")
        # 不作为致命错误

    # 步骤5: 验证安装
    if not verify_installation():
        log("安装验证失败", "ERROR")
        return 1

    log("=" * 50)
    log("Caddy部署完成！", "SUCCESS")
    log("=" * 50)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"部署过程中发生异常: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        sys.exit(1)
