from rest_framework import viewsets, status
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

