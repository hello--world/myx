from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
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
        
        # 获取所有可用的节点
        all_proxies = Proxy.objects.filter(created_by=subscription.created_by, status='active', enable=True)
        
        # 如果订阅指定了节点ID列表，则只包含选中的节点
        if subscription.proxy_ids and len(subscription.proxy_ids) > 0:
            proxies = all_proxies.filter(id__in=subscription.proxy_ids)
        else:
            # 如果没有指定节点，默认包含所有节点（向后兼容）
            proxies = all_proxies

        if subscription.format == 'base64':
            content = generate_v2ray_subscription(proxies, request)
            content_type = 'text/plain; charset=utf-8'
        else:  # clash
            content = generate_clash_subscription(proxies, request)
            content_type = 'application/json; charset=utf-8'

        # 使用 HttpResponse 直接返回内容，避免被 DRF 渲染成 HTML
        response = HttpResponse(content, content_type=content_type)
        # 添加 CORS 头，允许跨域访问
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

