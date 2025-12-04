"""
部署服务

负责Agent、Xray、Caddy等组件的部署业务逻辑
统一使用Ansible playbook（SSH本地执行或Agent远程执行）
"""
import logging
import time
from typing import Tuple, Optional
from django.utils import timezone
from apps.deployments.models import Deployment
from apps.servers.models import Server
from apps.agents.models import Agent
from apps.logs.utils import create_log_entry
from .ansible_executor import AnsibleExecutor

logger = logging.getLogger(__name__)


class DeploymentService:
    """部署业务服务"""

    @staticmethod
    def install_agent(server: Server, deployment: Deployment, user=None) -> Tuple[bool, str]:
        """
        安装Agent（使用install_agent.yml playbook）

        Args:
            server: Server对象
            deployment: Deployment对象
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            from apps.agents.services.agent_service import AgentService
            from apps.agents.services.certificate_service import CertificateService

            # 1. 创建或获取Agent记录
            agent = AgentService.create_or_get_agent(server)

            deployment.log = (deployment.log or '') + f"Agent Token已生成: {agent.token}\n"
            deployment.log += f"Agent RPC端口已分配: {agent.rpc_port}\n"
            deployment.log += f"Agent RPC路径已分配: {agent.rpc_path}\n"
            deployment.save()

            # 2. 生成SSL证书
            try:
                cert_bytes, key_bytes = CertificateService.generate_certificate(
                    server.host,
                    agent.token
                )
                agent.certificate_content = cert_bytes.decode('utf-8')
                agent.private_key_content = key_bytes.decode('utf-8')
                agent.certificate_path = '/etc/myx-agent/ssl/agent.crt'
                agent.private_key_path = '/etc/myx-agent/ssl/agent.key'
                agent.verify_ssl = False
                agent.save()

                deployment.log = (deployment.log or '') + "SSL证书已生成并存储到数据库\n"
                deployment.save()
            except Exception as e:
                logger.error(f"生成SSL证书失败: {e}", exc_info=True)
                deployment.log = (deployment.log or '') + f"警告: 生成SSL证书失败: {str(e)}\n"
                deployment.save()

            # 3. 上传Agent核心文件（通过SSH SFTP）
            deployment.log = (deployment.log or '') + "[信息] 上传Agent核心文件...\n"
            deployment.save()

            success = DeploymentService._upload_agent_files_via_ssh(server, agent, deployment)
            if not success:
                return False, "上传Agent文件失败"

            deployment.log = (deployment.log or '') + "[成功] Agent文件上传完成\n"
            deployment.save()

            # 4. 执行install_agent.yml playbook（通过SSH执行Ansible）
            deployment.log = (deployment.log or '') + "[信息] 执行Agent安装playbook...\n"
            deployment.save()

            executor = AnsibleExecutor(server)
            extra_vars = {
                'agent_token': agent.token,
                'secret_key': agent.secret_key,
                'rpc_port': agent.rpc_port,
                'rpc_path': agent.rpc_path,
                'certificate_path': agent.certificate_path,
                'private_key_path': agent.private_key_path,
            }

            success, output = executor.execute_playbook(
                playbook_name='install_agent.yml',
                extra_vars=extra_vars,
                method='ssh',
                timeout=600
            )

            deployment.log = (deployment.log or '') + f"\n=== Ansible执行输出 ===\n{output}\n"
            deployment.save()

            if success:
                deployment.log = (deployment.log or '') + "[成功] Agent安装完成\n"
                deployment.save()
                logger.info(f"Agent安装成功: server={server.name}")
                return True, "Agent安装成功"
            else:
                deployment.log = (deployment.log or '') + "[失败] Agent安装失败\n"
                deployment.save()
                logger.error(f"Agent安装失败: server={server.name}")
                return False, "Agent安装失败"

        except Exception as e:
            logger.error(f"安装Agent失败: {e}", exc_info=True)
            deployment.log = (deployment.log or '') + f"[异常] {str(e)}\n"
            deployment.save()
            return False, str(e)

    @staticmethod
    def _upload_agent_files_via_ssh(server: Server, agent: Agent, deployment: Deployment) -> bool:
        """
        通过SSH SFTP上传Agent核心文件

        Args:
            server: Server对象
            agent: Agent对象
            deployment: Deployment对象

        Returns:
            bool: 是否成功
        """
        import paramiko
        from io import StringIO
        from pathlib import Path
        from django.conf import settings

        try:
            # 建立SSH连接
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # 连接认证
            if server.private_key:
                try:
                    key = paramiko.RSAKey.from_private_key(StringIO(server.private_key))
                except:
                    try:
                        key = paramiko.Ed25519Key.from_private_key(StringIO(server.private_key))
                    except:
                        key = paramiko.ECDSAKey.from_private_key(StringIO(server.private_key))
                ssh.connect(server.host, port=server.port, username=server.username, pkey=key, timeout=30)
            else:
                ssh.connect(server.host, port=server.port, username=server.username, password=server.password, timeout=30)

            # 获取Agent文件路径
            agent_dir = Path(settings.BASE_DIR) / 'deployment-tool' / 'agent'
            if not agent_dir.exists():
                deployment.log = (deployment.log or '') + f"错误: 找不到Agent目录: {agent_dir}\n"
                deployment.save()
                ssh.close()
                return False

            # 需要上传的文件
            files_to_upload = [
                'main.py',
                'rpc_server.py',
                'ansible_executor.py',
                'requirements.txt',
                'pyproject.toml',
            ]

            # 创建目录
            sftp = ssh.open_sftp()
            try:
                sftp.mkdir('/opt/myx-agent')
            except:
                pass  # 目录可能已存在

            # 上传文件
            for filename in files_to_upload:
                local_path = agent_dir / filename
                if not local_path.exists():
                    logger.warning(f"文件不存在，跳过: {filename}")
                    continue

                remote_path = f'/opt/myx-agent/{filename}'
                sftp.put(str(local_path), remote_path)
                sftp.chmod(remote_path, 0o755 if filename.endswith('.py') else 0o644)
                logger.info(f"已上传: {filename}")

            # 上传SSL证书（如果有）
            if agent.certificate_content and agent.private_key_content:
                try:
                    # 创建SSL目录
                    try:
                        sftp.mkdir('/etc/myx-agent')
                    except:
                        pass
                    try:
                        sftp.mkdir('/etc/myx-agent/ssl')
                    except:
                        pass

                    # 上传证书
                    with sftp.file('/etc/myx-agent/ssl/agent.crt', 'w') as f:
                        f.write(agent.certificate_content)
                    sftp.chmod('/etc/myx-agent/ssl/agent.crt', 0o644)

                    # 上传私钥
                    with sftp.file('/etc/myx-agent/ssl/agent.key', 'w') as f:
                        f.write(agent.private_key_content)
                    sftp.chmod('/etc/myx-agent/ssl/agent.key', 0o600)

                    deployment.log = (deployment.log or '') + "已上传SSL证书和私钥\n"
                    deployment.save()
                except Exception as e:
                    logger.error(f"上传SSL证书失败: {e}", exc_info=True)
                    deployment.log = (deployment.log or '') + f"警告: 上传SSL证书失败: {str(e)}\n"
                    deployment.save()

            sftp.close()
            ssh.close()

            return True

        except Exception as e:
            logger.error(f"上传Agent文件失败: {e}", exc_info=True)
            deployment.log = (deployment.log or '') + f"错误: 上传文件失败: {str(e)}\n"
            deployment.save()
            return False

    @staticmethod
    def wait_for_agent_startup(server: Server, timeout: int = 60, deployment: Optional[Deployment] = None) -> Optional[Agent]:
        """
        等待Agent启动并检查RPC服务是否可用

        Args:
            server: Server对象
            timeout: 超时时间（秒）
            deployment: Deployment对象（可选）

        Returns:
            Agent: Agent对象，如果启动失败则返回None
        """
        from apps.agents.rpc_support import check_agent_rpc_support

        try:
            agent = Agent.objects.get(server=server)
        except Agent.DoesNotExist:
            logger.error(f"Agent不存在: server={server.name}")
            return None

        if deployment:
            deployment.log = (deployment.log or '') + f"[信息] 等待Agent启动（最多{timeout}秒）...\n"
            deployment.save()

        start_time = time.time()
        last_log_time = 0

        while time.time() - start_time < timeout:
            elapsed = int(time.time() - start_time)

            # 每10秒输出一次进度
            if elapsed - last_log_time >= 10 and deployment:
                deployment.log = (deployment.log or '') + f"[信息] 等待Agent启动... ({elapsed}秒)\n"
                deployment.save()
                last_log_time = elapsed

            # 检查RPC服务
            if check_agent_rpc_support(agent):
                agent.refresh_from_db()
                if agent.rpc_supported:
                    logger.info(f"Agent启动成功: server={server.name}")
                    if deployment:
                        deployment.log = (deployment.log or '') + "[成功] Agent RPC服务已启动\n"
                        deployment.save()
                    return agent

            time.sleep(3)

        # 超时
        logger.warning(f"Agent启动超时: server={server.name}")
        if deployment:
            deployment.log = (deployment.log or '') + "[警告] Agent启动超时\n"
            deployment.save()

        return agent

    @staticmethod
    def deploy_service(
        server: Server,
        service_type: str,
        deployment_target: str = 'host',
        deployment: Optional[Deployment] = None,
        user=None
    ) -> Tuple[bool, str]:
        """
        部署服务（Xray或Caddy）

        Args:
            server: Server对象
            service_type: 服务类型 'xray' | 'caddy'
            deployment_target: 部署目标 'host' | 'docker'（Caddy只支持host）
            deployment: Deployment对象（可选）
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            # Caddy只支持宿主机部署
            if service_type == 'caddy':
                deployment_target = 'host'
                if deployment:
                    deployment.log = (deployment.log or '') + "[信息] Caddy仅支持宿主机部署\n"
                    deployment.save()

            # 选择playbook
            if service_type == 'xray':
                playbook_name = 'deploy_xray_docker.yml' if deployment_target == 'docker' else 'deploy_xray.yml'
                log_prefix = "Xray (Docker)" if deployment_target == 'docker' else "Xray (宿主机)"
            elif service_type == 'caddy':
                playbook_name = 'deploy_caddy.yml'
                log_prefix = "Caddy (宿主机)"
            else:
                return False, f'不支持的服务类型: {service_type}'

            if deployment:
                deployment.log = (deployment.log or '') + f"[信息] 开始部署 {log_prefix}...\n"
                deployment.save()

            # 执行playbook（自动选择SSH或Agent方式）
            executor = AnsibleExecutor(server)
            success, output = executor.execute_playbook(
                playbook_name=playbook_name,
                extra_vars={},
                method='auto',
                timeout=600
            )

            if deployment:
                deployment.log = (deployment.log or '') + f"\n=== 部署输出 ===\n{output}\n"
                deployment.save()

            if success:
                logger.info(f"{log_prefix}部署成功: server={server.name}")
                if deployment:
                    deployment.log = (deployment.log or '') + f"[成功] {log_prefix} 部署成功\n"
                    deployment.save()
                return True, f'{log_prefix}部署成功'
            else:
                logger.error(f"{log_prefix}部署失败: server={server.name}")
                if deployment:
                    deployment.log = (deployment.log or '') + f"[失败] {log_prefix} 部署失败\n"
                    deployment.save()
                return False, f'{log_prefix}部署失败'

        except Exception as e:
            logger.error(f"部署服务失败: {e}", exc_info=True)
            if deployment:
                deployment.log = (deployment.log or '') + f"[异常] {str(e)}\n"
                deployment.save()
            return False, str(e)
