from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Server
from .serializers import ServerSerializer, ServerTestSerializer
from .utils import test_ssh_connection


class ServerViewSet(viewsets.ModelViewSet):
    """服务器视图集"""
    queryset = Server.objects.all()
    serializer_class = ServerSerializer

    def get_queryset(self):
        return Server.objects.filter(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试服务器SSH连接"""
        server = self.get_object()
        try:
            result = test_ssh_connection(
                host=server.host,
                port=server.port,
                username=server.username,
                password=server.password,
                private_key=server.private_key
            )
            if result['success']:
                server.status = 'active'
                server.last_check = timezone.now()
                server.save()
                return Response({'message': '连接成功', 'status': 'active'})
            else:
                server.status = 'error'
                server.last_check = timezone.now()
                server.save()
                return Response(
                    {'message': f"连接失败: {result.get('error', '未知错误')}", 'status': 'error'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            server.status = 'error'
            server.last_check = timezone.now()
            server.save()
            return Response(
                {'message': f"连接测试异常: {str(e)}", 'status': 'error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def test(self, request):
        """测试SSH连接（不保存）"""
        serializer = ServerTestSerializer(data=request.data)
        if serializer.is_valid():
            try:
                result = test_ssh_connection(**serializer.validated_data)
                if result['success']:
                    return Response({'message': '连接成功'})
                else:
                    return Response(
                        {'message': f"连接失败: {result.get('error', '未知错误')}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response(
                    {'message': f"连接测试异常: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

