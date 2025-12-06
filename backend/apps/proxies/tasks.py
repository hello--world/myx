import threading
import time
from django.utils import timezone
from .models import Proxy
from apps.logs.utils import create_log_entry
from apps.servers.models import Server
from apps.agents.models import Agent
from apps.deployments.tasks import install_agent_via_ssh, wait_for_agent_startup
from apps.deployments.agent_deployer import deploy_via_agent
from apps.deployments.models import Deployment


# 服务安装状态缓存（避免频繁检测）
# 格式: {(agent_id, service_name): (is_installed, timestamp)}
_service_install_cache = {}
_cache_ttl = 60  # 缓存60秒


def clear_service_cache(agent_id: int = None, service_name: str = None):
    """清除服务检测缓存

    Args:
        agent_id: Agent ID，如果为None则清除所有Agent的缓存
        service_name: 服务名称，如果为None则清除所有服务的缓存
    """
    global _service_install_cache

    if agent_id is None and service_name is None:
        # 清除所有缓存
        _service_install_cache.clear()
        print("已清除所有服务检测缓存")
    elif agent_id is not None and service_name is not None:
        # 清除指定Agent和服务的缓存
        cache_key = (agent_id, service_name)
        if cache_key in _service_install_cache:
            del _service_install_cache[cache_key]
            print(f"已清除 Agent {agent_id} 的 {service_name} 缓存")
    elif agent_id is not None:
        # 清除指定Agent的所有服务缓存
        keys_to_remove = [key for key in _service_install_cache.keys() if key[0] == agent_id]
        for key in keys_to_remove:
            del _service_install_cache[key]
        print(f"已清除 Agent {agent_id} 的所有服务缓存")
    elif service_name is not None:
        # 清除所有Agent的指定服务缓存
        keys_to_remove = [key for key in _service_install_cache.keys() if key[1] == service_name]
        for key in keys_to_remove:
            del _service_install_cache[key]
        print(f"已清除所有 Agent 的 {service_name} 缓存")


