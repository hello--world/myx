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
    AgentHeartbeatSerializer, AgentCommandSerializer,
    AgentCommandDetailSerializer
)
from apps.servers.models import Server


class AgentViewSet(viewsets.ReadOnlyModelViewSet):
    """Agent视图集"""
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer

    def get_queryset(self):
        # 只返回当前用户创建的服务器关联的 Agent
        return Agent.objects.filter(server__created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def send_command(self, request, pk=None):
        """下发命令到Agent"""
        agent = self.get_object()
        command = request.data.get('command')
        args = request.data.get('args', [])
        timeout = request.data.get('timeout', 300)

        if not command:
            return Response({'error': '命令不能为空'}, status=status.HTTP_400_BAD_REQUEST)

        from .command_queue import CommandQueue
        cmd = CommandQueue.add_command(agent, command, args, timeout)

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """重新部署Agent"""
        agent = self.get_object()
        server = agent.server

        # 检查服务器是否有SSH凭据
        if not server.password and not server.private_key:
            return Response({'error': '服务器缺少SSH凭据，无法重新部署'}, status=status.HTTP_400_BAD_REQUEST)

        # 创建部署任务
        from apps.deployments.models import Deployment
        deployment = Deployment.objects.create(
            server=server,
            deployment_type='agent',
            connection_method='ssh',
            deployment_target=server.deployment_target,
            created_by=request.user
        )

        # 异步执行部署
        from apps.deployments.tasks import install_agent_via_ssh
        import threading
        def _deploy():
            install_agent_via_ssh(server, deployment)

        thread = threading.Thread(target=_deploy)
        thread.daemon = True
        thread.start()

        return Response({
            'message': 'Agent重新部署已启动',
            'deployment_id': deployment.id
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def upgrade(self, request, pk=None):
        """升级Agent"""
        agent = self.get_object()
        server = agent.server

        # 通过Agent执行升级命令
        from .command_queue import CommandQueue
        from django.conf import settings
        import os

        github_repo = os.getenv('GITHUB_REPO', getattr(settings, 'GITHUB_REPO', 'hello--world/myx'))
        
        # 检测系统架构（通过Agent执行命令获取）
        # 这里简化处理，假设是linux-amd64，实际应该先检测
        upgrade_script = f"""#!/bin/bash
set -e

# 检测系统
OS_NAME=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ARCH="amd64"
elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    ARCH="arm64"
fi

BINARY_NAME="myx-agent-${{OS_NAME}}-${{ARCH}}"
GITHUB_URL="https://github.com/{github_repo}/releases/download/latest/${{BINARY_NAME}}"

echo "正在从 GitHub 下载最新 Agent..."
if curl -L -f -o /tmp/myx-agent "${{GITHUB_URL}}"; then
    echo "Agent 下载成功"
    chmod +x /tmp/myx-agent
    systemctl stop myx-agent || true
    mv /tmp/myx-agent /opt/myx-agent/myx-agent
    chmod +x /opt/myx-agent/myx-agent
    systemctl start myx-agent
    echo "Agent 升级完成"
else
    echo "Agent 下载失败"
    exit 1
fi
"""

        import base64
        script_b64 = base64.b64encode(upgrade_script.encode('utf-8')).decode('utf-8')
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=600
        )

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response({
            'message': 'Agent升级命令已下发',
            'command': serializer.data
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止Agent服务"""
        agent = self.get_object()

        from .command_queue import CommandQueue
        cmd = CommandQueue.add_command(
            agent=agent,
            command='systemctl',
            args=['stop', 'myx-agent'],
            timeout=30
        )

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response({
            'message': '停止Agent命令已下发',
            'command': serializer.data
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """启动Agent服务"""
        agent = self.get_object()

        from .command_queue import CommandQueue
        cmd = CommandQueue.add_command(
            agent=agent,
            command='systemctl',
            args=['start', 'myx-agent'],
            timeout=30
        )

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response({
            'message': '启动Agent命令已下发',
            'command': serializer.data
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def commands(self, request, pk=None):
        """获取Agent的命令历史"""
        agent = self.get_object()
        from .models import AgentCommand
        commands = AgentCommand.objects.filter(agent=agent).order_by('-created_at')[:50]

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(commands, many=True)
        return Response(serializer.data)


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

    # 返回配置信息（让 Agent 可以动态调整间隔）
    from django.conf import settings
    return Response({
        'status': 'ok',
        'config': {
            'heartbeat_min_interval': getattr(settings, 'AGENT_HEARTBEAT_MIN_INTERVAL', 30),
            'heartbeat_max_interval': getattr(settings, 'AGENT_HEARTBEAT_MAX_INTERVAL', 300),
            'poll_min_interval': getattr(settings, 'AGENT_POLL_MIN_INTERVAL', 5),
            'poll_max_interval': getattr(settings, 'AGENT_POLL_MAX_INTERVAL', 60),
        }
    })


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
    
    # 返回命令和配置信息
    from django.conf import settings
    return Response({
        'commands': commands,
        'status': 'ok',
        'config': {
            'heartbeat_min_interval': getattr(settings, 'AGENT_HEARTBEAT_MIN_INTERVAL', 30),
            'heartbeat_max_interval': getattr(settings, 'AGENT_HEARTBEAT_MAX_INTERVAL', 300),
            'poll_min_interval': getattr(settings, 'AGENT_POLL_MIN_INTERVAL', 5),
            'poll_max_interval': getattr(settings, 'AGENT_POLL_MAX_INTERVAL', 60),
        }
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

