#!/usr/bin/env python3
"""
MyX Agent - Python版本
简化版本，只保留命令执行和文件管理功能
"""
# Agent版本号
__version__ = '1.0.0'

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any

# 配置日志
def setup_logging():
    """设置日志"""
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = '/var/log/myx-agent.log'
    try:
        if os.path.exists('/var/log') and os.access('/var/log', os.W_OK):
            file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
            handlers.append(file_handler)
    except Exception:
        pass
    
    logging.basicConfig(
        level=logging.INFO,
        format=f'%(asctime)s - %(levelname)s - [Agent v{__version__}] - %(message)s',
        handlers=handlers
    )

setup_logging()
logger = logging.getLogger(__name__)

logger.info(f"MyX Agent v{__version__} 启动中...")


class Config:
    """Agent配置（从环境变量读取）"""
    def __init__(self):
        self.agent_token: str = os.environ.get('AGENT_TOKEN', '')
        self.secret_key: str = os.environ.get('SECRET_KEY', '')
        self.http_port: int = int(os.environ.get('HTTP_PORT', '8443'))
        self.http_path: str = os.environ.get('HTTP_PATH', '')
        self.certificate_path: Optional[str] = os.environ.get('CERTIFICATE_PATH')
        self.private_key_path: Optional[str] = os.environ.get('PRIVATE_KEY_PATH')