def check_service_installed(agent: Agent, service_name: str, force_check: bool = False, deployment_target: str = 'host') -> bool:
    """检查服务是否已安装

    Args:
        agent: Agent对象
        service_name: 服务名称 ('xray' 或 'caddy')
        force_check: 是否强制检查（忽略缓存）
        deployment_target: 部署目标 ('host' 或 'docker')，默认为 'host'

    Returns:
        bool: 是否已安装
    """
    import time as time_module
    from apps.agents.command_queue import CommandQueue
    from apps.agents.utils import AGENT_DEPLOYMENT_TOOL_DIR
    
    cache_key = (agent.id, service_name)
    current_time = time_module.time()
    
    # 如果不是强制检查，且缓存有效，直接返回缓存结果
    if not force_check and cache_key in _service_install_cache:
        is_installed, cached_time = _service_install_cache[cache_key]
        if current_time - cached_time < _cache_ttl:
            print(f"使用缓存: {service_name} 在 Agent {agent.id} 上{'已安装' if is_installed else '未安装'}（缓存时间: {int(current_time - cached_time)}秒前）")
            return is_installed
    
    # 检查 Agent 是否在线
    agent.refresh_from_db()
    if agent.status != 'online':
        print(f"Agent {agent.id} 不在线，状态: {agent.status}")
        return False
    
    # 使用check_service.yml playbook
    playbook_path = f"{AGENT_DEPLOYMENT_TOOL_DIR}/playbooks/check_service.yml"
    inventory_path = f"{AGENT_DEPLOYMENT_TOOL_DIR}/inventory/localhost.ini"
    
    # 构建extra_vars JSON
    import json
    extra_vars = {
        'service_name': service_name,
        'deployment_target': deployment_target
    }
    extra_vars_json = json.dumps(extra_vars, ensure_ascii=False)

    # 提前导入 format_log_content，避免在不同分支中重复导入
    from apps.logs.utils import format_log_content

    try:
        # 执行ansible-playbook命令
        cmd = CommandQueue.add_command(
            agent=agent,
            command='ansible-playbook',
            args=[
                '-i', inventory_path,
                playbook_path,
                '-e', extra_vars_json
            ],
            timeout=30  # playbook执行可能需要稍长时间
        )

        # 调试：立即验证命令是否成功创建
        print(f"[调试] 创建检测命令 - ID: {cmd.id}, Agent: {agent.id}, 状态: {cmd.status}, 服务: {service_name}")
        cmd.refresh_from_db()
        print(f"[调试] 命令创建后立即刷新 - 状态: {cmd.status}, 创建时间: {cmd.created_at}")

        # 验证命令是否在队列中
        from apps.agents.models import AgentCommand
        pending_count = AgentCommand.objects.filter(agent=agent, status='pending').count()
        print(f"[调试] Agent {agent.id} 当前待处理命令数: {pending_count}")

        # 等待命令执行完成
        # 优化后的等待时间：
        # - 如果Agent刚发送心跳，会在下次心跳时立即轮询（最多30-300秒，但部署时会加速到1-3秒）
        # - 如果Agent刚轮询完，会在下次轮询时获取（部署时1-3秒，正常时5-60秒）
        # - 命令执行时间：15秒
        # 为了兼容正常情况，保留较长的等待时间，但部署时通常会在几秒内完成
        max_wait = 90  # 保留足够时间，但部署时通常几秒内完成
        wait_time = 0
        last_status = cmd.status
        while wait_time < max_wait:
            cmd.refresh_from_db()
            agent.refresh_from_db()

            # 每10秒输出一次等待状态
            if wait_time > 0 and wait_time % 10 == 0:
                # 检查Agent状态和最后心跳
                time_since_heartbeat = (timezone.now() - agent.last_heartbeat).total_seconds() if agent.last_heartbeat else None
                heartbeat_info = f", 最后心跳: {int(time_since_heartbeat)}秒前" if time_since_heartbeat else ", 无心跳记录"
                print(f"[调试] 等待 {wait_time}秒 - 命令ID: {cmd.id}, 状态: {cmd.status}, Agent状态: {agent.status}{heartbeat_info}")

            # 状态变化时输出
            if cmd.status != last_status:
                print(f"[调试] 命令状态变化: {last_status} -> {cmd.status}")
                last_status = cmd.status

            # 如果命令还在pending状态，检查Agent是否在线
            if cmd.status == 'pending':
                if agent.status != 'online':
                    print(f"[警告] Agent不在线，状态: {agent.status}，命令可能无法执行")
                # 检查最后心跳时间，如果超过2分钟没有心跳，可能Agent有问题
                if agent.last_heartbeat:
                    time_since_heartbeat = (timezone.now() - agent.last_heartbeat).total_seconds()
                    if time_since_heartbeat > 120:
                        print(f"[警告] Agent最后心跳时间过长: {int(time_since_heartbeat)}秒前，可能连接有问题")

            if cmd.status in ['success', 'failed']:
                break
            time_module.sleep(0.5)  # 缩短轮询间隔
            wait_time += 0.5

        if wait_time >= max_wait:
            cmd.refresh_from_db()
            agent.refresh_from_db()
            time_since_heartbeat = (timezone.now() - agent.last_heartbeat).total_seconds() if agent.last_heartbeat else None
            heartbeat_info = f", Agent最后心跳: {int(time_since_heartbeat)}秒前" if time_since_heartbeat else ", Agent无心跳记录"
            print(f"检查 {service_name} 超时，命令状态: {cmd.status}, 命令ID: {cmd.id}, 已等待: {wait_time}秒{heartbeat_info}")
            # 超时时也检查命令结果（可能命令已执行但未及时更新状态）
            if cmd.result:
                # 解码base64内容
                decoded_result = format_log_content(cmd.result, decode_base64=True)
                if 'INSTALLED' in decoded_result:
                    print(f"检查 {service_name}: 已安装（超时但检测到INSTALLED）")
                    # 更新缓存
                    _service_install_cache[cache_key] = (True, current_time)
                    return True

            # 如果超时且没有结果，使用降级检测
            print(f"检测超时且无结果，使用降级方式检测 {service_name}")

            # 降级检测
            if service_name == 'xray':
                check_paths = '/usr/local/bin/xray /usr/bin/xray'
            elif service_name == 'caddy':
                check_paths = '/usr/bin/caddy /usr/local/bin/caddy /opt/caddy/caddy'
            else:
                check_paths = f'/usr/local/bin/{service_name} /usr/bin/{service_name}'

            fallback_cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', f'for p in {check_paths}; do if [ -x "$p" ]; then echo "INSTALLED:$p"; exit 0; fi; done; echo "NOT_INSTALLED"'],
                timeout=10
            )

            print(f"[调试] 创建降级命令 - ID: {fallback_cmd.id}, 状态: {fallback_cmd.status}")

            # 等待降级命令（增加等待时间，因为队列可能繁忙）
            # 降级检测也需要等待Agent轮询，所以也需要足够的时间
            fallback_wait = 0
            max_fallback_wait = 85  # 与主检测相同的等待时间
            while fallback_wait < max_fallback_wait:
                time_module.sleep(0.5)
                fallback_wait += 0.5
                fallback_cmd.refresh_from_db()
                agent.refresh_from_db()

                # 每10秒输出一次
                if fallback_wait > 0 and fallback_wait % 10 == 0:
                    time_since_heartbeat = (timezone.now() - agent.last_heartbeat).total_seconds() if agent.last_heartbeat else None
                    heartbeat_info = f", Agent最后心跳: {int(time_since_heartbeat)}秒前" if time_since_heartbeat else ", Agent无心跳记录"
                    print(f"[调试] 降级命令等待 {fallback_wait}秒 - 状态: {fallback_cmd.status}{heartbeat_info}")

                if fallback_cmd.status in ['success', 'failed']:
                    break

            if fallback_cmd.status == 'success' and fallback_cmd.result:
                fallback_result = format_log_content(fallback_cmd.result, decode_base64=True)
                print(f"[调试] 超时后降级检测结果: {repr(fallback_result)}")
                if 'INSTALLED:' in fallback_result:
                    detected_path = fallback_result.split('INSTALLED:')[1].strip().split('\n')[0]
                    print(f"检查 {service_name}: 已安装（超时后降级检测，路径: {detected_path}）")
                    _service_install_cache[cache_key] = (True, current_time)
                    return True

            print(f"检查 {service_name}: 超时且降级检测也失败，假设未安装")
            return False
        
        # 检查命令执行结果（需要先解码base64）
        decoded_result = format_log_content(cmd.result or '', decode_base64=True)
        decoded_error = format_log_content(cmd.error or '', decode_base64=True)

        # 调试：打印原始结果
        print(f"[调试] {service_name} 检测命令状态: {cmd.status}")
        print(f"[调试] {service_name} 原始结果: {repr(cmd.result[:200] if cmd.result else None)}")
        print(f"[调试] {service_name} 解码结果: {repr(decoded_result[:200] if decoded_result else None)}")

        is_installed = False
        if cmd.status == 'success':
            if decoded_result and 'INSTALLED' in decoded_result:
                print(f"检查 {service_name}: 已安装 - {decoded_result.strip()}")
                is_installed = True
            else:
                print(f"检查 {service_name}: 未安装")
                print(f"命令输出: {decoded_result[:200] if decoded_result else 'None'}")
                # 即使返回未安装，也尝试降级检测
                print(f"检测脚本返回未安装，使用降级方式再次检测 {service_name}")

                # 降级检测
                if service_name == 'xray':
                    check_paths = '/usr/local/bin/xray /usr/bin/xray'
                elif service_name == 'caddy':
                    check_paths = '/usr/bin/caddy /usr/local/bin/caddy /opt/caddy/caddy'
                else:
                    check_paths = f'/usr/local/bin/{service_name} /usr/bin/{service_name}'

                fallback_cmd = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'for p in {check_paths}; do if [ -x "$p" ]; then echo "INSTALLED:$p"; exit 0; fi; done; echo "NOT_INSTALLED"'],
                    timeout=10
                )
                # 等待降级命令执行（需要足够时间等待Agent轮询）
                fallback_wait = 0
                max_fallback_wait = 85
                while fallback_wait < max_fallback_wait:
                    time_module.sleep(0.5)
                    fallback_wait += 0.5
                    fallback_cmd.refresh_from_db()
                    if fallback_cmd.status in ['success', 'failed']:
                        break

                if fallback_cmd.status == 'success' and fallback_cmd.result:
                    fallback_result = format_log_content(fallback_cmd.result, decode_base64=True)
                    print(f"[调试] 降级检测结果: {repr(fallback_result)}")
                    if 'INSTALLED:' in fallback_result:
                        detected_path = fallback_result.split('INSTALLED:')[1].strip().split('\n')[0]
                        print(f"检查 {service_name}: 已安装（降级检测，路径: {detected_path}）")
                        is_installed = True
                    else:
                        print(f"检查 {service_name}: 降级检测也返回未安装")
                        is_installed = False
                else:
                    print(f"检查 {service_name}: 降级检测失败（等待{fallback_wait}秒后状态: {fallback_cmd.status}）")
                    is_installed = False
        elif cmd.status == 'failed':
            # 打印错误信息以便调试
            print(f"检查 {service_name}: 命令执行失败")
            print(f"错误信息: {decoded_error[:500] if decoded_error else 'None'}")
            print(f"命令输出: {decoded_result[:500] if decoded_result else 'None'}")

            # 即使命令失败，也先检查结果中是否有INSTALLED
            if decoded_result and 'INSTALLED' in decoded_result:
                print(f"检查 {service_name}: 已安装 (命令失败但检测到INSTALLED)")
                is_installed = True
            else:
                # 使用降级检测方式（无论什么原因失败都尝试降级检测）
                print(f"检测脚本失败或返回未安装，使用降级方式检测 {service_name}")

                # 降级方式1：检查二进制文件是否存在
                if service_name == 'xray':
                    check_paths = '/usr/local/bin/xray /usr/bin/xray'
                elif service_name == 'caddy':
                    check_paths = '/usr/bin/caddy /usr/local/bin/caddy /opt/caddy/caddy'
                else:
                    check_paths = f'/usr/local/bin/{service_name} /usr/bin/{service_name}'

                fallback_cmd = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'for p in {check_paths}; do if [ -x "$p" ]; then echo "INSTALLED:$p"; exit 0; fi; done; echo "NOT_INSTALLED"'],
                    timeout=10
                )
                # 等待降级命令执行（需要足够时间等待Agent轮询）
                fallback_wait = 0
                max_fallback_wait = 85
                while fallback_wait < max_fallback_wait:
                    time_module.sleep(0.5)
                    fallback_wait += 0.5
                    fallback_cmd.refresh_from_db()
                    if fallback_cmd.status in ['success', 'failed']:
                        break

                if fallback_cmd.status == 'success' and fallback_cmd.result:
                    fallback_result = format_log_content(fallback_cmd.result, decode_base64=True)
                    if 'INSTALLED:' in fallback_result:
                        # 提取检测到的路径
                        detected_path = fallback_result.split('INSTALLED:')[1].strip() if 'INSTALLED:' in fallback_result else 'unknown'
                        print(f"检查 {service_name}: 已安装（降级检测，路径: {detected_path}）")
                        is_installed = True
                    else:
                        print(f"检查 {service_name}: 未安装（降级检测）")
                        is_installed = False
                else:
                    print(f"降级检测也失败（等待{fallback_wait}秒后状态: {fallback_cmd.status}），假设未安装")
                    is_installed = False

        # 更新缓存
        _service_install_cache[cache_key] = (is_installed, current_time)
        return is_installed
    except Exception as e:
        print(f"检查 {service_name} 异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def deploy_agent_and_services(server: Server, user, log_callback=None):
    """安装Agent、Xray、Caddy（支持重复安装）
    
    Args:
        server: 服务器对象
        user: 用户对象
        log_callback: 日志回调函数，用于实时更新日志
        
    Returns:
        tuple[bool, str]: (是否成功, 错误信息或日志)
    """
    error_log = []
    
    def _log(message: str):
        """记录日志并调用回调"""
        error_log.append(message)
        if log_callback:
            log_callback(message)
    try:
        # 检查是否已安装Agent
        agent = None
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                agent = None
                _log(f"Agent状态为离线，需要重新安装")
        except Agent.DoesNotExist:
            _log("未找到Agent，需要安装")
        
        # 如果Agent不存在，需要先安装Agent
        if not agent:
            # 检查是否有SSH凭证（密码或私钥），有凭证才能通过SSH安装Agent
            if server.password or server.private_key:
                _log("通过SSH安装Agent...")
                
                # 保存原始连接方式（安装Agent时需要使用SSH）
                original_connection_method = server.connection_method
                
                # 临时将连接方式设置为SSH，以便安装Agent
                if server.connection_method == 'agent':
                    server.connection_method = 'ssh'
                    server.save()
                
                # 创建部署任务用于安装Agent
                deployment = Deployment.objects.create(
                    name=f"安装Agent - {server.name}",
                    server=server,
                    deployment_type='agent',  # 使用 'agent' 类型，更明确
                    connection_method='ssh',
                    deployment_target=server.deployment_target or 'host',
                    status='running',
                    created_by=user
                )
                
                _log(f"部署任务已创建: {deployment.id}")
                
                # 安装Agent，并实时更新日志
                _log("开始安装Agent...")
                if not install_agent_via_ssh(server, deployment):
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent安装失败'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    _log(f"Agent安装失败")
                    if deployment.log:
                        _log(f"部署日志:\n{deployment.log}")
                    if deployment.error_message:
                        _log(f"错误信息: {deployment.error_message}")
                    # 如果原始连接方式为Agent但安装失败，保持为SSH
                    if original_connection_method == 'agent':
                        server.connection_method = 'ssh'
                        server.save()
                    return False, "\n".join(error_log)
                
                # 等待Agent启动，实时更新进度
                _log("等待Agent启动...")
                from apps.deployments.tasks import wait_for_agent_startup
                agent = wait_for_agent_startup(server, timeout=60, deployment=deployment)
                if not agent or not agent.rpc_port:
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent启动超时或RPC不支持'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    _log("Agent启动超时或RPC不支持（60秒）")
                    if deployment.log:
                        _log(f"部署日志:\n{deployment.log}")
                    # 如果原始连接方式为Agent但注册失败，保持为SSH
                    if original_connection_method == 'agent':
                        server.connection_method = 'ssh'
                        server.save()
                    return False, "\n".join(error_log)
                
                # 更新服务器连接方式
                # 如果原始连接方式选择为Agent，安装成功后切换为Agent
                if original_connection_method == 'agent':
                    server.connection_method = 'agent'
                else:
                    # 如果原始连接方式为SSH，保持SSH（但Agent已安装，可以随时切换）
                    server.connection_method = 'ssh'
                server.status = 'active'
                server.save()
                
                
                deployment.status = 'success'
                deployment.completed_at = timezone.now()
                deployment.save()
                _log("Agent安装并注册成功")
            else:
                # 没有SSH凭证，无法安装Agent
                _log("缺少SSH凭证（密码或私钥），无法通过SSH安装Agent")
                _log("请先在服务器管理页面添加SSH凭证，然后手动安装Agent")
                return False, "\n".join(error_log)
        
        # 确保Agent在线
        agent = Agent.objects.get(server=server)
        agent.refresh_from_db()
        if agent.status != 'online':
            _log(f"Agent状态为 {agent.status}，不在线")
            _log(f"请检查Agent是否正常运行，最后心跳时间: {agent.last_heartbeat}")
            return False, "\n".join(error_log)
        
        _log(f"Agent在线，开始部署服务... (Agent ID: {agent.id}, Token: {agent.token})")
        
        # 检查并安装Xray（支持重复安装）
        _log("检查Xray是否已安装...")
        # 强制重新检测，避免使用过期的缓存
        deployment_target = server.deployment_target or 'host'
        xray_installed = check_service_installed(agent, 'xray', force_check=True, deployment_target=deployment_target)
        _log(f"Xray检查结果: {'已安装' if xray_installed else '未安装'} (部署目标: {deployment_target})")
        if not xray_installed:
            _log("Xray未安装，开始部署...")
            xray_deployment = Deployment.objects.create(
                name=f"Xray部署 - {server.name}",
                server=server,
                deployment_type='xray',
                connection_method='agent',
                deployment_target=server.deployment_target or 'host',
                status='running',
                created_by=user
            )
            _log("开始执行Xray部署...")
            deploy_via_agent(xray_deployment, server.deployment_target or 'host')
            
            # 等待部署完成，最多等待5分钟，实时更新日志
            max_wait = 300
            wait_time = 0
            last_log_length = 0
            while wait_time < max_wait:
                xray_deployment.refresh_from_db()
                if xray_deployment.status in ['success', 'failed']:
                    break
                # 实时读取并更新部署日志
                if xray_deployment.log and len(xray_deployment.log) > last_log_length:
                    new_log = xray_deployment.log[last_log_length:]
                    _log(f"[Xray部署] {new_log}")
                    last_log_length = len(xray_deployment.log)
                time.sleep(2)
                wait_time += 2
                if wait_time % 10 == 0:
                    _log(f"等待Xray部署完成... ({wait_time}秒)")
            
            if xray_deployment.status != 'success':
                _log(f"Xray部署失败")
                if xray_deployment.log:
                    _log(f"Xray部署日志:\n{xray_deployment.log}")
                if xray_deployment.error_message:
                    _log(f"错误信息: {xray_deployment.error_message}")
                return False, "\n".join(error_log)
            _log("Xray部署成功")
            
            # 部署成功后，立即更新缓存标记为已安装
            import time as time_module
            cache_key = (agent.id, 'xray')
            _service_install_cache[cache_key] = (True, time_module.time())
            _log("已更新Xray安装状态缓存")
        else:
            _log("Xray已安装，跳过部署")
        
        # 检查并安装Caddy（支持重复安装）
        _log("检查Caddy是否已安装...")
        # 强制重新检测，避免使用过期的缓存
        # Caddy仅支持宿主机部署
        caddy_installed = check_service_installed(agent, 'caddy', force_check=True, deployment_target='host')
        _log(f"Caddy检查结果: {'已安装' if caddy_installed else '未安装'} (部署目标: host)")
        if not caddy_installed:
            _log("Caddy未安装，开始部署...")
            caddy_deployment = Deployment.objects.create(
                name=f"Caddy部署 - {server.name}",
                server=server,
                deployment_type='caddy',
                connection_method='agent',
                deployment_target='host',  # Caddy 仅支持宿主机部署
                status='running',
                created_by=user
            )
            _log("开始执行Caddy部署（宿主机）...")
            deploy_via_agent(caddy_deployment, 'host')  # 强制使用宿主机部署
            
            # 等待部署完成，最多等待5分钟，实时更新日志
            max_wait = 300
            wait_time = 0
            last_log_length = 0
            while wait_time < max_wait:
                caddy_deployment.refresh_from_db()
                if caddy_deployment.status in ['success', 'failed']:
                    break
                # 实时读取并更新部署日志
                if caddy_deployment.log and len(caddy_deployment.log) > last_log_length:
                    new_log = caddy_deployment.log[last_log_length:]
                    _log(f"[Caddy部署] {new_log}")
                    last_log_length = len(caddy_deployment.log)
                time.sleep(2)
                wait_time += 2
                if wait_time % 10 == 0:
                    _log(f"等待Caddy部署完成... ({wait_time}秒)")
            
            if caddy_deployment.status != 'success':
                _log(f"Caddy部署失败")
                if caddy_deployment.log:
                    _log(f"Caddy部署日志:\n{caddy_deployment.log}")
                if caddy_deployment.error_message:
                    _log(f"错误信息: {caddy_deployment.error_message}")
                return False, "\n".join(error_log)
            _log("Caddy部署成功")
            
            # 部署成功后，立即更新缓存标记为已安装
            import time as time_module
            cache_key = (agent.id, 'caddy')
            _service_install_cache[cache_key] = (True, time_module.time())
            _log("已更新Caddy安装状态缓存")
        else:
            _log("Caddy已安装，跳过部署")
        
        return True, "\n".join(error_log)
        
    except Exception as e:
        import traceback
        error_msg = f"部署异常: {str(e)}\n{traceback.format_exc()}"
        _log(error_msg)
        # 记录错误到日志
        print(f"deploy_agent_and_services 错误: {error_msg}")
        return False, "\n".join(error_log)


def deploy_xray_config_via_agent(proxy: Proxy) -> bool:
    """通过Agent部署Xray配置
    
    注意：Xray支持多个inbound配置，每次部署时会获取服务器上所有启用的代理，
    生成包含所有inbound的完整配置。新添加的代理会被合并到配置中，不会覆盖已有的代理。
    只需要一个Xray进程，所有代理共享同一个Xray实例。
    
    Args:
        proxy: 代理对象（当前正在部署的代理）
        
    Returns:
        bool: 是否成功
    """
    # 导入时使用别名，避免与当前函数名冲突
    from apps.deployments.agent_deployer import deploy_xray_config_via_agent as _deploy_config
    from utils.xray_config import generate_xray_config_json_for_proxies
    
    try:
        # 获取服务器上的所有启用的代理（包括当前正在部署的代理）
        # Xray支持多个inbound，所以会合并所有代理的配置，不会覆盖
        server_proxies = Proxy.objects.filter(
            server=proxy.server, 
            status='active',
            enable=True
        ).order_by('id')
        
        # 生成完整的Xray配置（包含所有代理的inbound）
        config_json = generate_xray_config_json_for_proxies(list(server_proxies))
        
        # 通过Agent部署配置（会替换整个Xray配置文件，但包含所有代理）
        success, message = _deploy_config(proxy.server, config_json)
        if not success:
            proxy.deployment_log = (proxy.deployment_log or '') + f"❌ 部署配置失败: {message}\n"
            proxy.deployment_status = 'failed'
            proxy.save()
        return success
        
    except Exception as e:
        import traceback
        error_msg = f"❌ 部署配置失败: {str(e)}\n{traceback.format_exc()}\n"
        proxy.deployment_log = (proxy.deployment_log or '') + error_msg
        proxy.deployment_status = 'failed'
        proxy.save()
        return False


def auto_deploy_proxy(proxy_id: int):
    """自动部署代理（在线程中运行）
    
    Args:
        proxy_id: 代理ID
    """
    def _deploy():
        try:
            proxy = Proxy.objects.get(id=proxy_id)
            server = proxy.server
            
            proxy.deployment_status = 'running'
            proxy.deployment_log = "🚀 开始自动部署...\n"
            proxy.save()
            
            # 步骤1: 检查并安装Agent、Xray、Caddy
            proxy.deployment_log = (proxy.deployment_log or '') + "步骤1: 检查并安装Agent、Xray、Caddy...\n"
            proxy.save()
            
            try:
                # 获取心跳模式（从Agent或默认值）
                # 在函数内部重新导入Agent，避免作用域问题
                from apps.agents.models import Agent as AgentModel
                # 实时更新日志的回调函数
                def update_log_callback(message: str):
                    """实时更新部署日志"""
                    proxy.refresh_from_db()
                    proxy.deployment_log = (proxy.deployment_log or '') + message + "\n"
                    proxy.save()
                
                result, log_message = deploy_agent_and_services(
                    server, 
                    proxy.created_by, 
                    log_callback=update_log_callback
                )
                proxy.refresh_from_db()
                proxy.deployment_log = (proxy.deployment_log or '') + log_message + "\n"
                proxy.save()
                
                if not result:
                    proxy.deployment_status = 'failed'
                    proxy.deployment_log = (proxy.deployment_log or '') + "\n❌ Agent、Xray、Caddy安装失败\n"
                    proxy.save()
                    # 记录部署失败日志
                    create_log_entry(
                        log_type='proxy',
                        level='error',
                        title=f'代理节点部署失败: {proxy.name}',
                        content=f'代理节点 {proxy.name} 部署失败：Agent、Xray、Caddy安装失败',
                        user=proxy.created_by,
                        server=proxy.server,
                        related_id=proxy.id,
                        related_type='proxy'
                    )
                    return
            except Exception as e:
                import traceback
                proxy.deployment_status = 'failed'
                proxy.deployment_log = (proxy.deployment_log or '') + f"Agent、Xray、Caddy安装异常: {str(e)}\n{traceback.format_exc()}\n"
                proxy.save()
                # 记录部署异常日志
                create_log_entry(
                    log_type='proxy',
                    level='error',
                    title=f'代理节点部署异常: {proxy.name}',
                    content=f'代理节点 {proxy.name} 部署异常：{str(e)}',
                    user=proxy.created_by,
                    server=proxy.server,
                    related_id=proxy.id,
                    related_type='proxy'
                )
                return
            
            proxy.deployment_log = (proxy.deployment_log or '') + "✅ Agent、Xray、Caddy安装成功\n"
            proxy.save()
            
            # 步骤2: 部署Xray配置
            proxy.deployment_log = (proxy.deployment_log or '') + "步骤2: 部署Xray配置...\n"
            proxy.save()
            
            success = deploy_xray_config_via_agent(proxy)
            if not success:
                proxy.deployment_status = 'failed'
                # 错误信息已经在 deploy_xray_config_via_agent 中添加到 deployment_log 了
                proxy.save()
                # 记录Xray配置部署失败日志
                create_log_entry(
                    log_type='proxy',
                    level='error',
                    title=f'代理节点Xray配置部署失败: {proxy.name}',
                    content=f'代理节点 {proxy.name} 的Xray配置部署失败',
                    user=proxy.created_by,
                    server=proxy.server,
                    related_id=proxy.id,
                    related_type='proxy'
                )
                return
            
            proxy.deployment_status = 'success'
            proxy.deployment_log = (proxy.deployment_log or '') + "✅ 部署完成！\n"
            proxy.deployed_at = timezone.now()
            proxy.save()
            
            # 记录部署成功日志
            create_log_entry(
                log_type='proxy',
                level='success',
                title=f'代理节点部署成功: {proxy.name}',
                content=f'代理节点 {proxy.name} 部署成功',
                user=proxy.created_by,
                server=proxy.server,
                related_id=proxy.id,
                related_type='proxy'
            )
            
        except Proxy.DoesNotExist:
            pass
        except Exception as e:
            try:
                import traceback
                proxy = Proxy.objects.get(id=proxy_id)
                proxy.deployment_status = 'failed'
                proxy.deployment_log = (proxy.deployment_log or '') + f"❌ 部署异常: {str(e)}\n{traceback.format_exc()}\n"
                proxy.save()
                # 记录部署异常日志
                create_log_entry(
                    log_type='proxy',
                    level='error',
                    title=f'代理节点部署异常: {proxy.name}',
                    content=f'代理节点 {proxy.name} 部署过程中发生异常：{str(e)}',
                    user=proxy.created_by,
                    server=proxy.server,
                    related_id=proxy.id,
                    related_type='proxy'
                )
            except:
                pass
    
    thread = threading.Thread(target=_deploy)
    thread.daemon = True
    thread.start()

