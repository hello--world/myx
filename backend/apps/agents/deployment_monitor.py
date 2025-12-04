"""
Agent部署任务监控模块
"""
import time
import os
import logging
import threading
from django.utils import timezone
from apps.deployments.models import Deployment
from apps.agents.models import Agent
from apps.servers.models import Server
from .command_queue import CommandQueue

logger = logging.getLogger(__name__)


class DeploymentMonitor:
    """部署任务监控器"""
    
    def __init__(self, deployment: Deployment, agent: Agent, server: Server, log_file_path: str, command_id: int = None):
        self.deployment = deployment
        self.agent = agent
        self.server = server
        self.log_file_path = log_file_path
        self.command_id = command_id  # 命令ID，用于从命令结果读取日志
        self.max_wait = 600  # 最多等待10分钟
    
    def monitor(self):
        """监控部署任务执行"""
        start_time = time.time()
        last_log_size = 0
        agent_offline_detected = False
        agent_offline_time = None
        
        logger.info(f'开始监控部署任务: deployment_id={self.deployment.id}, log_file={self.log_file_path}')
        
        # 初始化部署日志
        self._update_log(f"[监控] 开始监控部署任务，日志文件: {self.log_file_path}\n")
        
        # 等待一下，让脚本有时间创建日志文件
        time.sleep(1)
        
        while time.time() - start_time < self.max_wait:
            try:
                # 检查Agent状态
                self.agent.refresh_from_db()
                if self.agent.status == 'offline' and not agent_offline_detected:
                    agent_offline_detected = True
                    agent_offline_time = time.time()
                    self._update_log(f"\n[进度] Agent已停止，等待重新启动...\n")
                
                # 如果Agent重新上线，继续监控
                if agent_offline_detected and self.agent.status == 'online':
                    self._update_log(f"\n[进度] Agent已重新上线，继续监控...\n")
                    agent_offline_detected = False
                    agent_offline_time = None
                
                # 从命令执行结果读取日志（如果命令已完成）
                if self.command_id:
                    try:
                        from .models import AgentCommand
                        cmd = AgentCommand.objects.filter(id=self.command_id).first()
                        if cmd:
                            # 如果命令已完成，从结果中读取日志
                            if cmd.status in ['success', 'failed']:
                                if cmd.result:
                                    # 检查是否已经添加过这个日志（避免重复）
                                    result_preview = cmd.result[:100] if len(cmd.result) > 100 else cmd.result
                                    if f"[命令结果]" not in (self.deployment.log or '') or result_preview not in (self.deployment.log or ''):
                                        self._update_log(f"\n=== 命令执行结果 ===\n{cmd.result}\n")
                                if cmd.error:
                                    self._update_log(f"\n=== 命令执行错误 ===\n{cmd.error}\n")
                    except Exception as e:
                        logger.debug(f'读取命令结果失败: {str(e)}')
                
                # 读取日志文件新增内容
                if os.path.exists(self.log_file_path):
                    try:
                        current_log_size = os.path.getsize(self.log_file_path)
                        if current_log_size > last_log_size:
                            with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                f.seek(last_log_size)
                                new_log_content = f.read()
                                if new_log_content.strip():
                                    self._update_log(new_log_content)
                                last_log_size = current_log_size
                    except Exception as e:
                        logger.debug(f'读取日志文件失败: {str(e)}')
                else:
                    # 如果日志文件不存在，每10秒记录一次
                    if int(time.time() - start_time) % 10 < 2:
                        logger.debug(f'日志文件不存在: {self.log_file_path}')
                        self._update_log(f"[监控] 等待日志文件创建: {self.log_file_path}\n")
                
                # 检查脚本是否完成（从日志文件或命令结果）
                script_completed, script_success = self._check_completion()
                
                # 如果命令已完成，也检查命令结果
                if self.command_id and not script_completed:
                    try:
                        from .models import AgentCommand
                        cmd = AgentCommand.objects.filter(id=self.command_id).first()
                        if cmd and cmd.status in ['success', 'failed']:
                            # 命令已完成，从结果判断脚本是否成功
                            if cmd.status == 'success':
                                # 检查命令结果中是否有完成标记
                                if cmd.result:
                                    if '[完成] Agent重新部署成功' in cmd.result or 'Agent重新部署成功，服务运行正常' in cmd.result:
                                        script_completed = True
                                        script_success = True
                                    elif '[错误]' in cmd.result:
                                        script_completed = True
                                        script_success = False
                            else:
                                script_completed = True
                                script_success = False
                    except Exception as e:
                        logger.debug(f'检查命令状态失败: {str(e)}')
                
                if script_completed:
                    self._handle_completion(script_success)
                    break
                
                # 如果命令已完成，也检查命令结果
                if self.command_id:
                    try:
                        from .models import AgentCommand
                        cmd = AgentCommand.objects.filter(id=self.command_id).first()
                        if cmd and cmd.status in ['success', 'failed']:
                            # 命令已完成，从结果判断脚本是否成功
                            # 如果命令成功且日志中有完成标记，认为脚本成功
                            if cmd.status == 'success':
                                # 检查命令结果中是否有完成标记
                                if cmd.result and ('[完成]' in cmd.result or 'Agent重新部署成功' in cmd.result):
                                    script_success = True
                                elif cmd.result and '[错误]' in cmd.result:
                                    script_success = False
                                else:
                                    # 如果命令成功但没有明确标记，检查日志文件
                                    if not script_completed:
                                        script_completed, script_success = self._check_completion()
                            else:
                                script_success = False
                            
                            if script_completed or (cmd.status in ['success', 'failed'] and not script_completed):
                                # 如果命令已完成但还没检查完成，现在处理
                                if not script_completed:
                                    script_completed = True
                                self._handle_completion(script_success)
                                break
                    except Exception as e:
                        logger.debug(f'检查命令状态失败: {str(e)}')
                
                # 等待2秒后继续检查
                time.sleep(2)
                
                # 如果Agent离线超过2分钟，尝试通过SSH检查
                if agent_offline_detected and agent_offline_time and (time.time() - agent_offline_time) > 120:
                    self._check_via_ssh()
                    agent_offline_detected = False
                    agent_offline_time = None
                
            except Exception as e:
                logger.error(f'监控部署任务时出错: {str(e)}', exc_info=True)
                time.sleep(5)
        
        # 如果超时仍未完成
        if self.deployment.status == 'running':
            self.deployment.status = 'failed'
            self.deployment.error_message = '部署超时'
            self.deployment.completed_at = timezone.now()
            self._update_log(f"\n[超时] 部署超时（超过10分钟）\n")
            self.deployment.save()
            logger.warning(f'部署任务超时: deployment_id={self.deployment.id}')
    
    def _update_log(self, log_content: str):
        """更新部署日志"""
        self.deployment.log = (self.deployment.log or '') + log_content
        self.deployment.save()
    
    def _check_completion(self):
        """检查脚本是否完成，返回(是否完成, 是否成功)"""
        if not os.path.exists(self.log_file_path):
            return False, False
        
        try:
            with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                full_log = f.read()
                
                # 检查完成标记
                success_markers = [
                    '[完成] Agent重新部署成功',
                    '[完成] Agent重新部署成功，服务运行正常'
                ]
                for marker in success_markers:
                    if marker in full_log:
                        logger.info(f'检测到脚本完成标记: {marker}')
                        return True, True
                
                # 检查错误标记
                if '[错误]' in full_log and ('exit 1' in full_log or 'exit 1' in full_log[-100:]):
                    logger.info(f'检测到脚本错误退出')
                    return True, False
        except Exception as e:
            logger.error(f'读取日志文件失败: {str(e)}, 路径: {self.log_file_path}')
        
        return False, False
    
    def _handle_completion(self, script_success: bool):
        """处理脚本完成"""
        # 等待一下，确保所有日志都已写入
        time.sleep(2)
        
        # 读取完整日志
        if os.path.exists(self.log_file_path):
            try:
                with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    full_log = f.read()
                    if full_log.strip():
                        self._update_log(f"\n=== 完整执行日志 ===\n{full_log}\n")
                    else:
                        logger.warning(f'日志文件存在但为空: {self.log_file_path}')
                        self._update_log(f"\n[警告] 日志文件存在但内容为空\n")
            except Exception as e:
                logger.error(f'读取完整日志文件失败: {str(e)}')
                self._update_log(f"\n[错误] 读取日志文件失败: {str(e)}\n")
        else:
            logger.warning(f'日志文件不存在: {self.log_file_path}')
            self._update_log(f"\n[警告] 日志文件不存在: {self.log_file_path}\n")
        
        if script_success:
            # 测试Agent是否在线
            agent_online = self._test_agent_online()
            
            if agent_online:
                self.deployment.status = 'success'
                self._update_log(f"\n[完成] Agent重新部署成功，服务运行正常\n")
                
                # 自动配置 Agent 域名（如果服务器还没有域名）
                try:
                    from apps.servers.server_domain_utils import auto_setup_server_agent_domain
                    result = auto_setup_server_agent_domain(
                        server=self.server,
                        auto_setup=True
                    )
                    if result.get('success'):
                        domain = result.get('domain')
                        self._update_log(f"\n[域名] Agent 域名自动配置成功: {domain}\n")
                        logger.info(f'Agent 域名自动配置成功: server_id={self.server.id}, domain={domain}')
                    elif not result.get('skipped'):
                        # 配置失败但不影响部署成功状态
                        error_msg = result.get('error', '未知错误')
                        self._update_log(f"\n[域名] Agent 域名自动配置失败: {error_msg}\n")
                        logger.warning(f'Agent 域名自动配置失败: server_id={self.server.id}, error={error_msg}')
                except Exception as e:
                    # 域名配置失败不影响部署成功状态
                    logger.warning(f'Agent 域名自动配置时出错: {str(e)}', exc_info=True)
                    self._update_log(f"\n[域名] Agent 域名自动配置时出错: {str(e)}\n")
            else:
                # 即使测试失败，如果脚本成功执行，也标记为成功
                self.deployment.status = 'success'
                self._update_log(f"\n[完成] Agent重新部署成功，但Agent尚未重新注册（可能需要等待）\n")
        else:
            self.deployment.status = 'failed'
            self.agent.refresh_from_db()
            if self.agent.status != 'online':
                self.deployment.error_message = 'Agent重新部署后未正常上线'
            else:
                self.deployment.error_message = '脚本执行失败'
        
        self.deployment.completed_at = timezone.now()
        self.deployment.save()
        logger.info(f'部署任务已更新为完成状态: {self.deployment.status}, Agent状态: {self.agent.status}')
    
    def _test_agent_online(self) -> bool:
        """测试Agent是否在线"""
        self._update_log(f"\n[测试] 正在测试Agent是否在线...\n")
        
        # 等待几秒让Agent有时间重新注册
        time.sleep(5)
        
        # 刷新Agent状态
        self.agent.refresh_from_db()
        
        # 尝试发送测试命令
        try:
            test_cmd = CommandQueue.add_command(
                agent=self.agent,
                command='echo',
                args=['test'],
                timeout=10
            )
            
            # 等待命令执行（最多等待10秒）
            for _ in range(10):
                time.sleep(1)
                test_cmd.refresh_from_db()
                if test_cmd.status in ['success', 'failed']:
                    if test_cmd.status == 'success':
                        self._update_log(f"\n[测试] Agent测试命令执行成功，确认Agent在线\n")
                        return True
                    else:
                        self._update_log(f"\n[测试] Agent测试命令执行失败: {test_cmd.error or '未知错误'}\n")
                        break
            
            if test_cmd.status not in ['success', 'failed']:
                self._update_log(f"\n[测试] Agent测试命令超时\n")
        except Exception as e:
            logger.warning(f'发送Agent测试命令失败: {str(e)}')
            self._update_log(f"\n[测试] 发送测试命令失败: {str(e)}，使用数据库状态判断\n")
        
        # 再次刷新Agent状态
        self.agent.refresh_from_db()
        return self.agent.status == 'online'
    
    def _check_via_ssh(self):
        """通过SSH检查Agent服务状态"""
        try:
            from apps.servers.utils import test_ssh_connection
            ssh_result = test_ssh_connection(
                host=self.server.host,
                port=self.server.port,
                username=self.server.username,
                password=self.server.password,
                private_key=self.server.private_key
            )
            
            if ssh_result['success']:
                import paramiko
                from io import StringIO
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # 使用私钥或密码连接
                if self.server.private_key:
                    key_file = StringIO(self.server.private_key)
                    try:
                        pkey = paramiko.RSAKey.from_private_key(key_file)
                    except:
                        key_file.seek(0)
                        try:
                            pkey = paramiko.Ed25519Key.from_private_key(key_file)
                        except:
                            key_file.seek(0)
                            pkey = paramiko.ECDSAKey.from_private_key(key_file)
                    ssh.connect(
                        self.server.host,
                        port=self.server.port,
                        username=self.server.username,
                        pkey=pkey,
                        timeout=10
                    )
                else:
                    ssh.connect(
                        self.server.host,
                        port=self.server.port,
                        username=self.server.username,
                        password=self.server.password,
                        timeout=10
                    )
                
                stdin, stdout, stderr = ssh.exec_command('systemctl is-active myx-agent')
                service_status = stdout.read().decode().strip()
                ssh.close()
                
                self._update_log(f"\n[检查] 通过SSH检查Agent服务状态: {service_status}\n")
                
                if service_status == 'active':
                    self._update_log(f"\n[进度] Agent服务已启动，等待Agent重新注册...\n")
        except Exception as e:
            logger.debug(f'通过SSH检查Agent状态失败: {str(e)}')


def start_monitor(deployment: Deployment, agent: Agent, server: Server, log_file_path: str, command_id: int = None):
    """启动部署监控线程"""
    monitor = DeploymentMonitor(deployment, agent, server, log_file_path, command_id)
    thread = threading.Thread(target=monitor.monitor, daemon=True)
    thread.start()
    return thread

