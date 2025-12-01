#!/usr/bin/env python3
"""
MyX Agent - Python版本
与Go版本功能完全兼容，支持实时上报
"""
import argparse
import json
import logging
import os
import platform
import random
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
def setup_logging():
    """设置日志"""
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = '/var/log/myx-agent.log'
    try:
        if os.path.exists('/var/log') and os.access('/var/log', os.W_OK):
            handlers.append(logging.FileHandler(log_file))
    except Exception:
        pass  # 如果无法创建日志文件，只使用控制台输出
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

setup_logging()
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_API_URL = "http://localhost:8000/api/agents"
HEARTBEAT_MIN_INTERVAL = 30  # 秒
HEARTBEAT_MAX_INTERVAL = 300  # 秒
POLL_MIN_INTERVAL = 5  # 秒
POLL_MAX_INTERVAL = 60  # 秒
PROGRESS_REPORT_INTERVAL = 2  # 秒，实时上报间隔


class Config:
    """Agent配置"""
    def __init__(self):
        self.server_token: str = ""
        self.secret_key: str = ""
        self.api_url: str = DEFAULT_API_URL
        self.agent_token: str = ""
        self.heartbeat_mode: str = "push"  # push 或 pull
        self.heartbeat_min_interval: int = HEARTBEAT_MIN_INTERVAL
        self.heartbeat_max_interval: int = HEARTBEAT_MAX_INTERVAL
        self.poll_min_interval: int = POLL_MIN_INTERVAL
        self.poll_max_interval: int = POLL_MAX_INTERVAL
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'server_token': self.server_token,
            'secret_key': self.secret_key,
            'api_url': self.api_url,
            'agent_token': self.agent_token,
            'heartbeat_mode': self.heartbeat_mode,
            'heartbeat_min_interval': self.heartbeat_min_interval,
            'heartbeat_max_interval': self.heartbeat_max_interval,
            'poll_min_interval': self.poll_min_interval,
            'poll_max_interval': self.poll_max_interval,
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """从字典加载"""
        self.server_token = data.get('server_token', '')
        self.secret_key = data.get('secret_key', '')
        self.api_url = data.get('api_url', DEFAULT_API_URL)
        self.agent_token = data.get('agent_token', '')
        self.heartbeat_mode = data.get('heartbeat_mode', 'push')
        self.heartbeat_min_interval = data.get('heartbeat_min_interval', HEARTBEAT_MIN_INTERVAL)
        self.heartbeat_max_interval = data.get('heartbeat_max_interval', HEARTBEAT_MAX_INTERVAL)
        self.poll_min_interval = data.get('poll_min_interval', POLL_MIN_INTERVAL)
        self.poll_max_interval = data.get('poll_max_interval', POLL_MAX_INTERVAL)


