"""
日志收集模块
从Agent端收集部署工具的执行日志
"""
import logging
from apps.agents.models import Agent
from apps.agents.utils import execute_script_via_agent
from .deployment_tool import AGENT_DEPLOYMENT_TOOL_DIR

logger = logging.getLogger(__name__)


def collect_deployment_logs(agent: Agent, task_id: str = None, log_type: str = 'ansible') -> str:
    """
    从Agent端收集部署工具的执行日志
    
    Args:
        agent: Agent对象
        task_id: 任务ID（可选，用于过滤特定任务的日志）
        log_type: 日志类型（'ansible' 或其他）
        
    Returns:
        str: 日志内容
    """
    try:
        # 构建日志文件路径
        if task_id:
            log_file = f"{AGENT_DEPLOYMENT_TOOL_DIR}/logs/{log_type}_{task_id}.log"
        else:
            # 获取最新的日志文件
            log_file = f"{AGENT_DEPLOYMENT_TOOL_DIR}/logs/{log_type}.log"
        
        # 读取日志文件的脚本
        read_script = f"""#!/bin/bash
if [ -f "{log_file}" ]; then
    cat "{log_file}"
    exit 0
else
    echo "日志文件不存在: {log_file}"
    exit 1
fi
"""
        
        # 通过Agent执行读取脚本
        cmd = execute_script_via_agent(agent, read_script, timeout=30, script_name='read_logs.sh')
        
        # 等待命令执行完成
        import time
        max_wait = 30
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status == 'success' and cmd.result:
            return cmd.result
        else:
            logger.warning(f"读取日志失败: {cmd.error}")
            return ""
            
    except Exception as e:
        logger.error(f"收集部署日志失败: {e}", exc_info=True)
        return ""


def list_deployment_logs(agent: Agent) -> list:
    """
    列出Agent端的所有部署日志文件
    
    Returns:
        list: 日志文件列表
    """
    try:
        list_script = f"""#!/bin/bash
if [ -d "{AGENT_DEPLOYMENT_TOOL_DIR}/logs" ]; then
    ls -lt {AGENT_DEPLOYMENT_TOOL_DIR}/logs/*.log 2>/dev/null | head -20 | awk '{{print $9}}'
    exit 0
else
    echo "日志目录不存在"
    exit 1
fi
"""
        
        cmd = execute_script_via_agent(agent, list_script, timeout=30, script_name='list_logs.sh')
        
        import time
        max_wait = 30
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status == 'success' and cmd.result:
            # 解析日志文件列表
            log_files = [line.strip() for line in cmd.result.strip().split('\n') if line.strip()]
            return log_files
        else:
            return []
            
    except Exception as e:
        logger.error(f"列出部署日志失败: {e}", exc_info=True)
        return []

