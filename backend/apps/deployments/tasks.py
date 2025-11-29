import threading
import time
from io import StringIO
from django.utils import timezone
from .models import Deployment
from .ansible_runner import run_ansible_playbook
from .agent_deployer import deploy_via_agent
from apps.servers.models import Server
from apps.agents.models import Agent
import paramiko


def deploy_xray(deployment_id):
    """部署Xray任务（在线程中运行）"""
    def _deploy():
        deployment = Deployment.objects.get(id=deployment_id)
        deployment.status = 'running'
        deployment.started_at = timezone.now()
        deployment.save()

        try:
            # 根据连接方式选择不同的部署方法
            connection_method = deployment.connection_method or deployment.server.connection_method
            deployment_target = deployment.deployment_target or deployment.server.deployment_target
            
            if connection_method == 'agent':
                deploy_via_agent(deployment, deployment_target)
            else:  # ssh
                # 根据部署目标选择不同的 playbook
                if deployment_target == 'docker':
                    playbook = 'deploy_xray_docker.yml'
                else:  # host
                    playbook = 'deploy_xray.yml'
                
                result = run_ansible_playbook(
                    deployment.server,
                    playbook
                )
                deployment.log = result.get('log', '')
                if result.get('success'):
                    deployment.status = 'success'
                else:
                    deployment.status = 'failed'
                    deployment.error_message = result.get('error', '部署失败')
                deployment.completed_at = timezone.now()
                deployment.save()
        except Exception as e:
            deployment.status = 'failed'
            deployment.error_message = str(e)
            deployment.completed_at = timezone.now()
            deployment.save()

    thread = threading.Thread(target=_deploy)
    thread.daemon = True
    thread.start()


def deploy_caddy(deployment_id):
    """部署Caddy任务（在线程中运行）"""
    def _deploy():
        deployment = Deployment.objects.get(id=deployment_id)
        deployment.status = 'running'
        deployment.started_at = timezone.now()
        deployment.save()

        try:
            # 根据连接方式选择不同的部署方法
            connection_method = deployment.connection_method or deployment.server.connection_method
            deployment_target = deployment.deployment_target or deployment.server.deployment_target
            
            if connection_method == 'agent':
                deploy_via_agent(deployment, deployment_target)
            else:  # ssh
                # 根据部署目标选择不同的 playbook
                if deployment_target == 'docker':
                    playbook = 'deploy_caddy_docker.yml'
                else:  # host
                    playbook = 'deploy_caddy.yml'
                
                result = run_ansible_playbook(
                    deployment.server,
                    playbook
                )
                deployment.log = result.get('log', '')
                if result.get('success'):
                    deployment.status = 'success'
                else:
                    deployment.status = 'failed'
                    deployment.error_message = result.get('error', '部署失败')
                deployment.completed_at = timezone.now()
                deployment.save()
        except Exception as e:
            deployment.status = 'failed'
            deployment.error_message = str(e)
            deployment.completed_at = timezone.now()
            deployment.save()

    thread = threading.Thread(target=_deploy)
    thread.daemon = True
    thread.start()


