"""
Agent工具函数
"""
import base64
import os
import random
import string
import json
from .models import Agent
from .command_queue import CommandQueue

# Agent端部署工具目录
AGENT_DEPLOYMENT_TOOL_DIR = '/opt/myx-deployment-tool'


def execute_script_via_agent(agent: Agent, script_content: str, timeout: int = 300, script_name: str = 'script.sh'):
    """
    通过Agent执行脚本（使用base64编码，写入临时文件后执行）
    自动检测脚本类型（Python或Shell）并选择合适的解释器
    
    Args:
        agent: Agent对象
        script_content: 脚本内容（字符串）
        timeout: 超时时间（秒）
        script_name: 临时脚本文件名（不含路径）
        
    Returns:
        AgentCommand对象
    """
    # 检测脚本类型：检查shebang
    is_python = script_content.strip().startswith('#!/usr/bin/env python') or \
                script_content.strip().startswith('#!/usr/bin/python') or \
                script_name.endswith('.py')
    
    # 生成随机文件名，避免冲突
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    if is_python:
        # Python脚本使用.py扩展名
        base_name = script_name.replace(".sh", "").replace(".py", "")
        script_file = f'/tmp/myx_{base_name}_{random_suffix}.py'
        interpreter = 'python3'
    else:
        # Shell脚本使用.sh扩展名
        base_name = script_name.replace(".sh", "").replace(".py", "")
        script_file = f'/tmp/myx_{base_name}_{random_suffix}.sh'
        interpreter = 'bash'
    
    # 将脚本内容进行base64编码，避免特殊字符问题
    script_base64 = base64.b64encode(script_content.encode('utf-8')).decode('ascii')
    
    # 构建命令：解码base64脚本内容，写入临时文件，然后执行
    command = f'''bash -c 'echo "{script_base64}" | base64 -d > "{script_file}" && chmod +x "{script_file}" && {interpreter} "{script_file}"; EXIT_CODE=$?; rm -f "{script_file}"; exit $EXIT_CODE' '''
    
    return CommandQueue.add_command(
        agent=agent,
        command='bash',
        args=['-c', command],
        timeout=timeout
    )


def execute_ansible_playbook_via_agent(
    agent: Agent,
    playbook_name: str,
    extra_vars: dict = None,
    timeout: int = 600,
    ensure_ansible: bool = True
):
    """
    通过Agent执行Ansible playbook
    
    Args:
        agent: Agent对象
        playbook_name: playbook文件名（如 'deploy_xray.yml'）
        extra_vars: 额外的Ansible变量（字典格式）
        timeout: 超时时间（秒）
        ensure_ansible: 是否确保Ansible已安装（默认True）
        
    Returns:
        AgentCommand对象
    """
    playbook_path = f'{AGENT_DEPLOYMENT_TOOL_DIR}/playbooks/{playbook_name}'
    inventory_path = f'{AGENT_DEPLOYMENT_TOOL_DIR}/inventory/localhost.ini'
    
    # 构建ansible-playbook命令
    cmd_args = [
        'ansible-playbook',
        '-i', inventory_path,
        playbook_path,
        '--become',
        '--become-method=sudo'
    ]
    
    # 添加extra_vars
    if extra_vars:
        # 将字典转换为JSON字符串，然后传递给-e参数
        extra_vars_json = json.dumps(extra_vars, ensure_ascii=False)
        cmd_args.extend(['-e', extra_vars_json])
    
    # 如果需要确保Ansible已安装，先执行安装检查脚本
    if ensure_ansible:
        # 使用内置的install_ansible.sh脚本
        install_script_path = f'{AGENT_DEPLOYMENT_TOOL_DIR}/scripts/install_ansible.sh'
        
        # 先执行Ansible安装检查，并等待完成
        install_cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=[install_script_path],
            timeout=300
        )
        # 等待安装完成（最多5分钟）
        import time
        max_wait = 300
        wait_time = 0
        while wait_time < max_wait:
            install_cmd.refresh_from_db()
            if install_cmd.status in ['success', 'failed']:
                break
            time.sleep(2)
            wait_time += 2
        
        if install_cmd.status != 'success':
            # 如果安装失败，仍然尝试执行playbook（可能Ansible已经存在）
            pass
    
    # 执行ansible-playbook命令
    # cmd_args[0]是'ansible-playbook'，cmd_args[1:]是其他参数
    return CommandQueue.add_command(
        agent=agent,
        command=cmd_args[0],  # 'ansible-playbook'
        args=cmd_args[1:],    # 其他参数
        timeout=timeout
    )

