import secrets
import logging
from datetime import datetime, timedelta
from pathlib import Path
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from .models import Agent
from .serializers import (
    AgentRegisterSerializer,
    AgentCommandSerializer,
)
from apps.servers.models import Server
from apps.logs.utils import create_log_entry

logger = logging.getLogger(__name__)


def get_agent_by_token(token):
    """
    通过token查找Agent，自动处理UUID格式转换（带连字符/不带连字符）
    """
    import uuid
    # 先尝试直接查询
    try:
        return Agent.objects.get(token=token)
    except Agent.DoesNotExist:
        # 如果直接查询失败，尝试格式转换
        try:
            # 如果token是带连字符的UUID格式，转换为不带连字符的格式
            if '-' in token:
                uuid_obj = uuid.UUID(token)
                token_hex = uuid_obj.hex
                return Agent.objects.get(token=token_hex)
            else:
                # 如果token是不带连字符的格式，尝试转换为带连字符的格式
                uuid_obj = uuid.UUID(token)
                token_with_dash = str(uuid_obj)
                return Agent.objects.get(token=token_with_dash)
        except (ValueError, Agent.DoesNotExist):
            raise Agent.DoesNotExist(f"Agent with token '{token}' does not exist")


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_register(request):
    """Agent注册接口"""
    logger.info(f'[agent_register] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}')
    serializer = AgentRegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    server_token = serializer.validated_data['server_token']
    
    try:
        # 通过server的id查找服务器
        # server_token可以是UUID字符串或整数ID
        import uuid
        try:
            # 尝试作为UUID解析
            server_id = uuid.UUID(str(server_token))
            server = Server.objects.get(id=server_id)
        except (ValueError, Server.DoesNotExist):
            # 如果不是UUID，尝试作为整数ID
            try:
                server = Server.objects.get(id=int(server_token))
            except (ValueError, Server.DoesNotExist):
                return Response({'error': '服务器不存在'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'查找服务器失败: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

    # 检查 Agent 是否已存在（用于判断是否是新建）
    try:
        existing_agent = Agent.objects.get(server=server)
        created = False
    except Agent.DoesNotExist:
        created = True
    
    # 使用 AgentService 创建或获取 Agent
    from .services import AgentService
    agent = AgentService.create_or_get_agent(server)
    
    # 更新 Agent 状态和版本信息
    agent.status = 'online'
    agent.last_heartbeat = timezone.now()
    if serializer.validated_data.get('version'):
        agent.version = serializer.validated_data['version']
    agent.save()
    
    if not created:
        # 记录Agent重新注册日志
        create_log_entry(
            log_type='agent',
            level='info',
            title=f'Agent重新注册: {server.name}',
            content=f'Agent已重新注册，Token: {agent.token}',
            user=server.created_by,
            server=server,
            related_id=agent.id,
            related_type='agent'
        )
    else:
        # 记录Agent首次注册日志
        create_log_entry(
            log_type='agent',
            level='success',
            title=f'Agent注册成功: {server.name}',
            content=f'Agent首次注册成功，Token: {agent.token}，版本: {agent.version or "未知"}',
            user=server.created_by,
            server=server,
            related_id=agent.id,
            related_type='agent'
        )

    # 确保secret_key存在
    if not agent.secret_key:
        agent.secret_key = secrets.token_urlsafe(32)
        agent.save(update_fields=['secret_key'])
    
    return Response({
        'token': str(agent.token),
        'secret_key': agent.secret_key,  # 返回加密密钥
        'server_id': server.id,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_command(request):
    """Agent命令执行接口"""
    logger.info(f'[agent_command] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}')
    token = request.headers.get('X-Agent-Token')
    token_display = token[:10] + "..." if token and len(token) > 10 else (token or "None")
    logger.info(f'[agent_command] Token: {token_display}')
    
    if not token:
        logger.warning('[agent_command] ✗ 缺少Agent Token - 返回401 Unauthorized')
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
        logger.info(f'[agent_command] ✓ Agent找到: ID={agent.id}, Server={agent.server.name if agent.server else "None"}')
    except Agent.DoesNotExist:
        logger.error(f'[agent_command] ✗ Agent不存在 - Token: {token_display} - 返回404（这是视图函数返回的404，不是路由404！URL匹配成功）')
        return Response({'error': 'Agent不存在', 'detail': f'Token: {token_display}', 'note': '这是视图函数返回的404，URL匹配成功'}, status=status.HTTP_404_NOT_FOUND)

    serializer = AgentCommandSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # 这里返回命令，实际执行由Agent完成
    # Agent会轮询或通过WebSocket获取命令
    return Response({
        'command': serializer.validated_data['command'],
        'args': serializer.validated_data.get('args', []),
        'timeout': serializer.validated_data.get('timeout', 300)
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_command_result(request, command_id):
    """Agent命令执行结果接口"""
    logger.info(f'[agent_command_result] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}, command_id={command_id}')
    token = request.headers.get('X-Agent-Token')
    token_display = token[:10] + "..." if token and len(token) > 10 else (token or "None")
    logger.info(f'[agent_command_result] Token: {token_display}')
    
    if not token:
        logger.warning('[agent_command_result] ✗ 缺少Agent Token - 返回401 Unauthorized')
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
        logger.info(f'[agent_command_result] ✓ Agent找到: ID={agent.id}, Server={agent.server.name if agent.server else "None"}')
    except Agent.DoesNotExist:
        logger.error(f'[agent_command_result] ✗ Agent不存在 - Token: {token_display} - 返回404（这是视图函数返回的404，不是路由404！URL匹配成功）')
        return Response({'error': 'Agent不存在', 'detail': f'Token: {token_display}', 'note': '这是视图函数返回的404，URL匹配成功'}, status=status.HTTP_404_NOT_FOUND)
    from .command_queue import CommandQueue
    
    success = request.data.get('success', False)
    result = request.data.get('stdout', '')
    error = request.data.get('error') or request.data.get('stderr', '')
    append = request.data.get('append', False)  # 默认为最终结果，不追加
    
    try:
        from .command_queue import CommandQueue
        from .models import AgentCommand
        cmd = AgentCommand.objects.get(id=command_id, agent=agent)
        CommandQueue.update_command_result(command_id, success, result, error, append=append)
        
        # 记录命令执行结果日志
        log_level = 'success' if success else 'error'
        log_title = f'命令执行{"成功" if success else "失败"}: {agent.server.name}'
        log_content = f'命令: {cmd.command} {", ".join(str(arg) for arg in cmd.args) if cmd.args else ""}\n'
        if success:
            # 不截断结果，完整显示（会自动解码base64）
            log_content += f'\n执行结果:\n{result}'
        else:
            # 不截断错误，完整显示（会自动解码base64）
            log_content += f'\n错误信息:\n{error}'
        
        create_log_entry(
            log_type='command',
            level=log_level,
            title=log_title,
            content=log_content,
            user=agent.server.created_by,
            server=agent.server,
            related_id=cmd.id,
            related_type='command',
            decode_base64=True  # 自动解码base64内容
        )
        
        return Response({'status': 'ok'})
    except Exception as e:
        logger.error(f'[agent_command_result] ✗ 错误: {str(e)}')
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


