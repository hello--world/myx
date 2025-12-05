"""
部署任务监控模块
使用全局调度器定期检查所有运行中的部署任务
"""
import os
import time
import logging
from django.utils import timezone
from .models import Deployment
from apps.agents.models import Agent, AgentCommand
from apps.logs.utils import create_log_entry

logger = logging.getLogger(__name__)


def check_running_deployments():
    """检查所有运行中的部署任务"""
    from datetime import timedelta
    
    # 获取所有运行中的部署任务
    running_deployments = Deployment.objects.filter(status='running')
    
    # 超时阈值：30分钟（1800秒）
    timeout_threshold = timedelta(minutes=30)
    current_time = timezone.now()
    
    for deployment in running_deployments:
        try:
            # 首先检查是否超时
            timeout_occurred = False
            timeout_duration = None
            
            # 如果有开始时间，检查是否超过阈值
            if deployment.started_at:
                elapsed_time = current_time - deployment.started_at
                if elapsed_time > timeout_threshold:
                    timeout_occurred = True
                    timeout_duration = elapsed_time
            # 如果没有开始时间，但创建时间超过阈值，也认为超时
            elif deployment.created_at:
                elapsed_time = current_time - deployment.created_at
                if elapsed_time > timeout_threshold:
                    timeout_occurred = True
                    timeout_duration = elapsed_time
            
            if timeout_occurred:
                # 标记为超时失败
                hours = int(timeout_duration.total_seconds() // 3600)
                minutes = int((timeout_duration.total_seconds() % 3600) // 60)
                timeout_message = f'部署任务超时（运行时间: {hours}小时{minutes}分钟，超过30分钟阈值）'
                
                logger.warning(f'部署任务超时: deployment_id={deployment.id}, 运行时间={timeout_duration}')
                
                deployment.status = 'timeout'
                deployment.error_message = timeout_message
                deployment.completed_at = current_time
                deployment.log = (deployment.log or '') + f"\n[超时] {timeout_message}\n"
                deployment.save()
                
                # 记录超时日志
                create_log_entry(
                    log_type='deployment',
                    level='error',
                    title=f'部署任务超时: {deployment.name}',
                    content=f'部署任务 {deployment.name} 运行超过30分钟，已自动标记为超时',
                    user=deployment.created_by,
                    server=deployment.server,
                    related_id=deployment.id,
                    related_type='deployment'
                )
                continue
            
            # 如果没有超时，继续正常检查
            _check_deployment(deployment)
        except Exception as e:
            logger.error(f'检查部署任务 {deployment.id} 失败: {str(e)}', exc_info=True)


def _check_deployment(deployment: Deployment):
    """检查单个部署任务"""
    # 对于非Agent类型的部署任务，只检查超时（不检查完成状态）
    if deployment.deployment_type != 'agent':
        # 非Agent类型的部署任务由其他机制处理，这里只做超时检查
        # 超时检查已在 check_running_deployments 中完成
        return
    
    # 只处理通过Agent方式执行的部署任务（connection_method='agent'）
    # SSH方式执行的部署任务由其他机制处理，不需要查找AgentCommand
    if deployment.connection_method != 'agent':
        logger.debug(f'部署任务 {deployment.id} 使用 {deployment.connection_method} 方式，跳过Agent命令监控')
        return
    
    # 获取服务器和Agent
    server = deployment.server
    try:
        agent = Agent.objects.get(server=server)
    except Agent.DoesNotExist:
        logger.debug(f'部署任务 {deployment.id} 的服务器没有Agent')
        return
    
    # 确定日志文件路径（Agent升级使用agent_upgrade前缀）
    log_file_path = f'/tmp/agent_upgrade_{deployment.id}.log'
    
    # 查找相关的命令（通过服务器和Agent查找最近的命令）
    # 查找最近1小时内创建的、与这个部署任务相关的命令
    # 通过命令内容（包含 deployment.id）来匹配
    from datetime import timedelta
    recent_time = timezone.now() - timedelta(hours=1)
    recent_commands = AgentCommand.objects.filter(
        agent=agent,
        created_at__gte=recent_time,
        status__in=['running', 'success', 'failed']
    ).order_by('-created_at')
    
    # 尝试通过命令内容匹配（包含 deployment.id 的命令）
    command = None
    for cmd in recent_commands:
        # 检查命令参数中是否包含 deployment.id（在脚本文件路径或日志文件路径中）
        if cmd.args and any(str(deployment.id) in str(arg) for arg in cmd.args):
            command = cmd
            break
    
    # 如果没找到，使用最近的命令（作为后备）
    if not command and recent_commands:
        command = recent_commands[0]
    
    # 从命令结果读取日志（只显示有用的信息，过滤掉"日志文件尚未创建"等提示）
    if command and command.status in ['success', 'failed']:
        if command.result:
            # 检查是否已经添加过这个日志（避免重复）
            result_preview = command.result[:100] if len(command.result) > 100 else command.result
            if f"[命令结果-{command.id}]" not in (deployment.log or ''):
                # 解码base64内容
                from apps.logs.utils import format_log_content
                formatted_result = format_log_content(command.result, decode_base64=True)
                
                # 过滤掉"日志文件尚未创建"等提示信息（这些信息不是实际的命令输出）
                if formatted_result and '[信息] 日志文件尚未创建' not in formatted_result:
                    # 检查命令结果是否只是systemd-run的输出（通常是服务名称）
                    # 如果是，不显示在部署日志中（因为实际日志在日志文件中）
                    lines = formatted_result.strip().split('\n')
                    if len(lines) == 1 and ('myx-agent-redeploy' in lines[0] or lines[0].isdigit()):
                        # 这可能是systemd-run的输出（服务名称或退出码），不显示
                        logger.debug(f'命令结果只是systemd-run输出，跳过显示: {formatted_result}')
                    else:
                        deployment.log = (deployment.log or '') + f"\n[命令结果-{command.id}]\n{formatted_result}\n"
                        deployment.save()
        if command.error:
            if f"[命令错误-{command.id}]" not in (deployment.log or ''):
                # 解码base64内容
                from apps.logs.utils import format_log_content
                formatted_error = format_log_content(command.error, decode_base64=True)
                deployment.log = (deployment.log or '') + f"\n[命令错误-{command.id}]\n{formatted_error}\n"
                deployment.save()
    
    # 尝试通过Agent读取日志文件（优先读取日志文件，因为实际日志在那里）
    log_content = None
    
    # 无论命令是否完成，都尝试读取日志文件（因为systemd-run的输出只是服务名称，实际日志在文件中）
    if command:
        log_content = _read_log_file_via_agent(agent, log_file_path, deployment)
        
        # 如果日志文件读取失败，且命令已完成，则从命令结果获取
        if not log_content and command.status in ['success', 'failed']:
            if command.result:
                log_content = command.result
            elif command.error:
                log_content = command.error
    
    # 检查脚本是否完成
    if log_content or command:
        script_completed, script_success = _check_completion(log_content or '', command)
        
        if script_completed:
            _handle_completion(deployment, agent, script_success, log_content, command)
        elif log_content:
            # 即使未完成，也更新日志内容
            # 直接更新整个日志内容（因为日志文件本身是完整的，包含所有历史记录）
            if log_content.strip():
                current_log = deployment.log or ''
                # 如果新日志和当前日志不同，就更新（可能是日志文件有新内容）
                if log_content != current_log:
                    # 解码base64内容
                    from apps.logs.utils import format_log_content
                    formatted_log = format_log_content(log_content, decode_base64=True)
                    deployment.log = formatted_log
                    deployment.save()
                    logger.debug(f'更新部署任务日志: deployment_id={deployment.id}, 新日志长度={len(log_content)}, 旧日志长度={len(current_log)}')


def _check_completion(log_content: str, command: AgentCommand = None):
    """检查脚本是否完成，返回(是否完成, 是否成功)"""
    # 从日志内容检查
    if log_content:
        success_markers = [
            '[完成] Agent重新部署成功',
            '[完成] Agent重新部署成功，服务运行正常'
        ]
        for marker in success_markers:
            if marker in log_content:
                return True, True
        
        if '[错误]' in log_content and ('exit 1' in log_content or 'exit 1' in log_content[-100:]):
            return True, False
    
    # 从命令结果检查
    if command and command.status in ['success', 'failed']:
        if command.status == 'success' and command.result:
            if '[完成] Agent重新部署成功' in command.result or 'Agent重新部署成功，服务运行正常' in command.result:
                return True, True
            elif '[错误]' in command.result:
                return True, False
        elif command.status == 'failed':
            return True, False
    
    return False, False


def _handle_completion(deployment: Deployment, agent: Agent, script_success: bool, log_content: str = None, command: AgentCommand = None):
    """处理脚本完成"""
    # 等待一下，确保所有日志都已写入
    time.sleep(2)
    
    # 读取完整日志
    if log_content:
        # 解码base64内容
        from apps.logs.utils import format_log_content
        formatted_log = format_log_content(log_content, decode_base64=True)
        deployment.log = (deployment.log or '') + f"\n=== 完整执行日志 ===\n{formatted_log}\n"
    elif command and command.result:
        # 解码base64内容
        from apps.logs.utils import format_log_content
        formatted_result = format_log_content(command.result, decode_base64=True)
        deployment.log = (deployment.log or '') + f"\n=== 命令执行结果 ===\n{formatted_result}\n"
    
    if script_success:
        # 测试Agent是否在线
        agent_online = _test_agent_online(agent, deployment)
        
        if agent_online:
            deployment.status = 'success'
            deployment.log = (deployment.log or '') + f"\n[完成] Agent重新部署成功，服务运行正常\n"
            
            # 自动配置 Agent 域名（如果服务器还没有域名）
            try:
                from apps.servers.server_domain_utils import auto_setup_server_agent_domain
                result = auto_setup_server_agent_domain(
                    server=deployment.server,
                    auto_setup=True
                )
                if result.get('success'):
                    domain = result.get('domain')
                    deployment.log = (deployment.log or '') + f"\n[域名] Agent 域名自动配置成功: {domain}\n"
                    logger.info(f'Agent 域名自动配置成功: server_id={deployment.server.id}, domain={domain}')
                elif not result.get('skipped'):
                    # 配置失败但不影响部署成功状态
                    error_msg = result.get('error', '未知错误')
                    deployment.log = (deployment.log or '') + f"\n[域名] Agent 域名自动配置失败: {error_msg}\n"
                    logger.warning(f'Agent 域名自动配置失败: server_id={deployment.server.id}, error={error_msg}')
            except Exception as e:
                # 域名配置失败不影响部署成功状态
                logger.warning(f'Agent 域名自动配置时出错: {str(e)}', exc_info=True)
                deployment.log = (deployment.log or '') + f"\n[域名] Agent 域名自动配置时出错: {str(e)}\n"
            
            # 记录部署成功日志
            create_log_entry(
                log_type='deployment',
                level='success',
                title=f'部署任务成功: {deployment.name}',
                content=f'部署任务 {deployment.name} 执行成功',
                user=deployment.created_by,
                server=deployment.server,
                related_id=deployment.id,
                related_type='deployment'
            )
        else:
            # 即使测试失败，如果脚本成功执行，也标记为成功
            deployment.status = 'success'
            deployment.log = (deployment.log or '') + f"\n[完成] Agent重新部署成功，但Agent尚未重新注册（可能需要等待）\n"
            # 记录部署成功日志（但Agent未重新注册）
            create_log_entry(
                log_type='deployment',
                level='warning',
                title=f'部署任务完成（Agent未重新注册）: {deployment.name}',
                content=f'部署任务 {deployment.name} 执行成功，但Agent尚未重新注册',
                user=deployment.created_by,
                server=deployment.server,
                related_id=deployment.id,
                related_type='deployment'
            )
    else:
        deployment.status = 'failed'
        agent.refresh_from_db()
        if agent.status != 'online':
            deployment.error_message = 'Agent重新部署后未正常上线'
        else:
            deployment.error_message = '脚本执行失败'
        # 记录部署失败日志
        create_log_entry(
            log_type='deployment',
            level='error',
            title=f'部署任务失败: {deployment.name}',
            content=f'部署任务 {deployment.name} 执行失败：{deployment.error_message}',
            user=deployment.created_by,
            server=deployment.server,
            related_id=deployment.id,
            related_type='deployment'
        )
    
    deployment.completed_at = timezone.now()
    deployment.save()
    logger.info(f'部署任务已更新为完成状态: deployment_id={deployment.id}, status={deployment.status}, Agent状态={agent.status}')


def _read_log_file_via_agent(agent: Agent, log_file_path: str, deployment: Deployment) -> str:
    """通过Agent读取日志文件"""
    try:
        from apps.agents.command_queue import CommandQueue
        # 先检查文件是否存在，然后再读取
        # 使用bash命令：先检查文件是否存在，如果存在则读取，否则返回空
        check_and_read_cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'if [ -f "{log_file_path}" ]; then cat "{log_file_path}"; else echo ""; fi'],
            timeout=10
        )
        
        # 等待命令执行（最多等待10秒，因为可能需要等待脚本写入日志）
        for i in range(10):
            time.sleep(1)
            check_and_read_cmd.refresh_from_db()
            if check_and_read_cmd.status in ['success', 'failed']:
                if check_and_read_cmd.status == 'success' and check_and_read_cmd.result:
                    # 解码base64内容
                    from apps.logs.utils import format_log_content
                    log_content = format_log_content(check_and_read_cmd.result, decode_base64=True)
                    # 如果日志文件不存在或为空，返回None（不记录到部署日志中）
                    if not log_content or not log_content.strip():
                        logger.debug(f'日志文件不存在或为空: {log_file_path}')
                        return None
                    logger.debug(f'成功读取日志文件: {log_file_path}, 长度: {len(log_content)}')
                    return log_content
                elif check_and_read_cmd.status == 'failed':
                    # 如果命令失败，可能是文件不存在，这是正常的
                    logger.debug(f'读取日志文件失败（可能文件不存在）: {log_file_path}')
                    break
            # 如果命令还在运行，继续等待
        else:
            # 超时
            logger.debug(f'读取日志文件超时: {log_file_path}')
    except Exception as e:
        logger.debug(f'通过Agent读取日志文件异常: {str(e)}')
    
    return None


def _test_agent_online(agent: Agent, deployment: Deployment) -> bool:
    """测试Agent是否在线"""
    deployment.log = (deployment.log or '') + f"\n[测试] 正在测试Agent是否在线...\n"
    deployment.save()
    
    # 等待几秒让Agent有时间重新注册
    time.sleep(5)
    
    # 刷新Agent状态
    agent.refresh_from_db()
    
    # 尝试发送测试命令
    try:
        from apps.agents.command_queue import CommandQueue
        test_cmd = CommandQueue.add_command(
            agent=agent,
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
                    deployment.log = (deployment.log or '') + f"\n[测试] Agent测试命令执行成功，确认Agent在线\n"
                    return True
                else:
                    deployment.log = (deployment.log or '') + f"\n[测试] Agent测试命令执行失败: {test_cmd.error or '未知错误'}\n"
                    break
    except Exception as e:
        logger.warning(f'发送Agent测试命令失败: {str(e)}')
        deployment.log = (deployment.log or '') + f"\n[测试] 发送测试命令失败: {str(e)}，使用数据库状态判断\n"
    
    # 再次刷新Agent状态
    agent.refresh_from_db()
    return agent.status == 'online'

