"""
Agent命令队列管理
使用HTTP API与Agent通信
"""
from django.utils import timezone
from .models import Agent, AgentCommand
import logging
import threading
import time
import requests
from urllib3.exceptions import InsecureRequestWarning
import urllib3

# 禁用SSL警告（因为使用自签名证书）
urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)

# 日志轮询任务字典：{command_id: {'thread': Thread, 'offset': int, 'stop': bool}}
_log_polling_tasks = {}
_log_polling_lock = threading.Lock()


class CommandQueue:
    """命令队列管理器"""
    
    @staticmethod
    def _get_agent_http_url(agent: Agent, endpoint: str) -> str:
        """
        构建Agent HTTP API URL
        
        Args:
            agent: Agent实例
            endpoint: API端点（如 'execute', 'log/123'）
            
        Returns:
            完整的HTTP URL
        """
        server = agent.server
        agent_host = server.agent_connect_host or server.host
        agent_port = agent.rpc_port
        
        # 判断是否使用HTTPS（如果Agent有证书配置，使用HTTPS）
        use_https = bool(agent.certificate_path and agent.private_key_path)
        protocol = 'https' if use_https else 'http'
        
        # 构建URL：/{http_path}/{endpoint}
        http_path = agent.rpc_path or ''
        if http_path:
            url = f"{protocol}://{agent_host}:{agent_port}/{http_path}/{endpoint}"
        else:
            # 如果没有路径，直接使用端点（向后兼容）
            url = f"{protocol}://{agent_host}:{agent_port}/{endpoint}"
        
        return url
    
    @staticmethod
    def _get_agent_verify_ssl(agent: Agent) -> bool:
        """
        判断是否验证SSL证书
        
        Args:
            agent: Agent实例
            
        Returns:
            是否验证SSL证书
        """
        server = agent.server
        # 如果配置了agent域名，则验证SSL证书；如果只使用IP地址，则不验证
        return bool(server.agent_connect_host)
    
    @staticmethod
    def _poll_command_log(command_id: int, agent: Agent):
        """
        轮询命令日志（后台任务，使用HTTP API）
        
        Args:
            command_id: 命令ID
            agent: Agent实例
        """
        offset = 0
        max_poll_time = 3600  # 最多轮询1小时
        start_time = time.time()
        poll_interval = 2  # 每2秒轮询一次
        
        logger.info(f'[CommandQueue] 开始轮询命令日志: command_id={command_id}')
        
        # 准备HTTP请求
        verify_ssl = CommandQueue._get_agent_verify_ssl(agent)
        headers = {
            'X-Agent-Token': str(agent.token),
            'Content-Type': 'application/json'
        }
        
        while time.time() - start_time < max_poll_time:
            try:
                # 检查命令状态
                try:
                    cmd = AgentCommand.objects.get(id=command_id)
                    if cmd.status in ['success', 'failed']:
                        # 命令已完成，停止轮询
                        logger.info(f'[CommandQueue] 命令已完成，停止轮询: command_id={command_id}, status={cmd.status}')
                        break
                except AgentCommand.DoesNotExist:
                    logger.warning(f'[CommandQueue] 命令不存在，停止轮询: command_id={command_id}')
                    break
                
                # 获取增量日志（使用HTTP API）
                log_url = CommandQueue._get_agent_http_url(agent, f'log/{command_id}')
                try:
                    response = requests.get(
                        log_url,
                        params={'offset': offset},
                        headers=headers,
                        verify=verify_ssl,
                        timeout=5
                    )
                    response.raise_for_status()
                    log_result = response.json()
                except requests.exceptions.RequestException as e:
                    logger.warning(f'[CommandQueue] 获取命令日志失败: command_id={command_id}, error={str(e)}')
                    time.sleep(poll_interval)
                    continue
                
                if 'error' in log_result:
                    logger.warning(f'[CommandQueue] 获取命令日志失败: command_id={command_id}, error={log_result.get("error")}')
                    if log_result.get('is_final'):
                        # 命令已失败或不存在，停止轮询
                        break
                else:
                    # 更新日志
                    log_data = log_result.get('log_data', '')
                    new_offset = log_result.get('new_offset', offset)
                    is_final = log_result.get('is_final', False)
                    
                    if log_data:
                        # 追加日志
                        CommandQueue.update_command_result(
                            command_id,
                            None,
                            log_data,
                            None,
                            append=True
                        )
                        offset = new_offset
                    
                    # 如果命令已完成，更新最终状态
                    if is_final:
                        final_result = log_result.get('result')
                        if final_result:
                            success = final_result.get('success', False)
                            stdout = final_result.get('stdout', '')
                            stderr = final_result.get('stderr') or final_result.get('error', '')
                            
                            CommandQueue.update_command_result(
                                command_id,
                                success,
                                stdout,
                                stderr,
                                append=False
                            )
                            
                            logger.info(f'[CommandQueue] 命令执行完成: command_id={command_id}, success={success}')
                        break
                
                # 等待下次轮询
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f'[CommandQueue] 轮询命令日志异常: command_id={command_id}, error={e}', exc_info=True)
                time.sleep(poll_interval)
        
        # 清理轮询任务
        with _log_polling_lock:
            if command_id in _log_polling_tasks:
                del _log_polling_tasks[command_id]
        
        logger.info(f'[CommandQueue] 停止轮询命令日志: command_id={command_id}')
    
    @staticmethod
    def add_command(agent: Agent, command: str, args: list = None, timeout: int = 300):
        """
        添加命令到队列或直接推送到Agent HTTP服务
        
        Args:
            agent: Agent实例
            command: 命令
            args: 参数列表
            timeout: 超时时间（秒）
            
        Returns:
            AgentCommand实例
        """
        if args is None:
            args = []

        # 创建命令，状态为 'running'（立即执行）
        cmd = AgentCommand.objects.create(
            agent=agent,
            command=command,
            args=args,
            timeout=timeout,
            status='running'  # 立即执行，不等待
        )

        logger.info(f'[CommandQueue] 创建命令 ID={cmd.id}, Agent={agent.id}, Command={command}, Args={args}, Status={cmd.status}')

        # 检查Agent是否有端口配置
        if not agent.rpc_port:
            logger.warning(f'[CommandQueue] Agent端口未配置，命令将等待Agent轮询: agent_id={agent.id}')
            cmd.status = 'pending'
            cmd.save()
            return cmd

        # 使用HTTP API推送命令
        try:
            # 构建HTTP请求
            execute_url = CommandQueue._get_agent_http_url(agent, 'execute')
            verify_ssl = CommandQueue._get_agent_verify_ssl(agent)
            headers = {
                'X-Agent-Token': str(agent.token),
                'Content-Type': 'application/json'
            }
            
            data = {
                'command': command,
                'args': args,
                'timeout': timeout,
                'command_id': cmd.id
            }
            
            # 发送HTTP请求
            response = requests.post(
                execute_url,
                json=data,
                headers=headers,
                verify=verify_ssl,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            # 命令已被Agent接受
            if result.get('status') == 'accepted' or result.get('command_id'):
                cmd.started_at = timezone.now()
                cmd.save()
                
                # 启动日志轮询任务（每2秒获取一次日志）
                with _log_polling_lock:
                    if cmd.id not in _log_polling_tasks:
                        poll_thread = threading.Thread(
                            target=CommandQueue._poll_command_log,
                            args=(cmd.id, agent),
                            daemon=True
                        )
                        poll_thread.start()
                        _log_polling_tasks[cmd.id] = {
                            'thread': poll_thread,
                            'offset': 0,
                            'stop': False
                        }
                        logger.info(f'[CommandQueue] 已启动日志轮询任务: command_id={cmd.id}')
                
                logger.info(f'[CommandQueue] 命令已通过HTTP API启动: command_id={cmd.id}')
                return cmd
            else:
                logger.warning(f'[CommandQueue] Agent HTTP服务拒绝命令: {result}')
                cmd.status = 'failed'
                cmd.error = f'Agent拒绝命令: {result.get("error", "未知错误")}'
                cmd.completed_at = timezone.now()
                cmd.save()
                return cmd
                
        except requests.exceptions.SSLError as e:
            logger.error(f'[CommandQueue] SSL错误: {e}', exc_info=True)
            cmd.status = 'failed'
            cmd.error = f'SSL连接错误: {str(e)}'
            cmd.completed_at = timezone.now()
            cmd.save()
            return cmd
        except requests.exceptions.ConnectionError as e:
            logger.warning(f'[CommandQueue] 无法连接到Agent HTTP服务: {e}')
            # 连接失败，命令将等待Agent轮询
            cmd.status = 'pending'
            cmd.save()
            return cmd
        except requests.exceptions.Timeout as e:
            logger.warning(f'[CommandQueue] 连接Agent HTTP服务超时: {e}')
            cmd.status = 'failed'
            cmd.error = f'连接超时: {str(e)}'
            cmd.completed_at = timezone.now()
            cmd.save()
            return cmd
        except Exception as e:
            logger.error(f'[CommandQueue] 推送到Agent HTTP服务失败: {e}', exc_info=True)
            # 推送失败，命令将等待Agent轮询
            cmd.status = 'pending'
            cmd.save()
            return cmd

        return cmd
    
    @staticmethod
    def get_pending_commands(agent: Agent):
        """获取待执行的命令"""
        commands = AgentCommand.objects.filter(
            agent=agent,
            status='pending'
        ).order_by('created_at')[:10]  # 每次最多返回10个命令

        logger.info(f'[CommandQueue] Agent {agent.id} 查询到 {commands.count()} 条pending命令')

        result = []
        for cmd in commands:
            logger.info(f'[CommandQueue] 命令 {cmd.id} 从pending转为running: {cmd.command} {cmd.args}')

            # 标记为执行中
            cmd.status = 'running'
            cmd.started_at = timezone.now()
            cmd.save()

            result.append({
                'id': cmd.id,
                'command': cmd.command,
                'args': cmd.args if cmd.args else [],
                'timeout': cmd.timeout
            })

        return result
    
    @staticmethod
    def update_command_result(command_id: int, success: bool = None, result: str = None, error: str = None, append: bool = False):
        """
        更新命令执行结果
        
        Args:
            command_id: 命令ID
            success: 是否成功
            result: 执行结果
            error: 错误信息
            append: 是否追加到现有结果（用于实时上报）
        """
        try:
            cmd = AgentCommand.objects.get(id=command_id)
            if append:
                # 增量更新：追加到现有结果
                if result:
                    cmd.result = (cmd.result or '') + result
                if error:
                    cmd.error = (cmd.error or '') + error
            else:
                # 最终结果：替换
                if success is not None:
                    cmd.status = 'success' if success else 'failed'
                if result is not None:
                    cmd.result = result
                if error is not None:
                    cmd.error = error
                if success is not None:
                    cmd.completed_at = timezone.now()
            cmd.save()
        except AgentCommand.DoesNotExist:
            pass
