from django.urls import path, include
from . import views
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'command-templates', views.CommandTemplateViewSet, basename='command-template')
router.register(r'', views.AgentViewSet, basename='agent')

urlpatterns = [
    path('register/', views.agent_register, name='agent-register'),
    path('heartbeat/', views.agent_heartbeat, name='agent-heartbeat'),
    path('command/', views.agent_command, name='agent-command'),
    path('poll/', views.agent_poll_commands, name='agent-poll'),
    path('commands/<int:command_id>/result/', views.agent_command_result, name='agent-command-result'),
    path('commands/<int:command_id>/progress/', views.agent_command_progress, name='agent-command-progress'),
    path('deployments/<int:deployment_id>/progress/', views.agent_report_progress, name='agent-report-progress'),
    path('files/<str:filename>/', views.agent_file_download, name='agent-file-download'),
    path('', include(router.urls)),
]

