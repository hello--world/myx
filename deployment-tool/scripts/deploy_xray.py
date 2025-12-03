#!/usr/bin/env python3
"""
Xray 部署脚本（纯Python实现）
支持宿主机部署，自动安装、配置systemd服务
"""
import os
import sys
import json
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


def check_xray_installed():
    """检查Xray是否已安装"""
    xray_paths = ['/usr/local/bin/xray', '/usr/bin/xray']
    for path in xray_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            log(f"发现Xray: {path}")
            return True, path
    return False, None


def install_xray():
    """安装Xray"""
    log("开始安装Xray...")

    # 下载官方安装脚本
    install_script_url = "https://github.com/XTLS/Xray-install/raw/main/install-release.sh"
    install_script_path = "/tmp/install-xray.sh"

    log(f"下载安装脚本: {install_script_url}")
    try:
        urllib.request.urlretrieve(install_script_url, install_script_path)
        os.chmod(install_script_path, 0o755)
    except Exception as e:
        log(f"下载安装脚本失败: {e}", "ERROR")
        return False

    # 执行安装脚本
    log("执行Xray安装脚本...")
    success, stdout, stderr = run_command(f"bash {install_script_path}", shell=True)

    if stdout:
        log(f"安装输出:\n{stdout}")
    if stderr:
        log(f"安装错误:\n{stderr}", "WARNING")

    if not success:
        log("Xray安装失败", "ERROR")
        return False

    log("Xray安装成功")
    return True


def create_systemd_service():
    """创建systemd服务文件"""
    log("创建systemd服务文件...")

    service_content = """[Unit]
Description=Xray Service
Documentation=https://github.com/xtls/xray-core
After=network.target nss-lookup.target

[Service]
Type=simple
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=/usr/local/bin/xray run -config /usr/local/etc/xray/config.json
Restart=on-failure
RestartPreventExitStatus=23
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
"""

    service_file = "/etc/systemd/system/xray.service"
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
        os.chmod(service_file, 0o644)
        log(f"服务文件已创建: {service_file}")
        return True
    except Exception as e:
        log(f"创建服务文件失败: {e}", "ERROR")
        return False


def create_default_config():
    """创建默认配置文件"""
    log("创建默认配置文件...")

    config_dir = Path("/usr/local/etc/xray")
    config_file = config_dir / "config.json"

    # 创建配置目录
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

    # 检查配置文件是否存在
    if config_file.exists():
        # 验证配置文件
        log("配置文件已存在，验证配置...")
        success, stdout, stderr = run_command(
            ["/usr/local/bin/xray", "run", "-config", str(config_file), "-test"],
            check=False
        )

        if not success or "Configuration OK" not in stdout:
            # 配置有错误，备份并重建
            import time
            backup_file = f"{config_file}.backup.{int(time.time())}"
            log(f"配置文件有错误，备份到: {backup_file}")
            config_file.rename(backup_file)
        else:
            log("配置文件验证通过")
            return True

    # 创建默认配置
    default_config = {
        "log": {
            "loglevel": "warning"
        },
        "inbounds": [],
        "outbounds": [
            {
                "protocol": "freedom",
                "tag": "direct"
            }
        ]
    }

    try:
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=2)
        os.chmod(config_file, 0o644)
        log(f"默认配置已创建: {config_file}")
        return True
    except Exception as e:
        log(f"创建配置文件失败: {e}", "ERROR")
        return False


def enable_service():
    """启用systemd服务"""
    log("重新加载systemd并启用Xray服务...")

    # 重新加载systemd
    run_command("systemctl daemon-reload", shell=True)

    # 启用服务（但不启动，等配置文件就绪后再启动）
    success, stdout, stderr = run_command("systemctl enable xray", shell=True, check=False)

    if success:
        log("Xray服务已启用")
        return True
    else:
        log(f"启用服务失败: {stderr}", "WARNING")
        return False


def verify_installation():
    """验证安装结果"""
    log("验证安装...")

    # 检查二进制文件
    installed, xray_path = check_xray_installed()
    if not installed:
        log("Xray二进制文件不存在", "ERROR")
        return False

    # 检查版本
    success, stdout, stderr = run_command([xray_path, "version"], check=False)
    if success and stdout:
        version_line = stdout.split('\n')[0]
        log(f"Xray版本: {version_line}")

    # 检查服务文件
    service_file = "/etc/systemd/system/xray.service"
    if not os.path.exists(service_file):
        log("服务文件不存在", "ERROR")
        return False

    # 检查配置文件
    config_file = "/usr/local/etc/xray/config.json"
    if not os.path.exists(config_file):
        log("配置文件不存在", "ERROR")
        return False

    log("安装验证通过", "SUCCESS")
    return True


def main():
    """主函数"""
    log("=" * 50)
    log("开始部署Xray (宿主机模式)")
    log("=" * 50)

    # 步骤1: 检查是否已安装
    installed, xray_path = check_xray_installed()
    if installed:
        log(f"Xray已安装: {xray_path}")
    else:
        # 步骤2: 安装Xray
        if not install_xray():
            log("Xray安装失败", "ERROR")
            return 1

    # 步骤3: 创建systemd服务
    if not create_systemd_service():
        log("创建服务文件失败", "ERROR")
        return 1

    # 步骤4: 创建默认配置
    if not create_default_config():
        log("创建配置文件失败", "ERROR")
        return 1

    # 步骤5: 启用服务
    if not enable_service():
        log("启用服务失败", "WARNING")
        # 不作为致命错误

    # 步骤6: 验证安装
    if not verify_installation():
        log("安装验证失败", "ERROR")
        return 1

    log("=" * 50)
    log("Xray部署完成！", "SUCCESS")
    log("提示: 服务已启用但未启动，配置代理后会自动启动")
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
