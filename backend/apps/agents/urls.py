from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.agent_register, name='agent-register'),
    path('command/', views.agent_command, name='agent-command'),
    path('commands/<int:command_id>/result/', views.agent_command_result, name='agent-command-result'),
]

