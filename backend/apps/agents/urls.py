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
    path('', include(router.urls)),
]

