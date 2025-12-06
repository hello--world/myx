#!/usr/bin/env python3
"""
Agent端Ansible执行器
使用ansible-runner执行Ansible playbook
"""
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import ansible_runner
    ANSIBLE_RUNNER_AVAILABLE = True
except ImportError:
    ansible_runner = None
    ANSIBLE_RUNNER_AVAILABLE = False

logger = logging.getLogger(__name__)


class AnsibleExecutor:
    """Ansible执行器（使用ansible-runner）"""
    
    def __init__(self, deployment_tool_dir: str = '/opt/myx-agent/deployment-tool'):
        """
        Args:
            deployment_tool_dir: 部署工具目录路径
        """
        self.deployment_tool_dir = Path(deployment_tool_dir)
        self.inventory_path = self.deployment_tool_dir / 'inventory' / 'localhost.ini'
        
        if not ANSIBLE_RUNNER_AVAILABLE:
            logger.warning("ansible-runner未安装，Ansible功能不可用")
    
    def run_playbook(
        self,
        playbook_path: str,
        extra_vars: Optional[Dict[str, Any]] = None,
        timeout: int = 600
    ) -> Dict[str, Any]:
        """
        执行Ansible playbook
        
        Args:
            playbook_path: playbook文件路径（可以是绝对路径或相对路径）
            extra_vars: 额外的Ansible变量
            timeout: 超时时间（秒）
            
        Returns:
            执行结果字典
        """
        if not ANSIBLE_RUNNER_AVAILABLE:
            return {
                'success': False,
                'error': 'ansible-runner未安装',
                'log': ''
            }
        
        # 转换为Path对象
        playbook_path_obj = Path(playbook_path)
        
        # 如果是相对路径，尝试从部署工具目录查找
        if not playbook_path_obj.is_absolute():
            playbook_path_obj = self.deployment_tool_dir / 'playbooks' / playbook_path
        
        if not playbook_path_obj.exists():
            return {
                'success': False,
                'error': f'Playbook不存在: {playbook_path_obj}',
                'log': ''
            }
        
        # 确保inventory文件存在
        if not self.inventory_path.exists():
            self.inventory_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.inventory_path, 'w') as f:
                f.write('[localhost]\n127.0.0.1 ansible_connection=local\n')
        
        # 创建临时目录用于ansible-runner
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # 准备extra_vars
                evars = extra_vars or {}
                
                # 运行ansible-runner
                r = ansible_runner.run(
                    playbook=str(playbook_path_obj),
                    inventory=str(self.inventory_path),
                    extravars=evars,
                    private_data_dir=tmpdir,
                    quiet=False,
                    json_mode=True
                )
                
                # 读取输出
                log_output = ''
                if r.stdout:
                    log_output += r.stdout
                if r.stderr:
                    log_output += '\n' + r.stderr
                
                return {
                    'success': r.status == 'successful',
                    'error': None if r.status == 'successful' else f'Playbook执行失败: {r.status}',
                    'log': log_output,
                    'exit_code': r.rc
                }
            except Exception as e:
                logger.error(f"执行Ansible playbook失败: {e}", exc_info=True)
                return {
                    'success': False,
                    'error': str(e),
                    'log': ''
                }
