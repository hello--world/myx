"""
Agent工具函数
"""
import os
import random
import string
from .models import Agent
from .command_queue import CommandQueue


def execute_script_via_agent(agent: Agent, script_content: str, timeout: int = 300, script_name: str = 'script.sh'):
    """
    通过Agent执行脚本（写入临时文件后执行）
    
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
    
    # 构建命令：使用heredoc写入脚本文件，然后执行
    # 使用单引号包裹heredoc标记，避免脚本内容中的特殊字符被shell解析
    # 脚本内容中的变量和命令会被正常执行
    command = f'''bash -c 'cat > "{script_file}" << '\''SCRIPT_EOF'\''
{script_content}
SCRIPT_EOF
chmod +x "{script_file}"
bash "{script_file}"
EXIT_CODE=$?
rm -f "{script_file}"
exit $EXIT_CODE' '''
    
    return CommandQueue.add_command(
        agent=agent,
        command='bash',
        args=['-c', command],
        timeout=timeout
    )

