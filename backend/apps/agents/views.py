import secrets
from datetime import datetime, timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils import timezone
from .models import Agent
from .serializers import (
    AgentSerializer, AgentRegisterSerializer,
    AgentHeartbeatSerializer, AgentCommandSerializer
)
from apps.servers.models import Server


class AgentViewSet(viewsets.ReadOnlyModelViewSet):
    """Agent视图集"""
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer

    def get_queryset(self):
        # 只返回当前用户创建的服务器关联的 Agent
        return Agent.objects.filter(server__created_by=self.request.user)


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_register(request):
    """Agent注册接口"""
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

    # 检查是否已有Agent
    agent, created = Agent.objects.get_or_create(
        server=server,
        defaults={
            'secret_key': secrets.token_urlsafe(32),
            'status': 'online',
            'version': serializer.validated_data.get('version', ''),
            'last_heartbeat': timezone.now()
        }
    )

    if not created:
        # 更新现有Agent
        agent.status = 'online'
        agent.last_heartbeat = timezone.now()
        if serializer.validated_data.get('version'):
            agent.version = serializer.validated_data['version']
        agent.save()

    return Response({
        'token': str(agent.token),
        'secret_key': agent.secret_key,
        'server_id': server.id
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_heartbeat(request):
    """Agent心跳接口"""
    token = request.headers.get('X-Agent-Token')
    if not token:
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = Agent.objects.get(token=token)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = AgentHeartbeatSerializer(data=request.data)
    if serializer.is_valid():
        if serializer.validated_data.get('status'):
            agent.status = serializer.validated_data['status']
        if serializer.validated_data.get('version'):
            agent.version = serializer.validated_data['version']

    agent.last_heartbeat = timezone.now()
    agent.status = 'online'
    agent.save()

    return Response({'status': 'ok'})


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_command(request):
    """Agent命令执行接口"""
    token = request.headers.get('X-Agent-Token')
    if not token:
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = Agent.objects.get(token=token)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent不存在'}, status=status.HTTP_404_NOT_FOUND)

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


@api_view(['GET'])
@permission_classes([AllowAny])
def agent_poll_commands(request):
    """Agent轮询命令接口"""
    token = request.headers.get('X-Agent-Token')
    if not token:
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = Agent.objects.get(token=token)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent不存在'}, status=status.HTTP_404_NOT_FOUND)

    # 更新心跳
    agent.last_heartbeat = timezone.now()
    agent.status = 'online'
    agent.save()

    # 从命令队列获取待执行的命令
    from .command_queue import CommandQueue
    commands = CommandQueue.get_pending_commands(agent)
    
    return Response({
        'commands': commands,
        'status': 'ok'
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_command_result(request, command_id):
    """Agent命令执行结果接口"""
    token = request.headers.get('X-Agent-Token')
    if not token:
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = Agent.objects.get(token=token)
        from .command_queue import CommandQueue
        
        success = request.data.get('success', False)
        result = request.data.get('stdout', '')
        error = request.data.get('error') or request.data.get('stderr', '')
        
        CommandQueue.update_command_result(command_id, success, result, error)
        
        return Response({'status': 'ok'})
    except Agent.DoesNotExist:
        return Response({'error': 'Agent不存在'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

