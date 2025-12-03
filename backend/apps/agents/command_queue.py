"""
Agent命令队列管理
支持三种模式：
1. JSON-RPC模式（优先）：后端主动推送命令到Agent JSON-RPC服务
2. Web服务模式：后端主动推送命令到Agent Web服务（旧架构）
3. 传统模式：Agent轮询获取命令
"""
from django.utils import timezone
from .models import Agent, AgentCommand
from .client import get_agent_client
from .rpc_client import get_agent_rpc_client
from .rpc_support import check_agent_rpc_support as _check_agent_rpc_support
import logging
import threading
import time

logger = logging.getLogger(__name__)

# 日志轮询任务字典：{command_id: {'thread': Thread, 'offset': int, 'stop': bool}}
_log_polling_tasks = {}
_log_polling_lock = threading.Lock()


class CommandQueue:
    """命令队列管理器"""
    
    @staticmethod
    def _poll_command_log(command_id: int, agent: Agent, rpc_client):
        """
        轮询命令日志（后台任务）
        
        Args:
            command_id: 命令ID
            agent: Agent实例
            rpc_client: RPC客户端实例
        """
        offset = 0
        max_poll_time = 3600  # 最多轮询1小时
        start_time = time.time()
        poll_interval = 1  # 每1秒轮询一次
        
        logger.info(f'[CommandQueue] 开始轮询命令日志: command_id={command_id}')
        
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
                
                # 获取增量日志
                log_result = rpc_client.get_command_log(command_id, offset)
                
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
                            stderr = final_result.get('stderr', '') or final_result.get('error', '')
                            return_code = final_result.get('return_code', -1)
                            
                            CommandQueue.update_command_result(
                                command_id,
                                success,
                                stdout,
                                stderr,
                                append=False
                            )
                            
                            # 注意：AgentCommand 模型没有 exit_code 字段
                            # 退出码信息可以通过 result 或 error 字段记录
                            
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
        """添加命令到队列或直接推送到Agent JSON-RPC服务"""
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

        # 所有 Agent 都必须支持 RPC，直接使用 RPC
        if agent.rpc_port:
            try:
                rpc_client = get_agent_rpc_client(agent)
                if rpc_client:
                    # 检查Agent是否在线
                    if rpc_client.health_check():
                        # 立即调用 execute_command（异步执行，立即返回）
                        result = rpc_client.execute_command(
                            command=command,
                            args=args,
                            timeout=timeout,
                            command_id=cmd.id
                        )
                        
                        # 命令已启动（异步执行）
                        if result.get('status') == 'running' or result.get('command_id'):
                            cmd.started_at = timezone.now()
                            cmd.save()
                            
                            # 启动日志轮询任务（每1秒获取一次日志）
                            with _log_polling_lock:
                                if cmd.id not in _log_polling_tasks:
                                    poll_thread = threading.Thread(
                                        target=CommandQueue._poll_command_log,
                                        args=(cmd.id, agent, rpc_client),
                                        daemon=True
                                    )
                                    poll_thread.start()
                                    _log_polling_tasks[cmd.id] = {
                                        'thread': poll_thread,
                                        'offset': 0,
                                        'stop': False
                                    }
                                    logger.info(f'[CommandQueue] 已启动日志轮询任务: command_id={cmd.id}')
                            
                            # 更新最后成功时间
                            from django.utils import timezone as tz
                            agent.rpc_last_success = tz.now()
                            agent.save(update_fields=['rpc_last_success'])
                            logger.info(f'[CommandQueue] 命令已通过JSON-RPC启动: command_id={cmd.id}')
                            return cmd
                        # 向后兼容：如果返回最终结果（同步执行）
                        elif result.get('success') is not None:
                            cmd.status = 'success' if result.get('success') else 'failed'
                            cmd.started_at = timezone.now()
                            cmd.completed_at = timezone.now()
                            cmd.result = result.get('stdout', '')
                            cmd.error = result.get('stderr') or result.get('error', '')
                            cmd.save()
                            logger.info(f'[CommandQueue] 命令已通过JSON-RPC执行完成: command_id={cmd.id}, success={result.get("success")}')
                            return cmd
                        else:
                            logger.warning(f'[CommandQueue] Agent JSON-RPC服务执行命令失败: {result}')
                    else:
                        logger.warning(f'[CommandQueue] Agent JSON-RPC服务不可用')
                        # RPC 不可用，触发重新安装
                        cmd.status = 'failed'
                        cmd.error = 'Agent RPC service not available, triggering reinstall'
                        cmd.completed_at = timezone.now()
                        cmd.save()
                        # TODO: 触发 Agent 重新安装
            except Exception as e:
                logger.error(f'[CommandQueue] 推送到Agent JSON-RPC服务失败: {e}', exc_info=True)
                # RPC 连接失败，触发重新安装
                cmd.status = 'failed'
                cmd.error = f'RPC connection failed: {str(e)}, triggering reinstall'
                cmd.completed_at = timezone.now()
                cmd.save()
                # TODO: 触发 Agent 重新安装
        
        # 回退到Web服务模式（旧架构）
        if agent.web_service_enabled:
            try:
                client = get_agent_client(agent)
                if client:
                    # 检查Agent是否在线
                    if client.health_check():
                        # 直接推送到Agent Web服务
                        result = client.execute_command(
                            command=command,
                            args=args,
                            timeout=timeout,
                            command_id=cmd.id
                        )
                        if result.get('status') == 'accepted':
                            # 命令已被Agent接受，标记为执行中
                            cmd.status = 'running'
                            cmd.started_at = timezone.now()
                            cmd.save()
                            logger.info(f'[CommandQueue] 命令已推送到Agent Web服务: command_id={cmd.id}')
                            return cmd
                        else:
                            logger.warning(f'[CommandQueue] Agent Web服务拒绝命令: {result}')
                    else:
                        logger.warning(f'[CommandQueue] Agent Web服务不可用，命令将等待Agent轮询')
            except Exception as e:
                logger.warning(f'[CommandQueue] 推送到Agent Web服务失败，将使用传统模式: {e}')

        return cmd
    
    @staticmethod
    def get_pending_commands(agent: Agent):
        """获取待执行的命令"""
        import logging
        logger = logging.getLogger(__name__)

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
    def update_command_result(command_id: int, success: bool, result: str = None, error: str = None, append: bool = False):
        """更新命令执行结果
        
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

