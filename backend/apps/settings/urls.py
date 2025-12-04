from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
# 注意：更具体的路由要放在通用路由之前，避免路由冲突
router.register(r'cloudflare/accounts', views.CloudflareAccountViewSet, basename='cloudflare-accounts')
router.register(r'cloudflare/zones', views.CloudflareZoneViewSet, basename='cloudflare-zones')
router.register(r'cloudflare/dns-records', views.CloudflareDNSRecordViewSet, basename='cloudflare-dns-records')
router.register(r'subdomain-words', views.SubdomainWordViewSet, basename='subdomain-words')
router.register(r'', views.AppSettingsViewSet, basename='settings')

urlpatterns = [
    path('', include(router.urls)),
]

