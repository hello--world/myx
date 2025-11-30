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
            
            # Caddy 仅支持宿主机部署，忽略 deployment_target 设置
            if connection_method == 'agent':
                deploy_via_agent(deployment, 'host')  # 强制使用宿主机部署
            else:  # ssh
                # Caddy 仅支持宿主机部署，使用宿主机 playbook
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
            deployment.log = (deployment.log or '') + "注意：这是临时服务器，部署完成后将清除SSH密码，仅保留Agent信息\n"
        deployment.save()
        
        # 记录部署任务开始日志
        create_log_entry(
            log_type='deployment',
            level='info',
            title=f'部署任务开始: {deployment.name}',
            content=f'部署任务 {deployment.name} 已开始执行',
            user=deployment.created_by,
            server=deployment.server,
            related_id=deployment.id,
            related_type='deployment'
        )

        try:
            # 步骤1: 通过SSH安装Agent
            deployment.log = (deployment.log or '') + "步骤1: 通过SSH安装Agent...\n"
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
                deployment_target='host',  # Caddy 仅支持宿主机部署
                status='running',
                created_by=deployment.created_by
            )
            
            deploy_via_agent(caddy_deployment, 'host')  # 强制使用宿主机部署
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
        
        # 获取API地址（优先使用环境变量，否则从settings获取，最后使用默认值）
        from django.conf import settings
        import os
        api_url = os.getenv('AGENT_API_URL', getattr(settings, 'AGENT_API_URL', None))
        
        # 如果API URL是localhost，需要替换为可以从服务器访问的地址
        if not api_url or 'localhost' in api_url or '127.0.0.1' in api_url:
            # 优先使用 BACKEND_HOST 环境变量
            backend_host = os.getenv('BACKEND_HOST', getattr(settings, 'BACKEND_HOST', None))
            if backend_host:
                api_url = f"http://{backend_host}:8000/api/agents"
            else:
                # 尝试从ALLOWED_HOSTS获取
                allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
                # 过滤掉localhost和127.0.0.1
                valid_hosts = [h for h in allowed_hosts if h and h not in ['localhost', '127.0.0.1', '*']]
                if valid_hosts:
                    # 使用第一个有效的主机，假设使用HTTP和8000端口
                    api_url = f"http://{valid_hosts[0]}:8000/api/agents"
                else:
                    # 如果都没有，使用默认值并警告
                    api_url = 'http://localhost:8000/api/agents'
                    deployment.log = (deployment.log or '') + f"⚠️ 警告: API地址为 {api_url}，Agent可能无法连接。请设置 BACKEND_HOST 环境变量或配置 ALLOWED_HOSTS\n"
                    deployment.save()
        
        # 检测操作系统和架构
        stdin, stdout, stderr = ssh.exec_command("uname -s", timeout=10)
        os_type = stdout.read().decode().strip().lower() or "linux"
        stdin, stdout, stderr = ssh.exec_command("uname -m", timeout=10)
        arch = stdout.read().decode().strip() or "amd64"
        
        # 标准化操作系统名称
        if "darwin" in os_type or "macos" in os_type:
            os_name = "darwin"
        else:
            os_name = "linux"
        
        # 标准化架构名称
        if "aarch64" in arch or "arm64" in arch:
            arch = "arm64"
        else:
            arch = "amd64"
        
        deployment.log = (deployment.log or '') + f"检测到系统: {os_name}, 架构: {arch}\n"
        deployment.log = (deployment.log or '') + f"API地址: {api_url}\n"
        deployment.save()
        
        # GitHub Releases URL
        from django.conf import settings
        github_repo = os.getenv('GITHUB_REPO', getattr(settings, 'GITHUB_REPO', 'hello--world/myx'))
        binary_name = f'myx-agent-{os_name}-{arch}'
        github_url = f'https://github.com/{github_repo}/releases/latest/download/{binary_name}'
        
        deployment.log = (deployment.log or '') + f"从 GitHub Releases 下载 Agent: {github_url}\n"
        deployment.save()
        
        # 创建安装脚本（直接在服务器上下载）
        install_script = f"""#!/bin/bash
set -e

# 创建目录
mkdir -p /opt/myx-agent
mkdir -p /etc/myx-agent

# 直接从 GitHub 下载 Agent 二进制文件
echo "正在从 GitHub 下载 Agent 二进制文件..."
if curl -L -f -o /tmp/myx-agent "{github_url}"; then
    echo "Agent 下载成功"
    chmod +x /tmp/myx-agent
else
    echo "Agent 下载失败，请检查网络连接或 GitHub Releases"
    exit 1
fi

# 移动二进制文件
mv /tmp/myx-agent /opt/myx-agent/myx-agent
chmod +x /opt/myx-agent/myx-agent

# 首次注册Agent
echo "正在注册 Agent..."
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