def quick_deploy_full(deployment_id, is_temporary=False):
    """一键部署：Agent + Xray + Caddy（在线程中运行）
    
    Args:
        deployment_id: 部署任务ID
        is_temporary: 是否为临时服务器（直接输入的，不保存密码）
    """
    def _deploy():
        deployment = Deployment.objects.get(id=deployment_id)
        server = deployment.server
        deployment.status = 'running'
        deployment.started_at = timezone.now()
        deployment.log = "开始一键部署流程...\n"
        if is_temporary:
            deployment.log += "注意：这是临时服务器，部署完成后将清除SSH密码，仅保留Agent信息\n"
        deployment.save()

        try:
            # 步骤1: 通过SSH安装Agent
            deployment.log += "步骤1: 通过SSH安装Agent...\n"
            deployment.save()
            
            agent_installed = install_agent_via_ssh(server, deployment)
            if not agent_installed:
                deployment.status = 'failed'
                deployment.error_message = 'Agent安装失败'
                deployment.completed_at = timezone.now()
                deployment.save()
                return
            
            # 等待Agent注册（最多等待30秒）
            deployment.log = (deployment.log or '') + "等待Agent注册...\n"
            deployment.save()
            
            agent = wait_for_agent_registration(server, timeout=30)
            if not agent:
                deployment.status = 'failed'
                deployment.error_message = 'Agent注册超时'
                deployment.completed_at = timezone.now()
                deployment.save()
                return
            
            deployment.log = (deployment.log or '') + f"Agent已注册，Token: {agent.token}\n"
            deployment.save()
            
            # 更新服务器连接方式为Agent
            server.connection_method = 'agent'
            server.status = 'active'
            
            # 如果是临时服务器（直接输入的），清除SSH密码，只保留Agent信息
            if is_temporary or server.name.startswith('[临时]'):
                server.password = ''  # 清除密码
                server.private_key = ''  # 清除私钥（可选，如果用户想保留可以注释掉）
                server.name = server.name.replace('[临时] ', '')  # 移除临时标记
                deployment.log = (deployment.log or '') + "已清除SSH密码，仅保留Agent信息\n"
            
            server.save()
            
            # 步骤2: 通过Agent部署Xray
            deployment.log = (deployment.log or '') + "步骤2: 通过Agent部署Xray...\n"
            deployment.save()
            
            xray_deployment = Deployment.objects.create(
                name=f"Xray部署 - {server.name}",
                server=server,
                deployment_type='xray',
                connection_method='agent',
                deployment_target=deployment.deployment_target or 'host',
                status='running',
                created_by=deployment.created_by
            )
            
            deploy_via_agent(xray_deployment, deployment.deployment_target or 'host')
            xray_deployment.refresh_from_db()
            
            if xray_deployment.status != 'success':
                deployment.status = 'failed'
                deployment.error_message = f'Xray部署失败: {xray_deployment.error_message}'
                deployment.log = (deployment.log or '') + f"Xray部署失败: {xray_deployment.error_message}\n"
                deployment.completed_at = timezone.now()
                deployment.save()
                return
            
            deployment.log = (deployment.log or '') + "Xray部署成功\n"
            deployment.save()
            
            # 步骤3: 通过Agent部署Caddy
            deployment.log = (deployment.log or '') + "步骤3: 通过Agent部署Caddy...\n"
            deployment.save()
            
            caddy_deployment = Deployment.objects.create(
                name=f"Caddy部署 - {server.name}",
                server=server,
                deployment_type='caddy',
                connection_method='agent',
                deployment_target=deployment.deployment_target or 'host',
                status='running',
                created_by=deployment.created_by
            )
            
            deploy_via_agent(caddy_deployment, deployment.deployment_target or 'host')
            caddy_deployment.refresh_from_db()
            
            if caddy_deployment.status != 'success':
                deployment.status = 'failed'
                deployment.error_message = f'Caddy部署失败: {caddy_deployment.error_message}'
                deployment.log = (deployment.log or '') + f"Caddy部署失败: {caddy_deployment.error_message}\n"
                deployment.completed_at = timezone.now()
                deployment.save()
                return
            
            deployment.log = (deployment.log or '') + "Caddy部署成功\n"
            deployment.status = 'success'
            deployment.log = (deployment.log or '') + "一键部署完成！Agent信息已自动记录。\n"
            deployment.completed_at = timezone.now()
            deployment.save()
            
        except Exception as e:
            deployment.status = 'failed'
            deployment.error_message = str(e)
            deployment.log = (deployment.log or '') + f"部署失败: {str(e)}\n"
            deployment.completed_at = timezone.now()
            deployment.save()

    thread = threading.Thread(target=_deploy)
    thread.daemon = True
    thread.start()


