"""
Agent相关异步任务
"""
from django.utils import timezone
from datetime import timedelta
from .models import Agent
import requests
import logging

logger = logging.getLogger(__name__)


def check_agent_status():
    """检查Agent状态（服务器主动检查）"""
    # 获取所有 Agent（服务器主动检查）
    agents = Agent.objects.filter(status__in=['online', 'offline'])
    
    for agent in agents:
        try:
            # 获取Agent连接地址
            server = agent.server
            connect_host = server.agent_connect_host or server.host
            connect_port = server.agent_connect_port or 8000
            
            # 构建Agent健康检查URL
            # 假设Agent提供一个健康检查端点
            health_url = f"http://{connect_host}:{connect_port}/health"
            
            # 发送HTTP请求检查Agent是否在线
            response = requests.get(health_url, timeout=5)
            
            if response.status_code == 200:
                agent.status = 'online'
                agent.last_heartbeat = timezone.now()
            else:
                agent.status = 'offline'
        except Exception as e:
            logger.error(f"检查Agent {agent.id} 状态失败: {str(e)}")
            agent.status = 'offline'
        
        agent.save()


def mark_offline_agents():
    """标记长时间未心跳的Agent为离线"""
    # 如果超过5分钟没有心跳，标记为离线
    threshold = timezone.now() - timedelta(minutes=5)
    Agent.objects.filter(
        status='online',
        last_heartbeat__lt=threshold
    ).update(status='offline')
