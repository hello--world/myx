#!/usr/bin/env python3
"""
服务检测脚本
用于检测服务（如xray、caddy）是否已安装
优先检查二进制文件，其次检查systemd服务，最后检查Docker容器
"""
import os
import subprocess
import sys
import shutil

if len(sys.argv) < 2:
    print("用法: check_service.py <service_name> [deployment_target]")
    sys.exit(1)

service_name = sys.argv[1]
# 部署目标：host（宿主机）或 docker，默认为 host
deployment_target = sys.argv[2] if len(sys.argv) > 2 else "host"
installed = False
detection_method = ""

# 优先级1: 检查二进制文件是否存在（最可靠）
# 对于Xray，检查特定路径
if service_name == "xray":
    xray_bin_paths = [
        "/usr/local/bin/xray",
        "/usr/bin/xray"
    ]
    for path in xray_bin_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            installed = True
            detection_method = f"Xray二进制文件存在: {path}"
            break

# 对于Caddy，检查特定路径
elif service_name == "caddy":
    caddy_bin_paths = [
        "/usr/bin/caddy",
        "/usr/local/bin/caddy",
        "/opt/caddy/caddy"
    ]
    for path in caddy_bin_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            installed = True
            detection_method = f"Caddy二进制文件存在: {path}"
            break

# 其他服务，检查PATH中的命令
else:
    try:
        cmd_path = shutil.which(service_name)
        if cmd_path:
            installed = True
            detection_method = f"命令在PATH中: {cmd_path}"
    except Exception:
        pass

# 优先级2: 如果二进制文件不存在，检查systemd服务
if not installed:
    try:
        # 使用systemctl list-unit-files检查服务是否存在
        result = subprocess.run(
            ["systemctl", "list-unit-files", f"{service_name}.service"],
            capture_output=True,
            timeout=5,
            stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            output = result.stdout.decode('utf-8', errors='ignore')
            if f"{service_name}.service" in output:
                installed = True
                detection_method = "systemd服务文件存在"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        pass

# 优先级3: 检查服务状态（作为最后的确认）
if not installed:
    try:
        # 检查服务状态，即使服务未运行或失败，只要服务文件存在就算已安装
        result = subprocess.run(
            ["systemctl", "status", service_name],
            capture_output=True,
            timeout=5,
            stderr=subprocess.DEVNULL
        )
        # 返回码0: 服务正在运行
        # 返回码1: 服务失败但存在
        # 返回码3: 服务已停止但服务文件存在
        # 返回码4: 服务不存在
        if result.returncode in [0, 1, 3]:
            installed = True
            status_map = {0: "运行中", 1: "失败", 3: "已停止"}
            status = status_map.get(result.returncode, "未知")
            detection_method = f"systemd服务存在（状态: {status}）"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

# 优先级4: 如果部署目标是docker，检查Docker容器
if not installed and deployment_target == "docker":
    try:
        # 检查Docker容器是否存在
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={service_name}", "--format", "{{.Names}}"],
            capture_output=True,
            timeout=5,
            stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            output = result.stdout.decode('utf-8', errors='ignore').strip()
            # 检查容器名称是否完全匹配（避免误匹配）
            if output == service_name:
                installed = True
                detection_method = f"Docker容器存在: {service_name}"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

# 输出结果
if installed:
    print("INSTALLED")
    print(f"检测方式: {detection_method}")
    sys.exit(0)
else:
    print("NOT_INSTALLED")
    sys.exit(0)

