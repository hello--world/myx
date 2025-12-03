#!/usr/bin/env python3
"""
卸载 Agent 脚本
用于卸载 MyX Agent 及其相关文件和服务
"""
import os
import subprocess
import sys
import shutil

def run_command(cmd, check=True, capture_output=True):
    """执行系统命令"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=check,
            capture_output=capture_output,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, '', '命令执行超时'
    except Exception as e:
        return False, '', str(e)

def main():
    """主函数"""
    print("[信息] 开始卸载 Agent...")
    
    # 1. 停止 Agent 服务
    print("[信息] 正在停止 Agent 服务...")
    success, stdout, stderr = run_command("systemctl is-active --quiet myx-agent", check=False)
    if success:
        run_command("systemctl stop myx-agent", check=False)
        print("[信息] Agent 服务已停止")
    else:
        print("[信息] Agent 服务未运行，跳过停止")
    
    # 2. 禁用 Agent 服务
    print("[信息] 正在禁用 Agent 服务...")
    success, stdout, stderr = run_command("systemctl is-enabled --quiet myx-agent", check=False)
    if success:
        run_command("systemctl disable myx-agent", check=False)
        print("[信息] Agent 服务已禁用")
    else:
        print("[信息] Agent 服务未启用，跳过禁用")
    
    # 3. 删除 systemd 服务文件
    service_file = "/etc/systemd/system/myx-agent.service"
    if os.path.exists(service_file):
        print("[信息] 正在删除 systemd 服务文件...")
        try:
            os.remove(service_file)
            run_command("systemctl daemon-reload", check=False)
            print("[信息] systemd 服务文件已删除")
        except Exception as e:
            print(f"[警告] 删除 systemd 服务文件失败: {e}")
    else:
        print("[信息] systemd 服务文件不存在，跳过删除")
    
    # 4. 删除 Agent 文件目录
    agent_dir = "/opt/myx-agent"
    if os.path.exists(agent_dir):
        print("[信息] 正在删除 Agent 文件目录...")
        try:
            shutil.rmtree(agent_dir)
            print("[信息] Agent 文件目录已删除")
        except Exception as e:
            print(f"[警告] 删除 Agent 文件目录失败: {e}")
    else:
        print("[信息] Agent 文件目录不存在，跳过删除")
    
    # 5. 删除 Agent 配置文件目录
    config_dir = "/etc/myx-agent"
    if os.path.exists(config_dir):
        print("[信息] 正在删除 Agent 配置文件目录...")
        try:
            shutil.rmtree(config_dir)
            print("[信息] Agent 配置文件目录已删除")
        except Exception as e:
            print(f"[警告] 删除 Agent 配置文件目录失败: {e}")
    else:
        print("[信息] Agent 配置文件目录不存在，跳过删除")
    
    # 6. 删除 Agent 日志文件
    log_file = "/var/log/myx-agent.log"
    if os.path.exists(log_file):
        print("[信息] 正在删除 Agent 日志文件...")
        try:
            os.remove(log_file)
            print("[信息] Agent 日志文件已删除")
        except Exception as e:
            print(f"[警告] 删除 Agent 日志文件失败: {e}")
    else:
        print("[信息] Agent 日志文件不存在，跳过删除")
    
    print("[成功] Agent 卸载完成")
    return 0

if __name__ == '__main__':
    sys.exit(main())

