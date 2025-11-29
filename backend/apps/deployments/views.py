from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
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
