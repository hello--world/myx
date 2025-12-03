#!/usr/bin/env python3
"""
Agent JSON-RPC服务器
提供JSON-RPC 2.0接口，支持HTTP和WebSocket传输
"""
import json
import logging
import os
import random
import socket
import ssl
import subprocess
import threading
import time
from typing import Dict, Any, Optional, Callable

try:
    from flask import Flask, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    Flask = None
    jsonify = None
    FLASK_AVAILABLE = False

try:
    import websockets
    from websockets.server import serve as ws_serve
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    websockets = None
    WEBSOCKETS_AVAILABLE = False

logger = logging.getLogger(__name__)

# 尝试从main模块导入版本号
try:
    from main import __version__ as AGENT_VERSION
except ImportError:
    AGENT_VERSION = '1.0.0'


class JSONRPCServer:
    """JSON-RPC 2.0服务器"""
    
    def __init__(self, config, command_executor: Callable, ansible_executor: Optional[Callable] = None, agent_instance: Optional[Any] = None):
        """
        Args:
            config: Agent配置对象
            command_executor: 命令执行器函数
            ansible_executor: Ansible执行器函数（可选）
            agent_instance: Agent实例（用于访问 get_command_log 方法）
        """
        self.config = config
        self.command_executor = command_executor
        self.ansible_executor = ansible_executor
        self.agent_instance = agent_instance
        self.running = False
        self.server_thread = None
        self.ws_server = None
        
        if FLASK_AVAILABLE:
            self.app = Flask(__name__)
            try:
                from flask_cors import CORS
                CORS(self.app)  # 允许跨域
            except ImportError:
                pass  # CORS 可选
            self.app.config['SECRET_KEY'] = config.secret_key or 'default-secret-key'
            self._setup_routes()
        else:
            self.app = None
            logger.warning("Flask未安装，HTTP JSON-RPC功能不可用")
    
    def _setup_routes(self):
        """设置HTTP路由"""
        if not self.app:
            return
        
        # 从配置读取 rpc_path，动态注册路由
        rpc_path = getattr(self.config, 'rpc_path', '')
        if not rpc_path:
            logger.error("配置文件中缺少 rpc_path。RPC路径必须由服务器在部署时指定并写入配置文件。")
            raise RuntimeError(
                "配置文件中缺少 rpc_path。"
                "RPC路径必须由服务器在部署时指定并写入配置文件。"
                "请重新部署Agent或检查配置文件: /etc/myx-agent/config.json"
            )
        
        # 动态注册路由：/{rpc_path}/rpc
        route_path = f'/{rpc_path}/rpc'
        logger.info(f"注册JSON-RPC路由: {route_path}")
        
        @self.app.route(route_path, methods=['POST'])
        def rpc_endpoint():
            """JSON-RPC HTTP端点"""
            try:
                data = request.get_json()
                if not data:
                    return jsonify({
                        'jsonrpc': '2.0',
                        'error': {'code': -32700, 'message': 'Parse error'},
                        'id': None
                    }), 400
                
                # 验证Token
                token = request.headers.get('X-Agent-Token')
                if not token or token != self.config.agent_token:
                    return jsonify({
                        'jsonrpc': '2.0',
                        'error': {'code': -32001, 'message': 'Unauthorized'},
                        'id': data.get('id')
                    }), 401
                
                # 处理JSON-RPC请求
                response = self._handle_request(data)
                return jsonify(response)
            except Exception as e:
                logger.error(f"处理JSON-RPC请求失败: {e}", exc_info=True)
                return jsonify({
                    'jsonrpc': '2.0',
                    'error': {'code': -32603, 'message': f'Internal error: {str(e)}'},
                    'id': None
                }), 500
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """健康检查"""
            return jsonify({
                'status': 'ok',
                'version': AGENT_VERSION,
                'timestamp': time.time()
            })
    
    def _handle_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理JSON-RPC请求"""
        method = request_data.get('method')
        params = request_data.get('params', {})
        request_id = request_data.get('id')
        
        if not method:
            return {
                'jsonrpc': '2.0',
                'error': {'code': -32600, 'message': 'Invalid Request'},
                'id': request_id
            }
        
        # 路由到对应的方法
        try:
            if method == 'execute_command':
                # 同步执行命令并返回结果
                result = self._execute_command(
                    params.get('command'),
                    params.get('args', []),
                    params.get('timeout', 300),
                    params.get('command_id')
                )
            elif method == 'execute_ansible':
                result = self._execute_ansible(
                    params.get('playbook'),
                    params.get('extra_vars', {}),
                    params.get('timeout', 600)
                )
            elif method == 'get_status':
                result = self._get_status()
            elif method == 'health_check':
                result = {'status': 'ok'}
            elif method == 'get_port':
                result = {'port': getattr(self.config, 'rpc_port', None)}
            elif method == 'heartbeat':
                # 服务器主动发送心跳
                result = {'status': 'ok', 'message': 'Heartbeat received'}
            elif method == 'get_command_log':
                # 获取命令日志（服务器主动调用，用于实时日志流式传输）
                result = self._get_command_log(
                    params.get('command_id'),
                    params.get('offset', 0)
                )
            else:
                return {
                    'jsonrpc': '2.0',
                    'error': {'code': -32601, 'message': f'Method not found: {method}'},
                    'id': request_id
                }
            
            return {
                'jsonrpc': '2.0',
                'result': result,
                'id': request_id
            }
        except Exception as e:
            logger.error(f"执行方法 {method} 失败: {e}", exc_info=True)
            return {
                'jsonrpc': '2.0',
                'error': {'code': -32603, 'message': f'Internal error: {str(e)}'},
                'id': request_id
            }
    
    def _execute_command(self, command: str, args: list, timeout: int, command_id: Optional[int] = None) -> Dict[str, Any]:
        """执行系统命令（异步执行，立即返回）"""
        if not command:
            raise ValueError("Command is required")
        
        cmd_id = command_id or int(time.time())
        cmd = {
            'id': cmd_id,
            'command': command,
            'args': args,
            'timeout': timeout
        }
        
        # 异步执行命令（通过command_executor，立即返回）
        result = self.command_executor(cmd)
        return result
    
    def _get_command_log(self, command_id: Optional[int], offset: int = 0) -> Dict[str, Any]:
        """获取命令日志（从缓冲区）"""
        if command_id is None:
            raise ValueError("command_id is required")
        
        # 优先使用 agent_instance
        if self.agent_instance and hasattr(self.agent_instance, 'get_command_log'):
            return self.agent_instance.get_command_log(command_id, offset)
        
        # 如果 command_executor 是绑定方法，尝试获取实例
        if hasattr(self.command_executor, '__self__'):
            agent_instance = self.command_executor.__self__
            if hasattr(agent_instance, 'get_command_log'):
                return agent_instance.get_command_log(command_id, offset)
        
        # 如果 command_executor 本身就是 Agent 实例
        if hasattr(self.command_executor, 'get_command_log'):
            return self.command_executor.get_command_log(command_id, offset)
        
        raise ValueError("无法访问 Agent 实例的 get_command_log 方法")
    
    def _execute_ansible(self, playbook: str, extra_vars: dict, timeout: int) -> Dict[str, Any]:
        """执行Ansible playbook"""
        if not self.ansible_executor:
            raise ValueError("Ansible executor not available")
        
        if not playbook:
            raise ValueError("Playbook is required")
        
        # 异步执行Ansible任务
        thread = threading.Thread(
            target=self.ansible_executor,
            args=(playbook, extra_vars, timeout),
            daemon=True
        )
        thread.start()
        
        return {
            'status': 'accepted',
            'message': 'Ansible playbook accepted and will be executed'
        }
    
    def _get_status(self) -> Dict[str, Any]:
        """获取Agent状态"""
        return {
            'status': 'online',
            'version': AGENT_VERSION,  # 使用从main模块导入的版本号
            'hostname': os.uname().nodename if hasattr(os, 'uname') else 'unknown',
            'platform': os.name,
            'timestamp': time.time(),
            'rpc_port': getattr(self.config, 'rpc_port', None)
        }
    
    def _generate_self_signed_cert(self, cert_dir: str = '/etc/myx-agent/ssl'):
        """生成自签名证书"""
        os.makedirs(cert_dir, exist_ok=True)
        
        cert_path = os.path.join(cert_dir, 'agent.crt')
        key_path = os.path.join(cert_dir, 'agent.key')
        
        if os.path.exists(cert_path) and os.path.exists(key_path):
            return cert_path, key_path
        
        try:
            subprocess.run([
                'openssl', 'genrsa', '-out', key_path, '2048'
            ], check=True, capture_output=True)
            
            hostname = os.uname().nodename if hasattr(os, 'uname') else 'localhost'
            subprocess.run([
                'openssl', 'req', '-new', '-x509', '-key', key_path,
                '-out', cert_path, '-days', '365',
                '-subj', f'/CN={hostname}/O=MyX Agent'
            ], check=True, capture_output=True)
            
            os.chmod(cert_path, 0o644)
            os.chmod(key_path, 0o600)
            
            logger.info(f"自签名证书已生成: {cert_path}, {key_path}")
            return cert_path, key_path
        except Exception as e:
            logger.error(f"生成证书失败: {e}")
            return None, None
    
    def _find_available_port(self, start_port: int = 8000, end_port: int = 65535, max_attempts: int = 100) -> Optional[int]:
        """查找可用端口"""
        excluded_ports = {22, 80, 443, 8000, 8443, 3306, 5432, 6379, 8080, 9000}
        
        for _ in range(max_attempts):
            port = random.randint(start_port, end_port)
            if port in excluded_ports:
                continue
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(('0.0.0.0', port))
                sock.close()
                return port
            except OSError:
                continue
        
        return None
    
    def start(self, host='0.0.0.0', port: Optional[int] = None, use_ssl: bool = True, enable_websocket: bool = True):
        """启动JSON-RPC服务器"""
        if self.running:
            logger.warning("JSON-RPC服务器已在运行")
            return
        
        # 确定端口（必须由服务器在部署时指定）
        if port is None:
            # 从配置读取（服务器在部署时已写入）
            port = getattr(self.config, 'rpc_port', None)
            if not port:
                # 如果配置文件中没有rpc_port，这是错误情况
                # 端口必须由服务器在部署时指定，Agent不应该自己生成
                raise RuntimeError(
                    "配置文件中缺少rpc_port。"
                    "RPC端口必须由服务器在部署时指定并写入配置文件。"
                    "请重新部署Agent或检查配置文件: /etc/myx-agent/config.json"
                )
            else:
                logger.info(f"使用配置的RPC端口: {port}（由服务器分配）")
        
        # 验证 rpc_path（必须由服务器在部署时指定）
        rpc_path = getattr(self.config, 'rpc_path', '')
        if not rpc_path:
            raise RuntimeError(
                "配置文件中缺少rpc_path。"
                "RPC路径必须由服务器在部署时指定并写入配置文件。"
                "请重新部署Agent或检查配置文件: /etc/myx-agent/config.json"
            )
        
        def run_http_server():
            """运行HTTP服务器"""
            if not self.app:
                logger.error("Flask未安装，无法启动HTTP服务器")
                self.running = False
                return
            
            try:
                # 使用局部变量跟踪SSL状态，避免UnboundLocalError
                should_use_ssl = use_ssl
                
                if should_use_ssl:
                    cert_path = getattr(self.config, 'certificate_path', None) or '/etc/myx-agent/ssl/agent.crt'
                    key_path = getattr(self.config, 'private_key_path', None) or '/etc/myx-agent/ssl/agent.key'
                    
                    if not os.path.exists(cert_path) or not os.path.exists(key_path):
                        logger.warning(f"证书文件不存在: cert={cert_path}, key={key_path}，尝试生成自签名证书")
                        cert_path, key_path = self._generate_self_signed_cert()
                        if not cert_path or not key_path:
                            logger.error("无法生成证书，使用HTTP模式")
                            should_use_ssl = False
                    
                    if should_use_ssl and os.path.exists(cert_path) and os.path.exists(key_path):
                        try:
                            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                            context.load_cert_chain(cert_path, key_path)
                            logger.info(f"启动HTTPS JSON-RPC服务器: https://{host}:{port}")
                            logger.info(f"使用证书: {cert_path}, 私钥: {key_path}")
                            self.app.run(host=host, port=port, ssl_context=context, threaded=True, debug=False)
                        except Exception as ssl_error:
                            logger.error(f"SSL上下文创建失败: {ssl_error}", exc_info=True)
                            logger.warning("回退到HTTP模式")
                            self.app.run(host=host, port=port, threaded=True, debug=False)
                    else:
                        logger.warning("证书文件不存在，使用HTTP模式（不安全）")
                        self.app.run(host=host, port=port, threaded=True, debug=False)
                else:
                    logger.warning("使用HTTP模式（不安全）")
                    self.app.run(host=host, port=port, threaded=True, debug=False)
            except Exception as e:
                logger.error(f"HTTP服务器启动失败: {e}", exc_info=True)
                self.running = False
                # 重新抛出异常，让调用者知道启动失败
                raise
        
        def run_websocket_server():
            """运行WebSocket服务器"""
            if not WEBSOCKETS_AVAILABLE:
                logger.warning("websockets未安装，WebSocket功能不可用")
                return
            
            import asyncio
            
            async def handle_websocket(websocket, path):
                """处理WebSocket连接"""
                try:
                    # 验证Token
                    token = websocket.request_headers.get('X-Agent-Token')
                    if not token or token != self.config.agent_token:
                        await websocket.close(code=1008, reason="Unauthorized")
                        return
                    
                    async for message in websocket:
                        try:
                            request_data = json.loads(message)
                            response = self._handle_request(request_data)
                            await websocket.send(json.dumps(response))
                        except Exception as e:
                            logger.error(f"处理WebSocket消息失败: {e}")
                            await websocket.send(json.dumps({
                                'jsonrpc': '2.0',
                                'error': {'code': -32603, 'message': str(e)},
                                'id': None
                            }))
                except Exception as e:
                    logger.error(f"WebSocket连接错误: {e}")
            
            async def serve():
                ws_port = port + 1  # WebSocket使用相邻端口
                logger.info(f"启动WebSocket JSON-RPC服务器: ws://{host}:{ws_port}")
                async with ws_serve(handle_websocket, host, ws_port):
                    await asyncio.Future()  # 永远运行
            
            if enable_websocket:
                # 在新的事件循环中运行
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(serve())
        
        self.running = True
        
        # 启动HTTP服务器
        if FLASK_AVAILABLE:
            self.server_thread = threading.Thread(target=run_http_server, daemon=True)
            self.server_thread.start()
            
            # 等待一小段时间，检查服务器是否成功启动
            import time
            time.sleep(0.5)
            
            # 检查服务器线程是否还在运行
            if not self.server_thread.is_alive():
                self.running = False
                raise RuntimeError("HTTP服务器线程启动后立即退出，请检查日志获取详细错误信息")
            
            # 验证端口是否在监听
            try:
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.settimeout(1)
                result = test_sock.connect_ex((host if host != '0.0.0.0' else '127.0.0.1', port))
                test_sock.close()
                if result != 0:
                    logger.warning(f"端口 {port} 可能尚未开始监听，但服务器线程正在运行")
            except Exception as check_error:
                logger.warning(f"端口检查失败: {check_error}")
        else:
            raise RuntimeError("Flask未安装，无法启动JSON-RPC服务器")
        
        # 启动WebSocket服务器（可选）
        if enable_websocket and WEBSOCKETS_AVAILABLE:
            ws_thread = threading.Thread(target=run_websocket_server, daemon=True)
            ws_thread.start()
        
        logger.info(f"JSON-RPC服务器已启动: {'HTTPS' if use_ssl else 'HTTP'}://{host}:{port}")
    
    def stop(self):
        """停止JSON-RPC服务器"""
        self.running = False
        logger.info("JSON-RPC服务器已停止")

