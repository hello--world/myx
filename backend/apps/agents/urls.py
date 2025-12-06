from django.urls import path
from . import views
from . import rpc_views

urlpatterns = [
    path('register/', views.agent_register, name='agent-register'),
    path('rpc/', rpc_views.agent_rpc, name='agent-rpc'),  # JSON-RPC端点
    path('command/', views.agent_command, name='agent-command'),
    path('commands/<int:command_id>/result/', views.agent_command_result, name='agent-command-result'),
]

