import threading
import time
from django.utils import timezone
from .models import Proxy
from apps.logs.utils import create_log_entry
from apps.servers.models import Server
from apps.agents.models import Agent
from apps.deployments.tasks import install_agent_via_ssh, wait_for_agent_registration
from apps.deployments.agent_deployer import deploy_via_agent
from apps.deployments.models import Deployment


def check_service_installed(agent: Agent, service_name: str) -> bool:
    """检查服务是否已安装
    
    Args:
        agent: Agent对象
        service_name: 服务名称 ('xray' 或 'caddy')
        
    Returns:
        bool: 是否已安装
    """
    from apps.agents.command_queue import CommandQueue
    from apps.agents.utils import execute_script_via_agent
    
    # 检查 Agent 是否在线
    agent.refresh_from_db()
    if agent.status != 'online':
        print(f"Agent {agent.id} 不在线，状态: {agent.status}")
        return False
    
    check_script = f"""#!/bin/bash
set +e  # 不因错误退出
# 检查命令是否存在
if command -v {service_name} &> /dev/null; then
    echo "INSTALLED"
    # 尝试获取版本信息（可能失败，但不影响判断）
    {service_name} version 2>&1 | head -n 1 || echo "已安装"
    exit 0
else
    echo "NOT_INSTALLED"
    exit 1
fi
"""
    try:
        cmd = execute_script_via_agent(agent, check_script, timeout=10, script_name='check_service.sh')
        
        # 等待命令执行完成，增加超时时间
        max_wait = 30  # 增加到30秒
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if wait_time >= max_wait:
            print(f"检查 {service_name} 超时，命令状态: {cmd.status}")
            # 超时时也检查命令结果（可能命令已执行但未及时更新状态）
            if cmd.result and 'INSTALLED' in cmd.result:
                return True
            return False
        
        # 检查命令执行结果
        if cmd.status == 'success':
            if cmd.result and 'INSTALLED' in cmd.result:
                print(f"检查 {service_name}: 已安装")
                return True
            else:
                print(f"检查 {service_name}: 未安装 (结果: {cmd.result})")
                return False
        elif cmd.status == 'failed':
            # 即使命令失败，也检查结果中是否有INSTALLED
            if cmd.result and 'INSTALLED' in cmd.result:
                print(f"检查 {service_name}: 已安装 (命令失败但检测到INSTALLED)")
                return True
            print(f"检查 {service_name}: 未安装 (命令失败: {cmd.error})")
            return False
        
        return False
    except Exception as e:
        print(f"检查 {service_name} 异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def deploy_agent_and_services(server: Server, user, heartbeat_mode: str = 'push', log_callback=None):
    """安装Agent、Xray、Caddy（支持重复安装）
    
    Args:
        server: 服务器对象
        user: 用户对象
        heartbeat_mode: Agent心跳模式（push/pull），默认push
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
                
                # 等待Agent注册，实时更新进度
                _log("等待Agent注册...")
                agent = wait_for_agent_registration(server, timeout=60)
                if not agent:
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent注册超时'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    _log("Agent注册超时（60秒）")
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
                
                # 更新Agent心跳模式
                if agent:
                    agent.heartbeat_mode = heartbeat_mode
                    agent.save()
                
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
        xray_installed = check_service_installed(agent, 'xray')
        _log(f"Xray检查结果: {'已安装' if xray_installed else '未安装'}")
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
        else:
            _log("Xray已安装，跳过部署")
        
        # 检查并安装Caddy（支持重复安装）
        _log("检查Caddy是否已安装...")
        caddy_installed = check_service_installed(agent, 'caddy')
        _log(f"Caddy检查结果: {'已安装' if caddy_installed else '未安装'}")
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
    from apps.deployments.agent_deployer import deploy_xray_config_via_agent
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
        return deploy_xray_config_via_agent(proxy.server, config_json)
        
    except Exception as e:
        import traceback
        proxy.deployment_log = (proxy.deployment_log or '') + f"❌ 部署配置失败: {str(e)}\n{traceback.format_exc()}\n"
        proxy.deployment_status = 'failed'
        proxy.save()
        return False


def auto_deploy_proxy(proxy_id: int, heartbeat_mode: str = 'push'):
    """自动部署代理（在线程中运行）
    
    Args:
        proxy_id: 代理ID
        heartbeat_mode: Agent心跳模式（push/pull）
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
                try:
                    agent = Agent.objects.get(server=server)
                    heartbeat_mode = agent.heartbeat_mode
                except Agent.DoesNotExist:
                    heartbeat_mode = 'push'  # 默认推送模式
                
                # 实时更新日志的回调函数
                def update_log_callback(message: str):
                    """实时更新部署日志"""
                    proxy.refresh_from_db()
                    proxy.deployment_log = (proxy.deployment_log or '') + message + "\n"
                    proxy.save()
                
                result, log_message = deploy_agent_and_services(
                    server, 
                    proxy.created_by, 
                    heartbeat_mode=heartbeat_mode,
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
            
            if not deploy_xray_config_via_agent(proxy):
                proxy.deployment_status = 'failed'
                proxy.deployment_log = (proxy.deployment_log or '') + "❌ Xray配置部署失败\n"
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

