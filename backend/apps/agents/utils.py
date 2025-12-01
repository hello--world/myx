"""
Agent工具函数
"""
import base64
import os
import random
import string
from .models import Agent
from .command_queue import CommandQueue


def execute_script_via_agent(agent: Agent, script_content: str, timeout: int = 300, script_name: str = 'script.sh'):
    """
    通过Agent执行脚本（使用base64编码，写入临时文件后执行）
    
    Args:
        agent: Agent对象
        script_content: 脚本内容（字符串）
        timeout: 超时时间（秒）
        script_name: 临时脚本文件名（不含路径）
        
    Returns:
        AgentCommand对象
    """
    # 生成随机文件名，避免冲突
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    script_file = f'/tmp/myx_{script_name.replace(".sh", "")}_{random_suffix}.sh'
    
    # 将脚本内容进行base64编码，避免特殊字符问题
    script_base64 = base64.b64encode(script_content.encode('utf-8')).decode('ascii')
    
    # 构建命令：解码base64脚本内容，写入临时文件，然后执行
    command = f'''bash -c 'echo "{script_base64}" | base64 -d > "{script_file}" && chmod +x "{script_file}" && bash "{script_file}"; EXIT_CODE=$?; rm -f "{script_file}"; exit $EXIT_CODE' '''
    
    return CommandQueue.add_command(
        agent=agent,
        command='bash',
        args=['-c', command],
        timeout=timeout
    )

