from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Proxy
from .serializers import ProxySerializer
from .tasks import auto_deploy_proxy


class ProxyViewSet(viewsets.ModelViewSet):
    """代理节点视图集"""
    queryset = Proxy.objects.all()
    serializer_class = ProxySerializer

    def get_queryset(self):
        return Proxy.objects.filter(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        """创建代理并自动部署"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # 创建代理
        proxy = serializer.save()
        
        # 异步启动自动部署
        auto_deploy_proxy(proxy.id)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """重新部署代理"""
        proxy = self.get_object()
        
        # 重置部署状态
        proxy.deployment_status = 'pending'
        proxy.deployment_log = ''
        proxy.deployed_at = None
        proxy.save()
        
        # 异步启动重新部署
        auto_deploy_proxy(proxy.id)
        
        return Response({
            'message': '重新部署已启动',
            'deployment_status': proxy.deployment_status
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def stop_deployment(self, request, pk=None):
        """停止部署"""
        proxy = self.get_object()
        
        if proxy.deployment_status != 'running':
            return Response({
                'message': '当前没有正在运行的部署任务',
                'deployment_status': proxy.deployment_status
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 停止部署：将状态改为失败，并记录停止信息
        proxy.deployment_status = 'failed'
        proxy.deployment_log = (proxy.deployment_log or '') + f"\n⚠️ 部署已被用户手动停止\n"
        proxy.save()
        
        return Response({
            'message': '部署已停止',
            'deployment_status': proxy.deployment_status
        }, status=status.HTTP_200_OK)

