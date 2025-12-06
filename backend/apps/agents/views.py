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
from .models import Agent, CommandTemplate
from .serializers import (
    AgentSerializer, AgentRegisterSerializer,
    AgentCommandSerializer,
    AgentCommandDetailSerializer, CommandTemplateSerializer
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

        # 调用Service
        from .services import AgentService
        cmd = AgentService.send_command(
            agent=agent,
            command=command,
            args=args,
            timeout=timeout,
            user=request.user
        )

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def update_certificate(self, request, pk=None):
        """更新Agent的SSL证书"""
        agent = self.get_object()

        regenerate = request.data.get('regenerate', False)
        verify_ssl = request.data.get('verify_ssl', agent.verify_ssl)

        # 调用Service
        from .services import CertificateService

        if regenerate:
            # 重新生成证书
            success, message = CertificateService.regenerate_agent_certificate(
                agent=agent,
                verify_ssl=verify_ssl,
                user=request.user
            )

            if success:
                serializer = self.get_serializer(agent)
                return Response({
                    'success': True,
                    'message': message,
                    'agent': serializer.data
                })
            else:
                return Response({
                    'error': message
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            # 只更新verify_ssl选项
            success, message = CertificateService.update_verify_ssl(
                agent=agent,
                verify_ssl=verify_ssl,
                user=request.user
            )

            if success:
                serializer = self.get_serializer(agent)
                return Response({
                    'success': True,
                    'message': message,
                    'agent': serializer.data
                })
            else:
                return Response({
                    'error': message
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def upgrade(self, request, pk=None):
        """升级Agent"""
        agent = self.get_object()
        server = agent.server

        # 检查并停止正在运行的相同类型的部署任务
        from apps.deployments.models import Deployment
        
        running_deployments = Deployment.objects.filter(
            server=server,
            deployment_type='agent',
            status='running'
        )
        
        if running_deployments.exists():
            for deployment in running_deployments:
                deployment.status = 'cancelled'
                deployment.error_message = f'被新的升级任务取消（{timezone.now().strftime("%Y-%m-%d %H:%M:%S")}）'
                deployment.completed_at = timezone.now()
                deployment.log = (deployment.log or '') + f"\n[取消] 升级任务被新的升级请求取消\n"
                deployment.save()
                logger.info(f'已取消正在运行的升级任务: deployment_id={deployment.id}, server={server.name}')

        # 创建部署任务
        deployment = Deployment.objects.create(
            name=f"升级Agent - {server.name}",
            server=server,
            deployment_type='agent',
            connection_method='agent' if (server.connection_method == 'agent' and agent.status == 'online') else 'ssh',
            deployment_target=server.deployment_target or 'host',
            status='running',
            started_at=timezone.now(),
            created_by=request.user
        )

        # 使用统一的安装/升级方法
        from apps.deployments.services import DeploymentService

        # 自动选择执行方式
        method = 'auto'
        if server.connection_method == 'agent' and agent.status == 'online':
            method = 'agent'
        elif not server.password and not server.private_key:
            deployment.status = 'failed'
            deployment.error_message = '服务器缺少SSH凭据'
            deployment.completed_at = timezone.now()
            deployment.save()
            return Response({
                'error': '服务器缺少SSH凭据，无法升级Agent'
            }, status=status.HTTP_400_BAD_REQUEST)
        else:
            method = 'ssh'

        # 异步执行安装/升级
        import threading

        def _upgrade():
            try:
                success, message = DeploymentService.install_or_upgrade_agent(
                    server=server,
                    deployment=deployment,
                    method=method,
                    user=request.user
                )

                if success:
                    deployment.status = 'success'
                else:
                    deployment.status = 'failed'
                    deployment.error_message = message

                deployment.completed_at = timezone.now()
                deployment.save()

            except Exception as e:
                deployment.status = 'failed'
                deployment.error_message = str(e)
                deployment.completed_at = timezone.now()
                deployment.save()

        thread = threading.Thread(target=_upgrade)
        thread.daemon = True
        thread.start()

        method_text = 'Agent' if method == 'agent' else 'SSH'
        return Response({
            'message': f'Agent升级已启动（通过{method_text}）',
            'deployment_id': deployment.id
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止Agent服务"""
        agent = self.get_object()

        # 调用Service
        from .services import AgentService
        cmd = AgentService.stop_agent(agent=agent, user=request.user)

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

        # 调用Service
        from .services import AgentService
        cmd = AgentService.start_agent(agent=agent, user=request.user)

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

    @action(detail=True, methods=['post'])
    def check_status(self, request, pk=None):
        """手动检查Agent状态（拉取模式）"""
        agent = self.get_object()

        # 调用Service
        from .services import AgentService
        success, message = AgentService.check_agent_status(agent)

        if success:
            serializer = self.get_serializer(agent)
            return Response(serializer.data)
        else:
            return Response({
                'error': message
            }, status=status.HTTP_400_BAD_REQUEST)


class CommandTemplateViewSet(viewsets.ModelViewSet):
    """命令模板视图集"""
    queryset = CommandTemplate.objects.all()
    serializer_class = CommandTemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CommandTemplate.objects.filter(created_by=self.request.user)


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

    # 检查是否已有Agent
    # 生成随机RPC端口（如果不存在）
    import random
    def generate_rpc_port():
        excluded_ports = {22, 80, 443, 8000, 8443, 3306, 5432, 6379, 8080, 9000}
        for _ in range(100):
            port = random.randint(8000, 65535)
            if port in excluded_ports:
                continue
            # 检查端口是否已被使用
            try:
                existing = Agent.objects.filter(rpc_port=port).exists()
                if existing:
                    continue
            except:
                pass
            return port
        return None
    
    agent, created = Agent.objects.get_or_create(
        server=server,
        defaults={
            'token': secrets.token_urlsafe(32),  # 生成token
            'secret_key': secrets.token_urlsafe(32),  # 生成加密密钥
            'status': 'online',
            'version': serializer.validated_data.get('version', ''),
            'last_heartbeat': timezone.now(),
            'web_service_enabled': True,  # 默认启用Web服务
            'web_service_port': 8443,  # 默认端口
            'rpc_port': generate_rpc_port()  # 生成随机RPC端口
        }
    )
    
    # 如果Agent已存在但没有token或secret_key，生成它们
    if not agent.token:
        import uuid
        agent.token = uuid.uuid4().hex
    if not agent.secret_key:
        agent.secret_key = secrets.token_urlsafe(32)
    if not agent.token or not agent.secret_key:
        agent.save()

    if not created:
        # 更新现有Agent
        agent.status = 'online'
        agent.last_heartbeat = timezone.now()
        if serializer.validated_data.get('version'):
            agent.version = serializer.validated_data['version']
        # 如果RPC端口未设置，生成一个（但不会更改已存在的端口）
        if not agent.rpc_port:
            agent.rpc_port = generate_rpc_port()
        # 保持现有心跳模式，不覆盖
        agent.save()
        
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


