from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Server
from .serializers import ServerSerializer, ServerTestSerializer
from .utils import test_ssh_connection
from apps.proxies.tasks import deploy_agent_and_services
from apps.agents.models import Agent
from apps.logs.utils import create_log_entry
import paramiko
from io import StringIO
import os
import subprocess
import tempfile
import threading
import logging

logger = logging.getLogger(__name__)


class ServerViewSet(viewsets.ModelViewSet):
    """服务器视图集"""
    queryset = Server.objects.all()
    serializer_class = ServerSerializer

    def get_queryset(self):
        return Server.objects.filter(created_by=self.request.user)
    
    def destroy(self, request, *args, **kwargs):
        """删除服务器（带确认功能）"""
        server = self.get_object()
        
        # 检查是否有相关的 Agent 和 Proxy
        has_agent = False
        has_proxies = False
        agent_info = None
        proxies_info = []
        proxies_count = 0
        
        try:
            agent = Agent.objects.get(server=server)
            has_agent = True
            agent_info = {
                'id': agent.id,
                'token': agent.token[:20] + '...' if agent.token else None,
                'status': agent.status,
                'version': agent.version,
                'rpc_port': agent.rpc_port,
            }
        except Agent.DoesNotExist:
            pass
        
        proxies = server.proxies.all()
        proxies_count = proxies.count()
        has_proxies = proxies_count > 0
        if has_proxies:
            proxies_info = [{
                'id': p.id,
                'name': p.name,
                'protocol': p.protocol,
                'port': p.port,
            } for p in proxies[:10]]  # 最多显示10个
        
        # 检查请求参数中的确认信息
        # 使用 query_params 或 data（DELETE 请求可能没有 body，所以用 query_params）
        confirmed = request.query_params.get('confirmed', '').lower() == 'true'
        delete_agent = request.query_params.get('delete_agent', '').lower() == 'true'
        delete_proxies = request.query_params.get('delete_proxies', '').lower() == 'true'
        
        # 如果有关联对象但用户没有明确确认，返回需要确认的信息
        if (has_agent or has_proxies) and not confirmed:
            return Response({
                'requires_confirmation': True,
                'server': {
                    'id': server.id,
                    'name': server.name,
                    'host': server.host,
                },
                'related_objects': {
                    'has_agent': has_agent,
                    'agent': agent_info,
                    'has_proxies': has_proxies,
                    'proxies_count': proxies_count,
                    'proxies': proxies_info,
                },
                'message': '删除服务器前，请确认是否同时删除相关的 Agent 和代理节点',
                'note': '注意：删除服务器将自动删除所有关联的 Agent 和代理节点（由于外键约束）',
            }, status=status.HTTP_200_OK)
        
        # 执行删除操作
        # 根据用户选择，先删除关联对象，再删除服务器
        try:
            server_name = server.name
            server_host = server.host
            server_id = server.id
            
            # 记录删除前的关联对象信息（用于日志）
            deleted_agent_info = None
            deleted_proxies_count = 0
            kept_proxies_count = 0
            
            # 根据用户选择删除 Agent
            if has_agent:
                try:
                    agent = Agent.objects.get(server=server)
                    agent_id = agent.id  # 保存 agent.id，因为删除后无法访问
                    deleted_agent_info = agent_info
                    
                    # 在删除数据库记录之前，先尝试卸载 Agent（如果 Agent 在线）
                    uninstall_success = False
                    uninstall_error = None
                    if agent.status == 'online' and agent.rpc_port and agent.rpc_supported:
                        try:
                            from apps.agents.rpc_client import get_agent_rpc_client
                            rpc_client = get_agent_rpc_client(agent)
                            if rpc_client and rpc_client.health_check():
                                # Agent 在线，发送卸载命令（使用 Python 脚本）
                                # 读取卸载脚本内容
                                import os
                                from pathlib import Path
                                
                                # 获取项目根目录
                                base_dir = Path(__file__).resolve().parent.parent.parent.parent
                                uninstall_script_path = base_dir / 'deployment-tool' / 'scripts' / 'uninstall_agent.py'
                                
                                if uninstall_script_path.exists():
                                    with open(uninstall_script_path, 'r', encoding='utf-8') as f:
                                        uninstall_script = f.read()
                                else:
                                    # 如果脚本文件不存在，使用内联脚本
                                    uninstall_script = """#!/usr/bin/env python3
import os
import subprocess
import sys
import shutil

def run_command(cmd, check=True, capture_output=True):
    try:
        result = subprocess.run(cmd, shell=True, check=check, capture_output=capture_output, text=True, timeout=30)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, '', str(e)

print("[信息] 开始卸载 Agent...")

# 停止 Agent 服务
success, _, _ = run_command("systemctl is-active --quiet myx-agent", check=False)
if success:
    run_command("systemctl stop myx-agent", check=False)
    print("[信息] Agent 服务已停止")

# 禁用 Agent 服务
success, _, _ = run_command("systemctl is-enabled --quiet myx-agent", check=False)
if success:
    run_command("systemctl disable myx-agent", check=False)
    print("[信息] Agent 服务已禁用")

# 删除 systemd 服务文件
if os.path.exists("/etc/systemd/system/myx-agent.service"):
    os.remove("/etc/systemd/system/myx-agent.service")
    run_command("systemctl daemon-reload", check=False)
    print("[信息] systemd 服务文件已删除")

# 删除 Agent 文件目录
if os.path.exists("/opt/myx-agent"):
    shutil.rmtree("/opt/myx-agent")
    print("[信息] Agent 文件目录已删除")

# 删除 Agent 配置文件目录
if os.path.exists("/etc/myx-agent"):
    shutil.rmtree("/etc/myx-agent")
    print("[信息] Agent 配置文件目录已删除")

# 删除 Agent 日志文件
if os.path.exists("/var/log/myx-agent.log"):
    os.remove("/var/log/myx-agent.log")
    print("[信息] Agent 日志文件已删除")

print("[成功] Agent 卸载完成")
"""
                                
                                from apps.agents.utils import execute_script_via_agent
                                cmd = execute_script_via_agent(agent, uninstall_script, timeout=60, script_name='uninstall_agent.py')
                                
                                # 等待命令执行完成（最多等待30秒）
                                import time
                                max_wait = 30
                                wait_time = 0
                                while wait_time < max_wait:
                                    cmd.refresh_from_db()
                                    if cmd.status in ['success', 'failed']:
                                        break
                                    time.sleep(1)
                                    wait_time += 1
                                
                                if cmd.status == 'success':
                                    uninstall_success = True
                                    logger.info(f'Agent 卸载成功: agent_id={agent_id}, server_id={server_id}')
                                else:
                                    uninstall_error = cmd.error or '卸载命令执行失败'
                                    logger.warning(f'Agent 卸载失败: agent_id={agent_id}, server_id={server_id}, error={uninstall_error}')
                            else:
                                logger.warning(f'Agent 不在线或 RPC 不可用，跳过卸载: agent_id={agent_id}, server_id={server_id}')
                        except Exception as e:
                            uninstall_error = str(e)
                            logger.warning(f'发送 Agent 卸载命令失败: agent_id={agent_id}, server_id={server_id}, error={e}', exc_info=True)
                    else:
                        logger.info(f'Agent 不在线或 RPC 不支持，跳过卸载: agent_id={agent_id}, server_id={server_id}, status={agent.status}, rpc_supported={agent.rpc_supported}')
                    
                    # 删除 Agent 数据库记录
                    agent.delete()
                    if delete_agent:
                        logger.info(f'已删除关联的 Agent: agent_id={agent_id}, server_id={server_id}, uninstall_success={uninstall_success}')
                    else:
                        logger.info(f'已删除关联的 Agent（由于外键约束）: agent_id={agent_id}, server_id={server_id}, uninstall_success={uninstall_success}')
                    
                    # 记录卸载结果到日志
                    if uninstall_success:
                        deleted_agent_info['uninstall_success'] = True
                    elif uninstall_error:
                        deleted_agent_info['uninstall_error'] = uninstall_error
                        
                except Agent.DoesNotExist:
                    pass
            
            # 根据用户选择删除代理节点
            if has_proxies and delete_proxies:
                proxies = server.proxies.all()
                deleted_proxies_count = proxies.count()
                proxies.delete()
                logger.info(f'已删除 {deleted_proxies_count} 个关联的代理节点: server_id={server_id}')
            elif has_proxies and not delete_proxies:
                # 用户不选择删除代理节点，但由于 CASCADE 约束，代理节点会在删除服务器时被删除
                # 这里我们提示用户，或者先删除代理节点（因为外键约束，不能解除关联）
                # 为了简化，我们仍然删除代理节点，但记录日志说明
                proxies = server.proxies.all()
                kept_proxies_count = proxies.count()
                proxies.delete()
                logger.warning(f'已删除 {kept_proxies_count} 个关联的代理节点（由于外键约束，无法保留）: server_id={server_id}')
            
            # 删除服务器
            server.delete()
            
            # 记录删除日志
            log_content = f'服务器 {server_name} ({server_host}) 已删除'
            if has_agent and deleted_agent_info:
                agent_log = f'\n已删除关联的 Agent (ID: {deleted_agent_info["id"]}, Token: {deleted_agent_info["token"]})'
                if deleted_agent_info.get('uninstall_success'):
                    agent_log += '\n  - Agent 已从服务器卸载（服务已停止，文件已删除）'
                elif deleted_agent_info.get('uninstall_error'):
                    agent_log += f'\n  - Agent 卸载失败: {deleted_agent_info["uninstall_error"]}（仅删除了数据库记录）'
                else:
                    agent_log += '\n  - Agent 不在线，跳过卸载（仅删除了数据库记录）'
                if not delete_agent:
                    agent_log += '（由于外键约束，无法保留）'
                log_content += agent_log
            
            if has_proxies and delete_proxies:
                log_content += f'\n已删除 {deleted_proxies_count} 个关联的代理节点'
            elif has_proxies and not delete_proxies:
                log_content += f'\n已删除 {kept_proxies_count} 个关联的代理节点（由于外键约束，无法保留）'
            
            logger.info(f'服务器已删除: server_id={server_id}, name={server_name}, agent_deleted={has_agent and delete_agent}, proxies_deleted={has_proxies and delete_proxies}')
            create_log_entry(
                log_type='server',
                level='info',
                title=f'删除服务器: {server_name}',
                content=log_content,
                user=request.user
            )
            
            return Response({
                'success': True,
                'message': '服务器删除成功',
                'deleted': {
                    'agent': has_agent and delete_agent,
                    'proxies_count': deleted_proxies_count if (has_proxies and delete_proxies) else kept_proxies_count,
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f'删除服务器失败: {e}', exc_info=True)
            return Response({
                'error': f'删除服务器失败: {str(e)}',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _test_agent_connection(self, server):
        """测试Agent连接（优先使用Web服务，回退到心跳检查）"""
        try:
            agent = Agent.objects.get(server=server)
            
            # 优先尝试使用RPC连接（新架构，支持随机路径）
            # 如果Agent有RPC端口，优先使用RPC客户端；否则使用Web服务客户端
            web_service_error = None
            if agent.rpc_port:
                try:
                    from apps.agents.rpc_client import get_agent_rpc_client
                    rpc_client = get_agent_rpc_client(agent)
                    if rpc_client:
                        # 尝试健康检查（RPC客户端支持随机路径）
                        if rpc_client.check_support():
                            # 获取Agent状态
                            status_result = rpc_client.get_status()
                            if status_result:
                                # status_result 已经是结果字典，不是包装在 {'result': ...} 中
                                return {
                                    'success': True,
                                    'message': 'Agent RPC服务连接成功',
                                    'agent_status': 'online',
                                    'connection_method': 'rpc',
                                    'rpc_info': status_result
                                }
                            else:
                                web_service_error = 'RPC服务连接成功但获取状态失败'
                        else:
                            web_service_error = 'RPC服务不支持或健康检查失败'
                    else:
                        logger.warning(f"无法创建Agent RPC客户端，尝试Web服务客户端")
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"连接Agent RPC服务失败: {error_msg}，尝试Web服务客户端", exc_info=True)
                    web_service_error = f'RPC服务连接异常: {error_msg}'
            
            # 如果RPC不可用，尝试Web服务（旧架构）
            if not web_service_error and agent.web_service_enabled:
                try:
                    from apps.agents.client import get_agent_client
                    client = get_agent_client(agent)
                    if client:
                        # 尝试健康检查
                        health_result = client.health_check()
                        if health_result is True:
                            # 获取Agent状态
                            status = client.get_status()
                            return {
                                'success': True,
                                'message': 'Agent Web服务连接成功',
                                'agent_status': 'online',
                                'connection_method': 'web_service',
                                'web_service_info': status
                            }
                        else:
                            # Web服务不可用，记录详细错误信息
                            error_detail = health_result if isinstance(health_result, str) else 'Web服务健康检查失败'
                            logger.warning(f"Agent Web服务健康检查失败: {error_detail}，回退到心跳检查")
                            web_service_error = error_detail
                    else:
                        logger.warning(f"无法创建Agent Web服务客户端，回退到心跳检查")
                        if not web_service_error:
                            web_service_error = 'Web服务未启用或配置不正确'
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"连接Agent Web服务失败: {error_msg}，回退到心跳检查", exc_info=True)
                    if not web_service_error:
                        web_service_error = f'Web服务连接异常: {error_msg}'
            
            # 回退到传统心跳检查
            # 构建消息，包含Web服务失败的原因（如果有）
            web_service_warning = None
            if 'web_service_error' in locals() and web_service_error:
                web_service_warning = web_service_error
            
            if agent.status == 'online':
                # 检查最后心跳时间
                if agent.last_heartbeat:
                    time_since_heartbeat = timezone.now() - agent.last_heartbeat
                    if time_since_heartbeat.total_seconds() <= 60:
                        message = 'Agent连接成功（心跳模式）'
                        if web_service_warning:
                            message += f'\n注意：Web服务健康检查失败（{web_service_warning}），已回退到心跳检查'
                        return {
                            'success': True,
                            'message': message,
                            'agent_status': 'online',
                            'connection_method': 'heartbeat',
                            'last_heartbeat': agent.last_heartbeat,
                            'web_service_warning': web_service_warning
                        }
                    else:
                        error_msg = f'Agent长时间未心跳（{int(time_since_heartbeat.total_seconds())}秒）'
                        if web_service_warning:
                            error_msg += f'\nWeb服务健康检查失败：{web_service_warning}'
                        return {
                            'success': False,
                            'error': error_msg,
                            'agent_status': 'offline',
                            'web_service_warning': web_service_warning
                        }
                else:
                    error_msg = 'Agent从未发送心跳'
                    if web_service_warning:
                        error_msg += f'\nWeb服务健康检查失败：{web_service_warning}'
                    return {
                        'success': False,
                        'error': error_msg,
                        'agent_status': 'offline',
                        'web_service_warning': web_service_warning
                    }
            else:
                error_msg = f'Agent状态为: {agent.status}'
                if web_service_warning:
                    error_msg += f'\nWeb服务健康检查失败：{web_service_warning}'
                return {
                    'success': False,
                    'error': error_msg,
                    'agent_status': agent.status,
                    'web_service_warning': web_service_warning
                }
        except Agent.DoesNotExist:
            return {
                'success': False,
                'error': '服务器未安装Agent',
                'agent_status': None
            }
        except Exception as e:
            logger.error(f"检查Agent连接异常: {e}", exc_info=True)
            return {
                'success': False,
                'error': f'检查Agent连接异常: {str(e)}',
                'agent_status': None
            }

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试服务器连接（根据连接方式自动选择SSH或Agent）"""
        server = self.get_object()
        
        # 检查是否强制使用SSH测试
        force_ssh = request.data.get('force_ssh', False)
        
        # 如果连接方式是Agent且未强制使用SSH，则使用Agent测试
        if server.connection_method == 'agent' and not force_ssh:
            try:
                result = self._test_agent_connection(server)
                if result['success']:
                    server.status = 'active'
                    server.last_check = timezone.now()
                    server.save()
                    # 记录连接测试成功日志
                    create_log_entry(
                        log_type='server',
                        level='success',
                        title=f'连接测试成功: {server.name}',
                        content=f'通过Agent连接测试成功，Agent状态: {result.get("agent_status", "未知")}',
                        user=request.user,
                        server=server
                    )
                    return Response({
                        'message': result['message'],
                        'status': 'active',
                        'connection_method': 'agent',
                        'agent_status': result.get('agent_status'),
                        'last_heartbeat': result.get('last_heartbeat')
                    })
                else:
                    server.status = 'error'
                    server.last_check = timezone.now()
                    server.save()
                    # 记录连接测试失败日志
                    create_log_entry(
                        log_type='server',
                        level='error',
                        title=f'连接测试失败: {server.name}',
                        content=f'通过Agent连接测试失败: {result.get("error", "未知错误")}',
                        user=request.user,
                        server=server
                    )
                    return Response(
                        {
                            'message': f"连接失败: {result.get('error', '未知错误')}",
                            'status': 'error',
                            'connection_method': 'agent',
                            'agent_status': result.get('agent_status')
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                server.status = 'error'
                server.last_check = timezone.now()
                server.save()
                # 记录连接测试异常日志
                create_log_entry(
                    log_type='server',
                    level='error',
                    title=f'连接测试异常: {server.name}',
                    content=f'通过Agent连接测试时发生异常: {str(e)}',
                    user=request.user,
                    server=server
                )
                return Response(
                    {
                        'message': f"连接测试异常: {str(e)}",
                        'status': 'error',
                        'connection_method': 'agent'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            # 使用SSH测试
            try:
                result = test_ssh_connection(
                    host=server.host,
                    port=server.port,
                    username=server.username,
                    password=server.password,
                    private_key=server.private_key
                )
                if result['success']:
                    server.status = 'active'
                    server.last_check = timezone.now()
                    server.save()
                    # 记录连接测试成功日志
                    create_log_entry(
                        log_type='server',
                        level='success',
                        title=f'连接测试成功: {server.name}',
                        content=f'通过SSH连接测试成功',
                        user=request.user,
                        server=server
                    )
                    return Response({
                        'message': '连接成功',
                        'status': 'active',
                        'connection_method': 'ssh'
                    })
                else:
                    server.status = 'error'
                    server.last_check = timezone.now()
                    server.save()
                    # 记录连接测试失败日志
                    create_log_entry(
                        log_type='server',
                        level='error',
                        title=f'连接测试失败: {server.name}',
                        content=f'通过SSH连接测试失败: {result.get("error", "未知错误")}',
                        user=request.user,
                        server=server
                    )
                    return Response(
                        {
                            'message': f"连接失败: {result.get('error', '未知错误')}",
                            'status': 'error',
                            'connection_method': 'ssh'
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                server.status = 'error'
                server.last_check = timezone.now()
                server.save()
                # 记录连接测试异常日志
                create_log_entry(
                    log_type='server',
                    level='error',
                    title=f'连接测试异常: {server.name}',
                    content=f'通过SSH连接测试时发生异常: {str(e)}',
                    user=request.user,
                    server=server
                )
                return Response(
                    {
                        'message': f"连接测试异常: {str(e)}",
                        'status': 'error',
                        'connection_method': 'ssh'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

    @action(detail=True, methods=['post'])
    def install_agent(self, request, pk=None):
        """安装Agent到服务器"""
        server = self.get_object()
        
        # 检查是否已有Agent（允许升级）
        is_upgrade = False
        agent = None
        try:
            agent = Agent.objects.get(server=server)
            is_upgrade = True
        except Agent.DoesNotExist:
            pass
        
        # 如果Agent已安装且在线，使用Agent进行升级
        if is_upgrade and agent and agent.status == 'online' and agent.rpc_supported:
            # 通过Agent进行升级（使用redeploy功能）
            from apps.deployments.models import Deployment
            from apps.agents.command_queue import CommandQueue
            from django.conf import settings
            import os
            import time as time_module
            
            # 创建部署任务
            task_name = f"升级Agent - {server.name}"
            deployment = Deployment.objects.create(
                name=task_name,
                server=server,
                deployment_type='agent',
                connection_method='agent',
                deployment_target=server.deployment_target or 'host',
                status='running',
                started_at=timezone.now(),
                created_by=request.user
            )
            
            # 获取API URL用于上报进度和下载文件
            api_url = os.getenv('AGENT_API_URL', getattr(settings, 'AGENT_API_URL', None))
            if not api_url:
                # 从request构建API URL
                scheme = 'https' if request.is_secure() else 'http'
                host = request.get_host()
                api_url = f"{scheme}://{host}/api/agents"
            
            # 从模板文件加载脚本
            from pathlib import Path
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            script_template_path = str(base_dir / 'backend' / 'apps' / 'agents' / 'scripts' / 'agent_redeploy.sh.template')
            with open(script_template_path, 'r', encoding='utf-8') as f:
                redeploy_script = f.read()
            
            # 替换占位符
            redeploy_script = redeploy_script.replace('{DEPLOYMENT_ID}', str(deployment.id))
            redeploy_script = redeploy_script.replace('{API_URL}', api_url)
            redeploy_script = redeploy_script.replace('{AGENT_TOKEN}', str(agent.token))
            
            # 使用deployment_id作为日志文件路径的唯一标识
            log_file = f'/tmp/agent_redeploy_{deployment.id}.log'
            script_file = f'/tmp/agent_redeploy_script_{deployment.id}.sh'
            
            # 生成唯一的服务名称
            service_name = f'myx-agent-redeploy-{deployment.id}-{int(time_module.time())}'
            
            # 使用base64编码脚本内容，避免heredoc中的特殊字符问题
            import base64
            script_base64 = base64.b64encode(redeploy_script.encode('utf-8')).decode('ascii')
            
            # 构建部署命令：使用base64解码脚本内容，写入脚本文件，然后使用systemd-run执行
            deploy_command = f'''bash -c 'echo "{script_base64}" | base64 -d > "{script_file}" && chmod +x "{script_file}" && systemd-run --unit={service_name} --service-type=oneshot --no-block --property=StandardOutput=file:{log_file} --property=StandardError=file:{log_file} bash "{script_file}"; echo $?' '''
            
            logger.info(f'[upgrade] 创建Agent升级命令: deployment_id={deployment.id}, script_file={script_file}, log_file={log_file}')
            
            # 使用systemd-run创建临时服务执行脚本，确保独立于Agent进程运行
            cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', deploy_command],
                timeout=600
            )
            
            logger.info(f'[upgrade] 命令已添加到队列: command_id={cmd.id}, agent_id={agent.id}')
            
            # 初始化部署日志
            deployment.log = f"[开始] Agent升级已启动（通过Agent），命令ID: {cmd.id}\n"
            deployment.log += f"[信息] 升级将使用systemd-run在独立进程中执行，确保升级过程不受影响\n"
            deployment.log += f"[信息] 日志文件: {log_file}\n"
            deployment.log += f"[信息] 脚本文件: {script_file}\n"
            deployment.log += f"[信息] 如果升级失败，系统会自动回滚到原始版本\n"
            deployment.save()
            
            # 记录Agent升级开始日志
            create_log_entry(
                log_type='agent',
                level='info',
                title=f'开始升级Agent: {server.name}',
                content=f'Agent升级已启动（通过Agent），部署任务ID: {deployment.id}，命令ID: {cmd.id}。升级将使用systemd-run在独立进程中执行，如果失败会自动回滚。',
                user=request.user,
                server=server,
                related_id=deployment.id,
                related_type='deployment'
            )
            
            return Response({
                'success': True,
                'message': 'Agent升级任务已启动（通过Agent），请查看部署任务',
                'deployment_id': deployment.id,
                'is_upgrade': True,
                'upgrade_method': 'agent'
            }, status=status.HTTP_202_ACCEPTED)
        
        # 如果Agent不在线或未安装，使用SSH安装/升级
        # 检查是否有SSH凭证
        if not server.password and not server.private_key:
            if is_upgrade:
                return Response({
                    'success': False,
                    'error': 'Agent不在线且服务器缺少SSH密码或私钥，无法升级Agent。请先编辑服务器并输入SSH凭证，或等待Agent上线后使用Agent升级。'
                }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'success': False,
                    'error': '服务器缺少SSH密码或私钥，无法安装Agent。请先编辑服务器并输入SSH凭证。'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取或设置save_password标志
        # 优先使用服务器已有的save_password设置（如果用户之前选择了保存密码）
        save_password = request.data.get('save_password', None)
        if save_password is None:
            # 如果服务器已有save_password设置，使用它；否则默认False（安装成功后删除密码）
            save_password = server.save_password if server.save_password else False
        else:
            save_password = bool(save_password)
        
        # 如果用户通过请求提供了密码，使用请求中的密码；否则使用服务器已有的密码
        if request.data.get('password'):
            server.password = request.data.get('password')
        if request.data.get('private_key'):
            server.private_key = request.data.get('private_key')
        
        # 设置save_password标志（如果save_password=True，确保密码被保存）
        # 如果save_password=False，临时设置为True以便安装，但会在安装成功后根据save_password决定是否删除
        original_save_password = server.save_password
        server.save_password = True  # 临时设置为True，确保密码被保存用于安装
        server.save()
        
        # 创建部署任务
        from apps.deployments.models import Deployment
        
        task_name = f"升级Agent - {server.name}" if is_upgrade else f"安装Agent - {server.name}"
        deployment = Deployment.objects.create(
            name=task_name,
            server=server,
            deployment_type='agent',
            connection_method='ssh',
            deployment_target=server.deployment_target or 'host',
            status='running',
            started_at=timezone.now(),
            created_by=request.user
        )
        
        # 记录Agent安装/升级开始日志
        log_title = f'开始升级Agent: {server.name}' if is_upgrade else f'开始安装Agent: {server.name}'
        log_content = f'开始通过SSH{"升级" if is_upgrade else "安装"}Agent到服务器 {server.name}，部署任务ID: {deployment.id}'
        if is_upgrade:
            log_content += '\n升级将安装最新版本的Agent文件并重启服务'
        create_log_entry(
            log_type='agent',
            level='info',
            title=log_title,
            content=log_content,
            user=request.user,
            server=server,
            related_id=deployment.id,
            related_type='deployment'
        )
        
        # 在后台线程中安装Agent
        def install_agent_async():
            try:
                # 重新获取服务器和部署对象
                server.refresh_from_db()
                deployment.refresh_from_db()
                
                # 临时设置连接方式为SSH（如果原来是Agent）
                original_connection_method = server.connection_method
                if server.connection_method == 'agent':
                    server.connection_method = 'ssh'
                    server.save()
                
                # 通过SSH安装Agent
                from apps.deployments.tasks import install_agent_via_ssh, wait_for_agent_startup
                
                action_text = "升级" if is_upgrade else "安装"
                deployment.log = (deployment.log or '') + f"[开始] 开始通过SSH{action_text}Agent到服务器 {server.host}\n"
                if is_upgrade:
                    deployment.log = (deployment.log or '') + f"[信息] 升级模式：将安装最新版本的Agent文件并重启服务\n"
                deployment.save()
                
                # 安装/升级Agent
                if not install_agent_via_ssh(server, deployment):
                    deployment.status = 'failed'
                    deployment.error_message = f'Agent{action_text}失败'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    
                    # 安装失败，根据save_password决定是否保留密码
                    server.refresh_from_db()
                    if save_password:
                        # save_password=True，保持密码和标志
                        server.save_password = True
                        server.save()
                        logger.info(f'Agent安装失败，保留密码（用户选择了保存密码）: server_id={server.id}')
                    else:
                        # save_password=False，保留密码以便重试，但保持save_password=False
                        server.save_password = False
                        server.save()
                        logger.info(f'Agent安装失败，保留密码以便重试: server_id={server.id}')
                    
                    # 恢复连接方式
                    if original_connection_method:
                        server.connection_method = original_connection_method
                        server.save()
                    
                    log_title = f'Agent{action_text}失败: {server.name}'
                    log_content = f'Agent{action_text}失败，部署任务ID: {deployment.id}'
                    create_log_entry(
                        log_type='agent',
                        level='error',
                        title=log_title,
                        content=log_content,
                        user=request.user,
                        server=server,
                        related_id=deployment.id,
                        related_type='deployment'
                    )
                    return
                
                # 等待Agent启动
                deployment.log = (deployment.log or '') + "等待Agent启动...\n"
                deployment.save()
                
                agent = wait_for_agent_startup(server, timeout=120, deployment=deployment)
                if not agent or not agent.rpc_supported:
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent启动超时或RPC不支持'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    
                    # 启动失败，根据save_password决定是否保留密码
                    server.refresh_from_db()
                    if save_password:
                        # save_password=True，保持密码和标志
                        server.save_password = True
                        server.save()
                        logger.info(f'Agent启动失败，保留密码（用户选择了保存密码）: server_id={server.id}')
                    else:
                        # save_password=False，保留密码以便重试，但保持save_password=False
                        server.save_password = False
                        server.save()
                        logger.info(f'Agent启动失败，保留密码以便重试: server_id={server.id}')
                    
                    # 恢复连接方式
                    if original_connection_method:
                        server.connection_method = original_connection_method
                        server.save()
                    
                    create_log_entry(
                        log_type='agent',
                        level='error',
                        title=f'Agent启动失败: {server.name}',
                        content=f'Agent启动超时或RPC不支持，部署任务ID: {deployment.id}',
                        user=request.user,
                        server=server,
                        related_id=deployment.id,
                        related_type='deployment'
                    )
                    return
                
                # 安装/升级成功
                deployment.status = 'success'
                deployment.completed_at = timezone.now()
                action_text = "升级" if is_upgrade else "安装"
                deployment.log = (deployment.log or '') + f"Agent{action_text}成功，已启动，RPC端口: {agent.rpc_port}\n"
                deployment.save()
                
                # 更新服务器状态
                server.refresh_from_db()
                server.connection_method = 'agent'
                server.status = 'active'
                
                # 如果save_password=False，删除密码
                if not save_password:
                    server.password = ''
                    server.private_key = ''
                    server.save_password = False
                    logger.info(f'Agent{action_text}成功，已删除密码: server_id={server.id}')
                else:
                    server.save_password = True
                
                server.save()
                
                # 恢复连接方式（如果原来是Agent）
                if original_connection_method == 'agent':
                    server.connection_method = 'agent'
                    server.save()
                
                log_title = f'Agent{action_text}成功: {server.name}'
                log_content = f'Agent已成功{action_text}并启动，RPC端口: {agent.rpc_port}，部署任务ID: {deployment.id}'
                create_log_entry(
                    log_type='agent',
                    level='success',
                    title=log_title,
                    content=log_content,
                    user=request.user,
                    server=server,
                    related_id=deployment.id,
                    related_type='deployment'
                )
                
            except Exception as e:
                logger.error(f'Agent安装异常: {e}', exc_info=True)
                deployment.refresh_from_db()
                deployment.status = 'failed'
                deployment.error_message = f'安装异常: {str(e)}'
                deployment.completed_at = timezone.now()
                deployment.save()
                
                # 异常情况，根据save_password决定是否保留密码
                server.refresh_from_db()
                if save_password:
                    # save_password=True，保持密码和标志
                    server.save_password = True
                    server.save()
                    logger.info(f'Agent安装异常，保留密码（用户选择了保存密码）: server_id={server.id}')
                else:
                    # save_password=False，保留密码以便重试，但保持save_password=False
                    server.save_password = False
                    server.save()
                    logger.info(f'Agent安装异常，保留密码以便重试: server_id={server.id}')
        
        # 启动后台线程
        thread = threading.Thread(target=install_agent_async)
        thread.daemon = True
        thread.start()
        
        return Response({
            'success': True,
            'message': 'Agent升级任务已启动' if is_upgrade else 'Agent安装任务已启动',
            'deployment_id': deployment.id,
            'save_password': save_password,
            'is_upgrade': is_upgrade
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def agent_logs(self, request, pk=None):
        """获取Agent日志（支持增量获取）"""
        server = self.get_object()
        
        # 检查是否有Agent
        try:
            agent = Agent.objects.get(server=server)
        except Agent.DoesNotExist:
            return Response({
                'error': '服务器未安装Agent'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # 获取增量参数
        agent_log_offset = int(request.query_params.get('agent_log_offset', 0))
        systemd_offset = int(request.query_params.get('systemd_offset', 0))
        journalctl_offset = int(request.query_params.get('journalctl_offset', 0))
        incremental = request.query_params.get('incremental', 'false').lower() == 'true'
        lines = int(request.query_params.get('lines', 200))  # 默认200行
        
        logs = {
            'agent_log': '',
            'systemd_status': '',
            'journalctl_log': '',
            'agent_log_offset': 0,
            'systemd_offset': 0,
            'journalctl_offset': 0,
            'error': None
        }
        
        # 优先尝试通过RPC获取日志（如果Agent在线）
        if agent.status == 'online' and agent.rpc_supported:
            try:
                from apps.agents.rpc_client import get_agent_rpc_client
                rpc_client = get_agent_rpc_client(agent)
                if rpc_client:
                    # 通过RPC执行命令读取日志
                    from apps.agents.command_queue import CommandQueue
                    
                    # 读取Agent日志文件（支持增量获取）
                    if incremental and agent_log_offset > 0:
                        # 增量获取：从指定行数开始读取新内容
                        read_log_cmd = CommandQueue.add_command(
                            agent=agent,
                            command='bash',
                            args=['-c', f'tail -n +{agent_log_offset + 1} /var/log/myx-agent.log 2>/dev/null || echo "日志文件不存在"'],
                            timeout=10
                        )
                    else:
                        # 首次获取：读取指定行数
                        read_log_cmd = CommandQueue.add_command(
                            agent=agent,
                            command='bash',
                            args=['-c', f'tail -n {lines} /var/log/myx-agent.log 2>/dev/null || echo "日志文件不存在"'],
                            timeout=10
                        )
                    
                    # 等待命令执行
                    import time
                    for _ in range(10):
                        time.sleep(1)
                        read_log_cmd.refresh_from_db()
                        if read_log_cmd.status in ['success', 'failed']:
                            if read_log_cmd.status == 'success' and read_log_cmd.result:
                                from apps.logs.utils import format_log_content
                                log_content = format_log_content(read_log_cmd.result, decode_base64=True)
                                logs['agent_log'] = log_content
                                # 计算新的offset（行数）
                                if log_content and log_content != '日志文件不存在':
                                    logs['agent_log_offset'] = agent_log_offset + len(log_content.split('\n'))
                                else:
                                    logs['agent_log_offset'] = agent_log_offset
                            break
                    
                    # 读取systemd状态（只在首次加载时获取，不增量）
                    if not incremental or systemd_offset == 0:
                        status_cmd = CommandQueue.add_command(
                            agent=agent,
                            command='bash',
                            args=['-c', 'systemctl status myx-agent --no-pager -l 2>/dev/null || echo "无法获取服务状态"'],
                            timeout=10
                        )
                        
                        for _ in range(10):
                            time.sleep(1)
                            status_cmd.refresh_from_db()
                            if status_cmd.status in ['success', 'failed']:
                                if status_cmd.status == 'success' and status_cmd.result:
                                    from apps.logs.utils import format_log_content
                                    logs['systemd_status'] = format_log_content(status_cmd.result, decode_base64=True)
                                    logs['systemd_offset'] = len(logs['systemd_status'].split('\n'))
                                break
                    else:
                        logs['systemd_offset'] = systemd_offset
                    
                    # 读取journalctl日志（支持增量获取）
                    if incremental and journalctl_offset > 0:
                        journal_cmd = CommandQueue.add_command(
                            agent=agent,
                            command='bash',
                            args=['-c', f'journalctl -u myx-agent -n +{journalctl_offset + 1} --no-pager 2>/dev/null || echo "无法读取journalctl日志"'],
                            timeout=10
                        )
                    else:
                        journal_cmd = CommandQueue.add_command(
                            agent=agent,
                            command='bash',
                            args=['-c', 'journalctl -u myx-agent -n 50 --no-pager 2>/dev/null || echo "无法读取journalctl日志"'],
                            timeout=10
                        )
                    
                    for _ in range(10):
                        time.sleep(1)
                        journal_cmd.refresh_from_db()
                        if journal_cmd.status in ['success', 'failed']:
                            if journal_cmd.status == 'success' and journal_cmd.result:
                                from apps.logs.utils import format_log_content
                                journal_content = format_log_content(journal_cmd.result, decode_base64=True)
                                logs['journalctl_log'] = journal_content
                                if journal_content and '无法读取journalctl日志' not in journal_content:
                                    logs['journalctl_offset'] = journalctl_offset + len(journal_content.split('\n'))
                                else:
                                    logs['journalctl_offset'] = journalctl_offset
                            break
                    
                    return Response(logs)
            except Exception as e:
                logger.warning(f'通过RPC获取Agent日志失败: {e}，尝试使用SSH')
                logs['error'] = f'RPC获取失败: {str(e)}，尝试使用SSH'
        
        # 回退到SSH方式
        if not server.password and not server.private_key:
            return Response({
                'error': '服务器缺少SSH凭证，无法获取Agent日志'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            import paramiko
            from io import StringIO
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 连接SSH
            if server.private_key:
                try:
                    key = paramiko.RSAKey.from_private_key(StringIO(server.private_key))
                except:
                    try:
                        key = paramiko.Ed25519Key.from_private_key(StringIO(server.private_key))
                    except:
                        key = paramiko.ECDSAKey.from_private_key(StringIO(server.private_key))
                ssh.connect(server.host, port=server.port, username=server.username, pkey=key, timeout=10)
            else:
                ssh.connect(server.host, port=server.port, username=server.username, password=server.password, timeout=10)
            
            # 读取Agent日志文件（支持增量获取）
            try:
                if incremental and agent_log_offset > 0:
                    # 增量获取：从指定行数开始读取新内容
                    stdin, stdout, stderr = ssh.exec_command(f'tail -n +{agent_log_offset + 1} /var/log/myx-agent.log 2>/dev/null || echo "日志文件不存在"', timeout=10)
                else:
                    # 首次获取：读取指定行数
                    stdin, stdout, stderr = ssh.exec_command(f'tail -n {lines} /var/log/myx-agent.log 2>/dev/null || echo "日志文件不存在"', timeout=10)
                log_content = stdout.read().decode()
                logs['agent_log'] = log_content
                # 计算新的offset（行数）
                if log_content and '日志文件不存在' not in log_content:
                    logs['agent_log_offset'] = agent_log_offset + len(log_content.split('\n'))
                else:
                    logs['agent_log_offset'] = agent_log_offset
            except Exception as e:
                logs['agent_log'] = f'读取日志文件失败: {str(e)}'
                logs['agent_log_offset'] = agent_log_offset
            
            # 读取systemd状态（只在首次加载时获取）
            if not incremental or systemd_offset == 0:
                try:
                    stdin, stdout, stderr = ssh.exec_command('systemctl status myx-agent --no-pager -l 2>/dev/null || echo "无法获取服务状态"', timeout=10)
                    status_content = stdout.read().decode()
                    logs['systemd_status'] = status_content
                    logs['systemd_offset'] = len(status_content.split('\n'))
                except Exception as e:
                    logs['systemd_status'] = f'读取服务状态失败: {str(e)}'
                    logs['systemd_offset'] = systemd_offset
            else:
                logs['systemd_offset'] = systemd_offset
            
            # 读取journalctl日志（支持增量获取）
            try:
                if incremental and journalctl_offset > 0:
                    stdin, stdout, stderr = ssh.exec_command(f'journalctl -u myx-agent -n +{journalctl_offset + 1} --no-pager 2>/dev/null || echo "无法读取journalctl日志"', timeout=10)
                else:
                    stdin, stdout, stderr = ssh.exec_command('journalctl -u myx-agent -n 50 --no-pager 2>/dev/null || echo "无法读取journalctl日志"', timeout=10)
                journal_content = stdout.read().decode()
                logs['journalctl_log'] = journal_content
                if journal_content and '无法读取journalctl日志' not in journal_content:
                    logs['journalctl_offset'] = journalctl_offset + len(journal_content.split('\n'))
                else:
                    logs['journalctl_offset'] = journalctl_offset
            except Exception as e:
                logs['journalctl_log'] = f'读取journalctl日志失败: {str(e)}'
                logs['journalctl_offset'] = journalctl_offset
            
            ssh.close()
            
            return Response(logs)
            
        except Exception as e:
            logger.error(f'通过SSH获取Agent日志失败: {e}', exc_info=True)
            return Response({
                'error': f'获取Agent日志失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def test(self, request):
        """测试连接（不保存，根据连接方式自动选择SSH或Agent）"""
        # 检查是否提供了服务器ID（用于Agent测试）
        server_id = request.data.get('server_id')
        connection_method = request.data.get('connection_method', 'agent')
        force_ssh = request.data.get('force_ssh', False)
        
        # 如果提供了server_id且连接方式是agent，使用Agent测试
        if server_id and connection_method == 'agent' and not force_ssh:
            try:
                server = Server.objects.get(id=server_id, created_by=request.user)
                result = self._test_agent_connection(server)
                if result['success']:
                    return Response({
                        'message': result['message'],
                        'connection_method': 'agent',
                        'agent_status': result.get('agent_status')
                    })
                else:
                    return Response(
                        {
                            'message': f"连接失败: {result.get('error', '未知错误')}",
                            'connection_method': 'agent',
                            'agent_status': result.get('agent_status')
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Server.DoesNotExist:
                return Response(
                    {'message': '服务器不存在'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Exception as e:
                return Response(
                    {
                        'message': f"连接测试异常: {str(e)}",
                        'connection_method': 'agent'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            # 使用SSH测试
            serializer = ServerTestSerializer(data=request.data)
            if serializer.is_valid():
                try:
                    result = test_ssh_connection(**serializer.validated_data)
                    if result['success']:
                        return Response({
                            'message': '连接成功',
                            'connection_method': 'ssh'
                        })
                    else:
                        return Response(
                            {
                                'message': f"连接失败: {result.get('error', '未知错误')}",
                                'connection_method': 'ssh'
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )
                except Exception as e:
                    return Response(
                        {
                            'message': f"连接测试异常: {str(e)}",
                            'connection_method': 'ssh'
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        """创建服务器，处理自动生成服务器名和密码保存"""
        # 如果服务器名为空，使用host作为默认值
        data = request.data.copy()
        if not data.get('name', '').strip():
            data['name'] = data.get('host', '未命名服务器')
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        
        save_password = data.get('save_password', False)
        enable_ssh_key = data.get('enable_ssh_key', False)
        password = data.get('password', '')
        connection_method = data.get('connection_method', 'agent')
        
        # 创建服务器（先保存密码，即使save_password=False，也需要临时保存用于安装Agent）
        # 安装完成后，如果save_password=False，再清空密码
        server = serializer.save()
        
        # 设置save_password标志（如果用户选择了保存密码，立即设置）
        # 即使save_password=False，也临时设置为True以便安装，但会在安装完成后根据save_password决定是否删除
        server.save_password = True  # 临时设置为True，确保密码被保存用于安装
        server.save()
        
        # 记录服务器创建日志
        create_log_entry(
            log_type='server',
            level='info',
            title=f'创建服务器: {server.name}',
            content=f'服务器名称: {server.name}\n主机地址: {server.host}\nSSH端口: {server.port}\n连接方式: {server.get_connection_method_display()}\n部署目标: {server.get_deployment_target_display()}',
            user=request.user,
            server=server
        )
        
        # 如果启用SSH key登录，生成key并添加到服务器
        if enable_ssh_key and password:
            try:
                result = self._generate_and_add_ssh_key(server, password)
                if result['success']:
                    server.generated_public_key = result['public_key']
                    server.save()
                    # 记录SSH key生成日志
                    create_log_entry(
                        log_type='server',
                        level='success',
                        title=f'SSH Key已生成并添加到服务器: {server.name}',
                        content=f'SSH Key已成功生成并添加到服务器 {server.name}',
                        user=request.user,
                        server=server
                    )
            except Exception as e:
                # 记录错误但不阻止服务器创建
                create_log_entry(
                    log_type='server',
                    level='error',
                    title=f'SSH Key生成失败: {server.name}',
                    content=f'SSH Key生成失败: {str(e)}',
                    user=request.user,
                    server=server
                )
        
        # 第一次添加服务器时，如果提供了SSH凭证，自动安装Agent
        # 这样后续就可以使用Agent连接，无需每次输入SSH密码
        if server.password or server.private_key:
            # 检查是否已经存在Agent（避免重复安装）
            try:
                existing_agent = Agent.objects.get(server=server)
                # 如果Agent已存在且在线，跳过安装
                if existing_agent.status == 'online':
                    return Response({
                        **serializer.data,
                        'message': '服务器已存在Agent，无需重新安装'
                    }, status=status.HTTP_201_CREATED)
            except Agent.DoesNotExist:
                # Agent不存在，需要安装
                pass
            
            # 创建部署任务（和Agent重新部署一样）
            from apps.deployments.models import Deployment
            from django.utils import timezone
            
            deployment = Deployment.objects.create(
                name=f"安装Agent - {server.name}",
                server=server,
                deployment_type='agent',
                connection_method='ssh',  # 首次安装使用SSH
                deployment_target=server.deployment_target or 'host',
                status='running',
                started_at=timezone.now(),
                created_by=request.user
            )
            
            # 记录Agent安装开始日志
            create_log_entry(
                log_type='agent',
                level='info',
                title=f'开始安装Agent: {server.name}',
                content=f'开始通过SSH安装Agent到服务器 {server.name}，部署任务ID: {deployment.id}',
                user=request.user,
                server=server,
                related_id=deployment.id,
                related_type='deployment'
            )
            
            # 保存原始连接方式（安装Agent时可能需要临时使用SSH）
            original_connection_method = server.connection_method
            
            # 在后台线程中安装Agent，不阻塞响应
            # 保存save_password标志，用于安装完成后决定是否清空密码
            should_save_password = save_password
            
            def install_agent_async():
                try:
                    # 重新获取服务器对象（避免缓存问题）
                    server.refresh_from_db()
                    deployment.refresh_from_db()
                    
                    # 如果连接方式选择为Agent，临时设置为SSH以便安装
                    if server.connection_method == 'agent':
                        server.connection_method = 'ssh'
                        server.save()
                    
                    # 使用和Agent重新部署相同的方式：通过SSH安装Agent
                    from apps.deployments.tasks import install_agent_via_ssh, wait_for_agent_startup
                    
                    deployment.log = (deployment.log or '') + f"[开始] 开始通过SSH安装Agent到服务器 {server.name}\n"
                    deployment.save()
                    
                    # 通过SSH安装Agent
                    if not install_agent_via_ssh(server, deployment):
                        deployment.status = 'failed'
                        deployment.error_message = 'Agent安装失败'
                        deployment.completed_at = timezone.now()
                        deployment.save()
                        
                        # 更新服务器状态
                        server.refresh_from_db()
                        server.status = 'error'
                        if original_connection_method == 'agent':
                            server.connection_method = 'ssh'
                        server.save()
                        
                        # 记录Agent安装失败日志
                        create_log_entry(
                            log_type='agent',
                            level='error',
                            title=f'Agent安装失败: {server.name}',
                            content=f'Agent安装失败，部署任务ID: {deployment.id}',
                            user=request.user,
                            server=server,
                            related_id=deployment.id,
                            related_type='deployment'
                        )
                        
                        # 如果用户选择了保存密码，保留密码；否则也保留密码以便重试
                        server.refresh_from_db()
                        if should_save_password:
                            server.save_password = True
                            server.save()
                            logger.info(f'Agent安装失败，保留密码（用户选择了保存密码）: server_id={server.id}')
                        else:
                            # 即使未选择保存密码，安装失败时也保留密码以便重试
                            server.save_password = False
                            server.save()
                            logger.info(f'Agent安装失败，保留密码以便重试: server_id={server.id}')
                        return
                    
                    # 等待Agent启动
                    deployment.log = (deployment.log or '') + "等待Agent启动...\n"
                    deployment.save()
                    
                    agent = wait_for_agent_startup(server, timeout=120, deployment=deployment)
                    if not agent or not agent.rpc_supported:
                        deployment.status = 'failed'
                        deployment.error_message = 'Agent启动超时或RPC不支持'
                        deployment.completed_at = timezone.now()
                        deployment.save()
                        
                        # 更新服务器状态
                        server.refresh_from_db()
                        server.status = 'error'
                        if original_connection_method == 'agent':
                            server.connection_method = 'ssh'
                        server.save()
                        
                        # 记录Agent启动超时日志
                        create_log_entry(
                            log_type='agent',
                            level='error',
                            title=f'Agent启动超时: {server.name}',
                            content=f'Agent安装完成但启动超时或RPC不支持，部署任务ID: {deployment.id}',
                            user=request.user,
                            server=server,
                            related_id=deployment.id,
                            related_type='deployment'
                        )
                        
                        # 如果用户选择了保存密码，保留密码；否则也保留密码以便重试
                        server.refresh_from_db()
                        if should_save_password:
                            server.save_password = True
                            server.save()
                            logger.info(f'Agent启动失败，保留密码（用户选择了保存密码）: server_id={server.id}')
                        else:
                            # 即使未选择保存密码，启动失败时也保留密码以便重试
                            server.save_password = False
                            server.save()
                            logger.info(f'Agent启动失败，保留密码以便重试: server_id={server.id}')
                        return
                    
                    deployment.log = (deployment.log or '') + f"Agent已注册，Token: {agent.token}\n"
                    deployment.status = 'success'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    
                    # 更新服务器状态
                    server.refresh_from_db()
                    server.status = 'active'
                    
                    # 如果原始连接方式选择为Agent，安装成功后切换为Agent
                    if original_connection_method == 'agent':
                        server.connection_method = 'agent'
                    # 如果原始连接方式为SSH，保持SSH（但Agent已安装，可以随时切换）
                    
                    server.save()
                    
                    # 自动配置 Agent 域名（如果服务器还没有域名）
                    try:
                        from apps.servers.server_domain_utils import auto_setup_server_agent_domain
                        result = auto_setup_server_agent_domain(
                            server=server,
                            auto_setup=True
                        )
                        if result.get('success'):
                            domain = result.get('domain')
                            deployment.log = (deployment.log or '') + f"\n[域名] Agent 域名自动配置成功: {domain}\n"
                            deployment.save()
                            logger.info(f'Agent 域名自动配置成功: server_id={server.id}, domain={domain}')
                        elif not result.get('skipped'):
                            # 配置失败但不影响安装成功状态
                            error_msg = result.get('error', '未知错误')
                            deployment.log = (deployment.log or '') + f"\n[域名] Agent 域名自动配置失败: {error_msg}\n"
                            deployment.save()
                            logger.warning(f'Agent 域名自动配置失败: server_id={server.id}, error={error_msg}')
                    except Exception as e:
                        # 域名配置失败不影响安装成功状态
                        logger.warning(f'Agent 域名自动配置时出错: {str(e)}', exc_info=True)
                        deployment.log = (deployment.log or '') + f"\n[域名] Agent 域名自动配置时出错: {str(e)}\n"
                        deployment.save()
                    
                    # 记录Agent安装成功日志
                    create_log_entry(
                        log_type='agent',
                        level='success',
                        title=f'Agent安装成功: {server.name}',
                        content=f'Agent已成功安装并注册，Token: {agent.token}，部署任务ID: {deployment.id}',
                        user=request.user,
                        server=server,
                        related_id=deployment.id,
                        related_type='deployment'
                    )
                    
                    # 如果用户选择了保存密码，保留密码；否则删除密码
                    server.refresh_from_db()
                    if should_save_password:
                        server.save_password = True
                        server.save()
                        logger.info(f'Agent安装成功，保留密码（用户选择了保存密码）: server_id={server.id}')
                    else:
                        server.password = None
                        server.private_key = None
                        server.save_password = False
                        server.save()
                        # 记录密码清理日志
                        create_log_entry(
                            log_type='server',
                            level='info',
                            title=f'已清理密码: {server.name}',
                            content=f'Agent安装成功，已清理服务器密码（未选择保存密码）',
                            user=request.user,
                            server=server
                        )
                except Exception as e:
                    # 安装异常，记录错误但保持服务器创建
                    import traceback
                    server.refresh_from_db()
                    deployment.refresh_from_db()
                    server.status = 'error'
                    deployment.status = 'failed'
                    deployment.error_message = f'安装异常: {str(e)}'
                    deployment.completed_at = timezone.now()
                    deployment.save()
                    # 如果原始连接方式为Agent但安装失败，保持为SSH
                    if original_connection_method == 'agent':
                        server.connection_method = 'ssh'
                    
                    # 如果用户选择了保存密码，保留密码；否则也保留密码以便重试
                    if should_save_password:
                        server.save_password = True
                        server.save()
                        logger.info(f'Agent安装异常，保留密码（用户选择了保存密码）: server_id={server.id}')
                    else:
                        # 即使未选择保存密码，安装异常时也保留密码以便重试
                        server.save_password = False
                        server.save()
                        logger.info(f'Agent安装异常，保留密码以便重试: server_id={server.id}')
                    
                    # 记录Agent安装异常日志
                    create_log_entry(
                        log_type='agent',
                        level='error',
                        title=f'Agent安装异常: {server.name}',
                        content=f'Agent安装过程中发生异常: {str(e)}\n部署任务ID: {deployment.id}',
                        user=request.user,
                        server=server,
                        related_id=deployment.id,
                        related_type='deployment'
                    )
                    
                    # 如果已清理密码，记录日志
                    if not should_save_password:
                        create_log_entry(
                            log_type='server',
                            level='info',
                            title=f'已清理密码: {server.name}',
                            content=f'Agent安装异常，已清理服务器密码（未选择保存密码）',
                            user=request.user,
                            server=server
                        )
            
            # 启动后台线程安装Agent
            thread = threading.Thread(target=install_agent_async, daemon=True)
            thread.start()
            
            # 返回响应，提示Agent正在安装，并返回部署任务ID
            return Response({
                **serializer.data,
                'message': '服务器已创建，Agent正在后台安装中，请查看部署任务',
                'deployment_id': deployment.id
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """更新服务器，处理密码保存和SSH key生成"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # 如果服务器名为空，使用host作为默认值
        data = request.data.copy()
        if not data.get('name', '').strip():
            data['name'] = data.get('host', instance.host) or '未命名服务器'
        
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        save_password = request.data.get('save_password', False)
        enable_ssh_key = request.data.get('enable_ssh_key', False)
        password = request.data.get('password', '')
        
        # 如果未开启保存密码，清空密码
        if not save_password:
            serializer.validated_data['password'] = None
        
        # 更新服务器
        server = serializer.save()
        
        # 记录服务器更新日志
        create_log_entry(
            log_type='server',
            level='info',
            title=f'更新服务器: {server.name}',
            content=f'服务器信息已更新',
            user=request.user,
            server=server
        )
        
        # 如果启用SSH key登录且提供了密码，生成key并添加到服务器
        if enable_ssh_key and password:
            try:
                result = self._generate_and_add_ssh_key(server, password)
                if result['success']:
                    server.generated_public_key = result['public_key']
                    server.save()
                    # 记录SSH key生成日志
                    create_log_entry(
                        log_type='server',
                        level='success',
                        title=f'SSH Key已生成并添加到服务器: {server.name}',
                        content=f'SSH Key已成功生成并添加到服务器 {server.name}',
                        user=request.user,
                        server=server
                    )
            except Exception as e:
                create_log_entry(
                    log_type='server',
                    level='error',
                    title=f'SSH Key生成失败: {server.name}',
                    content=f'SSH Key生成失败: {str(e)}',
                    user=request.user,
                    server=server
                )
        
        return Response(serializer.data)

    def _generate_and_add_ssh_key(self, server, password):
        """生成SSH key并添加到服务器"""
        try:
            # 生成SSH key对
            key = paramiko.RSAKey.generate(2048)
            
            # 获取公钥
            public_key = f"{key.get_name()} {key.get_base64()}"
            
            # 获取私钥
            private_key_str = StringIO()
            key.write_private_key(private_key_str)
            private_key_content = private_key_str.getvalue()
            
            # 保存私钥到服务器对象
            server.private_key = private_key_content
            server.save()
            
            # 通过SSH连接，添加公钥到服务器的authorized_keys
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            try:
                ssh.connect(
                    server.host,
                    port=server.port,
                    username=server.username,
                    password=password,
                    timeout=10
                )
                
                # 确保.ssh目录存在
                ssh.exec_command('mkdir -p ~/.ssh && chmod 700 ~/.ssh')
                
                # 读取现有的authorized_keys
                stdin, stdout, stderr = ssh.exec_command('cat ~/.ssh/authorized_keys 2>/dev/null || echo ""')
                existing_keys = stdout.read().decode().strip()
                
                # 检查公钥是否已存在
                if public_key not in existing_keys:
                    # 添加新公钥
                    if existing_keys:
                        new_keys = existing_keys + '\n' + public_key
                    else:
                        new_keys = public_key
                    
                    # 写入authorized_keys
                    sftp = ssh.open_sftp()
                    try:
                        with sftp.file('~/.ssh/authorized_keys', 'w') as f:
                            f.write(new_keys)
                    except:
                        # 如果文件不存在，创建它
                        stdin, stdout, stderr = ssh.exec_command(f'echo "{new_keys}" > ~/.ssh/authorized_keys')
                        stdout.channel.recv_exit_status()
                    
                    # 设置正确的权限
                    ssh.exec_command('chmod 600 ~/.ssh/authorized_keys')
                    sftp.close()
                
                ssh.close()
                
                return {
                    'success': True,
                    'public_key': public_key,
                    'message': 'SSH key已成功添加到服务器'
                }
            except Exception as e:
                ssh.close()
                return {
                    'success': False,
                    'error': f'添加SSH key到服务器失败: {str(e)}'
                }
        except Exception as e:
            return {
                'success': False,
                'error': f'生成SSH key失败: {str(e)}'
            }

