from .models import Agent
from django.utils import timezone
from datetime import timedelta


def check_agent_status():
    """检查Agent状态（定期任务）"""
    # 检查超过60秒没有心跳的Agent，标记为离线
    offline_threshold = timezone.now() - timedelta(seconds=60)
    Agent.objects.filter(
        last_heartbeat__lt=offline_threshold,
        status='online'
    ).update(status='offline')

