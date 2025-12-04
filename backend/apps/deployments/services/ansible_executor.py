"""
Ansible执行器

统一SSH和Agent两种方式执行Ansible playbook，遵循架构设计原则：
- SSH方式：本地执行Ansible（通过SSH连接到目标服务器）
- Agent方式：上传playbook到Agent，通过RPC调用ansible执行（Agent端使用ansible-runner）
"""
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
import paramiko
from io import StringIO

logger = logging.getLogger(__name__)


class AnsibleExecutor:
    """统一的Ansible执行器"""

    def __init__(self, server):
        """
        初始化Ansible执行器

        Args:
            server: Server对象
        """
        self.server = server

    def execute_playbook(
        self,
        playbook_name: str,
        extra_vars: Optional[Dict[str, Any]] = None,
        method: str = 'auto',
        timeout: int = 600
    ) -> tuple[bool, str]:
        """
        执行Ansible playbook

        Args:
            playbook_name: playbook文件名（如 'install_agent.yml'）
            extra_vars: Ansible extra_vars参数
            method: 执行方式 'ssh' | 'agent' | 'auto'（auto根据情况自动选择）
            timeout: 超时时间（秒）

        Returns:
            tuple: (success: bool, output: str)
        """
        extra_vars = extra_vars or {}

        # 自动选择执行方式
        if method == 'auto':
            method = self._choose_method()

        logger.info(f"执行Ansible playbook: {playbook_name}, 方式: {method}, 服务器: {self.server.name}")

        if method == 'ssh':
            return self._execute_via_ssh(playbook_name, extra_vars, timeout)
        elif method == 'agent':
            return self._execute_via_agent(playbook_name, extra_vars, timeout)
        else:
            return False, f"不支持的执行方式: {method}"

    def _choose_method(self) -> str:
        """
        自动选择执行方式

        Returns:
            str: 'ssh' 或 'agent'
        """
        # 检查是否有Agent且在线
        try:
            from apps.agents.models import Agent
            agent = Agent.objects.get(server=self.server)
            if agent.status == 'online' and agent.rpc_supported:
                return 'agent'
        except Agent.DoesNotExist:
            pass

        # 默认使用SSH
        return 'ssh'

    def _execute_via_ssh(
        self,
        playbook_name: str,
        extra_vars: Dict[str, Any],
        timeout: int
    ) -> tuple[bool, str]:
        """
        通过SSH执行Ansible playbook（本地执行）

        Args:
            playbook_name: playbook文件名
            extra_vars: extra_vars参数
            timeout: 超时时间

        Returns:
            tuple: (success: bool, output: str)
        """
        try:
            # 获取playbook文件路径
            from django.conf import settings
            playbook_path = Path(settings.BASE_DIR) / 'deployment-tool' / 'playbooks' / playbook_name

            if not playbook_path.exists():
                return False, f"Playbook文件不存在: {playbook_path}"

            # 构建ansible-playbook命令
            import json
            import subprocess

            # 创建临时inventory文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as inv_file:
                # 写入inventory内容
                inv_file.write(f"[target]\n")
                inv_file.write(f"{self.server.host} ")
                inv_file.write(f"ansible_port={self.server.port} ")
                inv_file.write(f"ansible_user={self.server.username} ")

                # 认证方式
                if self.server.private_key:
                    # 使用私钥：创建临时文件
                    with tempfile.NamedTemporaryFile(mode='w', suffix='_key', delete=False) as key_file:
                        key_file.write(self.server.private_key)
                        key_file_path = key_file.name
                    inv_file.write(f"ansible_ssh_private_key_file={key_file_path} ")
                else:
                    # 使用密码
                    inv_file.write(f"ansible_password={self.server.password} ")

                inv_file.write(f"ansible_become=yes ansible_become_method=sudo\n")
                inventory_path = inv_file.name

            # 构建命令
            cmd = [
                'ansible-playbook',
                str(playbook_path),
                '-i', inventory_path,
                '--extra-vars', json.dumps(extra_vars)
            ]

            logger.info(f"执行命令: {' '.join(cmd)}")

            # 执行命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # 清理临时文件
            import os
            os.unlink(inventory_path)
            if self.server.private_key and 'key_file_path' in locals():
                os.unlink(key_file_path)

            # 判断成功/失败
            success = result.returncode == 0
            output = result.stdout + result.stderr

            if success:
                logger.info(f"Ansible playbook执行成功: {playbook_name}")
            else:
                logger.error(f"Ansible playbook执行失败: {playbook_name}, 退出码: {result.returncode}")

            return success, output

        except subprocess.TimeoutExpired:
            return False, f"执行超时（{timeout}秒）"
        except Exception as e:
            logger.error(f"执行Ansible playbook失败: {e}", exc_info=True)
            return False, str(e)

    def _execute_via_agent(
        self,
        playbook_name: str,
        extra_vars: Dict[str, Any],
        timeout: int
    ) -> tuple[bool, str]:
        """
        通过Agent执行Ansible playbook（RPC调用）

        Args:
            playbook_name: playbook文件名
            extra_vars: extra_vars参数
            timeout: 超时时间

        Returns:
            tuple: (success: bool, output: str)
        """
        try:
            from apps.agents.models import Agent
            from apps.agents.rpc_client import get_agent_rpc_client
            from apps.deployments.deployment_tool import sync_deployment_tool_to_agent

            # 获取Agent
            agent = Agent.objects.get(server=self.server)

            if agent.status != 'online':
                return False, f"Agent不在线: {agent.status}"

            # 同步部署工具到Agent（如果需要）
            from apps.deployments.deployment_tool import check_deployment_tool_version
            if not check_deployment_tool_version(agent):
                logger.info(f"部署工具版本不一致，开始同步...")
                if not sync_deployment_tool_to_agent(agent):
                    logger.warning(f"部署工具同步失败，继续尝试执行playbook")

            # 通过RPC执行Ansible
            playbook_path = f"/opt/myx-deployment-tool/playbooks/{playbook_name}"

            logger.info(f"通过Agent RPC执行playbook: {playbook_path}")

            # 调用Agent的execute_ansible方法
            client = get_agent_rpc_client(agent)
            result = client.execute_ansible(
                playbook=playbook_path,
                extra_vars=extra_vars,
                timeout=timeout
            )

            # 解析结果
            success = result.get('success', False)
            output = result.get('stdout', '') + result.get('stderr', '')

            if success:
                logger.info(f"Agent执行playbook成功: {playbook_name}")
            else:
                logger.error(f"Agent执行playbook失败: {playbook_name}")

            return success, output

        except Agent.DoesNotExist:
            return False, "Agent不存在"
        except Exception as e:
            logger.error(f"通过Agent执行playbook失败: {e}", exc_info=True)
            return False, str(e)
