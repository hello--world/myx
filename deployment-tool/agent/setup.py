#!/usr/bin/env python3
"""
MyX Agent安装脚本
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

def main():
    """安装Agent"""
    print("MyX Agent (Python) 安装脚本")
    print("=" * 50)
    
    # 检查Python版本
    if sys.version_info < (3, 6):
        print("错误: 需要Python 3.6或更高版本")
        sys.exit(1)
    
    # 获取安装目录
    install_dir = Path("/opt/myx-agent")
    config_dir = Path("/etc/myx-agent")
    log_dir = Path("/var/log")
    
    print(f"安装目录: {install_dir}")
    print(f"配置目录: {config_dir}")
    
    # 创建目录
    install_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 复制文件
    script_dir = Path(__file__).parent
    files_to_copy = ['main.py', 'requirements.txt']
    
    for file in files_to_copy:
        src = script_dir / file
        if src.exists():
            dst = install_dir / file
            shutil.copy2(src, dst)
            print(f"已复制: {file}")
    
    # 安装依赖
    print("\n安装Python依赖...")
    try:
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', '-r',
            str(install_dir / 'requirements.txt')
        ])
        print("依赖安装成功")
    except subprocess.CalledProcessError as e:
        print(f"依赖安装失败: {e}")
        sys.exit(1)
    
    # 设置可执行权限
    main_script = install_dir / 'main.py'
    os.chmod(main_script, 0o755)
    
    # 创建systemd服务文件
    service_file = Path("/etc/systemd/system/myx-agent.service")
    service_content = f"""[Unit]
Description=MyX Agent (Python)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={install_dir}
ExecStart={sys.executable} {main_script}
Restart=always
RestartSec=10
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
"""
    
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
        print(f"\n已创建systemd服务文件: {service_file}")
    except PermissionError:
        print(f"\n警告: 无法创建systemd服务文件（需要root权限）")
        print("请手动创建服务文件:")
        print(service_content)
    
    print("\n安装完成！")
    print("\n下一步:")
    print(f"1. 注册Agent: {sys.executable} {main_script} --token <server_token> --api <api_url>")
    print("2. 启动服务: systemctl daemon-reload && systemctl enable myx-agent && systemctl start myx-agent")

if __name__ == '__main__':
    if os.geteuid() != 0:
        print("错误: 需要root权限运行安装脚本")
        sys.exit(1)
    main()


