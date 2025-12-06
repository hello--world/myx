"""
Agent相关异步任务
"""
from django.utils import timezone
from datetime import timedelta
from .models import Agent
import requests
import logging
import urllib3

# 禁用SSL警告（因为使用自签名证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


def check_agent_status():
    """检查Agent状态（服务器主动检查）"""
    # 获取所有 Agent（服务器主动检查）
    agents = Agent.objects.filter(status__in=['online', 'offline'])
    
    for agent in agents:
        try:
            # 检查Agent是否有端口配置
            if not agent.rpc_port:
                agent.status = 'offline'
                agent.save()
                continue
            
            # 获取Agent连接地址
            server = agent.server
            connect_host = server.agent_connect_host or server.host
            # 使用Agent的rpc_port（实际存储的是HTTP/HTTPS端口）
            connect_port = agent.rpc_port
            
            # 判断是否使用HTTPS（如果Agent有证书配置，使用HTTPS）
            use_https = bool(agent.certificate_path and agent.private_key_path)
            protocol = 'https' if use_https else 'http'
            
            # 构建Agent健康检查URL（/health端点不需要路径前缀）
            health_url = f"{protocol}://{connect_host}:{connect_port}/health"
            
            # 如果配置了agent域名，则验证SSL证书；如果只使用IP地址，则不验证
            verify_ssl = bool(server.agent_connect_host)
            
            # 发送HTTP/HTTPS请求检查Agent是否在线
            response = requests.get(health_url, timeout=5, verify=verify_ssl)
            
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
