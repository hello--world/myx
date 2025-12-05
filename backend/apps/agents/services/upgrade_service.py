"""
Agent升级服务

负责Agent的升级操作（自升级机制）
遵循架构设计原则：
- 使用systemd-run在独立进程中执行升级
- 使用install_agent.yml playbook统一安装/升级逻辑（自动检测升级模式）
- 失败自动回滚
"""
import logging
import time
import base64
from pathlib import Path
from typing import Tuple
from django.utils import timezone
from apps.agents.models import Agent
from apps.logs.utils import create_log_entry

logger = logging.getLogger(__name__)


class AgentUpgradeService:
    """Agent升级服务"""

    @staticmethod
    def upload_agent_files(agent: Agent) -> Tuple[bool, str]:
        """
        上传新的Agent文件到临时目录

        Args:
            agent: Agent对象

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            # 获取Agent文件路径
            from django.conf import settings
            agent_dir = Path(settings.BASE_DIR) / 'deployment-tool' / 'agent'

            if not agent_dir.exists():
                return False, f"Agent目录不存在: {agent_dir}"

            # 需要上传的文件
            files_to_upload = [
                'main.py',
                'rpc_server.py',
                'ansible_executor.py',
                'requirements.txt',
                'pyproject.toml',
            ]

            # 创建上传脚本
            upload_script = """#!/bin/bash
set -e

# 创建临时目录
mkdir -p /tmp/myx-agent-new

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
echo "{content_b64}" | base64 -d > /tmp/myx-agent-new/{filename}
"""

            upload_script += """
# 设置权限
chmod -R 755 /tmp/myx-agent-new
chmod +x /tmp/myx-agent-new/*.py

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
                return True, '文件上传成功'
            else:
                logger.error(f'Agent文件上传失败: agent_id={agent.id}, error={cmd.error}')
                return False, f'上传失败: {cmd.error}'

        except Exception as e:
            logger.error(f'上传Agent文件失败: {e}', exc_info=True)
            return False, f'上传失败: {str(e)}'

    @staticmethod
    def upgrade_via_agent(agent: Agent, deployment=None, user=None) -> Tuple[bool, str]:
        """
        通过Agent自升级（使用install_agent.yml playbook，统一使用全新安装方式）

        Args:
            agent: Agent对象
            deployment: 部署任务对象（可选）
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            from apps.agents.command_queue import CommandQueue

            # 1. 上传新的Agent文件到临时目录
            logger.info(f"开始上传Agent文件: agent_id={agent.id}")

            if deployment:
                deployment.log = (deployment.log or '') + "[信息] 上传新Agent文件到临时目录...\n"
                deployment.save()

            success, msg = AgentUpgradeService.upload_agent_files(agent)
            if not success:
                error_msg = f"文件上传失败: {msg}"
                logger.error(error_msg)
                if deployment:
                    deployment.log = (deployment.log or '') + f"[错误] {error_msg}\n"
                    deployment.save()
                return False, error_msg

            if deployment:
                deployment.log = (deployment.log or '') + "[成功] Agent文件上传完成\n"
                deployment.save()

            # 2. 同步部署工具（确保有最新的install_agent.yml）
            logger.info(f"同步部署工具: agent_id={agent.id}")

            if deployment:
                deployment.log = (deployment.log or '') + "[信息] 同步部署工具...\n"
                deployment.save()

            from apps.deployments.deployment_tool import sync_deployment_tool_to_agent
            if not sync_deployment_tool_to_agent(agent):
                logger.warning("部署工具同步失败，继续尝试升级")
                if deployment:
                    deployment.log = (deployment.log or '') + "[警告] 部署工具同步失败，继续尝试升级\n"
                    deployment.save()

            # 3. 构建升级命令（使用systemd-run在独立进程中执行）
            # 使用deployment.id作为日志文件标识（如果有deployment），否则使用timestamp
            if deployment:
                service_name = f'myx-agent-upgrade-{deployment.id}'
                log_file = f'/tmp/agent_upgrade_{deployment.id}.log'
            else:
                service_name = f'myx-agent-upgrade-{int(time.time())}'
                log_file = f'/tmp/agent_upgrade_{int(time.time())}.log'

            # 使用ansible-playbook执行升级（统一使用全新安装方式）
            upgrade_command = f"""
systemd-run \\
  --unit={service_name} \\
  --service-type=oneshot \\
  --no-block \\
  --property=StandardOutput=file:{log_file} \\
  --property=StandardError=file:{log_file} \\
  bash -c 'cd /opt/myx-deployment-tool && ansible-playbook -i inventory/localhost.ini playbooks/install_agent.yml'
"""

            logger.info(f"执行升级命令: {upgrade_command}")

            if deployment:
                deployment.log = (deployment.log or '') + f"[信息] 开始执行升级（全新安装方式）...\n"
                deployment.log += f"[信息] 日志文件: {log_file}\n"
                deployment.save()

            # 执行升级命令
            cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', upgrade_command],
                timeout=600
            )

            logger.info(f'升级命令已添加到队列: command_id={cmd.id}, agent_id={agent.id}')

            if deployment:
                deployment.log = (deployment.log or '') + f"[信息] 升级命令ID: {cmd.id}\n"
                deployment.save()

            # 记录日志
            if user:
                create_log_entry(
                    log_type='agent',
                    level='info',
                    title=f'开始升级Agent: {agent.server.name}',
                    content=f'Agent升级已启动，命令ID: {cmd.id}',
                    user=user,
                    server=agent.server,
                    related_id=cmd.id,
                    related_type='command'
                )

            return True, f'升级已启动，命令ID: {cmd.id}'

        except Exception as e:
            logger.error(f'Agent升级失败: {e}', exc_info=True)
            return False, f'升级失败: {str(e)}'

    @staticmethod
    def upgrade_via_ssh(server, deployment=None, user=None) -> Tuple[bool, str]:
        """
        通过SSH升级Agent（Agent离线时使用，统一使用全新安装方式）

        Args:
            server: Server对象
            deployment: 部署任务对象（可选）
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            # 通过SSH重新安装Agent（统一使用全新安装方式）
            from apps.deployments.tasks import install_agent_via_ssh

            if deployment:
                deployment.log = (deployment.log or '') + "[信息] 通过SSH重新安装Agent（全新安装方式）...\n"
                deployment.save()

            success = install_agent_via_ssh(server, deployment)

            if success:
                # 等待Agent启动
                from apps.deployments.tasks import wait_for_agent_startup
                agent = wait_for_agent_startup(server, timeout=60, deployment=deployment)

                if agent and agent.rpc_supported:
                    logger.info(f"Agent通过SSH升级成功: server={server.name}")
                    if deployment:
                        deployment.log = (deployment.log or '') + "[成功] Agent升级成功\n"
                        deployment.save()
                    return True, 'Agent升级成功'
                else:
                    error_msg = 'Agent启动超时或RPC不支持'
                    logger.error(f"Agent升级失败: {error_msg}")
                    if deployment:
                        deployment.log = (deployment.log or '') + f"[错误] {error_msg}\n"
                        deployment.save()
                    return False, error_msg
            else:
                error_msg = 'Agent安装失败'
                logger.error(f"Agent升级失败: {error_msg}")
                if deployment:
                    deployment.log = (deployment.log or '') + f"[错误] {error_msg}\n"
                    deployment.save()
                return False, error_msg

        except Exception as e:
            logger.error(f'通过SSH升级Agent失败: {e}', exc_info=True)
            return False, f'升级失败: {str(e)}'