class Agent:
    """MyX Agent主类"""
    
    def __init__(self, config: Config):
        self.config = config
        self.running = True
        self.http_session = self._create_session()
        self.command_threads: Dict[int, threading.Thread] = {}
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _create_session(self) -> requests.Session:
        """创建HTTP会话，带重试机制"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.timeout = 10
        return session
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"收到信号 {signum}，正在关闭...")
        self.running = False
        sys.exit(0)
    
    def register(self, server_token: str, api_url: str) -> bool:
        """注册Agent"""
        try:
            hostname = socket.gethostname()
            os_name = platform.system().lower()
            
            data = {
                'server_token': server_token,
                'version': '1.0.0',
                'hostname': hostname,
                'os': os_name,
            }
            
            response = self.http_session.post(
                f"{api_url}/register/",
                json=data,
                timeout=10
            )
            response.raise_for_status()
            
            result = response.json()
            self.config.server_token = server_token
            self.config.secret_key = result.get('secret_key', '')
            self.config.api_url = api_url
            self.config.agent_token = result.get('token', '')
            self.config.heartbeat_mode = result.get('heartbeat_mode', 'push')
            
            logger.info("注册成功！")
            logger.info(f"Agent Token: {self.config.agent_token}")
            return True
            
        except Exception as e:
            logger.error(f"注册失败: {e}")
            return False
    
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
    
    def send_heartbeat(self) -> bool:
        """发送心跳"""
        try:
            data = {
                'status': 'online',
                'version': '1.0.0',
            }
            
            headers = {
                'X-Agent-Token': self.config.agent_token,
                'Content-Type': 'application/json',
            }
            
            response = self.http_session.post(
                f"{self.config.api_url}/heartbeat/",
                json=data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
            result = response.json()
            # 更新心跳模式和配置
            if 'heartbeat_mode' in result:
                self.config.heartbeat_mode = result['heartbeat_mode']
            if 'config' in result and result['config']:
                config = result['config']
                if 'heartbeat_min_interval' in config:
                    self.config.heartbeat_min_interval = config['heartbeat_min_interval']
                if 'heartbeat_max_interval' in config:
                    self.config.heartbeat_max_interval = config['heartbeat_max_interval']
                if 'poll_min_interval' in config:
                    self.config.poll_min_interval = config['poll_min_interval']
                if 'poll_max_interval' in config:
                    self.config.poll_max_interval = config['poll_max_interval']
            
            return True
            
        except Exception as e:
            logger.error(f"心跳失败: {e}")
            return False
    
    def heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            interval = self._random_interval(
                self.config.heartbeat_min_interval,
                self.config.heartbeat_max_interval
            )
            logger.info(f"下次心跳将在 {interval} 秒后发送")
            
            time.sleep(interval)
            
            if not self.running:
                break
            
            self.send_heartbeat()
    
    def poll_commands(self) -> List[Dict[str, Any]]:
        """轮询命令"""
        try:
            headers = {
                'X-Agent-Token': self.config.agent_token,
            }
            
            response = self.http_session.get(
                f"{self.config.api_url}/poll/",
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
            result = response.json()
            
            # 更新心跳模式和配置
            if 'heartbeat_mode' in result:
                old_mode = self.config.heartbeat_mode
                self.config.heartbeat_mode = result['heartbeat_mode']
                if old_mode != self.config.heartbeat_mode:
                    logger.info(f"心跳模式已更新: {old_mode} -> {self.config.heartbeat_mode}")
            
            if 'config' in result and result['config']:
                self._update_config(result['config'])
            
            return result.get('commands', [])
            
        except Exception as e:
            logger.error(f"轮询命令失败: {e}")
            return []
    
    def _update_config(self, new_config: Dict[str, Any]):
        """更新配置"""
        if 'heartbeat_min_interval' in new_config:
            self.config.heartbeat_min_interval = new_config['heartbeat_min_interval']
        if 'heartbeat_max_interval' in new_config:
            self.config.heartbeat_max_interval = new_config['heartbeat_max_interval']
        if 'poll_min_interval' in new_config:
            self.config.poll_min_interval = new_config['poll_min_interval']
        if 'poll_max_interval' in new_config:
            self.config.poll_max_interval = new_config['poll_max_interval']
        
        logger.info(
            f"配置已更新: 心跳 {self.config.heartbeat_min_interval}-{self.config.heartbeat_max_interval}秒, "
            f"轮询 {self.config.poll_min_interval}-{self.config.poll_max_interval}秒"
        )
    
    def command_loop(self):
        """命令轮询循环"""
        while self.running:
            min_interval = self.config.poll_min_interval or POLL_MIN_INTERVAL
            max_interval = self.config.poll_max_interval or POLL_MAX_INTERVAL
            
            commands = self.poll_commands()
            
            # 执行命令
            for cmd in commands:
                if cmd['id'] not in self.command_threads:
                    thread = threading.Thread(
                        target=self.execute_command,
                        args=(cmd,),
                        daemon=True
                    )
                    thread.start()
                    self.command_threads[cmd['id']] = thread
            
            # 清理已完成的线程
            self.command_threads = {
                cmd_id: thread for cmd_id, thread in self.command_threads.items()
                if thread.is_alive()
            }
            
            # 随机间隔
            interval = self._random_interval(min_interval, max_interval)
            time.sleep(interval)
    
    def execute_command(self, cmd: Dict[str, Any]):
        """执行命令（实时上报输出）"""
        cmd_id = cmd['id']
        command = cmd['command']
        args = cmd.get('args', [])
        timeout = cmd.get('timeout', 300)
        
        logger.info(f"执行命令 [ID:{cmd_id}]: {command} {args}")
        
        try:
            # 使用subprocess.Popen实时读取输出
            process = subprocess.Popen(
                [command] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # 行缓冲
            )
            
            # 实时读取并上报输出
            stdout_lines = []
            stderr_lines = []
            accumulated_output = []
            last_report_time = time.time()
            
            def read_output(pipe, lines_list, is_stdout=True):
                """读取输出"""
                try:
                    for line in iter(pipe.readline, ''):
                        if not line:
                            break
                        line = line.rstrip('\n\r')
                        lines_list.append(line)
                        accumulated_output.append(('stdout' if is_stdout else 'stderr', line))
                except Exception as e:
                    logger.error(f"读取输出错误: {e}")
                finally:
                    pipe.close()
            
            # 启动读取线程
            stdout_thread = threading.Thread(
                target=read_output,
                args=(process.stdout, stdout_lines, True),
                daemon=True
            )
            stderr_thread = threading.Thread(
                target=read_output,
                args=(process.stderr, stderr_lines, False),
                daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()
            
            # 等待命令完成，定时上报输出
            start_time = time.time()
            while process.poll() is None:
                # 检查超时
                if time.time() - start_time > timeout:
                    logger.warning(f"命令超时，终止进程 [ID:{cmd_id}]")
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                
                # 每2秒上报一次累积的输出
                if time.time() - last_report_time >= PROGRESS_REPORT_INTERVAL:
                    if accumulated_output:
                        stdout_new = '\n'.join(
                            line for stream, line in accumulated_output if stream == 'stdout'
                        )
                        stderr_new = '\n'.join(
                            line for stream, line in accumulated_output if stream == 'stderr'
                        )
                        if stdout_new or stderr_new:
                            self.send_command_progress(cmd_id, stdout_new, stderr_new)
                        accumulated_output.clear()
                    last_report_time = time.time()
                
                time.sleep(0.5)  # 短暂休眠，避免CPU占用过高
            
            # 等待读取线程完成
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            
            # 上报剩余输出
            if accumulated_output:
                stdout_new = '\n'.join(
                    line for stream, line in accumulated_output if stream == 'stdout'
                )
                stderr_new = '\n'.join(
                    line for stream, line in accumulated_output if stream == 'stderr'
                )
                if stdout_new or stderr_new:
                    self.send_command_progress(cmd_id, stdout_new, stderr_new)
            
            # 获取最终结果
            stdout_str = '\n'.join(stdout_lines)
            stderr_str = '\n'.join(stderr_lines)
            return_code = process.returncode
            
            success = return_code == 0
            logger.info(f"命令执行完成 [ID:{cmd_id}]: success={success}, return_code={return_code}")
            
            # 上报最终结果
            self.send_command_result(cmd_id, success, stdout_str, stderr_str, return_code)
            
        except Exception as e:
            logger.error(f"执行命令失败 [ID:{cmd_id}]: {e}")
            self.send_command_result(cmd_id, False, "", str(e), None)
    
    def send_command_progress(self, command_id: int, stdout: str, stderr: str):
        """发送命令进度（增量更新）"""
        try:
            data = {
                'stdout': stdout,
                'stderr': stderr,
                'append': True,
            }
            
            headers = {
                'X-Agent-Token': self.config.agent_token,
                'Content-Type': 'application/json',
            }
            
            response = self.http_session.post(
                f"{self.config.api_url}/commands/{command_id}/progress/",
                json=data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
        except Exception as e:
            logger.debug(f"发送命令进度失败: {e}")
    
    def send_command_result(self, command_id: int, success: bool, stdout: str, stderr: str, return_code: Optional[int]):
        """发送命令执行结果"""
        try:
            data = {
                'success': success,
                'stdout': stdout,
                'stderr': stderr,
                'append': False,
            }
            
            if return_code is not None:
                data['return_code'] = return_code
            
            headers = {
                'X-Agent-Token': self.config.agent_token,
                'Content-Type': 'application/json',
            }
            
            response = self.http_session.post(
                f"{self.config.api_url}/commands/{command_id}/result/",
                json=data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
        except Exception as e:
            logger.error(f"发送命令结果失败: {e}")
    
    def _random_interval(self, min_seconds: int, max_seconds: int) -> int:
        """生成随机间隔（秒）"""
        if min_seconds >= max_seconds:
            return min_seconds
        return random.randint(min_seconds, max_seconds)
    
    def run(self):
        """运行Agent"""
        logger.info("Agent启动中...")
        logger.info(f"API地址: {self.config.api_url}")
        logger.info(f"Agent Token: {self.config.agent_token}")
        logger.info(f"心跳模式: {self.config.heartbeat_mode}")
        
        # 启动心跳循环（仅在push模式下）
        if self.config.heartbeat_mode != 'pull':
            heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
            heartbeat_thread.start()
            logger.info("心跳模式: 推送模式（Agent主动发送心跳）")
        else:
            logger.info("心跳模式: 拉取模式（中心服务器主动检查），不发送心跳")
        
        # 启动命令轮询循环（主循环）
        self.command_loop()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='MyX Agent - Python版本')
    parser.add_argument('--token', type=str, help='服务器Token（用于首次注册）')
    parser.add_argument('--api', type=str, default=DEFAULT_API_URL, help='API服务器地址')
    parser.add_argument('--config', type=str, default='/etc/myx-agent/config.json', help='配置文件路径')
    
    args = parser.parse_args()
    
    config = Config()
    agent = Agent(config)
    
    # 首次注册
    if args.token:
        if not agent.register(args.token, args.api):
            sys.exit(1)
        
        # 保存配置
        agent.save_config(args.config)
        logger.info("注册完成，配置文件已保存")
        return
    
    # 从配置文件加载
    if not agent.load_config(args.config):
        logger.error("无法加载配置文件，请先注册")
        logger.error(f"使用方法: {sys.argv[0]} --token <server_token> --api <api_url>")
        sys.exit(1)
    
    # 运行Agent
    try:
        agent.run()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
        agent.running = False
    except Exception as e:
        logger.error(f"Agent运行错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

