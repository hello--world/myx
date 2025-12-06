import logging
import threading
import time
from io import StringIO, BytesIO
from django.utils import timezone
from .models import Deployment
from .ansible_runner import run_ansible_playbook
from .agent_deployer import deploy_via_agent
from apps.servers.models import Server
from apps.agents.models import Agent
from apps.logs.utils import create_log_entry
import paramiko
import os
import ipaddress
from datetime import datetime, timedelta

# 证书生成依赖
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

logger = logging.getLogger(__name__)


def generate_ssl_certificate(server_host: str, agent_token: str) -> tuple[bytes, bytes]:
    """
    生成SSL证书和私钥（服务器端生成）
    
    Args:
        server_host: 服务器主机名或IP
        agent_token: Agent Token（用于证书标识）
        
    Returns:
        (certificate_bytes, private_key_bytes): 证书和私钥的字节内容
    """
    if not CRYPTOGRAPHY_AVAILABLE:
        raise ImportError("cryptography库未安装，无法生成证书。请运行: pip install cryptography")
    
    # 生成私钥
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # 生成证书
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "MyX"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Agent"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MyX Agent"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"{server_host}-{agent_token[:8]}"),
    ])
    
    # 构建Subject Alternative Name
    san_list = [x509.DNSName(server_host)]
    try:
        # 尝试解析为IP地址
        ip = ipaddress.ip_address(server_host)
        if isinstance(ip, ipaddress.IPv4Address):
            san_list.append(x509.IPAddress(ip))
        elif isinstance(ip, ipaddress.IPv6Address):
            san_list.append(x509.IPAddress(ip))
    except ValueError:
        # 不是IP地址，跳过
        pass
    
    cert_builder = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.utcnow()
    ).not_valid_after(
        datetime.utcnow() + timedelta(days=365)
    )
    
    # 添加Subject Alternative Name扩展
    if san_list:
        cert_builder = cert_builder.add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
    
    cert = cert_builder.sign(private_key, hashes.SHA256())
    
    # 序列化证书和私钥
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    return cert_bytes, key_bytes


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
            
            # 等待Agent启动（最多等待30秒）
            deployment.log = (deployment.log or '') + "等待Agent启动...\n"
            deployment.save()
            
            agent = wait_for_agent_startup(server, timeout=30, deployment=deployment)
            if not agent or not agent.rpc_supported:
                deployment.status = 'failed'
                deployment.error_message = 'Agent启动超时或RPC不支持'
                deployment.completed_at = timezone.now()
                deployment.save()
                return
            
            deployment.log = (deployment.log or '') + f"Agent已启动，RPC端口: {agent.rpc_port}\n"
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
    """
    通过SSH安装Agent（已重构为调用DeploymentService，统一使用全新安装方式）

    注意：保留此函数是为了向后兼容，内部已使用Service层重构

    Args:
        server: Server对象
        deployment: Deployment对象
    """
    try:
        # 调用Service层的install_agent
        from apps.deployments.services import DeploymentService

        success, message = DeploymentService.install_agent(
            server=server,
            deployment=deployment,
            user=deployment.created_by if deployment else None
        )

        return success
    except Exception as e:
        logger.error(f'安装Agent失败: {e}', exc_info=True)
        if deployment:
            deployment.log = (deployment.log or '') + f"[异常] {str(e)}\n"
            deployment.save()
        return False


