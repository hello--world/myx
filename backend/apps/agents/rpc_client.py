"""
Agent JSON-RPC客户端
用于后端连接到Agent的JSON-RPC服务
"""
import json
import logging
import requests
from typing import Dict, Any, Optional
from urllib3.exceptions import InsecureRequestWarning
import urllib3

# 禁用SSL警告（因为使用自签名证书）
urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)


class AgentRPCClient:
    """Agent JSON-RPC客户端"""
    
    def __init__(self, agent_host: str, agent_port: int, agent_token: str, rpc_path: str = '', verify_ssl: bool = False):
        """
        Args:
            agent_host: Agent主机地址
            agent_port: Agent RPC端口
            agent_token: Agent Token
            rpc_path: RPC随机路径（用于路径混淆，保障安全）
            verify_ssl: 是否验证SSL证书（默认False，因为使用自签名证书）
        """
        self.agent_host = agent_host
        self.agent_port = agent_port
        self.agent_token = agent_token
        self.rpc_path = rpc_path
        self.verify_ssl = verify_ssl
        self.base_url = f"https://{agent_host}:{agent_port}"
        
        # 创建会话
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({
            'X-Agent-Token': agent_token,
            'Content-Type': 'application/json'
        })
    
    def _call(self, method: str, params: Dict[str, Any] = None, request_id: int = None, max_retries: int = 3) -> Dict[str, Any]:
        """
        调用JSON-RPC方法（带重试机制）
        
        Args:
            method: 方法名
            params: 参数
            request_id: 请求ID（可选）
            max_retries: 最大重试次数（默认3次）
            
        Returns:
            JSON-RPC响应
        """
        if params is None:
            params = {}
        
        if request_id is None:
            import time
            request_id = int(time.time() * 1000)
        
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': request_id
        }
        
        # 构建完整 URL，包含 rpc_path
        if self.rpc_path:
            rpc_url = f"{self.base_url}/{self.rpc_path}/rpc"
        else:
            rpc_url = f"{self.base_url}/rpc"  # 向后兼容
        
        # 重试机制：指数退避（1秒、2秒、4秒）
        last_exception = None
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    rpc_url,
                    json=payload,
                    timeout=30
                )
                response.raise_for_status()
                result = response.json()
                
                # 检查是否是认证错误（不重试）
                if 'error' in result:
                    error_code = result['error'].get('code', 0)
                    if error_code == -32001:  # Unauthorized
                        logger.error(f"JSON-RPC认证失败: {result['error']}")
                        return result
                
                return result
            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < max_retries - 1:
                    # 指数退避：1秒、2秒、4秒
                    delay = 2 ** attempt
                    logger.warning(f"JSON-RPC调用失败（尝试 {attempt + 1}/{max_retries}），{delay}秒后重试: {e}")
                    import time
                    time.sleep(delay)
                else:
                    logger.error(f"JSON-RPC调用失败（已重试{max_retries}次）: {e}")
        
        # 所有重试都失败
        return {
            'jsonrpc': '2.0',
            'error': {'code': -32000, 'message': f'Request failed after {max_retries} retries: {str(last_exception)}'},
            'id': request_id
        }
    
    def health_check(self) -> bool:
        """健康检查（通过JSON-RPC）"""
        try:
            # 先尝试HTTP健康检查端点（更快）
            try:
                response = self.session.get(
                    f"{self.base_url}/health",
                    timeout=3
                )
                if response.status_code == 200:
                    return response.json().get('status') == 'ok'
            except:
                pass
            
            # 回退到JSON-RPC调用
            result = self._call('health_check', {})
            if 'error' in result:
                return False
            return result.get('result', {}).get('status') == 'ok'
        except Exception as e:
            logger.debug(f"Agent健康检查失败: {e}")
            return False
    
    def check_support(self) -> bool:
        """
        检查Agent是否支持JSON-RPC
        
        Returns:
            True if agent supports JSON-RPC, False otherwise
        """
        try:
            # 先检查健康端点（不在 rpc_path 下，在根路径）
            try:
                response = self.session.get(
                    f"{self.base_url}/health",
                    timeout=5,
                    verify=self.verify_ssl
                )
                if response.status_code == 200:
                    logger.debug(f"Agent健康检查成功: {self.base_url}/health")
                    return True
            except Exception as e:
                # SSL错误通常表示服务还没完全启动，这是正常的
                error_str = str(e)
                if 'SSL' in error_str or 'EOF' in error_str:
                    logger.debug(f"Agent健康端点SSL错误（服务可能还在启动）: {e}")
                else:
                    logger.debug(f"Agent健康端点检查失败: {e}")
            
            # 尝试JSON-RPC调用（使用完整路径，包含 rpc_path）
            # 注意：对于刚启动的Agent，SSL错误是正常的，所以不重试
            result = self._call('health_check', {}, max_retries=1)  # 只重试1次，快速失败
            if 'error' not in result:
                logger.debug(f"Agent JSON-RPC健康检查成功")
                return True
            else:
                error_info = result.get('error', {})
                error_msg = error_info.get('message', 'Unknown error') if isinstance(error_info, dict) else str(error_info)
                logger.debug(f"Agent JSON-RPC健康检查失败: {error_msg}")
                return False
        except Exception as e:
            # SSL错误通常表示服务还没完全启动，这是正常的
            error_str = str(e)
            if 'SSL' in error_str or 'EOF' in error_str:
                logger.debug(f"Agent JSON-RPC检查SSL错误（服务可能还在启动）: {e}")
            else:
                logger.debug(f"检查Agent JSON-RPC支持失败: {e}")
            return False
    
    def heartbeat(self) -> bool:
        """发送心跳到Agent（通过JSON-RPC）"""
        try:
            result = self._call('heartbeat', {})
            if 'error' in result:
                return False
            return result.get('result', {}).get('status') == 'ok'
        except Exception as e:
            logger.debug(f"向Agent发送心跳失败: {e}")
            return False
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """获取Agent状态"""
        result = self._call('get_status')
        if 'error' in result:
            logger.error(f"获取Agent状态失败: {result['error']}")
            return None
        return result.get('result')
    
    def execute_command(
        self,
        command: str,
        args: list = None,
        timeout: int = 300,
        command_id: int = None
    ) -> Dict[str, Any]:
        """
        执行命令（同步执行，直接返回结果）
        
        Args:
            command: 命令
            args: 参数列表
            timeout: 超时时间（秒）
            command_id: 命令ID（可选）
            
        Returns:
            命令执行结果（包含success, stdout, stderr, return_code等）
        """
        if args is None:
            args = []
        
        params = {
            'command': command,
            'args': args,
            'timeout': timeout
        }
        if command_id:
            params['command_id'] = command_id
        
        result = self._call('execute_command', params)
        if 'error' in result:
            return {
                'success': False,
                'error': result['error'].get('message', 'Unknown error'),
                'status': 'failed'
            }
        return result.get('result', {})
    
    def execute_ansible(
        self,
        playbook: str,
        extra_vars: dict = None,
        timeout: int = 600
    ) -> Dict[str, Any]:
        """
        执行Ansible playbook
        
        Args:
            playbook: playbook文件名
            extra_vars: 额外的Ansible变量
            timeout: 超时时间（秒）
            
        Returns:
            执行结果
        """
        if extra_vars is None:
            extra_vars = {}
        
        params = {
            'playbook': playbook,
            'extra_vars': extra_vars,
            'timeout': timeout
        }
        
        result = self._call('execute_ansible', params)
        if 'error' in result:
            return {'error': result['error'], 'status': 'failed'}
        return result.get('result', {})
    
    def get_command_log(
        self,
        command_id: int,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        获取命令日志（服务器主动调用，用于实时日志流式传输）
        
        Args:
            command_id: 命令ID
            offset: 已读取的字节数（用于增量获取）
            
        Returns:
            日志数据（包含log_data, log_type, new_offset, is_final, result等）
        """
        params = {
            'command_id': command_id,
            'offset': offset
        }
        
        result = self._call('get_command_log', params)
        if 'error' in result:
            return {
                'error': result['error'].get('message', 'Unknown error'),
                'is_final': True
            }
        return result.get('result', {})


def get_agent_rpc_client(agent) -> Optional[AgentRPCClient]:
    """
    获取Agent RPC客户端
    
    Args:
        agent: Agent模型实例
        
    Returns:
        AgentRPCClient实例，如果Agent未启用RPC或端口未设置则返回None
    """
    if not agent.rpc_port:
        return None
    
    # 获取Agent连接地址
    server = agent.server
    agent_host = server.agent_connect_host or server.host
    
    # 获取RPC路径（用于路径混淆，保障安全）
    rpc_path = getattr(agent, 'rpc_path', '') or ''
    
    # 从Agent模型读取verify_ssl配置（默认False，因为使用自签名证书）
    verify_ssl = getattr(agent, 'verify_ssl', False)
    
    return AgentRPCClient(
        agent_host=agent_host,
        agent_port=agent.rpc_port,
        agent_token=str(agent.token),
        rpc_path=rpc_path,
        verify_ssl=verify_ssl
    )

