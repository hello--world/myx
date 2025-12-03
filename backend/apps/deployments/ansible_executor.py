"""
统一的Ansible执行器
使用ansible-runner执行所有Ansible任务
"""
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Generator

try:
    import ansible_runner
    ANSIBLE_RUNNER_AVAILABLE = True
except ImportError:
    ansible_runner = None
    ANSIBLE_RUNNER_AVAILABLE = False

logger = logging.getLogger(__name__)


class AnsibleExecutor:
    """统一的Ansible执行器（使用ansible-runner）"""
    
    def __init__(self, playbooks_dir: Optional[str] = None):
        """
        Args:
            playbooks_dir: Playbooks目录路径（可选）
        """
        if playbooks_dir:
            self.playbooks_dir = Path(playbooks_dir)
        else:
            # 默认从项目根目录查找
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            self.playbooks_dir = base_dir / 'deployment-tool' / 'playbooks'
        
        if not ANSIBLE_RUNNER_AVAILABLE:
            logger.warning("ansible-runner未安装，Ansible功能可能不可用")
    
    def run_playbook(
        self,
        playbook_name: str,
        inventory_content: str,
        extra_vars: Optional[Dict[str, Any]] = None,
        timeout: int = 600
    ) -> Dict[str, Any]:
        """
        执行Ansible playbook
        
        Args:
            playbook_name: playbook文件名（如 'deploy_xray.yml'）
            inventory_content: inventory文件内容
            extra_vars: 额外的Ansible变量
            timeout: 超时时间（秒）
            
        Returns:
            执行结果字典，包含success, log, error等字段
        """
        if not ANSIBLE_RUNNER_AVAILABLE:
            return {
                'success': False,
                'error': 'ansible-runner未安装',
                'log': ''
            }
        
        playbook_path = self.playbooks_dir / playbook_name
        if not playbook_path.exists():
            return {
                'success': False,
                'error': f'Playbook不存在: {playbook_path}',
                'log': ''
            }
        
        # 创建临时目录用于ansible-runner
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # 写入inventory文件
                inventory_path = Path(tmpdir) / 'inventory' / 'hosts'
                inventory_path.parent.mkdir(parents=True, exist_ok=True)
                with open(inventory_path, 'w') as f:
                    f.write(inventory_content)
                
                # 准备extra_vars
                evars = extra_vars or {}
                
                # 运行ansible-runner
                r = ansible_runner.run(
                    playbook=str(playbook_path),
                    inventory=str(inventory_path),
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
    
    def run_playbook_streaming(
        self,
        playbook_name: str,
        inventory_content: str,
        extra_vars: Optional[Dict[str, Any]] = None,
        timeout: int = 600
    ) -> Generator[str, None, None]:
        """
        执行Ansible playbook并流式返回日志
        
        Args:
            playbook_name: playbook文件名
            inventory_content: inventory文件内容
            extra_vars: 额外的Ansible变量
            timeout: 超时时间（秒）
            
        Yields:
            日志行（字符串）
        """
        if not ANSIBLE_RUNNER_AVAILABLE:
            yield "ERROR: ansible-runner未安装\n"
            return
        
        playbook_path = self.playbooks_dir / playbook_name
        if not playbook_path.exists():
            yield f"ERROR: Playbook不存在: {playbook_path}\n"
            return
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # 写入inventory文件
                inventory_path = Path(tmpdir) / 'inventory' / 'hosts'
                inventory_path.parent.mkdir(parents=True, exist_ok=True)
                with open(inventory_path, 'w') as f:
                    f.write(inventory_content)
                
                # 准备extra_vars
                evars = extra_vars or {}
                
                # 运行ansible-runner（流式模式）
                r = ansible_runner.run(
                    playbook=str(playbook_path),
                    inventory=str(inventory_path),
                    extravars=evars,
                    private_data_dir=tmpdir,
                    quiet=False,
                    streamer=None  # 可以设置自定义streamer
                )
                
                # 读取实时输出
                if hasattr(r, 'events'):
                    for event in r.events:
                        if 'stdout' in event:
                            yield event['stdout'] + '\n'
                        if 'stderr' in event:
                            yield event['stderr'] + '\n'
            except Exception as e:
                logger.error(f"执行Ansible playbook失败: {e}", exc_info=True)
                yield f"ERROR: {str(e)}\n"

