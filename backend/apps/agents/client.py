"""
Agent Web服务客户端
用于后端主动连接到Agent Web服务
"""
import logging
import requests
from typing import Dict, Any, Optional
from urllib3.exceptions import InsecureRequestWarning
import urllib3

# 禁用SSL警告（因为使用自签名证书）
urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)


class AgentWebClient:
    """Agent Web服务客户端"""
    
    def __init__(self, agent_host: str, agent_port: int, agent_token: str, verify_ssl: bool = False):
        """
        Args:
            agent_host: Agent主机地址
            agent_port: Agent Web服务端口
            agent_token: Agent Token
            verify_ssl: 是否验证SSL证书（默认False，因为使用自签名证书）
        """
        self.agent_host = agent_host
        self.agent_port = agent_port
        self.agent_token = agent_token
        self.verify_ssl = verify_ssl
        self.base_url = f"https://{agent_host}:{agent_port}"
        
        # 创建会话
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({
            'X-Agent-Token': agent_token,
            'Content-Type': 'application/json'
        })
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            response = self.session.get(
                f"{self.base_url}/health",
                timeout=5
            )
            response.raise_for_status()
            return response.json().get('status') == 'ok'
        except requests.exceptions.SSLError as e:
            # SSL错误可能是证书问题或服务未启动
            logger.debug(f"Agent Web服务SSL错误（可能服务未启动或证书问题）: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            # 连接错误，服务可能未启动
            logger.debug(f"Agent Web服务连接错误（可能服务未启动）: {e}")
            return False
        except Exception as e:
            logger.debug(f"Agent健康检查失败: {e}")
            return False
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """获取Agent状态"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/status",
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取Agent状态失败: {e}")
            return None
    
    def execute_command(self, command: str, args: list = None, timeout: int = 300, command_id: int = None) -> Dict[str, Any]:
        """
        执行命令
        
        Args:
            command: 命令
            args: 参数列表
            timeout: 超时时间（秒）
            command_id: 命令ID（可选）
            
        Returns:
            命令执行结果
        """
        if args is None:
            args = []
        
        try:
            data = {
                'command': command,
                'args': args,
                'timeout': timeout
            }
            if command_id:
                data['command_id'] = command_id
            
            response = self.session.post(
                f"{self.base_url}/api/execute",
                json=data,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"执行命令失败: {e}")
            return {'error': str(e), 'status': 'failed'}
        except Exception as e:
            logger.error(f"执行命令异常: {e}", exc_info=True)
            return {'error': str(e), 'status': 'failed'}


def get_agent_client(agent) -> Optional[AgentWebClient]:
    """
    获取Agent客户端
    
    Args:
        agent: Agent模型实例
        
    Returns:
        AgentWebClient实例，如果Agent未启用Web服务则返回None
    """
    if not agent.web_service_enabled:
        return None
    
    # 获取Agent连接地址
    server = agent.server
    agent_host = server.agent_connect_host or server.host
    agent_port = agent.web_service_port or 8443
    
    return AgentWebClient(
        agent_host=agent_host,
        agent_port=agent_port,
        agent_token=str(agent.token),
        verify_ssl=False  # 默认不验证，因为使用自签名证书
    )

