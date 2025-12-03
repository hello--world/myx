#!/usr/bin/env python3
"""
Agent端JSON-RPC客户端
用于Agent连接到服务器的JSON-RPC服务
"""
import json
import logging
import time
from typing import Dict, Any, Optional, List
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class ServerRPCClient:
    """服务器JSON-RPC客户端"""
    
    def __init__(self, api_url: str, agent_token: str):
        """
        Args:
            api_url: 服务器API地址（如 https://example.com/api/agents）
            agent_token: Agent Token
        """
        self.api_url = api_url.rstrip('/')
        self.agent_token = agent_token
        
        # 创建HTTP会话
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.timeout = 10
        
        self.session.headers.update({
            'X-Agent-Token': agent_token,
            'Content-Type': 'application/json'
        })
    
    def _call(self, method: str, params: Dict[str, Any] = None, request_id: int = None) -> Dict[str, Any]:
        """
        调用JSON-RPC方法
        
        Args:
            method: 方法名
            params: 参数
            request_id: 请求ID（可选）
            
        Returns:
            JSON-RPC响应
        """
        if params is None:
            params = {}
        
        if request_id is None:
            request_id = int(time.time() * 1000)
        
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': request_id
        }
        
        try:
            response = self.session.post(
                f"{self.api_url}/rpc/",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"JSON-RPC调用失败: {e}")
            return {
                'jsonrpc': '2.0',
                'error': {'code': -32000, 'message': str(e)},
                'id': request_id
            }
    
    def poll_commands(self) -> List[Dict[str, Any]]:
        """轮询获取命令"""
        result = self._call('poll_commands')
        if 'error' in result:
            logger.error(f"轮询命令失败: {result['error']}")
            return []
        return result.get('result', {}).get('commands', [])
    
    def report_result(
        self,
        command_id: int,
        success: bool,
        result: str = None,
        error: str = None
    ) -> bool:
        """上报命令执行结果"""
        params = {
            'command_id': command_id,
            'success': success
        }
        if result is not None:
            params['result'] = result
        if error is not None:
            params['error'] = error
        
        rpc_result = self._call('report_result', params)
        return 'error' not in rpc_result
    
    def heartbeat(self, status: str = 'online', version: str = '1.0.0', rpc_port: int = None) -> Dict[str, Any]:
        """发送心跳"""
        params = {
            'status': status,
            'version': version
        }
        if rpc_port:
            params['rpc_port'] = rpc_port
        
        result = self._call('heartbeat', params)
        if 'error' in result:
            logger.error(f"心跳失败: {result['error']}")
            return {}
        return result.get('result', {})

