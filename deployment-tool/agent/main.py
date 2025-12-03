#!/usr/bin/env python3
"""
MyX Agent - Python版本
与Go版本功能完全兼容，支持实时上报
"""
# Agent版本号
__version__ = '1.0.0'

import argparse
import json
import logging
import os
import platform
import random
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List, Any

# 尝试导入Flask（Web服务需要）
try:
    from flask import Flask, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    Flask = None
    jsonify = None
    FLASK_AVAILABLE = False

# 配置日志
def setup_logging():
    """设置日志"""
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = '/var/log/myx-agent.log'
    try:
        if os.path.exists('/var/log') and os.access('/var/log', os.W_OK):
            # 使用追加模式，保留历史日志
            file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
            handlers.append(file_handler)
    except Exception:
        pass  # 如果无法创建日志文件，只使用控制台输出
    
    logging.basicConfig(
        level=logging.INFO,
        format=f'%(asctime)s - %(levelname)s - [Agent v{__version__}] - %(message)s',
        handlers=handlers
    )

setup_logging()
logger = logging.getLogger(__name__)

# 启动时记录版本信息
logger.info(f"MyX Agent v{__version__} 启动中...")

# Agent无状态，不需要默认API URL和心跳配置


class Config:
    """Agent配置（无状态，只存储必要信息）"""
    def __init__(self):
        self.agent_token: str = ""  # Agent Token（服务器分配）
        self.secret_key: str = ""  # 加密密钥（服务器分配）
        self.rpc_port: Optional[int] = None  # RPC端口（首次启动时确定，不可更改）
        self.rpc_path: str = ""  # RPC随机路径（服务器分配，用于路径混淆，保障安全）
        self.certificate_path: Optional[str] = None
        self.private_key_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'agent_token': self.agent_token,
            'secret_key': self.secret_key,
            'rpc_port': self.rpc_port,
            'rpc_path': self.rpc_path,
            'certificate_path': self.certificate_path,
            'private_key_path': self.private_key_path,
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """从字典加载"""
        self.agent_token = data.get('agent_token', '')
        self.secret_key = data.get('secret_key', '')
        self.rpc_port = data.get('rpc_port')
        self.rpc_path = data.get('rpc_path', '')
        self.certificate_path = data.get('certificate_path')
        self.private_key_path = data.get('private_key_path')