def install_agent_via_ssh(server: Server, deployment: Deployment) -> bool:
    """通过SSH安装Agent"""
    try:
        # 建立SSH连接
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 连接认证
        if server.private_key:
            # 使用私钥
            try:
                key = paramiko.RSAKey.from_private_key(StringIO(server.private_key))
            except:
                try:
                    # 尝试其他密钥类型
                    key = paramiko.Ed25519Key.from_private_key(StringIO(server.private_key))
                except:
                    # 尝试ECDSA
                    key = paramiko.ECDSAKey.from_private_key(StringIO(server.private_key))
            ssh.connect(server.host, port=server.port, username=server.username, pkey=key, timeout=10)
        else:
            # 使用密码
            ssh.connect(server.host, port=server.port, username=server.username, password=server.password, timeout=10)
        
        # 获取API地址
        from django.conf import settings
        import os
        api_url = os.getenv('AGENT_API_URL', getattr(settings, 'AGENT_API_URL', 'http://localhost:8000/api/agents'))
        
        # 检测系统架构
        stdin, stdout, stderr = ssh.exec_command("uname -m", timeout=10)
        arch = stdout.read().decode().strip() or "amd64"
        if "aarch64" in arch or "arm64" in arch:
            arch = "arm64"
        else:
            arch = "amd64"
        
        deployment.log = (deployment.log or '') + f"检测到系统架构: {arch}\n"
        deployment.save()
        
        # 从 GitHub Releases 下载 Agent 二进制文件
        import subprocess
        import os
        from pathlib import Path
        import urllib.request
        from django.conf import settings
        
        # GitHub Releases URL
        # 格式: https://github.com/OWNER/REPO/releases/latest/download/myx-agent-linux-{arch}
        github_repo = os.getenv('GITHUB_REPO', getattr(settings, 'GITHUB_REPO', 'hello--world/myx'))
        binary_name = f'myx-agent-linux-{arch}'
        github_url = f'https://github.com/{github_repo}/releases/latest/download/{binary_name}'
        
        # 临时文件路径
        temp_dir = Path('/tmp/myx-agent-builds')
        temp_dir.mkdir(exist_ok=True)
        binary_path = temp_dir / binary_name
        
        # 如果二进制文件不存在，从 GitHub 下载
        if not binary_path.exists():
            deployment.log = (deployment.log or '') + f"从 GitHub Releases 下载 Agent 二进制文件...\n"
            deployment.log = (deployment.log or '') + f"下载地址: {github_url}\n"
            deployment.save()
            
            try:
                # 下载二进制文件
                deployment.log = (deployment.log or '') + "正在下载...\n"
                deployment.save()
                
                urllib.request.urlretrieve(github_url, binary_path)
                
                # 设置执行权限
                os.chmod(binary_path, 0o755)
                
                deployment.log = (deployment.log or '') + f"Agent 二进制文件下载成功: {binary_path}\n"
                deployment.save()
                
            except urllib.error.HTTPError as e:
                deployment.log = (deployment.log or '') + f"下载失败 (HTTP {e.code}): {e.reason}\n"
                deployment.log = (deployment.log or '') + f"请确保 GitHub Releases 中存在 {binary_name} 文件\n"
                deployment.status = 'failed'
                deployment.error_message = f'Agent下载失败: HTTP {e.code} - {e.reason}'
                deployment.completed_at = timezone.now()
                deployment.save()
                return False
            except Exception as e:
                import traceback
                deployment.log = (deployment.log or '') + f"下载异常: {str(e)}\n{traceback.format_exc()}\n"
                deployment.status = 'failed'
                deployment.error_message = f'Agent下载异常: {str(e)}'
                deployment.completed_at = timezone.now()
                deployment.save()
                return False
        else:
            deployment.log = (deployment.log or '') + f"使用已存在的 Agent 二进制文件: {binary_path}\n"
            deployment.save()
        
        # 上传二进制文件到服务器
        deployment.log = (deployment.log or '') + f"上传 Agent 二进制文件到服务器...\n"
        deployment.save()
        
        sftp = ssh.open_sftp()
        remote_binary = '/tmp/myx-agent'
        
        try:
            with open(binary_path, 'rb') as local_file:
                with sftp.file(remote_binary, 'wb') as remote_file:
                    remote_file.write(local_file.read())
            sftp.chmod(remote_binary, 0o755)
            deployment.log = (deployment.log or '') + "二进制文件上传成功\n"
            deployment.save()
        except Exception as e:
            deployment.log = (deployment.log or '') + f"上传失败: {str(e)}\n"
            deployment.status = 'failed'
            deployment.error_message = f'Agent上传失败: {str(e)}'
            deployment.completed_at = timezone.now()
            deployment.save()
            sftp.close()
            return False
        
        sftp.close()
        
        # 创建安装脚本
        install_script = f"""#!/bin/bash
set -e

# 创建目录
mkdir -p /opt/myx-agent
mkdir -p /etc/myx-agent

# 移动二进制文件
mv /tmp/myx-agent /opt/myx-agent/myx-agent
chmod +x /opt/myx-agent/myx-agent

# 首次注册Agent
/opt/myx-agent/myx-agent -token {server.id} -api {api_url}

# 创建systemd服务
cat > /etc/systemd/system/myx-agent.service << 'EOF'
[Unit]
Description=MyX Agent
After=network.target

[Service]
Type=simple
User=root
ExecStart=/opt/myx-agent/myx-agent
Restart=always
RestartSec=10
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
systemctl daemon-reload
systemctl enable myx-agent
systemctl start myx-agent

echo "Agent安装完成"
"""
        
        # 上传安装脚本并执行
        sftp = ssh.open_sftp()
        remote_script = '/tmp/install_agent.sh'
        with sftp.file(remote_script, 'w') as f:
            f.write(install_script)
        sftp.chmod(remote_script, 0o755)
        sftp.close()
        
        # 执行安装脚本
        stdin, stdout, stderr = ssh.exec_command(f"bash {remote_script}", timeout=300)
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode()
        error = stderr.read().decode()
        
        deployment.log = (deployment.log or '') + f"Agent安装输出:\n{output}\n"
        if error:
            deployment.log = (deployment.log or '') + f"错误信息:\n{error}\n"
        deployment.save()
        
        if exit_status != 0:
            deployment.log = (deployment.log or '') + f"Agent安装失败，退出码: {exit_status}\n"
            deployment.save()
            ssh.close()
            return False
        
        ssh.close()
        return True
        
    except Exception as e:
        deployment.log = (deployment.log or '') + f"SSH连接或安装失败: {str(e)}\n"
        deployment.save()
        return False


def wait_for_agent_registration(server: Server, timeout: int = 30) -> Agent:
    """等待Agent注册"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            agent = Agent.objects.get(server=server)
            if agent.status == 'online':
                return agent
        except Agent.DoesNotExist:
            pass
        
        time.sleep(2)
    
    return None
