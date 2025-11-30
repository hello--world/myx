import threading
import time
from django.utils import timezone
from .models import Proxy
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
    import base64
    
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
    script_b64 = base64.b64encode(check_script.encode('utf-8')).decode('utf-8')
    
    try:
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=10
        )
        
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


def deploy_agent_and_services(server: Server, user, heartbeat_mode: str = 'push'):
    """安装Agent、Xray、Caddy（支持重复安装）
    
    Args:
        server: 服务器对象
        user: 用户对象
        heartbeat_mode: Agent心跳模式（push/pull），默认push
        
    Returns:
        tuple[bool, str]: (是否成功, 错误信息或日志)
    """
    error_log = []
    try:
        # 检查是否已安装Agent
        agent = None
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                agent = None
                error_log.append(f"Agent状态为离线，需要重新安装")
        except Agent.DoesNotExist:
            error_log.append("未找到Agent，需要安装")
        
        # 如果服务器连接方式是SSH，需要先安装Agent
        if not agent:
            if server.connection_method == 'ssh':
                error_log.append("通过SSH安装Agent...")
                # 创建临时部署任务用于安装Agent
                deployment = Deployment.objects.create(
                    name=f"安装Agent - {server.name}",
                    server=server,
                    deployment_type='full',
                    connection_method='ssh',
                    deployment_target=server.deployment_target or 'host',
                    status='running',
                    created_by=user
                )
                
                # 安装Agent
                if not install_agent_via_ssh(server, deployment):
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent安装失败'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    error_log.append(f"Agent安装失败")
                    if deployment.log:
                        error_log.append(f"部署日志:\n{deployment.log}")
                    if deployment.error_message:
                        error_log.append(f"错误信息: {deployment.error_message}")
                    return False, "\n".join(error_log)
                
                # 等待Agent注册
                error_log.append("等待Agent注册...")
                agent = wait_for_agent_registration(server, timeout=60)
                if not agent:
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent注册超时'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    error_log.append("Agent注册超时（60秒）")
                    if deployment.log:
                        error_log.append(f"部署日志:\n{deployment.log}")
                    return False, "\n".join(error_log)
                
                # 更新服务器连接方式
                server.connection_method = 'agent'
                server.status = 'active'
                server.save()
                
                # 更新Agent心跳模式
                if agent:
                    agent.heartbeat_mode = heartbeat_mode
                    agent.save()
                
                deployment.status = 'success'
                deployment.completed_at = timezone.now()
                deployment.save()
                error_log.append("Agent安装并注册成功")
            else:
                # 没有Agent且不是SSH连接，无法安装
                error_log.append(f"服务器连接方式为 {server.connection_method}，无法通过SSH安装Agent")
                return False, "\n".join(error_log)
        
        # 确保Agent在线
        agent = Agent.objects.get(server=server)
        agent.refresh_from_db()
        if agent.status != 'online':
            error_log.append(f"Agent状态为 {agent.status}，不在线")
            error_log.append(f"请检查Agent是否正常运行，最后心跳时间: {agent.last_heartbeat}")
            return False, "\n".join(error_log)
        
        error_log.append(f"Agent在线，开始部署服务... (Agent ID: {agent.id}, Token: {agent.token})")
        
        # 检查并安装Xray（支持重复安装）
        error_log.append("检查Xray是否已安装...")
        xray_installed = check_service_installed(agent, 'xray')
        error_log.append(f"Xray检查结果: {'已安装' if xray_installed else '未安装'}")
        if not xray_installed:
            error_log.append("Xray未安装，开始部署...")
            xray_deployment = Deployment.objects.create(
                name=f"Xray部署 - {server.name}",
                server=server,
                deployment_type='xray',
                connection_method='agent',
                deployment_target=server.deployment_target or 'host',
                status='running',
                created_by=user
            )
            error_log.append("开始执行Xray部署...")
            deploy_via_agent(xray_deployment, server.deployment_target or 'host')
            
            # 等待部署完成，最多等待5分钟
            max_wait = 300
            wait_time = 0
            while wait_time < max_wait:
                xray_deployment.refresh_from_db()
                if xray_deployment.status in ['success', 'failed']:
                    break
                time.sleep(2)
                wait_time += 2
                if wait_time % 10 == 0:
                    error_log.append(f"等待Xray部署完成... ({wait_time}秒)")
            
            if xray_deployment.status != 'success':
                error_log.append(f"Xray部署失败")
                if xray_deployment.log:
                    error_log.append(f"Xray部署日志:\n{xray_deployment.log}")
                if xray_deployment.error_message:
                    error_log.append(f"错误信息: {xray_deployment.error_message}")
                return False, "\n".join(error_log)
            error_log.append("Xray部署成功")
        else:
            error_log.append("Xray已安装，跳过部署")
        
        # 检查并安装Caddy（支持重复安装）
        error_log.append("检查Caddy是否已安装...")
        caddy_installed = check_service_installed(agent, 'caddy')
        error_log.append(f"Caddy检查结果: {'已安装' if caddy_installed else '未安装'}")
        if not caddy_installed:
            error_log.append("Caddy未安装，开始部署...")
            caddy_deployment = Deployment.objects.create(
                name=f"Caddy部署 - {server.name}",
                server=server,
                deployment_type='caddy',
                connection_method='agent',
                deployment_target='host',  # Caddy 仅支持宿主机部署
                status='running',
                created_by=user
            )
            error_log.append("开始执行Caddy部署（宿主机）...")
            deploy_via_agent(caddy_deployment, 'host')  # 强制使用宿主机部署
            
            # 等待部署完成，最多等待5分钟
            max_wait = 300
            wait_time = 0
            while wait_time < max_wait:
                caddy_deployment.refresh_from_db()
                if caddy_deployment.status in ['success', 'failed']:
                    break
                time.sleep(2)
                wait_time += 2
                if wait_time % 10 == 0:
                    error_log.append(f"等待Caddy部署完成... ({wait_time}秒)")
            
            if caddy_deployment.status != 'success':
                error_log.append(f"Caddy部署失败")
                if caddy_deployment.log:
                    error_log.append(f"Caddy部署日志:\n{caddy_deployment.log}")
                if caddy_deployment.error_message:
                    error_log.append(f"错误信息: {caddy_deployment.error_message}")
                return False, "\n".join(error_log)
            error_log.append("Caddy部署成功")
        else:
            error_log.append("Caddy已安装，跳过部署")
        
        return True, "\n".join(error_log)
        
    except Exception as e:
        import traceback
        error_msg = f"部署异常: {str(e)}\n{traceback.format_exc()}"
        error_log.append(error_msg)
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
                
                result, log_message = deploy_agent_and_services(server, proxy.created_by, heartbeat_mode=heartbeat_mode)
                proxy.deployment_log = (proxy.deployment_log or '') + log_message + "\n"
                proxy.save()
                
                if not result:
                    proxy.deployment_status = 'failed'
                    proxy.deployment_log = (proxy.deployment_log or '') + "\n❌ Agent、Xray、Caddy安装失败\n"
                    proxy.save()
                    return
            except Exception as e:
                import traceback
                proxy.deployment_status = 'failed'
                proxy.deployment_log = (proxy.deployment_log or '') + f"Agent、Xray、Caddy安装异常: {str(e)}\n{traceback.format_exc()}\n"
                proxy.save()
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
                return
            
            proxy.deployment_status = 'success'
            proxy.deployment_log = (proxy.deployment_log or '') + "✅ 部署完成！\n"
            proxy.deployed_at = timezone.now()
            proxy.save()
            
        except Proxy.DoesNotExist:
            pass
        except Exception as e:
            try:
                import traceback
                proxy = Proxy.objects.get(id=proxy_id)
                proxy.deployment_status = 'failed'
                proxy.deployment_log = (proxy.deployment_log or '') + f"❌ 部署异常: {str(e)}\n{traceback.format_exc()}\n"
                proxy.save()
            except:
                pass
    
    thread = threading.Thread(target=_deploy)
    thread.daemon = True
    thread.start()

