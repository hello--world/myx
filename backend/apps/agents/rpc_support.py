"""
Agent JSON-RPC支持检查
检查Agent是否支持JSON-RPC协议，并记录支持状态
"""
import logging
from django.utils import timezone
from .models import Agent
from .rpc_client import get_agent_rpc_client

logger = logging.getLogger(__name__)


def check_agent_rpc_support(agent: Agent) -> bool:
    """
    检查Agent是否支持JSON-RPC
    
    Args:
        agent: Agent实例
        
    Returns:
        True if agent supports JSON-RPC, False otherwise
    """
    if not agent.rpc_port:
        # 没有RPC端口，不支持
        agent.rpc_supported = False
        agent.rpc_last_check = timezone.now()
        agent.save(update_fields=['rpc_supported', 'rpc_last_check'])
        return False
    
    try:
        rpc_client = get_agent_rpc_client(agent)
        if not rpc_client:
            agent.rpc_supported = False
            agent.rpc_last_check = timezone.now()
            agent.save(update_fields=['rpc_supported', 'rpc_last_check'])
            logger.debug(f"Agent {agent.id} RPC客户端创建失败")
            return False
        
        # 检查是否支持JSON-RPC
        is_supported = rpc_client.check_support()
        
        # 如果支持，获取Agent状态（包含版本号）
        if is_supported:
            try:
                status = rpc_client.get_status()
                if status and 'result' in status and 'version' in status['result']:
                    agent.version = status['result']['version']
                    logger.info(f"Agent {agent.id} 版本号已更新: {agent.version}")
            except Exception as e:
                logger.debug(f"获取Agent {agent.id} 版本号失败: {e}")
        
        # 更新支持状态
        agent.rpc_supported = is_supported
        agent.rpc_last_check = timezone.now()
        if is_supported:
            agent.rpc_last_success = timezone.now()
        agent.save(update_fields=['rpc_supported', 'rpc_last_check', 'rpc_last_success', 'version'])
        
        if is_supported:
            logger.info(f"Agent {agent.id} 支持JSON-RPC (端口: {agent.rpc_port}, 路径: {agent.rpc_path})")
        else:
            logger.debug(f"Agent {agent.id} 不支持JSON-RPC (端口: {agent.rpc_port}, 路径: {agent.rpc_path})")
        
        return is_supported
    except Exception as e:
        logger.debug(f"检查Agent {agent.id} JSON-RPC支持失败: {e}", exc_info=True)
        agent.rpc_supported = False
        agent.rpc_last_check = timezone.now()
        agent.save(update_fields=['rpc_supported', 'rpc_last_check'])
        return False


def check_all_agents_rpc_support():
    """检查所有Agent的JSON-RPC支持状态"""
    agents = Agent.objects.filter(rpc_port__isnull=False)
    supported_count = 0
    unsupported_count = 0
    
    for agent in agents:
        if check_agent_rpc_support(agent):
            supported_count += 1
        else:
            unsupported_count += 1
    
    logger.info(f"Agent JSON-RPC支持检查完成: 支持={supported_count}, 不支持={unsupported_count}")
    return supported_count, unsupported_count

