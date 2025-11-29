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


def deploy_agent_and_services(server: Server, user) -> bool:
    """安装Agent、Xray、Caddy（支持重复安装）
    
    Args:
        server: 服务器对象
        user: 用户对象
        
    Returns:
        bool: 是否成功
    """
    try:
        # 检查是否已安装Agent
        agent = None
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                agent = None
        except Agent.DoesNotExist:
            pass
        
        # 如果服务器连接方式是SSH，需要先安装Agent
        if not agent:
            if server.connection_method == 'ssh':
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
                    return False
                
                # 等待Agent注册
                agent = wait_for_agent_registration(server, timeout=60)
                if not agent:
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent注册超时'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    return False
                
                # 更新服务器连接方式
                server.connection_method = 'agent'
                server.status = 'active'
                server.save()
                
                deployment.status = 'success'
                deployment.completed_at = timezone.now()
                deployment.save()
            else:
                # 没有Agent且不是SSH连接，无法安装
                return False
        
        # 确保Agent在线
        agent = Agent.objects.get(server=server)
        if agent.status != 'online':
            return False
        
        # 检查并安装Xray（支持重复安装）
        xray_installed = check_service_installed(agent, 'xray')
        if not xray_installed:
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
                return False
        # 如果已安装，也尝试更新（幂等性）
        else:
            xray_deployment = Deployment.objects.create(
                name=f"Xray更新 - {server.name}",
                server=server,
                deployment_type='xray',
                connection_method='agent',
                deployment_target=server.deployment_target or 'host',
                status='running',
                created_by=user
            )
            deploy_via_agent(xray_deployment, server.deployment_target or 'host')
            xray_deployment.refresh_from_db()
            # 更新失败不影响，因为已经安装了
        
        # 检查并安装Caddy（支持重复安装）
        caddy_installed = check_service_installed(agent, 'caddy')
        if not caddy_installed:
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
                return False
        # 如果已安装，也尝试更新（幂等性）
        else:
            caddy_deployment = Deployment.objects.create(
                name=f"Caddy更新 - {server.name}",
                server=server,
                deployment_type='caddy',
                connection_method='agent',
                deployment_target=server.deployment_target or 'host',
                status='running',
                created_by=user
            )
            deploy_via_agent(caddy_deployment, server.deployment_target or 'host')
            caddy_deployment.refresh_from_db()
            # 更新失败不影响，因为已经安装了
        
        return True
        
    except Exception as e:
        import traceback
        error_msg = f"部署异常: {str(e)}\n{traceback.format_exc()}"
        # 记录错误到日志
        print(f"deploy_agent_and_services 错误: {error_msg}")
        return False


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
        proxy.deployment_log += f"部署配置失败: {str(e)}\n"
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
            proxy.deployment_log = "开始自动部署...\n"
            proxy.save()
            
            # 步骤1: 检查并安装Agent、Xray、Caddy
            proxy.deployment_log += "步骤1: 检查并安装Agent、Xray、Caddy...\n"
            proxy.save()
            
            try:
                result = deploy_agent_and_services(server, proxy.created_by)
                if not result:
                    proxy.deployment_status = 'failed'
                    proxy.deployment_log += "Agent、Xray、Caddy安装失败，请检查服务器连接和Agent状态\n"
                    proxy.save()
                    return
            except Exception as e:
                proxy.deployment_status = 'failed'
                proxy.deployment_log += f"Agent、Xray、Caddy安装异常: {str(e)}\n"
                proxy.save()
                return
            
            proxy.deployment_log += "Agent、Xray、Caddy安装成功\n"
            proxy.save()
            
            # 步骤2: 部署Xray配置
            proxy.deployment_log += "步骤2: 部署Xray配置...\n"
            proxy.save()
            
            if not deploy_xray_config_via_agent(proxy):
                proxy.deployment_status = 'failed'
                proxy.deployment_log += "Xray配置部署失败\n"
                proxy.save()
                return
            
            proxy.deployment_status = 'success'
            proxy.deployment_log += "部署完成！\n"
            proxy.deployed_at = timezone.now()
            proxy.save()
            
        except Proxy.DoesNotExist:
            pass
        except Exception as e:
            try:
                proxy = Proxy.objects.get(id=proxy_id)
                proxy.deployment_status = 'failed'
                proxy.deployment_log += f"部署异常: {str(e)}\n"
                proxy.save()
            except:
                pass
    
    thread = threading.Thread(target=_deploy)
    thread.daemon = True
    thread.start()

