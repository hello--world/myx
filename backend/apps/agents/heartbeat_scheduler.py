"""
Agent心跳调度器
服务器主动向Agent发送心跳，检查Agent状态（使用HTTP健康检查）
"""
import logging
import time
import requests
import urllib3
from django.utils import timezone
from django.db.models import Q
from .models import Agent

# 禁用SSL警告（因为使用自签名证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


def check_agent_heartbeat(agent: Agent) -> bool:
    """
    检查Agent心跳（通过HTTP健康检查端点）
    
    Args:
        agent: Agent实例
        
    Returns:
        True if agent is online, False otherwise
    """
    if not agent.rpc_port:
        # 如果没有端口，标记为离线
        if agent.status == 'online':
            agent.status = 'offline'
            agent.save(update_fields=['status'])
        return False
    
    try:
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
            # 更新Agent状态
            agent.status = 'online'
            agent.last_heartbeat = timezone.now()
            agent.save(update_fields=['status', 'last_heartbeat'])
            return True
        
        # 如果健康检查失败，标记为离线
        if agent.status == 'online':
            agent.status = 'offline'
            agent.save(update_fields=['status'])
        return False
    except Exception as e:
        logger.debug(f"检查Agent {agent.id} 心跳失败: {e}")
        if agent.status == 'online':
            agent.status = 'offline'
            agent.save(update_fields=['status'])
        return False


def check_all_agents_heartbeat():
    """检查所有Agent的心跳（随机顺序，使用HTTP健康检查）"""
    import random
    agents = list(Agent.objects.filter(rpc_port__isnull=False))
    # 随机打乱顺序，避免所有Agent同时被检查
    random.shuffle(agents)
    
    online_count = 0
    offline_count = 0
    
    for agent in agents:
        if check_agent_heartbeat(agent):
            online_count += 1
        else:
            offline_count += 1
    
    logger.debug(f"Agent心跳检查完成: 在线={online_count}, 离线={offline_count}")
    return online_count, offline_count

