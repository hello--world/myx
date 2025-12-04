"""
重构后的Agent视图（示例）

将业务逻辑从View迁移到Service层，View只负责：
1. 接收HTTP请求
2. 参数验证
3. 调用Service层
4. 返回HTTP响应
"""
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

from .models import Agent
from .serializers import AgentSerializer, AgentCommandDetailSerializer
from .services import AgentService, CertificateService
from .services.upgrade_service import AgentUpgradeService

logger = logging.getLogger(__name__)


class AgentViewSetRefactored(viewsets.ReadOnlyModelViewSet):
    """重构后的Agent视图集"""
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer

    def get_queryset(self):
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
        cmd = AgentService.send_command(
            agent=agent,
            command=command,
            args=args,
            timeout=timeout,
            user=request.user
        )

        serializer = AgentCommandDetailSerializer(cmd)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def update_certificate(self, request, pk=None):
        """更新Agent的SSL证书"""
        agent = self.get_object()

        regenerate = request.data.get('regenerate', False)
        verify_ssl = request.data.get('verify_ssl', agent.verify_ssl)

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
    def redeploy(self, request, pk=None):
        """重新部署Agent"""
        agent = self.get_object()
        server = agent.server

        # 创建部署任务
        from apps.deployments.models import Deployment

        deployment = Deployment.objects.create(
            name=f"重新部署Agent - {server.name}",
            server=server,
            deployment_type='agent',
            connection_method='agent' if (server.connection_method == 'agent' and agent.status == 'online') else 'ssh',
            deployment_target=server.deployment_target or 'host',
            status='running',
            started_at=timezone.now(),
            created_by=request.user
        )

        # 根据Agent状态选择升级方式
        if server.connection_method == 'agent' and agent.status == 'online':
            # Agent在线：通过Agent自升级
            success, message = AgentUpgradeService.upgrade_via_agent(
                agent=agent,
                deployment=deployment,
                user=request.user
            )

            if success:
                return Response({
                    'message': 'Agent重新部署已启动，请查看部署任务',
                    'deployment_id': deployment.id
                }, status=status.HTTP_202_ACCEPTED)
            else:
                deployment.status = 'failed'
                deployment.error_message = message
                deployment.completed_at = timezone.now()
                deployment.save()

                return Response({
                    'error': message
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        else:
            # Agent离线：通过SSH升级
            if not server.password and not server.private_key:
                deployment.status = 'failed'
                deployment.error_message = '服务器缺少SSH凭据'
                deployment.completed_at = timezone.now()
                deployment.save()

                return Response({
                    'error': '服务器缺少SSH凭据，无法重新部署'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 异步执行SSH升级
            import threading

            def _upgrade():
                try:
                    success, message = AgentUpgradeService.upgrade_via_ssh(
                        server=server,
                        deployment=deployment,
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

            return Response({
                'message': 'Agent重新部署已启动（通过SSH）',
                'deployment_id': deployment.id
            }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止Agent服务"""
        agent = self.get_object()

        cmd = AgentService.stop_agent(agent=agent, user=request.user)

        serializer = AgentCommandDetailSerializer(cmd)
        return Response({
            'message': '停止Agent命令已下发',
            'command': serializer.data
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """启动Agent服务"""
        agent = self.get_object()

        cmd = AgentService.start_agent(agent=agent, user=request.user)

        serializer = AgentCommandDetailSerializer(cmd)
        return Response({
            'message': '启动Agent命令已下发',
            'command': serializer.data
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def check_status(self, request, pk=None):
        """手动检查Agent状态（拉取模式）"""
        agent = self.get_object()

        success, message = AgentService.check_agent_status(agent)

        if success:
            serializer = self.get_serializer(agent)
            return Response(serializer.data)
        else:
            return Response({
                'error': message
            }, status=status.HTTP_400_BAD_REQUEST)