class AgentWebServer:
    """Agent Web服务器"""
    
    def __init__(self, config, command_executor):
        """
        Args:
            config: Agent配置对象
            command_executor: 命令执行器（Agent主类的execute_command方法）
        """
        if not FLASK_AVAILABLE:
            raise ImportError("Flask未安装，无法启动Web服务。请运行: pip install flask")
        
        self.config = config
        self.command_executor = command_executor
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = config.secret_key or 'default-secret-key'
        self.running = False
        self.server_thread = None
        self._setup_routes()
    
    def _setup_routes(self):
        """设置路由"""
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """健康检查"""
            return jsonify({
                'status': 'ok',
                'version': __version__,
                'timestamp': time.time()
            })
        
        @self.app.route('/api/execute', methods=['POST'])
        def execute_command():
            """执行命令"""
            # 验证Token
            token = request.headers.get('X-Agent-Token')
            if not token or token != self.config.agent_token:
                return jsonify({'error': 'Unauthorized'}), 401
            
            try:
                data = request.get_json()
                command = data.get('command')
                args = data.get('args', [])
                timeout = data.get('timeout', 300)
                command_id = data.get('command_id')
                
                if not command:
                    return jsonify({'error': 'Command is required'}), 400
                
                # 创建命令对象
                cmd = {
                    'id': command_id or int(time.time()),
                    'command': command,
                    'args': args,
                    'timeout': timeout
                }
                
                # 异步执行命令
                thread = threading.Thread(
                    target=self.command_executor,
                    args=(cmd,),
                    daemon=True
                )
                thread.start()
                
                return jsonify({
                    'status': 'accepted',
                    'command_id': cmd['id'],
                    'message': 'Command accepted and will be executed'
                }), 202
                
            except Exception as e:
                logger.error(f"执行命令失败: {e}", exc_info=True)
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            """获取Agent状态"""
            token = request.headers.get('X-Agent-Token')
            if not token or token != self.config.agent_token:
                return jsonify({'error': 'Unauthorized'}), 401
            
            return jsonify({
                'status': 'online',
                'version': __version__,
                'hostname': os.uname().nodename if hasattr(os, 'uname') else 'unknown',
                'platform': os.name,
                'timestamp': time.time()
            })
        
        @self.app.route('/api/commands/<int:command_id>/result', methods=['POST'])
        def submit_result():
            """提交命令执行结果（Agent内部使用）"""
            token = request.headers.get('X-Agent-Token')
            if not token or token != self.config.agent_token:
                return jsonify({'error': 'Unauthorized'}), 401
            
            return jsonify({'status': 'ok'}), 200
    
    def _generate_self_signed_cert(self, cert_dir: str = '/etc/myx-agent/ssl'):
        """生成自签名证书"""
        os.makedirs(cert_dir, exist_ok=True)
        
        cert_path = os.path.join(cert_dir, 'agent.crt')
        key_path = os.path.join(cert_dir, 'agent.key')
        
        # 如果证书已存在，直接返回
        if os.path.exists(cert_path) and os.path.exists(key_path):
            return cert_path, key_path
        
        # 使用openssl生成自签名证书
        try:
            # 生成私钥
            subprocess.run([
                'openssl', 'genrsa', '-out', key_path, '2048'
            ], check=True, capture_output=True)
            
            # 生成证书
            hostname = os.uname().nodename if hasattr(os, 'uname') else 'localhost'
            subprocess.run([
                'openssl', 'req', '-new', '-x509', '-key', key_path,
                '-out', cert_path, '-days', '365',
                '-subj', f'/CN={hostname}/O=MyX Agent'
            ], check=True, capture_output=True)
            
            # 设置权限
            os.chmod(cert_path, 0o644)
            os.chmod(key_path, 0o600)
            
            logger.info(f"自签名证书已生成: {cert_path}, {key_path}")
            return cert_path, key_path
            
        except subprocess.CalledProcessError as e:
            logger.error(f"生成证书失败: {e}")
            return None, None
        except FileNotFoundError:
            logger.error("未找到openssl命令，无法生成证书")
            return None, None
    
    def start(self, host='0.0.0.0', port=8443, use_ssl=True):
        """启动Web服务器"""
        if self.running:
            logger.warning("Web服务器已在运行")
            return
        
        def run_server():
            try:
                # 使用局部变量跟踪SSL状态
                should_use_ssl = use_ssl
                
                if should_use_ssl:
                    # 获取证书路径
                    cert_path = getattr(self.config, 'certificate_path', None) or '/etc/myx-agent/ssl/agent.crt'
                    key_path = getattr(self.config, 'private_key_path', None) or '/etc/myx-agent/ssl/agent.key'
                    
                    # 如果证书不存在，生成自签名证书
                    if not os.path.exists(cert_path) or not os.path.exists(key_path):
                        cert_path, key_path = self._generate_self_signed_cert()
                        if not cert_path or not key_path:
                            logger.error("无法生成证书，使用HTTP模式")
                            should_use_ssl = False
                    
                    if should_use_ssl and os.path.exists(cert_path) and os.path.exists(key_path):
                        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                        context.load_cert_chain(cert_path, key_path)
                        logger.info(f"启动HTTPS服务器: https://{host}:{port}")
                        self.app.run(host=host, port=port, ssl_context=context, threaded=True, debug=False)
                    else:
                        logger.warning("证书文件不存在，使用HTTP模式（不安全）")
                        self.app.run(host=host, port=port, threaded=True, debug=False)
                else:
                    logger.warning("使用HTTP模式（不安全）")
                    self.app.run(host=host, port=port, threaded=True, debug=False)
            except Exception as e:
                logger.error(f"Web服务器启动失败: {e}", exc_info=True)
                self.running = False
        
        self.running = True
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        logger.info(f"Agent Web服务器已启动: {'HTTPS' if use_ssl else 'HTTP'}://{host}:{port}")
    
    def stop(self):
        """停止Web服务器"""
        self.running = False
        logger.info("Agent Web服务器已停止")


