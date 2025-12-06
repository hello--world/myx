#!/usr/bin/env python3
"""
Agent HTTP服务器
使用Flask实现HTTP服务器，提供命令执行和文件管理接口
"""
import json
import logging
import os
import ssl
import threading
import time
from flask import Flask, request, jsonify
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AgentHTTPServer:
    """Agent HTTP服务器（使用Flask）"""
    
    def __init__(self, config, agent_instance):
        """
        Args:
            config: Agent配置对象
            agent_instance: Agent实例
        """
        self.config = config
        self.agent = agent_instance
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = config.secret_key or 'default-secret-key'
        self.running = False
        self.server_thread = None
        self._setup_routes()
    
    def _verify_token(self) -> bool:
        """验证Token"""
        token = request.headers.get('X-Agent-Token')
        if not token or token != self.config.agent_token:
            return False
        return True
    
    def _setup_routes(self):
        """设置路由"""
        http_path = self.config.http_path
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """健康检查"""
            return jsonify({
                'status': 'ok',
                'timestamp': time.time()
            })
        
        @self.app.route(f'/{http_path}/execute', methods=['POST'])
        def execute():
            """执行命令"""
            if not self._verify_token():
                return jsonify({'error': 'Unauthorized'}), 401
            
            try:
                data = request.get_json()
                command = data.get('command')
                args = data.get('args', [])
                timeout = data.get('timeout', 300)
                command_id = data.get('command_id')
                
                if not command:
                    return jsonify({'error': 'Command is required'}), 400
                
                cmd = {
                    'id': command_id or int(time.time()),
                    'command': command,
                    'args': args,
                    'timeout': timeout
                }
                
                # 异步执行命令
                thread = threading.Thread(
                    target=self.agent.execute_command,
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
        
        @self.app.route(f'/{http_path}/file', methods=['POST'])
        def set_file():
            """上传文件（set）"""
            if not self._verify_token():
                return jsonify({'error': 'Unauthorized'}), 401
            
            try:
                data = request.get_json()
                file_path = data.get('path')
                content = data.get('content')
                mode = data.get('mode', '0644')
                
                if not file_path or content is None:
                    return jsonify({'error': 'path and content are required'}), 400
                
                result = self.agent.set_file(file_path, content, mode)
                if result.get('error'):
                    return jsonify({'error': result['error']}), 500
                else:
                    return jsonify(result)
            except Exception as e:
                logger.error(f"上传文件失败: {e}", exc_info=True)
                return jsonify({'error': str(e)}), 500
        
        @self.app.route(f'/{http_path}/file', methods=['GET'])
        def get_file():
            """获取文件（get）"""
            if not self._verify_token():
                return jsonify({'error': 'Unauthorized'}), 401
            
            try:
                file_path = request.args.get('path')
                if not file_path:
                    return jsonify({'error': 'path parameter is required'}), 400
                
                result = self.agent.get_file(file_path)
                if result.get('error'):
                    return jsonify({'error': result['error']}), 404
                else:
                    return jsonify(result)
            except Exception as e:
                logger.error(f"获取文件失败: {e}", exc_info=True)
                return jsonify({'error': str(e)}), 500
        
        @self.app.route(f'/{http_path}/log/<int:command_id>', methods=['GET'])
        def get_log(command_id):
            """获取命令日志"""
            if not self._verify_token():
                return jsonify({'error': 'Unauthorized'}), 401
            
            try:
                offset = int(request.args.get('offset', 0))
                result = self.agent.get_command_log(command_id, offset)
                if result.get('error'):
                    return jsonify({'error': result['error']}), 404
                else:
                    return jsonify(result)
            except Exception as e:
                logger.error(f"获取命令日志失败: {e}", exc_info=True)
                return jsonify({'error': str(e)}), 500
    
    def start(self, host='0.0.0.0', port=None, use_ssl=True):
        """启动HTTP服务器"""
        if self.running:
            logger.warning("HTTP服务器已在运行")
            return
        
        if port is None:
            port = self.config.http_port
        
        if not port:
            raise RuntimeError("HTTP端口未配置，请检查环境变量 HTTP_PORT")
        
        if not self.config.http_path:
            raise RuntimeError("HTTP路径未配置，请检查环境变量 HTTP_PATH")
        
        def run_server():
            """运行服务器"""
            try:
                should_use_ssl = use_ssl
                
                if should_use_ssl and self.config.certificate_path and self.config.private_key_path:
                    if os.path.exists(self.config.certificate_path) and os.path.exists(self.config.private_key_path):
                        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                        context.load_cert_chain(self.config.certificate_path, self.config.private_key_path)
                        logger.info(f"启动HTTPS服务器: https://{host}:{port}")
                        self.app.run(host=host, port=port, ssl_context=context, threaded=True, debug=False)
                    else:
                        logger.warning("证书文件不存在，使用HTTP模式")
                        logger.info(f"启动HTTP服务器: http://{host}:{port}")
                        self.app.run(host=host, port=port, threaded=True, debug=False)
                else:
                    logger.warning("使用HTTP模式（不安全）")
                    logger.info(f"启动HTTP服务器: http://{host}:{port}")
                    self.app.run(host=host, port=port, threaded=True, debug=False)
            except Exception as e:
                logger.error(f"HTTP服务器启动失败: {e}", exc_info=True)
                self.running = False
                raise
        
        self.running = True
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        
        # 等待服务器启动
        time.sleep(0.5)
        if not self.server_thread.is_alive():
            raise RuntimeError("HTTP服务器启动失败")
        
        logger.info(f"Agent HTTP服务器已启动: {'HTTPS' if use_ssl else 'HTTP'}://{host}:{port}/{self.config.http_path}/")
    
    def stop(self):
        """停止HTTP服务器"""
        self.running = False
        logger.info("Agent HTTP服务器已停止")