def install_agent_via_ssh_legacy(server: Server, deployment: Deployment) -> bool:
    """
    通过SSH安装Agent（旧版本，已弃用）

    保留用于参考，新代码请使用install_agent_via_ssh（内部调用DeploymentService）
    """
    backup_path = None  # 记录备份路径，用于失败时恢复
    try:
        # 先创建或获取Agent记录（服务器端生成Token和RPC端口）
        import secrets
        import random
        from apps.agents.models import Agent
        
        def generate_rpc_port():
            """生成随机RPC端口"""
            excluded_ports = {22, 80, 443, 8000, 8443, 3306, 5432, 6379, 8080, 9000}
            for _ in range(100):
                port = random.randint(8000, 65535)
                if port in excluded_ports:
                    continue
                # 检查端口是否已被使用
                try:
                    existing = Agent.objects.filter(rpc_port=port).exists()
                    if existing:
                        continue
                except:
                    pass
                return port
            return None
        
        def generate_rpc_path():
            """生成随机RPC路径（用于路径混淆，保障安全）"""
            return secrets.token_urlsafe(16)  # 生成32字符的随机路径
        
        # 创建或获取Agent记录
        agent, created = Agent.objects.get_or_create(
            server=server,
            defaults={
                'token': secrets.token_urlsafe(32),
                'secret_key': secrets.token_urlsafe(32),
                'status': 'offline',  # 初始状态为离线，启动后更新
                'web_service_enabled': True,
                'web_service_port': 8443,
                'rpc_port': generate_rpc_port(),
                'rpc_path': generate_rpc_path(),  # 生成随机RPC路径
            }
        )
        
        # 如果Agent已存在但没有Token或RPC端口，生成它们（但不会更改已存在的）
        if not agent.token:
            agent.token = secrets.token_urlsafe(32)
        if not agent.secret_key:
            agent.secret_key = secrets.token_urlsafe(32)
        if not agent.rpc_port:
            agent.rpc_port = generate_rpc_port()
        if not agent.rpc_path:
            agent.rpc_path = generate_rpc_path()
        agent.save()
        
        deployment.log = (deployment.log or '') + f"Agent Token已生成: {agent.token}\n"
        deployment.log = (deployment.log or '') + f"Agent RPC端口已分配: {agent.rpc_port}\n"
        deployment.log = (deployment.log or '') + f"Agent RPC路径已分配: {agent.rpc_path}\n"
        deployment.save()
        
        # 生成SSL证书（服务器端生成）
        try:
            cert_bytes, key_bytes = generate_ssl_certificate(server.host, agent.token)
            # 存储证书内容到数据库
            agent.certificate_content = cert_bytes.decode('utf-8')
            agent.private_key_content = key_bytes.decode('utf-8')
            agent.certificate_path = '/etc/myx-agent/ssl/agent.crt'
            agent.private_key_path = '/etc/myx-agent/ssl/agent.key'
            agent.verify_ssl = False  # 默认不验证，因为使用自签名证书
            agent.save()
            deployment.log = (deployment.log or '') + f"SSL证书已生成并存储到数据库\n"
            deployment.save()
        except Exception as e:
            logger.error(f"生成SSL证书失败: {e}", exc_info=True)
            deployment.log = (deployment.log or '') + f"警告: 生成SSL证书失败: {str(e)}\n"
            deployment.save()
            # 证书生成失败不影响部署，Agent可以使用HTTP模式
        
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
        
        # Agent无状态，不需要API地址
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
        deployment.save()
        
        # 获取Agent文件路径（从deployment-tool目录）
        from pathlib import Path
        # __file__ 是 backend/apps/deployments/tasks.py
        # 需要回到项目根目录: backend/apps/deployments -> backend/apps -> backend -> 项目根
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        agent_dir = base_dir / 'deployment-tool' / 'agent'
        
        if not agent_dir.exists():
            deployment.log = (deployment.log or '') + f"错误: 找不到Agent目录: {agent_dir}\n"
            deployment.save()
            ssh.close()
            return False
        
        deployment.log = (deployment.log or '') + f"准备上传Agent文件（从目录: {agent_dir}）\n"
        deployment.save()
        
        # 通过SFTP上传Agent文件
        sftp = ssh.open_sftp()
        try:
            # 部署前备份（如果目录存在且有文件）
            deployment.log = (deployment.log or '') + f"检查是否需要备份...\n"
            deployment.save()
            
            # 检查/opt/myx-agent目录是否存在且有文件
            stdin, stdout, stderr = ssh.exec_command('test -d /opt/myx-agent && ls -A /opt/myx-agent 2>/dev/null | head -1', timeout=10)
            has_existing_files = bool(stdout.read().decode().strip())
            
            if has_existing_files:
                # 创建备份目录
                import time as time_module
                backup_dir = f'/opt/myx-agent/backup/backup_{int(time_module.time())}'
                backup_commands = [
                    f'mkdir -p {backup_dir}',
                    f'cp -r /opt/myx-agent/*.py {backup_dir}/ 2>/dev/null || true',
                    f'cp /opt/myx-agent/requirements.txt {backup_dir}/ 2>/dev/null || true',
                    f'cp -r /opt/myx-agent/__pycache__ {backup_dir}/ 2>/dev/null || true',
                    f'cp /etc/myx-agent/config.json {backup_dir}/config.json.bak 2>/dev/null || true',
                ]
                
                deployment.log = (deployment.log or '') + f"正在备份现有文件到 {backup_dir}...\n"
                deployment.save()
                
                for cmd in backup_commands:
                    try:
                        ssh.exec_command(cmd, timeout=10)
                    except:
                        pass
                
                deployment.log = (deployment.log or '') + f"备份完成: {backup_dir}\n"
                deployment.save()
            
            # 停止Agent服务（如果正在运行）
            try:
                ssh.exec_command('systemctl stop myx-agent 2>/dev/null || true', timeout=10)
            except:
                pass
            
            # 清理旧的Agent文件（保留backup目录和目录结构）
            deployment.log = (deployment.log or '') + f"清理旧的Agent文件（保留backup目录）...\n"
            deployment.save()
            
            cleanup_commands = [
                'rm -f /opt/myx-agent/*.py',
                'rm -f /opt/myx-agent/*.pyc',
                'rm -f /opt/myx-agent/requirements.txt',
                'rm -rf /opt/myx-agent/__pycache__',
                # 不删除backup目录
            ]
            for cmd in cleanup_commands:
                try:
                    ssh.exec_command(cmd, timeout=10)
                except:
                    pass
            
            deployment.log = (deployment.log or '') + f"旧文件清理完成\n"
            deployment.save()
            
            # 创建目录
            ssh.exec_command('mkdir -p /opt/myx-agent')
            ssh.exec_command('mkdir -p /etc/myx-agent')
            
            # 上传所有Python文件（.py文件）
            python_files = [
                'main.py',
                'http_server.py',
                'ansible_executor.py',
            ]
            
            for py_file in python_files:
                local_file = agent_dir / py_file
                if local_file.exists():
                    remote_file = f'/opt/myx-agent/{py_file}'
                    sftp.put(str(local_file), remote_file)
                    # main.py需要可执行权限
                    if py_file == 'main.py':
                        sftp.chmod(remote_file, 0o755)
                    else:
                        sftp.chmod(remote_file, 0o644)
                    deployment.log = (deployment.log or '') + f"已上传: {py_file}\n"
                    deployment.save()
                else:
                    deployment.log = (deployment.log or '') + f"警告: 文件不存在，跳过: {py_file}\n"
                    deployment.save()
            
            # 上传requirements.txt
            agent_requirements = agent_dir / 'requirements.txt'
            if agent_requirements.exists():
                remote_requirements = '/opt/myx-agent/requirements.txt'
                sftp.put(str(agent_requirements), remote_requirements)
                deployment.log = (deployment.log or '') + f"已上传: requirements.txt\n"
                deployment.save()
            else:
                # 创建默认的requirements.txt（包含Web服务依赖）
                remote_requirements = '/opt/myx-agent/requirements.txt'
                with sftp.file(remote_requirements, 'w') as f:
                    f.write('requests>=2.31.0\nurllib3>=2.0.0\nflask>=3.0.0\ncryptography>=41.0.0\npyopenssl>=23.3.0\n')
                deployment.log = (deployment.log or '') + f"已创建默认: requirements.txt（包含Web服务依赖）\n"
                deployment.save()
            
            # 上传SSL证书（如果已生成）
            if agent.certificate_content and agent.private_key_content:
                try:
                    # 创建SSL目录
                    ssh.exec_command('mkdir -p /etc/myx-agent/ssl')
                    
                    # 上传证书
                    remote_cert = '/etc/myx-agent/ssl/agent.crt'
                    with sftp.file(remote_cert, 'w') as f:
                        f.write(agent.certificate_content)
                    sftp.chmod(remote_cert, 0o644)
                    
                    # 上传私钥
                    remote_key = '/etc/myx-agent/ssl/agent.key'
                    with sftp.file(remote_key, 'w') as f:
                        f.write(agent.private_key_content)
                    sftp.chmod(remote_key, 0o600)
                    
                    deployment.log = (deployment.log or '') + f"已上传SSL证书和私钥到Agent服务器\n"
                    deployment.save()
                except Exception as e:
                    logger.error(f"上传SSL证书失败: {e}", exc_info=True)
                    deployment.log = (deployment.log or '') + f"警告: 上传SSL证书失败: {str(e)}\n"
                    deployment.save()
        finally:
            sftp.close()
        
        # 创建安装脚本（仅支持Python版本）
        install_script = f"""#!/bin/bash
set -e

# 检查Python版本
echo "[信息] 检测Python版本..."
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到Python3，Agent需要Python 3.6+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{{print $2}}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 6 ]); then
    echo "[错误] Python版本过低 ($PYTHON_VERSION)，需要3.6+"
    exit 1
fi

echo "[信息] 检测到Python $PYTHON_VERSION，继续安装..."

# 验证Agent文件是否存在
if [ ! -f /opt/myx-agent/main.py ]; then
    echo "[错误] Agent文件不存在: /opt/myx-agent/main.py"
    exit 1
fi

# 安装uv（如果不存在）
echo "[信息] 检查uv是否已安装..."
UV_PATH=""
if command -v uv &> /dev/null; then
    UV_PATH=$(command -v uv)
    echo "[成功] 找到已安装的uv: $UV_PATH"
else
    echo "[信息] uv未安装，正在安装uv..."
    # 使用官方安装脚本安装uv（安装到~/.cargo/bin）
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>&1 || {{
        echo "[警告] 官方安装脚本失败，尝试使用pip安装uv..."
        if command -v pip3 &> /dev/null; then
            pip3 install --user uv 2>&1 || {{
                echo "[警告] pip安装uv失败，尝试使用--break-system-packages..."
                pip3 install --user --break-system-packages uv 2>&1 || {{
                    echo "[错误] 无法安装uv，请手动安装"
                    exit 1
                }}
            }}
        else
            echo "[错误] 未找到pip3，无法安装uv"
            exit 1
        fi
    }}
    
    # 确定uv的安装路径
    if [ -f "$HOME/.cargo/bin/uv" ]; then
        UV_PATH="$HOME/.cargo/bin/uv"
        # 创建符号链接到/usr/local/bin（如果可能）
        if [ -w /usr/local/bin ]; then
            ln -sf "$UV_PATH" /usr/local/bin/uv 2>/dev/null || true
        fi
    elif [ -f "$HOME/.local/bin/uv" ]; then
        UV_PATH="$HOME/.local/bin/uv"
        # 创建符号链接到/usr/local/bin（如果可能）
        if [ -w /usr/local/bin ]; then
            ln -sf "$UV_PATH" /usr/local/bin/uv 2>/dev/null || true
        fi
    else
        echo "[错误] uv安装后无法找到，请检查安装日志"
        exit 1
    fi
    echo "[成功] uv已安装: $UV_PATH"
fi

# 验证uv是否可用
if [ -z "$UV_PATH" ]; then
    UV_PATH=$(command -v uv 2>/dev/null || echo "")
fi

if [ -z "$UV_PATH" ] || [ ! -f "$UV_PATH" ]; then
    echo "[错误] uv安装失败或不在PATH中"
    exit 1
fi

echo "[信息] 使用uv路径: $UV_PATH"

echo "[信息] 使用uv管理Agent依赖..."
# 切换到Agent目录
cd /opt/myx-agent

# 优先使用uv sync（如果存在pyproject.toml）
if [ -f pyproject.toml ]; then
    echo "[信息] 检测到pyproject.toml，使用uv sync创建虚拟环境..."
    $UV_PATH sync 2>&1 || {{
        echo "[警告] uv sync失败，直接使用uv pip install..."
    }}
    # 无论uv sync是否成功，都使用uv pip install确保所有依赖被正确安装
    echo "[信息] 使用uv pip install安装依赖（确保所有依赖被正确安装）..."
        $UV_PATH pip install -r requirements.txt 2>&1 || {{
            echo "[错误] uv pip安装失败"
            exit 1
        }}
    echo "[成功] Python依赖安装完成（使用uv sync + uv pip install）"
else
    echo "[信息] 未找到pyproject.toml，使用uv pip install安装依赖..."
    # 使用uv安装依赖（uv会自动管理虚拟环境）
    $UV_PATH pip install -r requirements.txt 2>&1 || {{
        echo "[错误] uv pip安装失败"
        exit 1
    }}
    echo "[成功] Python依赖安装完成（使用uv pip install）"
fi

# 创建Agent配置文件（服务器端已生成Token和配置，直接写入）
echo "[信息] 正在创建Agent配置文件..."
mkdir -p /etc/myx-agent
cat > /etc/myx-agent/config.json << 'EOFCONFIG'
{{
    "agent_token": "{agent.token}",
    "secret_key": "{agent.secret_key}",
    "rpc_port": {agent.rpc_port},
    "rpc_path": "{agent.rpc_path}",
    "certificate_path": "{agent.certificate_path or '/etc/myx-agent/ssl/agent.crt'}",
    "private_key_path": "{agent.private_key_path or '/etc/myx-agent/ssl/agent.key'}"
}}
EOFCONFIG
chmod 600 /etc/myx-agent/config.json
echo "[成功] Agent配置文件已创建（Token、RPC端口和路径已由服务器分配）"

# 创建systemd服务（使用uv启动）
# 使用确定的uv路径创建服务文件
# 优先使用uv run，如果uv sync失败则回退到使用虚拟环境中的Python
cat > /etc/systemd/system/myx-agent.service << 'EOFSERVICE'
[Unit]
Description=MyX Agent (Python)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/myx-agent
# 使用uv run启动，如果uv sync失败则使用已安装的虚拟环境中的Python
# 在ExecStart中动态查找uv路径，并处理uv sync失败的情况
ExecStart=/bin/bash -c 'UV_PATH=$(command -v uv 2>/dev/null || echo "$HOME/.cargo/bin/uv"); if [ ! -f "$UV_PATH" ] && [ -f "$HOME/.local/bin/uv" ]; then UV_PATH="$HOME/.local/bin/uv"; fi; if [ -d .venv ] && [ -f .venv/bin/python3 ]; then .venv/bin/python3 /opt/myx-agent/main.py; else "$UV_PATH" run /opt/myx-agent/main.py; fi'
Restart=always
RestartSec=10
Environment="PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin:/root/.cargo/bin:/root/.local/bin"

[Install]
WantedBy=multi-user.target
EOFSERVICE

# 启动服务
systemctl daemon-reload
systemctl enable myx-agent
systemctl start myx-agent

echo "[完成] Agent安装完成"
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
        
        # 等待Agent服务启动（给systemd一些时间）
        time.sleep(3)
        
        # 读取Agent日志（如果存在）
        try:
            deployment.log = (deployment.log or '') + f"\n=== Agent服务日志 ===\n"
            deployment.save()
            
            # 读取systemd服务状态
            stdin, stdout, stderr = ssh.exec_command('systemctl status myx-agent --no-pager -l', timeout=10)
            status_output = stdout.read().decode()
            if status_output:
                deployment.log = (deployment.log or '') + f"systemd服务状态:\n{status_output}\n"
                deployment.save()
            
            # 读取Agent日志文件（最后50行）
            stdin, stdout, stderr = ssh.exec_command('tail -n 50 /var/log/myx-agent.log 2>/dev/null || echo "日志文件不存在或无法读取"', timeout=10)
            log_output = stdout.read().decode()
            if log_output:
                deployment.log = (deployment.log or '') + f"Agent日志（最后50行）:\n{log_output}\n"
                deployment.save()
            
            # 读取journalctl日志（最后30行）
            stdin, stdout, stderr = ssh.exec_command('journalctl -u myx-agent -n 30 --no-pager 2>/dev/null || echo "无法读取journalctl日志"', timeout=10)
            journal_output = stdout.read().decode()
            if journal_output:
                deployment.log = (deployment.log or '') + f"systemd日志（最后30行）:\n{journal_output}\n"
                deployment.save()
        except Exception as log_error:
            logger.warning(f"读取Agent日志失败: {log_error}")
            deployment.log = (deployment.log or '') + f"警告: 读取Agent日志失败: {str(log_error)}\n"
            deployment.save()
        
        if exit_status != 0:
            deployment.log = (deployment.log or '') + f"Agent安装失败，退出码: {exit_status}\n"
            deployment.save()
            
            # 部署失败，尝试从备份恢复
            if backup_path:
                try:
                    deployment.log = (deployment.log or '') + f"部署失败，正在从备份恢复: {backup_path}...\n"
                    deployment.save()
                    
                    restore_commands = [
                        f'cp -r {backup_path}/*.py /opt/myx-agent/ 2>/dev/null || true',
                        f'cp {backup_path}/requirements.txt /opt/myx-agent/ 2>/dev/null || true',
                        f'cp -r {backup_path}/__pycache__ /opt/myx-agent/ 2>/dev/null || true',
                        f'cp {backup_path}/config.json.bak /etc/myx-agent/config.json 2>/dev/null || true',
                    ]
                    
                    for cmd in restore_commands:
                        try:
                            ssh.exec_command(cmd, timeout=10)
                        except:
                            pass
                    
                    # 恢复后尝试启动Agent服务
                    try:
                        ssh.exec_command('systemctl start myx-agent 2>/dev/null || true', timeout=10)
                    except:
                        pass
                    
                    deployment.log = (deployment.log or '') + f"已从备份恢复文件，Agent服务已尝试重启\n"
                    deployment.save()
                except Exception as restore_error:
                    logger.error(f"从备份恢复失败: {restore_error}", exc_info=True)
                    deployment.log = (deployment.log or '') + f"警告: 从备份恢复失败: {str(restore_error)}\n"
                    deployment.save()
            
            ssh.close()
            return False
        
        # 再次读取Agent日志，确认启动状态
        try:
            time.sleep(2)  # 再等待2秒
            deployment.log = (deployment.log or '') + f"\n=== Agent启动后日志检查 ===\n"
            deployment.save()
            
            # 检查服务状态
            stdin, stdout, stderr = ssh.exec_command('systemctl is-active myx-agent', timeout=10)
            service_status = stdout.read().decode().strip()
            deployment.log = (deployment.log or '') + f"Agent服务状态: {service_status}\n"
            deployment.save()
            
            # 读取最新的Agent日志
            stdin, stdout, stderr = ssh.exec_command('tail -n 20 /var/log/myx-agent.log 2>/dev/null || echo "日志文件不存在"', timeout=10)
            latest_log = stdout.read().decode()
            if latest_log:
                deployment.log = (deployment.log or '') + f"最新Agent日志:\n{latest_log}\n"
                deployment.save()
        except Exception as log_error:
            logger.warning(f"读取Agent启动后日志失败: {log_error}")
        
        ssh.close()
        return True
        
    except Exception as e:
        deployment.log = (deployment.log or '') + f"SSH连接或安装失败: {str(e)}\n"
        deployment.save()
        
        # 尝试读取日志以了解失败原因
        try:
            if 'ssh' in locals():
                stdin, stdout, stderr = ssh.exec_command('tail -n 30 /var/log/myx-agent.log 2>/dev/null || journalctl -u myx-agent -n 30 --no-pager 2>/dev/null || echo "无法读取日志"', timeout=10)
                error_log = stdout.read().decode()
                if error_log:
                    deployment.log = (deployment.log or '') + f"\n错误时的Agent日志:\n{error_log}\n"
                    deployment.save()
        except:
            pass
        
        # 部署失败，尝试从备份恢复
        if 'backup_path' in locals() and backup_path:
            try:
                deployment.log = (deployment.log or '') + f"部署异常，正在从备份恢复: {backup_path}...\n"
                deployment.save()
                
                restore_commands = [
                    f'cp -r {backup_path}/*.py /opt/myx-agent/ 2>/dev/null || true',
                    f'cp {backup_path}/requirements.txt /opt/myx-agent/ 2>/dev/null || true',
                    f'cp -r {backup_path}/__pycache__ /opt/myx-agent/ 2>/dev/null || true',
                    f'cp {backup_path}/config.json.bak /etc/myx-agent/config.json 2>/dev/null || true',
                ]
                
                for cmd in restore_commands:
                    try:
                        ssh.exec_command(cmd, timeout=10)
                    except:
                        pass
                
                # 恢复后尝试启动Agent服务
                try:
                    ssh.exec_command('systemctl start myx-agent 2>/dev/null || true', timeout=10)
                except:
                    pass
                
                deployment.log = (deployment.log or '') + f"已从备份恢复文件，Agent服务已尝试重启\n"
                deployment.save()
            except Exception as restore_error:
                logger.error(f"从备份恢复失败: {restore_error}", exc_info=True)
                deployment.log = (deployment.log or '') + f"警告: 从备份恢复失败: {str(restore_error)}\n"
                deployment.save()
        
        return False


def wait_for_agent_startup(server: Server, timeout: int = 60, deployment: Deployment = None) -> Agent:
    """
    等待Agent启动并检查RPC支持（已重构为调用DeploymentService）

    注意：保留此函数是为了向后兼容，内部已使用Service层重构

    Args:
        server: 服务器实例
        timeout: 超时时间（秒）
        deployment: 部署实例（可选，用于更新日志）
    """
    # 调用Service层的wait_for_agent_startup
    from apps.deployments.services import DeploymentService

    return DeploymentService.wait_for_agent_startup(
        server=server,
        timeout=timeout,
        deployment=deployment
    )


def wait_for_agent_startup_legacy(server: Server, timeout: int = 60, deployment: Deployment = None) -> Agent:
    """
    等待Agent启动并检查RPC支持（旧版本，已弃用）

    保留用于参考，新代码请使用wait_for_agent_startup（内部调用DeploymentService）

    Args:
        server: 服务器实例
        timeout: 超时时间（秒）
        deployment: 部署实例（可选，用于更新日志）
    """
    import time
    start_time = time.time()
    check_interval = 5  # 每5秒检查一次（减少检查频率）
    last_log_time = 0
    consecutive_failures = 0  # 连续失败次数
    max_consecutive_failures = 3  # 最多连续失败3次后提前返回
    
    # 获取Agent记录（部署时已创建）
    try:
        agent = Agent.objects.get(server=server)
    except Agent.DoesNotExist:
        logger.error(f"Agent记录不存在: server={server.name}")
        if deployment:
            deployment.log = (deployment.log or '') + f"错误: Agent记录不存在\n"
            deployment.save()
        return None
    
    # 检查RPC端口是否存在
    if not agent.rpc_port:
        logger.warning(f"Agent {agent.id} 没有RPC端口，无法检查RPC支持")
        if deployment:
            deployment.log = (deployment.log or '') + f"警告: Agent没有RPC端口\n"
            deployment.save()
        return agent
    
    # 等待Agent启动并检查RPC支持
    from apps.agents.rpc_support import check_agent_rpc_support
    logger.info(f"开始等待Agent启动: server={server.name}, rpc_port={agent.rpc_port}, rpc_path={agent.rpc_path}, timeout={timeout}秒")
    
    # 先等待几秒，让Agent服务有时间启动（systemd服务启动需要时间）
    initial_wait = 10  # 增加到10秒，给Agent更多启动时间
    logger.info(f"等待Agent服务启动（{initial_wait}秒）...")
    if deployment:
        deployment.log = (deployment.log or '') + f"等待Agent服务启动（{initial_wait}秒，让systemd服务有时间启动）...\n"
        deployment.save()
    time.sleep(initial_wait)
    
    # 调整开始时间，排除初始等待时间
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)
        remaining = int(timeout - elapsed)
        
        try:
            # 每10秒输出一次进度，并读取Agent日志
            if elapsed - last_log_time >= 10:
                logger.info(f"检查Agent RPC支持... (已等待{elapsed}秒, 剩余{remaining}秒)")
                if deployment:
                    deployment.log = (deployment.log or '') + f"检查Agent RPC支持... (已等待{elapsed}秒, 剩余{remaining}秒)\n"
                    
                    # 读取Agent日志以了解启动状态
                    try:
                        import paramiko
                        ssh_client = paramiko.SSHClient()
                        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        
                        # 连接服务器
                        if server.private_key:
                            try:
                                key = paramiko.RSAKey.from_private_key(StringIO(server.private_key))
                            except:
                                try:
                                    key = paramiko.Ed25519Key.from_private_key(StringIO(server.private_key))
                                except:
                                    key = paramiko.ECDSAKey.from_private_key(StringIO(server.private_key))
                            ssh_client.connect(server.host, port=server.port, username=server.username, pkey=key, timeout=5)
                        else:
                            ssh_client.connect(server.host, port=server.port, username=server.username, password=server.password, timeout=5)
                        
                        # 读取Agent日志（最后10行）
                        stdin, stdout, stderr = ssh_client.exec_command('tail -n 10 /var/log/myx-agent.log 2>/dev/null || journalctl -u myx-agent -n 10 --no-pager 2>/dev/null || echo "无法读取日志"', timeout=5)
                        log_output = stdout.read().decode().strip()
                        if log_output and log_output != "无法读取日志":
                            deployment.log = (deployment.log or '') + f"Agent日志（最后10行）:\n{log_output}\n"
                        
                        ssh_client.close()
                    except Exception as log_error:
                        # 忽略日志读取错误，不影响主流程
                        pass
                    
                    deployment.save()
                last_log_time = elapsed
            
            # 检查Agent是否支持JSON-RPC
            try:
                is_supported = check_agent_rpc_support(agent)
                agent.refresh_from_db()
                
                if is_supported and agent.rpc_supported:
                    elapsed_total = int(time.time() - start_time)
                    logger.info(f"Agent {agent.id} 已启动并支持JSON-RPC，端口: {agent.rpc_port}, 路径: {agent.rpc_path} (耗时{elapsed_total}秒)")
                    if deployment:
                        deployment.log = (deployment.log or '') + f"Agent已启动并支持JSON-RPC，端口: {agent.rpc_port}, 路径: {agent.rpc_path} (耗时{elapsed_total}秒)\n"
                        deployment.save()
                    return agent
                
                # 检查失败，但如果是SSL错误（服务可能还在启动），不计入连续失败
                # 只有非SSL错误才计入连续失败
                from apps.agents.rpc_client import get_agent_rpc_client
                rpc_client = get_agent_rpc_client(agent)
                if rpc_client:
                    # 尝试检查是否是SSL错误（服务可能还在启动）
                    try:
                        # 快速检查是否是SSL相关错误
                        health_check = rpc_client.health_check()
                        if not health_check:
                            # 健康检查失败，可能是服务还没启动，不算连续失败
                            logger.debug(f"Agent健康检查失败（服务可能还在启动），继续等待...")
                            consecutive_failures = 0  # 重置连续失败计数
                    except Exception as check_e:
                        error_str = str(check_e)
                        if 'SSL' in error_str or 'EOF' in error_str:
                            # SSL错误，服务可能还在启动，不算连续失败
                            logger.debug(f"Agent SSL错误（服务可能还在启动），继续等待...")
                            consecutive_failures = 0  # 重置连续失败计数
                        else:
                            # 其他错误，计入连续失败
                            consecutive_failures += 1
                else:
                    # 无法创建RPC客户端，计入连续失败
                    consecutive_failures += 1
                
                # 如果连续失败多次（非SSL错误），提前返回
                if consecutive_failures >= max_consecutive_failures:
                    elapsed_total = int(time.time() - start_time)
                    logger.warning(f"Agent RPC检查连续失败{consecutive_failures}次（非SSL错误），提前返回: server={server.name}, rpc_port={agent.rpc_port}, rpc_path={agent.rpc_path}")
                    if deployment:
                        deployment.log = (deployment.log or '') + f"Agent RPC检查连续失败{consecutive_failures}次（非SSL错误），提前返回 (已等待{elapsed_total}秒)\n"
                        deployment.log = (deployment.log or '') + f"RPC端口: {agent.rpc_port}, RPC路径: {agent.rpc_path}, RPC支持状态: {agent.rpc_supported}\n"
                        deployment.save()
                    return agent
            except Exception as check_ex:
                # 检查过程中的异常
                error_str = str(check_ex)
                if 'SSL' in error_str or 'EOF' in error_str:
                    # SSL错误，服务可能还在启动，不算连续失败
                    logger.debug(f"Agent检查异常（SSL错误，服务可能还在启动）: {check_ex}")
                    consecutive_failures = 0  # 重置连续失败计数
                else:
                    # 其他异常，计入连续失败
                    consecutive_failures += 1
                    logger.debug(f"Agent检查异常: {check_ex}")
                    if consecutive_failures >= max_consecutive_failures:
                        elapsed_total = int(time.time() - start_time)
                        logger.warning(f"Agent RPC检查连续异常{consecutive_failures}次，提前返回: server={server.name}, error={check_ex}")
                        if deployment:
                            deployment.log = (deployment.log or '') + f"Agent RPC检查连续异常{consecutive_failures}次，提前返回 (已等待{elapsed_total}秒): {str(check_ex)}\n"
                            deployment.save()
                        return agent
            
            # 等待后再次检查
            time.sleep(check_interval)
            
        except Exception as e:
            consecutive_failures += 1
            logger.debug(f"检查Agent RPC支持异常: {e}")
            if consecutive_failures >= max_consecutive_failures:
                # 连续异常多次，提前返回
                elapsed_total = int(time.time() - start_time)
                logger.warning(f"Agent RPC检查连续异常{consecutive_failures}次，提前返回: server={server.name}, error={e}")
                if deployment:
                    deployment.log = (deployment.log or '') + f"Agent RPC检查连续异常{consecutive_failures}次，提前返回 (已等待{elapsed_total}秒): {str(e)}\n"
                    deployment.save()
                return agent
            time.sleep(check_interval)
    
    # 超时
    elapsed_total = int(time.time() - start_time)
    agent.refresh_from_db()
    logger.warning(f"Agent启动超时: server={server.name}, timeout={timeout}秒, 实际等待{elapsed_total}秒, rpc_port={agent.rpc_port}, rpc_path={agent.rpc_path}, rpc_supported={agent.rpc_supported}")
    if deployment:
        deployment.log = (deployment.log or '') + f"Agent启动超时 (等待{elapsed_total}秒)\n"
        deployment.log = (deployment.log or '') + f"RPC端口: {agent.rpc_port}, RPC路径: {agent.rpc_path}, RPC支持状态: {agent.rpc_supported}\n"
        
        # 超时时读取完整的Agent日志
        try:
            import paramiko
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 连接服务器
            if server.private_key:
                try:
                    key = paramiko.RSAKey.from_private_key(StringIO(server.private_key))
                except:
                    try:
                        key = paramiko.Ed25519Key.from_private_key(StringIO(server.private_key))
                    except:
                        key = paramiko.ECDSAKey.from_private_key(StringIO(server.private_key))
                ssh_client.connect(server.host, port=server.port, username=server.username, pkey=key, timeout=5)
            else:
                ssh_client.connect(server.host, port=server.port, username=server.username, password=server.password, timeout=5)
            
            # 读取systemd服务状态
            stdin, stdout, stderr = ssh_client.exec_command('systemctl status myx-agent --no-pager -l', timeout=5)
            status_output = stdout.read().decode()
            if status_output:
                deployment.log = (deployment.log or '') + f"\n=== systemd服务状态 ===\n{status_output}\n"
            
            # 读取Agent日志（最后50行）
            stdin, stdout, stderr = ssh_client.exec_command('tail -n 50 /var/log/myx-agent.log 2>/dev/null || echo "日志文件不存在"', timeout=5)
            log_output = stdout.read().decode()
            if log_output and "日志文件不存在" not in log_output:
                deployment.log = (deployment.log or '') + f"\n=== Agent日志（最后50行）===\n{log_output}\n"
            
            # 读取journalctl日志
            stdin, stdout, stderr = ssh_client.exec_command('journalctl -u myx-agent -n 50 --no-pager 2>/dev/null || echo "无法读取journalctl"', timeout=5)
            journal_output = stdout.read().decode()
            if journal_output and "无法读取journalctl" not in journal_output:
                deployment.log = (deployment.log or '') + f"\n=== systemd日志（最后50行）===\n{journal_output}\n"
            
            ssh_client.close()
        except Exception as log_error:
            logger.warning(f"读取Agent超时日志失败: {log_error}")
            deployment.log = (deployment.log or '') + f"警告: 读取Agent日志失败: {str(log_error)}\n"
        
        # 尝试最后一次检查，并记录详细错误信息
        try:
            from apps.agents.rpc_client import get_agent_rpc_client
            rpc_client = get_agent_rpc_client(agent)
            if rpc_client:
                # 尝试健康检查
                health_ok = rpc_client.health_check()
                deployment.log = (deployment.log or '') + f"最后健康检查: {'成功' if health_ok else '失败'}\n"
                if not health_ok:
                    # 尝试获取详细错误
                    try:
                        result = rpc_client._call('health_check', {}, max_retries=1)
                        if 'error' in result:
                            deployment.log = (deployment.log or '') + f"RPC错误详情: {result.get('error')}\n"
                    except Exception as e:
                        deployment.log = (deployment.log or '') + f"RPC调用异常: {str(e)}\n"
        except Exception as e:
            deployment.log = (deployment.log or '') + f"获取RPC客户端失败: {str(e)}\n"
        deployment.save()
    
    # 返回agent（即使不支持RPC），让调用者决定如何处理
    return agent
