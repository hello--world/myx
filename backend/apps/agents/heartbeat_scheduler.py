"""
Agent心跳调度器
服务器主动向Agent发送心跳，检查Agent状态
"""
import logging
import time
from django.utils import timezone
from django.db.models import Q
from .models import Agent
from .rpc_client import get_agent_rpc_client

logger = logging.getLogger(__name__)


def check_agent_heartbeat(agent: Agent) -> bool:
    """
    检查Agent心跳（通过JSON-RPC发送心跳并获取状态）
    
    Args:
        agent: Agent实例
        
    Returns:
        True if agent is online, False otherwise
    """
    if not agent.rpc_port:
        # 如果没有RPC端口，标记为离线
        if agent.status == 'online':
            agent.status = 'offline'
            agent.save(update_fields=['status'])
        return False
    
    # 如果还未检查过支持状态，先检查
    if agent.rpc_last_check is None:
        from .rpc_support import check_agent_rpc_support
        check_agent_rpc_support(agent)
    
    # 如果确认不支持JSON-RPC，跳过
    if not agent.rpc_supported:
        return False
    
    try:
        rpc_client = get_agent_rpc_client(agent)
        if not rpc_client:
            return False
        
        # 发送心跳到Agent
        if rpc_client.heartbeat():
            # 获取Agent状态
            status = rpc_client.get_status()
            if status:
                # 更新Agent状态
                agent.status = 'online'
                agent.last_heartbeat = timezone.now()
                agent.rpc_last_success = timezone.now()
                if status.get('version'):
                    agent.version = status.get('version')
                agent.save(update_fields=['status', 'last_heartbeat', 'rpc_last_success', 'version'])
                return True
        
        # 如果心跳失败，标记为离线
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
    """检查所有Agent的心跳（随机顺序）"""
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