class Agent:
    """MyX Agent主类（无状态，只等待服务器连接）"""
    
    def __init__(self, config: Config):
        self.config = config
        self.running = True
        self.command_threads: Dict[int, threading.Thread] = {}
        self.rpc_server = None  # JSON-RPC服务器实例
        self.ansible_executor = None  # Ansible执行器
        
        # 日志缓冲区（用于实时日志流式传输）
        self.log_buffer: Dict[int, Dict[str, Any]] = {}  # {command_id: {'stdout': str, 'stderr': str, 'completed': bool, 'result': dict}}
        self.log_buffer_lock = threading.Lock()  # 保护日志缓冲区的锁
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
        # 初始化Ansible执行器
        try:
            # 尝试相对导入（作为包的一部分）
            try:
                from .ansible_executor import AnsibleExecutor
            except ImportError:
                # 如果相对导入失败，尝试绝对导入（直接运行脚本时）
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
        sys.exit(0)
    
    # 移除register方法 - Agent不再向服务器注册，配置由服务器在部署时生成
    
    def save_config(self, config_path: str):
        """保存配置到文件"""
        try:
            config_dir = Path(config_path).parent
            config_dir.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, 'w') as f:
                json.dump(self.config.to_dict(), f, indent=2)
            
            # 设置文件权限为600
            os.chmod(config_path, 0o600)
            logger.info(f"配置文件已保存到: {config_path}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            raise
    
    def load_config(self, config_path: str) -> bool:
        """从文件加载配置"""
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
            self.config.from_dict(data)
            return True
        except FileNotFoundError:
            logger.error(f"配置文件不存在: {config_path}")
            return False
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            return False
    
    # 移除send_heartbeat方法 - 不再主动发送心跳，由服务器主动检查
    # 移除heartbeat_loop方法 - 不再主动发送心跳，由服务器主动检查
    # 移除poll_commands方法 - 不再轮询命令，由服务器主动推送
    
    # 移除_update_config方法 - 不再需要更新配置，由服务器主动管理
    # 移除command_loop方法 - 不再轮询命令，由服务器主动推送
    
    def execute_command(self, cmd: Dict[str, Any]):
        """
        执行命令（异步执行，日志存储在缓冲区）
        
        注意：Agent无状态，不主动上报结果，日志存储在本地缓冲区，服务器主动获取
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
        
        # 使用 subprocess.Popen 异步执行命令
        try:
            process = subprocess.Popen(
                [command] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # 行缓冲
                universal_newlines=True
            )
            
            # 启动后台线程实时读取 stdout/stderr
            def read_stdout():
                """读取 stdout"""
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
                """读取 stderr"""
                try:
                    for line in iter(process.stderr.readline, ''):
                        if line:
                            with self.log_buffer_lock:
                                if cmd_id in self.log_buffer:
                                    self.log_buffer[cmd_id]['stderr'] += line
                    process.stderr.close()
                except Exception as e:
                    logger.error(f"读取stderr失败 [ID:{cmd_id}]: {e}")
            
            # 启动读取线程
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            
            # 等待命令完成（在后台线程中）
            def wait_process():
                try:
                    process.wait(timeout=timeout)
                    return_code = process.returncode
                    success = return_code == 0

                    # 等待读取线程完成
                    stdout_thread.join(timeout=1)
                    stderr_thread.join(timeout=1)

                    # 获取最终输出
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
            
            # 在后台线程中等待命令完成
            wait_thread = threading.Thread(target=wait_process, daemon=True)
            wait_thread.start()
            
            # 立即返回，不等待命令完成
            return {
                'status': 'running',
                'command_id': cmd_id,
                'message': 'Command started, use get_command_log to retrieve logs'
            }
            
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
            return {
                'success': False,
                'error': str(e),
                'return_code': -1
            }
    
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
            # 简单实现：返回所有新数据（实际可以使用更精确的 offset 机制）
            new_stdout = stdout[offset:] if offset < len(stdout) else ''
            new_stderr = stderr[offset:] if offset < len(stderr) else ''
            
            # 合并 stdout 和 stderr（按时间顺序可能需要更复杂的逻辑）
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
    
    # 移除send_command_progress和send_command_result方法
    # Agent不再主动上报结果，结果通过JSON-RPC返回给服务器
    
    def _load_rpc_port(self) -> int:
        """加载RPC端口（必须由服务器在部署时指定）"""
        # 从配置文件读取（服务器在部署时已写入）
        if self.config.rpc_port:
            logger.info(f"从配置文件读取RPC端口: {self.config.rpc_port}")
            return self.config.rpc_port
        
        # 如果配置文件中没有rpc_port，这是错误情况
        # 端口必须由服务器在部署时指定，Agent不应该自己生成
        raise RuntimeError(
            "配置文件中缺少rpc_port。"
            "RPC端口必须由服务器在部署时指定并写入配置文件。"
            "请重新部署Agent或检查配置文件: /etc/myx-agent/config.json"
        )
    
    def _execute_ansible_wrapper(self, playbook: str, extra_vars: dict, timeout: int):
        """Ansible执行包装器（用于JSON-RPC）"""
        if not self.ansible_executor:
            logger.error("Ansible执行器不可用")
            return
        
        result = self.ansible_executor.run_playbook(playbook, extra_vars, timeout)
        logger.info(f"Ansible playbook执行完成: {playbook}, 成功: {result['success']}")
    
    def _save_rpc_port_to_config(self):
        """保存RPC端口到配置文件"""
        try:
            config_path = '/etc/myx-agent/config.json'
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
                config_data['rpc_port'] = self.config.rpc_port
                with open(config_path, 'w') as f:
                    json.dump(config_data, f, indent=2)
                os.chmod(config_path, 0o600)
                logger.info(f"RPC端口已保存到配置文件: {self.config.rpc_port}")
        except Exception as e:
            logger.warning(f"保存RPC端口到配置文件失败: {e}")
    
    def run(self, enable_rpc=True, enable_web_service=False, web_port=8443):
        """运行Agent（无状态，只等待服务器连接）"""
        logger.info("=" * 60)
        logger.info(f"Agent启动中...")
        logger.info(f"Agent版本: {__version__}")
        logger.info(f"Agent Token: {self.config.agent_token[:10]}...")
        logger.info(f"RPC端口: {self.config.rpc_port}")
        logger.info(f"RPC路径: {self.config.rpc_path}")
        logger.info("运行模式: 无状态，被动等待服务器连接")
        logger.info("=" * 60)
        
        # 启动JSON-RPC服务器（新架构）
        if enable_rpc:
            try:
                # 尝试相对导入（作为包的一部分）
                try:
                    from .rpc_server import JSONRPCServer
                except ImportError:
                    # 如果相对导入失败，尝试绝对导入（直接运行脚本时）
                    import sys
                    import os
                    agent_dir = os.path.dirname(os.path.abspath(__file__))
                    if agent_dir not in sys.path:
                        sys.path.insert(0, agent_dir)
                    from rpc_server import JSONRPCServer
                
                # 确定RPC端口
                rpc_port = self._load_rpc_port()
                
                # 创建JSON-RPC服务器
                self.rpc_server = JSONRPCServer(
                    self.config,
                    self.execute_command,
                    self._execute_ansible_wrapper if self.ansible_executor else None,
                    agent_instance=self  # 传递 Agent 实例以便访问 get_command_log
                )
                self.rpc_server.start(host='0.0.0.0', port=rpc_port, use_ssl=True, enable_websocket=True)
                logger.info(f"Agent JSON-RPC服务已启动: https://0.0.0.0:{rpc_port}")
                
                # 保存端口到配置文件
                self._save_rpc_port_to_config()
            except ImportError as e:
                logger.error(f"启动JSON-RPC服务器失败（导入错误）: {e}", exc_info=True)
                logger.warning("JSON-RPC功能不可用，将使用传统模式")
                enable_rpc = False
            except RuntimeError as e:
                logger.error(f"启动JSON-RPC服务器失败（配置错误）: {e}", exc_info=True)
                logger.error("配置错误，Agent无法启动RPC服务，请检查配置文件")
                # 配置错误是致命错误，应该退出
                raise
            except Exception as e:
                logger.error(f"启动JSON-RPC服务器失败（未知错误）: {e}", exc_info=True)
                logger.warning("将使用传统轮询模式")
                enable_rpc = False
        
        # 启动Web服务器（旧架构，保留兼容）
        if enable_web_service and not enable_rpc:
            try:
                self.web_server = AgentWebServer(self.config, self.execute_command)
                self.web_server.start(host='0.0.0.0', port=web_port, use_ssl=True)
                logger.info(f"Agent Web服务已启动: https://0.0.0.0:{web_port}")
            except Exception as e:
                logger.error(f"启动Web服务器失败: {e}", exc_info=True)
                enable_web_service = False
        
        # Agent不再主动发送心跳或轮询命令，只等待服务器连接
        logger.info("Agent模式: 被动等待服务器连接（服务器主动发送心跳和命令）")
        
        # 保持主线程运行，等待服务器连接
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭...")
            self.running = False


def main():
    """主函数（Agent无状态，只等待服务器连接）"""
    parser = argparse.ArgumentParser(description='MyX Agent - Python版本（无状态）')
    parser.add_argument('--config', type=str, default='/etc/myx-agent/config.json', help='配置文件路径')
    
    args = parser.parse_args()
    
    config = Config()
    agent = Agent(config)
    
    # 从配置文件加载（配置由服务器在部署时生成）
    if not agent.load_config(args.config):
        logger.error("无法加载配置文件")
        logger.error("配置文件应由服务器在部署时生成，请通过服务器重新部署Agent")
        sys.exit(1)
    
    # 验证必要配置
    if not agent.config.agent_token:
        logger.error("配置文件缺少agent_token，请通过服务器重新部署Agent")
        sys.exit(1)
    
    # 运行Agent（只启动JSON-RPC服务器，等待服务器连接）
    try:
        agent.run(enable_rpc=True, enable_web_service=False)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
        agent.running = False
        if agent.rpc_server:
            agent.rpc_server.stop()
    except Exception as e:
        logger.error(f"Agent运行错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

