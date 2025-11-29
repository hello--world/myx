from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Subscription
from .serializers import SubscriptionSerializer
from apps.proxies.models import Proxy

# 使用相对路径导入utils
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
from utils.subscription import generate_v2ray_subscription, generate_clash_subscription


class SubscriptionViewSet(viewsets.ModelViewSet):
    """订阅视图集"""
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer

    def get_queryset(self):
        return Subscription.objects.filter(created_by=self.request.user)

    def retrieve(self, request, pk=None):
        """获取订阅内容（通过token）"""
        subscription = get_object_or_404(Subscription, token=pk, enabled=True)
        proxies = Proxy.objects.filter(created_by=subscription.created_by, status='active')

        if subscription.format == 'v2ray':
            content = generate_v2ray_subscription(proxies, request)
            content_type = 'text/plain; charset=utf-8'
        else:  # clash
            content = generate_clash_subscription(proxies, request)
            content_type = 'application/json; charset=utf-8'

        return Response(content, content_type=content_type)

