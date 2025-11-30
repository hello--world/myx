from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import AppSettings
from .serializers import AppSettingsSerializer


class AppSettingsViewSet(viewsets.ModelViewSet):
    """应用设置视图集"""
    queryset = AppSettings.objects.all()
    serializer_class = AppSettingsSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        """获取或创建设置实例（单例）"""
        return AppSettings.get_settings()

    def list(self, request, *args, **kwargs):
        """获取设置"""
        settings = AppSettings.get_settings()
        serializer = self.get_serializer(settings)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """获取设置详情"""
        return self.list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """更新设置（单例，所以用create来更新）"""
        settings = AppSettings.get_settings()
        serializer = self.get_serializer(settings, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """更新设置"""
        settings = self.get_object()
        serializer = self.get_serializer(settings, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        """部分更新设置"""
        return self.update(request, *args, **kwargs)

