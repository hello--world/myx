from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from .models import Deployment
from .serializers import DeploymentSerializer, QuickDeploySerializer
from .tasks import deploy_xray, deploy_caddy, quick_deploy_full
from apps.servers.models import Server
from datetime import datetime


class DeploymentViewSet(viewsets.ModelViewSet):
    """部署任务视图集"""
    queryset = Deployment.objects.all()
    serializer_class = DeploymentSerializer

    def get_queryset(self):
        return Deployment.objects.filter(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        """创建部署任务并开始执行"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deployment = serializer.save()
        deployment.status = 'pending'
        
        # 如果未指定连接方式和部署目标，使用服务器的默认值
        if not deployment.connection_method:
            deployment.connection_method = deployment.server.connection_method
        if not deployment.deployment_target:
            deployment.deployment_target = deployment.server.deployment_target
        
        deployment.save()

        # 异步执行部署任务（使用线程）
        try:
            if deployment.deployment_type == 'full':
                from .tasks import quick_deploy_full
                quick_deploy_full(deployment.id)
            elif deployment.deployment_type == 'xray':
                deploy_xray(deployment.id)
            elif deployment.deployment_type == 'caddy':
                deploy_caddy(deployment.id)
            elif deployment.deployment_type == 'both':
                deploy_xray(deployment.id)
                deploy_caddy(deployment.id)
        except Exception as e:
            deployment.status = 'failed'
            deployment.error_message = str(e)
            deployment.save()

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """获取部署日志"""
        deployment = self.get_object()
        return Response({
            'log': deployment.log,
            'error_message': deployment.error_message,
            'status': deployment.status
        })

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """重试失败的部署任务"""
        deployment = self.get_object()
        
        # 只能重试失败、超时或已取消的部署任务
        if deployment.status not in ['failed', 'timeout', 'cancelled']:
            return Response({
                'error': f'只能重试失败、超时或已取消的部署任务，当前状态: {deployment.get_status_display()}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 重置部署任务状态
        deployment.status = 'pending'
        deployment.error_message = None
        deployment.started_at = None
        deployment.completed_at = None
        deployment.log = (deployment.log or '') + f"\n[重试] 用户 {request.user.username} 于 {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} 重试此部署任务\n"
        deployment.save()
        
        # 异步执行部署任务（使用线程）
        try:
            if deployment.deployment_type == 'full':
                from .tasks import quick_deploy_full
                quick_deploy_full(deployment.id)
            elif deployment.deployment_type == 'xray':
                deploy_xray(deployment.id)
            elif deployment.deployment_type == 'caddy':
                deploy_caddy(deployment.id)
            elif deployment.deployment_type == 'both':
                deploy_xray(deployment.id)
                deploy_caddy(deployment.id)
            elif deployment.deployment_type == 'agent':
                # Agent部署任务需要特殊处理
                from .tasks import install_agent_via_ssh, wait_for_agent_startup
                from django.utils import timezone
                import threading
                
                def _retry_agent():
                    deployment.refresh_from_db()
                    deployment.status = 'running'
                    deployment.started_at = timezone.now()
                    deployment.save()
                    
                    try:
                        server = deployment.server
                        agent_installed = install_agent_via_ssh(server, deployment)
                        if not agent_installed:
                            deployment.status = 'failed'
                            deployment.error_message = 'Agent安装失败'
                            deployment.completed_at = timezone.now()
                            deployment.save()
                            return
                        
                        agent = wait_for_agent_startup(server, timeout=120, deployment=deployment)
                        if not agent:
                            deployment.status = 'failed'
                            deployment.error_message = 'Agent注册超时'
                            deployment.completed_at = timezone.now()
                            deployment.save()
                            return
                        
                        deployment.status = 'success'
                        deployment.completed_at = timezone.now()
                        deployment.save()
                    except Exception as e:
                        deployment.status = 'failed'
                        deployment.error_message = str(e)
                        deployment.completed_at = timezone.now()
                        deployment.save()
                
                thread = threading.Thread(target=_retry_agent)
                thread.daemon = True
                thread.start()
        except Exception as e:
            deployment.status = 'failed'
            deployment.error_message = str(e)
            deployment.save()
        
        return Response({
            'message': '部署任务已重新启动',
            'deployment_id': deployment.id
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止正在运行的部署任务"""
        deployment = self.get_object()
        
        # 只能停止运行中的部署任务
        if deployment.status != 'running':
            return Response({
                'error': f'只能停止运行中的部署任务，当前状态: {deployment.get_status_display()}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 标记为已取消
        deployment.status = 'cancelled'
        deployment.completed_at = timezone.now()
        
        # 计算运行时间
        if deployment.started_at:
            elapsed_time = timezone.now() - deployment.started_at
            hours = int(elapsed_time.total_seconds() // 3600)
            minutes = int((elapsed_time.total_seconds() % 3600) // 60)
            elapsed_str = f'{hours}小时{minutes}分钟' if hours > 0 else f'{minutes}分钟'
        else:
            elapsed_str = '未知'
        
        deployment.error_message = f'部署任务已被用户 {request.user.username} 手动停止（运行时间: {elapsed_str}）'
        deployment.log = (deployment.log or '') + f"\n[停止] 用户 {request.user.username} 于 {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} 手动停止此部署任务\n"
        deployment.log = (deployment.log or '') + f"[停止] 运行时间: {elapsed_str}\n"
        deployment.save()
        
        # 记录停止日志
        from apps.logs.utils import create_log_entry
        create_log_entry(
            log_type='deployment',
            level='warning',
            title=f'部署任务已停止: {deployment.name}',
            content=f'部署任务 {deployment.name} 已被用户手动停止（运行时间: {elapsed_str}）',
            user=request.user,
            server=deployment.server,
            related_id=deployment.id,
            related_type='deployment'
        )
        
        return Response({
            'message': '部署任务已停止',
            'deployment_id': deployment.id,
            'status': deployment.status
        }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def quick_deploy(request):
    """一键快速部署（可选择已有服务器或直接输入SSH信息，不保存密码）"""
    serializer = QuickDeploySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    data = serializer.validated_data
    server = None
    is_temporary = False
    
    if data.get('server_id'):
        # 使用已有服务器
        try:
            server = Server.objects.get(id=data['server_id'], created_by=request.user)
        except Server.DoesNotExist:
            return Response({'error': '服务器不存在'}, status=status.HTTP_404_NOT_FOUND)
        
        # 更新部署目标（如果指定）
        if data.get('deployment_target'):
            server.deployment_target = data['deployment_target']
            server.save()
    else:
        # 直接输入SSH信息（不保存密码，临时使用）
        is_temporary = True
        # 创建临时服务器对象（仅用于部署，不保存密码）
        server = Server(
            name=f"[临时] {data['name']}",
            host=data['host'],
            port=data.get('port', 22),
            username=data['username'],
            password=data.get('password', ''),  # 临时使用，部署完成后会清除
            private_key=data.get('private_key', ''),  # 临时使用，部署完成后会清除
            connection_method='ssh',
            deployment_target=data.get('deployment_target', 'host'),
            status='inactive',
            created_by=request.user
        )
        # 临时保存以便部署使用
        server.save()
    
    # 创建一键部署任务
    deployment = Deployment.objects.create(
        name=f"一键部署 - {server.name.replace('[临时] ', '')}",
        server=server,
        deployment_type='full',
        connection_method='ssh',  # 初始使用SSH连接
        deployment_target=data.get('deployment_target', 'host'),
        status='pending',
        created_by=request.user
    )
    
    # 如果临时服务器，在部署任务中标记，部署完成后清除密码
    if is_temporary:
        deployment.log = f"临时服务器，部署完成后将清除SSH密码\n"
        deployment.save()
    
    # 异步执行一键部署
    try:
        quick_deploy_full(deployment.id, is_temporary=is_temporary)
    except Exception as e:
        deployment.status = 'failed'
        deployment.error_message = str(e)
        deployment.save()
    
    return Response({
        'deployment_id': deployment.id,
        'server_id': server.id,
        'message': '一键部署任务已创建',
        'is_temporary': is_temporary
    }, status=status.HTTP_201_CREATED)
