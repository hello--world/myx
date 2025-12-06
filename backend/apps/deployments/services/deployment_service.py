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
    def install_or_upgrade_agent(
        server: Server,
        deployment: Deployment,
        method: str = 'auto',
        user=None
    ) -> Tuple[bool, str]:
        """
        安装或升级Agent（统一使用全新安装方式，删除旧的然后全新安装）
        
        支持SSH和Agent两种方式：
        - SSH方式：通过SSH上传文件并执行playbook
        - Agent方式：通过Agent上传文件并执行playbook（Agent在线时）

        Args:
            server: Server对象
            deployment: Deployment对象
            method: 执行方式 'ssh' | 'agent' | 'auto'（自动选择）
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            from apps.agents.services.agent_service import AgentService
            from apps.agents.services.certificate_service import CertificateService

            # 自动选择执行方式
            if method == 'auto':
                try:
                    agent = Agent.objects.get(server=server)
                    if agent.status == 'online' and agent.rpc_supported and server.connection_method == 'agent':
                        method = 'agent'
                    else:
                        method = 'ssh'
                except Agent.DoesNotExist:
                    method = 'ssh'

            # 1. 创建或获取Agent记录
            agent = AgentService.create_or_get_agent(server)

            deployment.log = (deployment.log or '') + f"Agent Token已生成: {agent.token}\n"
            deployment.log += f"Agent HTTP端口已分配: {agent.rpc_port}\n"
            deployment.log += f"Agent HTTP路径已分配: {agent.rpc_path}\n"
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

            # 3. 上传Agent核心文件
            deployment.log = (deployment.log or '') + "[信息] 上传Agent核心文件...\n"
            deployment.save()

            if method == 'agent':
                success = DeploymentService._upload_agent_files_via_agent(agent, deployment)
            else:
                success = DeploymentService._upload_agent_files_via_ssh(server, agent, deployment)
            
            if not success:
                return False, "上传Agent文件失败"

            deployment.log = (deployment.log or '') + "[成功] Agent文件上传完成\n"
            deployment.save()

            # 4. 执行install_agent.yml playbook
            deployment.log = (deployment.log or '') + "[信息] 执行Agent安装playbook...\n"
            deployment.save()

            extra_vars = {
                'agent_token': agent.token,
                'secret_key': agent.secret_key,
                'http_port': agent.rpc_port,  # 使用rpc_port字段存储HTTP端口
                'http_path': agent.rpc_path,  # 使用rpc_path字段存储HTTP路径
                'certificate_path': agent.certificate_path,
                'private_key_path': agent.private_key_path,
            }

            if method == 'agent':
                # 通过Agent执行playbook
                success, output = DeploymentService._execute_playbook_via_agent(
                    agent, deployment, extra_vars
                )
            else:
                # 通过SSH执行playbook
                executor = AnsibleExecutor(server)
                success, output = executor.execute_playbook(
                    playbook_name='install_agent.yml',
                    extra_vars=extra_vars,
                    method='ssh',
                    timeout=600
                )

            # 记录详细的执行输出
            if output:
                deployment.log = (deployment.log or '') + f"\n=== Ansible执行输出 ===\n{output}\n"
            else:
                deployment.log = (deployment.log or '') + "\n=== Ansible执行输出 ===\n[警告] 未获取到执行输出\n"
            deployment.save()

            if success:
                deployment.log = (deployment.log or '') + "[成功] Agent安装完成\n"
                deployment.save()
                logger.info(f"Agent安装成功: server={server.name}")
                return True, "Agent安装成功"
            else:
                error_msg = output if output else "Ansible执行失败，但未获取到错误信息"
                deployment.log = (deployment.log or '') + f"[失败] Agent安装失败\n错误信息: {error_msg}\n"
                deployment.save()
                logger.error(f"Agent安装失败: server={server.name}, 错误: {error_msg}")
                return False, f"Agent安装失败: {error_msg}"

        except Exception as e:
            logger.error(f"安装Agent失败: {e}", exc_info=True)
            deployment.log = (deployment.log or '') + f"[异常] {str(e)}\n"
            deployment.save()
            return False, str(e)

    @staticmethod
    def install_agent(server: Server, deployment: Deployment, user=None) -> Tuple[bool, str]:
        """
        安装Agent（使用install_agent.yml playbook，统一使用全新安装方式）
        兼容性方法，内部调用 install_or_upgrade_agent

        Args:
            server: Server对象
            deployment: Deployment对象
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        return DeploymentService.install_or_upgrade_agent(server, deployment, method='ssh', user=user)
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

            # 4. 执行前置检查playbook（通过SSH执行Ansible）
            deployment.log = (deployment.log or '') + "[信息] 检查Agent安装前置条件...\n"
            deployment.save()

            executor = AnsibleExecutor(server)
            
            # 先执行前置检查
            check_success, check_output = executor.execute_playbook(
                playbook_name='check_agent_prerequisites.yml',
                extra_vars={},
                method='ssh',
                timeout=120
            )

            if check_output:
                deployment.log = (deployment.log or '') + f"\n=== 前置检查输出 ===\n{check_output}\n"
            deployment.save()

            if not check_success:
                error_msg = check_output if check_output else "前置检查失败，但未获取到错误信息"
                deployment.log = (deployment.log or '') + f"[失败] 前置检查失败\n错误信息: {error_msg}\n"
                deployment.save()
                logger.error(f"Agent前置检查失败: server={server.name}, 错误: {error_msg}")
                return False, f"前置检查失败: {error_msg}"

            deployment.log = (deployment.log or '') + "[成功] 前置检查通过\n"
            deployment.save()

            # 5. 执行install_agent.yml playbook（通过SSH执行Ansible）
            deployment.log = (deployment.log or '') + "[信息] 执行Agent安装playbook...\n"
            deployment.save()
            extra_vars = {
                'agent_token': agent.token,
                'secret_key': agent.secret_key,
                'http_port': agent.rpc_port,  # 使用rpc_port字段存储HTTP端口
                'http_path': agent.rpc_path,  # 使用rpc_path字段存储HTTP路径
                'certificate_path': agent.certificate_path,
                'private_key_path': agent.private_key_path,
                'certificate_content': agent.certificate_content or '',  # 证书内容
                'private_key_content': agent.private_key_content or '',  # 私钥内容
            }

            success, output = executor.execute_playbook(
                playbook_name='install_agent.yml',
                extra_vars=extra_vars,
                method='ssh',
                timeout=600
            )

            # 记录详细的执行输出
            if output:
                deployment.log = (deployment.log or '') + f"\n=== Ansible执行输出 ===\n{output}\n"
            else:
                deployment.log = (deployment.log or '') + "\n=== Ansible执行输出 ===\n[警告] 未获取到执行输出\n"
            deployment.save()

            if success:
                deployment.log = (deployment.log or '') + "[成功] Agent安装完成\n"
                deployment.save()
                logger.info(f"Agent安装成功: server={server.name}")
                return True, "Agent安装成功"
            else:
                error_msg = output if output else "Ansible执行失败，但未获取到错误信息"
                deployment.log = (deployment.log or '') + f"[失败] Agent安装失败\n错误信息: {error_msg}\n"
                deployment.save()
                logger.error(f"Agent安装失败: server={server.name}, 错误: {error_msg}")
                return False, f"Agent安装失败: {error_msg}"

        except Exception as e:
            logger.error(f"安装Agent失败: {e}", exc_info=True)
            deployment.log = (deployment.log or '') + f"[异常] {str(e)}\n"
            deployment.save()
            return False, str(e)

    @staticmethod
    def _upload_agent_files_via_agent(agent: Agent, deployment: Deployment) -> bool:
        """
        通过Agent上传Agent核心文件到临时目录

        Args:
            agent: Agent对象
            deployment: Deployment对象

        Returns:
            bool: 是否成功
        """
        import base64
        from pathlib import Path
        from django.conf import settings

        try:
            # 获取Agent文件路径
            agent_dir = Path(settings.BASE_DIR) / 'deployment-tool' / 'agent'
            if not agent_dir.exists():
                deployment.log = (deployment.log or '') + f"错误: 找不到Agent目录: {agent_dir}\n"
                deployment.save()
                return False

            # 需要上传的文件
            files_to_upload = [
                'main.py',
                'http_server.py',
                'ansible_executor.py',
                'requirements.txt',
            ]

            # 创建上传脚本
            upload_script = """#!/bin/bash
set -e

# 创建临时目录
mkdir -p /tmp/myx-agent-files

"""

            # 为每个文件创建上传命令
            for filename in files_to_upload:
                file_path = agent_dir / filename
                if not file_path.exists():
                    logger.warning(f"文件不存在，跳过: {filename}")
                    continue

                # 读取文件内容并base64编码
                with open(file_path, 'rb') as f:
                    content = f.read()
                content_b64 = base64.b64encode(content).decode('ascii')

                # 添加解码和写入命令
                upload_script += f"""
# 上传 {filename}
echo "{content_b64}" | base64 -d > /tmp/myx-agent-files/{filename}
"""

            upload_script += """
# 设置权限
chmod -R 755 /tmp/myx-agent-files
chmod +x /tmp/myx-agent-files/*.py

echo "文件上传完成"
"""

            # 执行上传脚本
            from apps.agents.utils import execute_script_via_agent
            cmd = execute_script_via_agent(
                agent,
                upload_script,
                timeout=60,
                script_name='upload_agent_files.sh'
            )

            # 等待命令完成
            max_wait = 60
            wait_time = 0
            while wait_time < max_wait:
                cmd.refresh_from_db()
                if cmd.status in ['success', 'failed']:
                    break
                time.sleep(1)
                wait_time += 1

            if cmd.status == 'success':
                logger.info(f'Agent文件上传成功: agent_id={agent.id}')
                return True
            else:
                logger.error(f'Agent文件上传失败: agent_id={agent.id}, error={cmd.error}')
                deployment.log = (deployment.log or '') + f"错误: 文件上传失败: {cmd.error}\n"
                deployment.save()
                return False

        except Exception as e:
            logger.error(f'上传Agent文件失败: {e}', exc_info=True)
            deployment.log = (deployment.log or '') + f"错误: 上传文件失败: {str(e)}\n"
            deployment.save()
            return False

    @staticmethod
    def _execute_playbook_via_agent(
        agent: Agent,
        deployment: Deployment,
        extra_vars: dict
    ) -> Tuple[bool, str]:
        """
        通过Agent执行playbook

        Args:
            agent: Agent对象
            deployment: Deployment对象
            extra_vars: Ansible extra_vars

        Returns:
            Tuple[bool, str]: (是否成功, 输出)
        """
        try:
            from apps.agents.command_queue import CommandQueue
            from apps.deployments.deployment_tool import sync_deployment_tool_to_agent

            # 同步部署工具（确保有最新的install_agent.yml）
            if not sync_deployment_tool_to_agent(agent):
                logger.warning("部署工具同步失败，继续尝试执行playbook")
                deployment.log = (deployment.log or '') + "[警告] 部署工具同步失败，继续尝试执行playbook\n"
                deployment.save()

            # 获取Agent对象以获取证书内容
            agent.refresh_from_db()
            extra_vars['certificate_content'] = agent.certificate_content or ''
            extra_vars['private_key_content'] = agent.private_key_content or ''

            # 先执行前置检查
            deployment.log = (deployment.log or '') + "[信息] 检查Agent安装前置条件...\n"
            deployment.save()

            check_command = """
cd /opt/myx-deployment-tool && 
ansible-playbook -i inventory/localhost.ini playbooks/check_agent_prerequisites.yml
"""

            check_cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', check_command],
                timeout=120
            )

            # 等待检查完成
            max_wait = 120
            wait_time = 0
            while wait_time < max_wait:
                check_cmd.refresh_from_db()
                if check_cmd.status in ['success', 'failed']:
                    break
                time.sleep(2)
                wait_time += 2

            # 获取检查结果
            from apps.logs.utils import format_log_content
            check_output = ''
            if check_cmd.result:
                check_output = format_log_content(check_cmd.result, decode_base64=True)
            if check_cmd.error:
                error_output = format_log_content(check_cmd.error, decode_base64=True)
                if error_output:
                    check_output += '\n' + error_output

            if check_output:
                deployment.log = (deployment.log or '') + f"\n=== 前置检查输出 ===\n{check_output}\n"
            deployment.save()

            if check_cmd.status != 'success':
                error_msg = check_output if check_output else "前置检查失败，但未获取到错误信息"
                deployment.log = (deployment.log or '') + f"[失败] 前置检查失败\n错误信息: {error_msg}\n"
                deployment.save()
                logger.error(f"Agent前置检查失败: agent_id={agent.id}, 错误: {error_msg}")
                return False, f"前置检查失败: {error_msg}"

            deployment.log = (deployment.log or '') + "[成功] 前置检查通过\n"
            deployment.save()

            # 构建extra_vars JSON
            import json
            extra_vars_json = json.dumps(extra_vars, ensure_ascii=False)

            # 构建ansible-playbook命令（执行安装）
            playbook_command = f"""
cd /opt/myx-deployment-tool && 
ansible-playbook -i inventory/localhost.ini playbooks/install_agent.yml -e '{extra_vars_json}'
"""

            # 执行命令
            cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', playbook_command],
                timeout=600
            )

            deployment.log = (deployment.log or '') + f"[信息] 执行命令ID: {cmd.id}\n"
            deployment.save()

            # 等待命令完成
            max_wait = 600
            wait_time = 0
            while wait_time < max_wait:
                cmd.refresh_from_db()
                if cmd.status in ['success', 'failed']:
                    break
                time.sleep(2)
                wait_time += 2

            # 获取命令结果
            from apps.logs.utils import format_log_content
            output = ''
            if cmd.result:
                output = format_log_content(cmd.result, decode_base64=True)
            if cmd.error:
                error_output = format_log_content(cmd.error, decode_base64=True)
                if error_output:
                    output += '\n' + error_output

            success = cmd.status == 'success'
            return success, output

        except Exception as e:
            logger.error(f'通过Agent执行playbook失败: {e}', exc_info=True)
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
                'http_server.py',
                'ansible_executor.py',
                'requirements.txt',
            ]

            # 创建临时目录（playbook会删除/opt/myx-agent，所以先上传到临时目录）
            temp_dir = '/tmp/myx-agent-files'
            sftp = ssh.open_sftp()
            try:
                sftp.mkdir(temp_dir)
            except:
                pass  # 目录可能已存在

            # 上传文件到临时目录
            for filename in files_to_upload:
                local_path = agent_dir / filename
                if not local_path.exists():
                    logger.warning(f"文件不存在，跳过: {filename}")
                    continue

                remote_path = f'{temp_dir}/{filename}'
                sftp.put(str(local_path), remote_path)
                sftp.chmod(remote_path, 0o755 if filename.endswith('.py') else 0o644)
                logger.info(f"已上传到临时目录: {filename}")

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
