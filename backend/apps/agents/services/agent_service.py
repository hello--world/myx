"""
Agent服务

负责Agent的安装、升级、管理等业务逻辑
"""
import logging
import secrets
import random
from typing import Optional, Tuple
from django.utils import timezone
from apps.agents.models import Agent, AgentCommand
from apps.servers.models import Server
from apps.logs.utils import create_log_entry

logger = logging.getLogger(__name__)


class AgentService:
    """Agent业务服务"""

    @staticmethod
    def generate_rpc_port() -> Optional[int]:
        """
        生成随机RPC端口

        Returns:
            int: RPC端口，如果无法生成则返回None
        """
        excluded_ports = {22, 80, 443, 8000, 8443, 3306, 5432, 6379, 8080, 9000}

        for _ in range(100):
            port = random.randint(8000, 65535)
            if port in excluded_ports:
                continue

            # 检查端口是否已被使用
            try:
                if Agent.objects.filter(rpc_port=port).exists():
                    continue
            except Exception:
                pass

            return port

        return None

    @staticmethod
    def generate_rpc_path() -> str:
        """
        生成随机RPC路径（用于路径混淆，保障安全）

        Returns:
            str: 随机路径字符串
        """
        return secrets.token_urlsafe(16)

    @staticmethod
    def create_or_get_agent(server: Server) -> Agent:
        """
        创建或获取Agent记录（服务器端生成Token和RPC端口）

        Args:
            server: Server对象

        Returns:
            Agent: Agent对象
        """
        agent, created = Agent.objects.get_or_create(
            server=server,
            defaults={
                'token': secrets.token_urlsafe(32),
                'secret_key': secrets.token_urlsafe(32),
                'status': 'offline',
                'web_service_enabled': True,
                'web_service_port': 8443,
                'rpc_port': AgentService.generate_rpc_port(),
                'rpc_path': AgentService.generate_rpc_path(),
            }
        )

        # 如果Agent已存在但没有Token或RPC端口，生成它们
        needs_save = False

        if not agent.token:
            agent.token = secrets.token_urlsafe(32)
            needs_save = True

        if not agent.secret_key:
            agent.secret_key = secrets.token_urlsafe(32)
            needs_save = True

        if not agent.rpc_port:
            agent.rpc_port = AgentService.generate_rpc_port()
            needs_save = True

        if not agent.rpc_path:
            agent.rpc_path = AgentService.generate_rpc_path()
            needs_save = True

        if needs_save:
            agent.save()

        return agent

    @staticmethod
    def send_command(
        agent: Agent,
        command: str,
        args: list = None,
        timeout: int = 300,
        user=None
    ) -> AgentCommand:
        """
        发送命令到Agent

        Args:
            agent: Agent对象
            command: 命令
            args: 参数列表
            timeout: 超时时间
            user: 执行用户

        Returns:
            AgentCommand: 命令对象
        """
        from apps.agents.command_queue import CommandQueue

        args = args or []

        cmd = CommandQueue.add_command(agent, command, args, timeout)

        # 记录日志
        if user:
            create_log_entry(
                log_type='command',
                level='info',
                title=f'下发命令到Agent: {agent.server.name}',
                content=f'命令: {command} {", ".join(str(arg) for arg in args) if args else ""}\n超时: {timeout}秒',
                user=user,
                server=agent.server,
                related_id=cmd.id,
                related_type='command'
            )

        return cmd

    @staticmethod
    def stop_agent(agent: Agent, user=None) -> AgentCommand:
        """
        停止Agent服务

        Args:
            agent: Agent对象
            user: 执行用户

        Returns:
            AgentCommand: 命令对象
        """
        cmd = AgentService.send_command(
            agent=agent,
            command='systemctl',
            args=['stop', 'myx-agent'],
            timeout=30,
            user=user
        )

        if user:
            create_log_entry(
                log_type='agent',
                level='info',
                title=f'停止Agent服务: {agent.server.name}',
                content=f'停止Agent服务命令已下发，命令ID: {cmd.id}',
                user=user,
                server=agent.server,
                related_id=cmd.id,
                related_type='command'
            )

        return cmd

    @staticmethod
    def start_agent(agent: Agent, user=None) -> AgentCommand:
        """
        启动Agent服务

        Args:
            agent: Agent对象
            user: 执行用户

        Returns:
            AgentCommand: 命令对象
        """
        cmd = AgentService.send_command(
            agent=agent,
            command='systemctl',
            args=['start', 'myx-agent'],
            timeout=30,
            user=user
        )

        if user:
            create_log_entry(
                log_type='agent',
                level='info',
                title=f'启动Agent服务: {agent.server.name}',
                content=f'启动Agent服务命令已下发，命令ID: {cmd.id}',
                user=user,
                server=agent.server,
                related_id=cmd.id,
                related_type='command'
            )

        return cmd

    @staticmethod
    def check_agent_status(agent: Agent) -> Tuple[bool, str]:
        """
        检查Agent状态（服务器主动检查）

        Args:
            agent: Agent对象

        Returns:
            Tuple[bool, str]: (是否在线, 状态消息)
        """
        # 服务器主动检查 Agent 状态（通过 HTTP/HTTPS 健康检查端点）

        try:
            # 检查Agent是否有端口配置
            if not agent.rpc_port:
                agent.status = 'offline'
                agent.save()
                return False, 'Agent端口未配置'

            import requests
            import urllib3
            # 禁用SSL警告（因为使用自签名证书）
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            server = agent.server
            connect_host = server.agent_connect_host or server.host
            # 使用Agent的rpc_port（实际存储的是HTTP/HTTPS端口）
            connect_port = agent.rpc_port

            # 判断是否使用HTTPS（如果Agent有证书配置，使用HTTPS）
            use_https = bool(agent.certificate_path and agent.private_key_path)
            protocol = 'https' if use_https else 'http'

            # 构建Agent健康检查URL（/health端点不需要路径前缀）
            health_url = f"{protocol}://{connect_host}:{connect_port}/health"
            
            # 如果配置了agent域名，则验证SSL证书；如果只使用IP地址，则不验证
            verify_ssl = bool(server.agent_connect_host)
            
            response = requests.get(health_url, timeout=5, verify=verify_ssl)

            if response.status_code == 200:
                agent.status = 'online'
                agent.last_heartbeat = timezone.now()
                agent.save()
                return True, 'Agent在线'
            else:
                agent.status = 'offline'
                agent.save()
                return False, f'健康检查失败: {response.status_code}'

        except Exception as e:
            agent.status = 'offline'
            agent.save()
            return False, f'连接失败: {str(e)}'
