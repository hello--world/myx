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
    
    check_script = f"""#!/bin/bash
if command -v {service_name} &> /dev/null; then
    echo "INSTALLED"
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
        
        # 等待命令执行完成
        max_wait = 10
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status == 'success' and cmd.result and 'INSTALLED' in cmd.result:
            return True
        return False
    except:
        return False


def deploy_agent_and_services(server: Server, user) -> tuple[bool, str]:
    """安装Agent、Xray、Caddy（支持重复安装）
    
    Args:
        server: 服务器对象
        user: 用户对象
        
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
        if agent.status != 'online':
            error_log.append(f"Agent状态为 {agent.status}，不在线")
            return False, "\n".join(error_log)
        
        error_log.append("Agent在线，开始部署服务...")
        
        # 检查并安装Xray（支持重复安装）
        xray_installed = check_service_installed(agent, 'xray')
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
            deploy_via_agent(xray_deployment, server.deployment_target or 'host')
            xray_deployment.refresh_from_db()
            
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
        caddy_installed = check_service_installed(agent, 'caddy')
        if not caddy_installed:
            error_log.append("Caddy未安装，开始部署...")
            caddy_deployment = Deployment.objects.create(
                name=f"Caddy部署 - {server.name}",
                server=server,
                deployment_type='caddy',
                connection_method='agent',
                deployment_target=server.deployment_target or 'host',
                status='running',
                created_by=user
            )
            deploy_via_agent(caddy_deployment, server.deployment_target or 'host')
            caddy_deployment.refresh_from_db()
            
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
    
    Args:
        proxy: 代理对象
        
    Returns:
        bool: 是否成功
    """
    from apps.deployments.agent_deployer import deploy_xray_config_via_agent
    from utils.xray_config import generate_xray_config_json_for_proxies
    
    try:
        # 获取服务器上的所有代理
        server_proxies = Proxy.objects.filter(server=proxy.server, status='active')
        
        # 生成完整的Xray配置
        config_json = generate_xray_config_json_for_proxies(list(server_proxies))
        
        # 通过Agent部署配置
        return deploy_xray_config_via_agent(proxy.server, config_json)
        
    except Exception as e:
        import traceback
        proxy.deployment_log = (proxy.deployment_log or '') + f"❌ 部署配置失败: {str(e)}\n{traceback.format_exc()}\n"
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
                result, log_message = deploy_agent_and_services(server, proxy.created_by)
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

