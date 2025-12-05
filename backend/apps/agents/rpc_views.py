"""
Agent JSON-RPC视图
提供服务器端的JSON-RPC方法，供Agent调用
"""
import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from .models import Agent
from .command_queue import CommandQueue

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_rpc(request):
    """Agent JSON-RPC端点"""
    try:
        data = request.data
        
        # 验证JSON-RPC格式
        if data.get('jsonrpc') != '2.0':
            return Response({
                'jsonrpc': '2.0',
                'error': {'code': -32600, 'message': 'Invalid Request'},
                'id': data.get('id')
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证Token
        token = request.headers.get('X-Agent-Token')
        if not token:
            return Response({
                'jsonrpc': '2.0',
                'error': {'code': -32001, 'message': 'Unauthorized'},
                'id': data.get('id')
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            agent = Agent.objects.get(token=token)
        except Agent.DoesNotExist:
            return Response({
                'jsonrpc': '2.0',
                'error': {'code': -32001, 'message': 'Unauthorized'},
                'id': data.get('id')
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        method = data.get('method')
        params = data.get('params', {})
        request_id = data.get('id')
        
        if not method:
            return Response({
                'jsonrpc': '2.0',
                'error': {'code': -32600, 'message': 'Invalid Request'},
                'id': request_id
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 路由到对应的方法
        try:
            if method == 'poll_commands':
                result = _poll_commands(agent)
            elif method == 'report_result':
                result = _report_result(agent, params)
            elif method == 'heartbeat':
                result = _heartbeat(agent, params)
            else:
                return Response({
                    'jsonrpc': '2.0',
                    'error': {'code': -32601, 'message': f'Method not found: {method}'},
                    'id': request_id
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'jsonrpc': '2.0',
                'result': result,
                'id': request_id
            })
        except Exception as e:
            logger.error(f"执行JSON-RPC方法 {method} 失败: {e}", exc_info=True)
            return Response({
                'jsonrpc': '2.0',
                'error': {'code': -32603, 'message': f'Internal error: {str(e)}'},
                'id': request_id
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    except Exception as e:
        logger.error(f"处理JSON-RPC请求失败: {e}", exc_info=True)
        return Response({
            'jsonrpc': '2.0',
            'error': {'code': -32700, 'message': 'Parse error'},
            'id': None
        }, status=status.HTTP_400_BAD_REQUEST)


def _poll_commands(agent: Agent) -> dict:
    """Agent轮询获取命令"""
    commands = CommandQueue.get_pending_commands(agent)
    return {
        'commands': commands
    }


def _report_result(agent: Agent, params: dict) -> dict:
    """Agent上报命令执行结果"""
    command_id = params.get('command_id')
    success = params.get('success')
    result = params.get('result')
    error = params.get('error')
    
    if not command_id:
        raise ValueError("command_id is required")
    
    CommandQueue.update_command_result(
        command_id=command_id,
        success=success,
        result=result,
        error=error,
        append=False
    )
    
    return {'status': 'ok'}


def _heartbeat(agent: Agent, params: dict) -> dict:
    """Agent心跳"""
    agent.status = 'online'
    agent.last_heartbeat = timezone.now()
    
    # 更新RPC端口（如果提供）
    if 'rpc_port' in params:
        rpc_port = params['rpc_port']
        if rpc_port and not agent.rpc_port:
            # 只有在端口未设置时才设置（不可更改已存在的端口）
            agent.rpc_port = rpc_port
            logger.info(f"Agent {agent.id} 设置RPC端口: {rpc_port}")
    
    agent.save()
    
    return {
        'status': 'ok'
    }

