from django.urls import path, include
from . import views
from . import rpc_views
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'command-templates', views.CommandTemplateViewSet, basename='command-template')
router.register(r'', views.AgentViewSet, basename='agent')

urlpatterns = [
    path('register/', views.agent_register, name='agent-register'),
    path('rpc/', rpc_views.agent_rpc, name='agent-rpc'),  # JSON-RPC端点
    path('command/', views.agent_command, name='agent-command'),
    path('commands/<int:command_id>/result/', views.agent_command_result, name='agent-command-result'),
    path('', include(router.urls)),
]