class Agent:
    """MyX Agent主类"""
    
    def __init__(self, config: Config):
        self.config = config
        self.running = True
        self.http_server = None
        self.ansible_executor = None
        
        # 日志缓冲区（用于实时日志流式传输）
        self.log_buffer: Dict[int, Dict[str, Any]] = {}
        self.log_buffer_lock = threading.Lock()
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
        # 初始化Ansible执行器
        try:
            import sys
            import os
            agent_dir = os.path.dirname(os.path.abspath(__file__))
            if agent_dir not in sys.path:
                sys.path.insert(0, agent_dir)
            from ansible_executor import AnsibleExecutor
            self.ansible_executor = AnsibleExecutor()
        except ImportError:
            logger.warning("Ansible执行器不可用")
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"收到信号 {signum}，正在关闭...")
        self.running = False
        if self.http_server:
            self.http_server.stop()
        sys.exit(0)
    
    def execute_command(self, cmd: Dict[str, Any]):
        """
        执行命令（异步执行，日志存储在缓冲区）
        
        支持系统命令和Ansible命令
        """
        cmd_id = cmd.get('id') or int(time.time())
        command = cmd['command']
        args = cmd.get('args', [])
        timeout = cmd.get('timeout', 300)
        
        logger.info(f"执行命令 [ID:{cmd_id}]: {command} {args}")
        
        # 初始化日志缓冲区
        with self.log_buffer_lock:
            self.log_buffer[cmd_id] = {
                'stdout': '',
                'stderr': '',
                'completed': False,
                'result': None
            }
        
        # 检查是否是Ansible命令
        if command == 'ansible' or (args and 'ansible-playbook' in args):
            # 执行Ansible playbook
            self._execute_ansible_command(cmd_id, command, args, timeout)
        else:
            # 执行系统命令
            self._execute_system_command(cmd_id, command, args, timeout)
    
    def _execute_system_command(self, cmd_id: int, command: str, args: list, timeout: int):
        """执行系统命令"""
        try:
            process = subprocess.Popen(
                [command] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # 启动后台线程实时读取 stdout/stderr
            def read_stdout():
                try:
                    for line in iter(process.stdout.readline, ''):
                        if line:
                            with self.log_buffer_lock:
                                if cmd_id in self.log_buffer:
                                    self.log_buffer[cmd_id]['stdout'] += line
                    process.stdout.close()
                except Exception as e:
                    logger.error(f"读取stdout失败 [ID:{cmd_id}]: {e}")
            
            def read_stderr():
                try:
                    for line in iter(process.stderr.readline, ''):
                        if line:
                            with self.log_buffer_lock:
                                if cmd_id in self.log_buffer:
                                    self.log_buffer[cmd_id]['stderr'] += line
                    process.stderr.close()
                except Exception as e:
                    logger.error(f"读取stderr失败 [ID:{cmd_id}]: {e}")
            
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            
            # 等待命令完成
            def wait_process():
                try:
                    process.wait(timeout=timeout)
                    return_code = process.returncode
                    success = return_code == 0
                    
                    stdout_thread.join(timeout=1)
                    stderr_thread.join(timeout=1)
                    
                    final_stdout = ''
                    final_stderr = ''
                    with self.log_buffer_lock:
                        if cmd_id in self.log_buffer:
                            final_stdout = self.log_buffer[cmd_id]['stdout']
                            final_stderr = self.log_buffer[cmd_id]['stderr']
                            self.log_buffer[cmd_id]['completed'] = True
                            self.log_buffer[cmd_id]['result'] = {
                                'success': success,
                                'stdout': final_stdout,
                                'stderr': final_stderr,
                                'return_code': return_code
                            }
                    
                    logger.info(f"命令执行完成 [ID:{cmd_id}]: success={success}, return_code={return_code}")
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    with self.log_buffer_lock:
                        if cmd_id in self.log_buffer:
                            self.log_buffer[cmd_id]['completed'] = True
                            self.log_buffer[cmd_id]['result'] = {
                                'success': False,
                                'error': f'Command timeout after {timeout} seconds',
                                'return_code': -1
                            }
                    logger.warning(f"命令超时 [ID:{cmd_id}]")
                except Exception as e:
                    logger.error(f"执行命令失败 [ID:{cmd_id}]: {e}")
                    with self.log_buffer_lock:
                        if cmd_id in self.log_buffer:
                            self.log_buffer[cmd_id]['completed'] = True
                            self.log_buffer[cmd_id]['result'] = {
                                'success': False,
                                'error': str(e),
                                'return_code': -1
                            }
            
            wait_thread = threading.Thread(target=wait_process, daemon=True)
            wait_thread.start()
            
        except Exception as e:
            logger.error(f"启动命令失败 [ID:{cmd_id}]: {e}")
            with self.log_buffer_lock:
                if cmd_id in self.log_buffer:
                    self.log_buffer[cmd_id]['completed'] = True
                    self.log_buffer[cmd_id]['result'] = {
                        'success': False,
                        'error': str(e),
                        'return_code': -1
                    }
    
    def _execute_ansible_command(self, cmd_id: int, command: str, args: list, timeout: int):
        """执行Ansible命令"""
        if not self.ansible_executor:
            with self.log_buffer_lock:
                if cmd_id in self.log_buffer:
                    self.log_buffer[cmd_id]['completed'] = True
                    self.log_buffer[cmd_id]['result'] = {
                        'success': False,
                        'error': 'Ansible执行器不可用',
                        'return_code': -1
                    }
            return
        
        def run_ansible():
            try:
                # 从args中提取playbook路径
                playbook_path = None
                extra_vars = {}
                
                for i, arg in enumerate(args):
                    if arg == '--playbook' or arg == '-p':
                        if i + 1 < len(args):
                            playbook_path = args[i + 1]
                    elif arg.startswith('--extra-vars'):
                        if i + 1 < len(args):
                            try:
                                extra_vars = json.loads(args[i + 1])
                            except:
                                pass
                
                if not playbook_path:
                    # 尝试从args中找到.yml或.yaml文件
                    for arg in args:
                        if arg.endswith('.yml') or arg.endswith('.yaml'):
                            playbook_path = arg
                            break
                
                if not playbook_path:
                    raise ValueError("未找到playbook路径")
                
                result = self.ansible_executor.run_playbook(playbook_path, extra_vars, timeout)
                
                with self.log_buffer_lock:
                    if cmd_id in self.log_buffer:
                        self.log_buffer[cmd_id]['stdout'] = result.get('log', '')
                        self.log_buffer[cmd_id]['completed'] = True
                        self.log_buffer[cmd_id]['result'] = {
                            'success': result.get('success', False),
                            'stdout': result.get('log', ''),
                            'stderr': result.get('error', ''),
                            'return_code': 0 if result.get('success') else 1
                        }
                
                logger.info(f"Ansible命令执行完成 [ID:{cmd_id}]: success={result.get('success', False)}")
            except Exception as e:
                logger.error(f"执行Ansible命令失败 [ID:{cmd_id}]: {e}", exc_info=True)
                with self.log_buffer_lock:
                    if cmd_id in self.log_buffer:
                        self.log_buffer[cmd_id]['completed'] = True
                        self.log_buffer[cmd_id]['result'] = {
                            'success': False,
                            'error': str(e),
                            'return_code': -1
                        }
        
        thread = threading.Thread(target=run_ansible, daemon=True)
        thread.start()
    
    def get_command_log(self, command_id: int, offset: int = 0) -> Dict[str, Any]:
        """
        获取命令日志（服务器主动调用）
        
        Args:
            command_id: 命令ID
            offset: 已读取的字节数（用于增量获取）
            
        Returns:
            {log_data, log_type, new_offset, is_final, result}
        """
        with self.log_buffer_lock:
            if command_id not in self.log_buffer:
                return {
                    'error': f'Command {command_id} not found',
                    'is_final': True
                }
            
            buffer = self.log_buffer[command_id]
            stdout = buffer['stdout']
            stderr = buffer['stderr']
            completed = buffer['completed']
            result = buffer['result']
            
            # 计算新的日志数据（从 offset 开始）
            new_stdout = stdout[offset:] if offset < len(stdout) else ''
            new_stderr = stderr[offset:] if offset < len(stderr) else ''
            
            # 合并 stdout 和 stderr
            log_data = new_stdout + new_stderr
            new_offset = len(stdout) + len(stderr)
            
            response = {
                'log_data': log_data,
                'log_type': 'stdout' if new_stdout else ('stderr' if new_stderr else 'stdout'),
                'new_offset': new_offset,
                'is_final': completed
            }
            
            # 如果命令已完成，返回最终结果
            if completed and result:
                response['result'] = result
            
            return response
    
    def set_file(self, file_path: str, content: str, mode: str = '0644') -> Dict[str, Any]:
        """
        通用文件上传方法（set）
        
        Args:
            file_path: 文件路径
            content: 文件内容
            mode: 文件权限（八进制字符串，如 '0644'）
            
        Returns:
            {'status': 'ok', 'path': file_path} 或 {'error': '...'}
        """
        try:
            # 确保目录存在
            file_dir = os.path.dirname(file_path)
            if file_dir:
                os.makedirs(file_dir, exist_ok=True)
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # 设置文件权限
            try:
                mode_int = int(mode, 8)
                os.chmod(file_path, mode_int)
            except ValueError:
                logger.warning(f"无效的文件权限模式: {mode}，使用默认权限")
            
            logger.info(f"文件已上传: {file_path}")
            return {'status': 'ok', 'path': file_path}
        except Exception as e:
            logger.error(f"上传文件失败: {e}", exc_info=True)
            return {'error': str(e)}
    
    def get_file(self, file_path: str) -> Dict[str, Any]:
        """
        通用文件获取方法（get）
        
        Args:
            file_path: 文件路径
            
        Returns:
            {'status': 'ok', 'content': '...', 'path': file_path} 或 {'error': '...'}
        """
        try:
            if not os.path.exists(file_path):
                return {'error': f'File not found: {file_path}'}
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return {'status': 'ok', 'content': content, 'path': file_path}
        except Exception as e:
            logger.error(f"获取文件失败: {e}", exc_info=True)
            return {'error': str(e)}
    
    def run(self):
        """运行Agent"""
        logger.info("=" * 60)
        logger.info(f"Agent启动中...")
        logger.info(f"Agent版本: {__version__}")
        logger.info(f"Agent Token: {self.config.agent_token[:10]}...")
        logger.info(f"HTTP端口: {self.config.http_port}")
        logger.info(f"HTTP路径: {self.config.http_path}")
        logger.info("=" * 60)
        
        # 验证必要配置
        if not self.config.agent_token:
            raise RuntimeError("环境变量 AGENT_TOKEN 未设置")
        
        if not self.config.http_path:
            raise RuntimeError("环境变量 HTTP_PATH 未设置")
        
        # 启动HTTP服务器
        try:
            from http_server import AgentHTTPServer
            self.http_server = AgentHTTPServer(self.config, self)
            self.http_server.start(host='0.0.0.0', port=self.config.http_port, use_ssl=True)
            logger.info("Agent HTTP服务器已启动")
        except Exception as e:
            logger.error(f"启动HTTP服务器失败: {e}", exc_info=True)
            raise
        
        # 保持主线程运行
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭...")
            self.running = False
            if self.http_server:
                self.http_server.stop()


def main():
    """主函数"""
    config = Config()
    agent = Agent(config)
    
    # 验证必要配置
    if not config.agent_token:
        logger.error("环境变量 AGENT_TOKEN 未设置，请通过服务器重新部署Agent")
        sys.exit(1)
    
    if not config.http_path:
        logger.error("环境变量 HTTP_PATH 未设置，请通过服务器重新部署Agent")
        sys.exit(1)
    
    # 运行Agent
    try:
        agent.run()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
        agent.running = False
        if agent.http_server:
            agent.http_server.stop()
    except Exception as e:
        logger.error(f"Agent运行错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
