import secrets
import logging
from datetime import datetime, timedelta
from pathlib import Path
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from .models import Agent, CommandTemplate
from .serializers import (
    AgentSerializer, AgentRegisterSerializer,
    AgentHeartbeatSerializer, AgentCommandSerializer,
    AgentCommandDetailSerializer, CommandTemplateSerializer
)
from apps.servers.models import Server
from apps.logs.utils import create_log_entry

logger = logging.getLogger(__name__)


def get_agent_by_token(token):
    """
    通过token查找Agent，自动处理UUID格式转换（带连字符/不带连字符）
    """
    import uuid
    # 先尝试直接查询
    try:
        return Agent.objects.get(token=token)
    except Agent.DoesNotExist:
        # 如果直接查询失败，尝试格式转换
        try:
            # 如果token是带连字符的UUID格式，转换为不带连字符的格式
            if '-' in token:
                uuid_obj = uuid.UUID(token)
                token_hex = uuid_obj.hex
                return Agent.objects.get(token=token_hex)
            else:
                # 如果token是不带连字符的格式，尝试转换为带连字符的格式
                uuid_obj = uuid.UUID(token)
                token_with_dash = str(uuid_obj)
                return Agent.objects.get(token=token_with_dash)
        except (ValueError, Agent.DoesNotExist):
            raise Agent.DoesNotExist(f"Agent with token '{token}' does not exist")


class AgentViewSet(viewsets.ReadOnlyModelViewSet):
    """Agent视图集"""
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer

    def get_queryset(self):
        # 只返回当前用户创建的服务器关联的 Agent
        return Agent.objects.filter(server__created_by=self.request.user)

    @action(detail=True, methods=['patch'])
    def update_heartbeat_mode(self, request, pk=None):
        """更新Agent心跳模式"""
        agent = self.get_object()
        heartbeat_mode = request.data.get('heartbeat_mode')
        
        if heartbeat_mode not in ['push', 'pull']:
            return Response({'error': '心跳模式必须是push或pull'}, status=status.HTTP_400_BAD_REQUEST)
        
        old_mode = agent.heartbeat_mode
        agent.heartbeat_mode = heartbeat_mode
        agent.save()
        
        # 记录心跳模式更新日志
        create_log_entry(
            log_type='agent',
            level='info',
            title=f'更新Agent心跳模式: {agent.server.name}',
            content=f'心跳模式从 {old_mode} 更新为 {heartbeat_mode}',
            user=request.user,
            server=agent.server,
            related_id=agent.id,
            related_type='agent'
        )
        
        serializer = self.get_serializer(agent)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def send_command(self, request, pk=None):
        """下发命令到Agent"""
        agent = self.get_object()
        command = request.data.get('command')
        args = request.data.get('args', [])
        timeout = request.data.get('timeout', 300)

        if not command:
            return Response({'error': '命令不能为空'}, status=status.HTTP_400_BAD_REQUEST)

        from .command_queue import CommandQueue
        cmd = CommandQueue.add_command(agent, command, args, timeout)
        
        # 记录命令下发日志
        create_log_entry(
            log_type='command',
            level='info',
            title=f'下发命令到Agent: {agent.server.name}',
            content=f'命令: {command} {", ".join(str(arg) for arg in args) if args else ""}\n超时: {timeout}秒',
            user=request.user,
            server=agent.server,
            related_id=cmd.id,
            related_type='command'
        )

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def update_certificate(self, request, pk=None):
        """更新Agent的SSL证书"""
        agent = self.get_object()
        
        # 检查是否提供新证书
        regenerate = request.data.get('regenerate', False)
        verify_ssl = request.data.get('verify_ssl', agent.verify_ssl)
        
        try:
            if regenerate:
                # 重新生成证书
                from apps.deployments.tasks import generate_ssl_certificate
                cert_bytes, key_bytes = generate_ssl_certificate(agent.server.host, agent.token)
                agent.certificate_content = cert_bytes.decode('utf-8')
                agent.private_key_content = key_bytes.decode('utf-8')
                agent.verify_ssl = verify_ssl
                agent.save()
                
                # 如果Agent在线，上传新证书到Agent服务器
                if agent.status == 'online' and agent.rpc_port:
                    try:
                        from apps.agents.rpc_client import get_agent_rpc_client
                        from apps.agents.utils import execute_script_via_agent
                        
                        # 创建上传证书的脚本（使用base64编码避免特殊字符问题）
                        import base64
                        cert_b64 = base64.b64encode(agent.certificate_content.encode('utf-8')).decode('ascii')
                        key_b64 = base64.b64encode(agent.private_key_content.encode('utf-8')).decode('ascii')
                        
                        upload_script = f"""#!/usr/bin/env python3
import os
import sys
import base64

# 创建SSL目录
os.makedirs('/etc/myx-agent/ssl', exist_ok=True)

# 解码并写入证书
cert_b64 = '{cert_b64}'
cert_content = base64.b64decode(cert_b64).decode('utf-8')
with open('/etc/myx-agent/ssl/agent.crt', 'w') as f:
    f.write(cert_content)
os.chmod('/etc/myx-agent/ssl/agent.crt', 0o644)

# 解码并写入私钥
key_b64 = '{key_b64}'
key_content = base64.b64decode(key_b64).decode('utf-8')
with open('/etc/myx-agent/ssl/agent.key', 'w') as f:
    f.write(key_content)
os.chmod('/etc/myx-agent/ssl/agent.key', 0o600)

print("[成功] SSL证书已更新")
sys.exit(0)
"""
                        
                        # 通过RPC执行脚本
                        cmd = execute_script_via_agent(agent, upload_script, timeout=30, script_name='update_certificate.py')
                        
                        # 等待命令完成
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
                            logger.info(f'Agent证书已更新并上传: agent_id={agent.id}')
                            # 重启Agent服务以使用新证书
                            from apps.agents.command_queue import CommandQueue
                            CommandQueue.add_command(agent, 'systemctl', ['restart', 'myx-agent'], timeout=30)
                        else:
                            logger.warning(f'Agent证书更新失败: agent_id={agent.id}, error={cmd.error}')
                    except Exception as e:
                        logger.error(f'上传证书到Agent失败: {e}', exc_info=True)
                
                # 记录日志
                create_log_entry(
                    log_type='agent',
                    level='info',
                    title=f'更新Agent SSL证书: {agent.server.name}',
                    content=f'SSL证书已重新生成并{'已上传到Agent服务器' if agent.status == 'online' else '等待Agent上线后上传'}',
                    user=request.user,
                    server=agent.server,
                    related_id=agent.id,
                    related_type='agent'
                )
                
                serializer = self.get_serializer(agent)
                return Response({
                    'success': True,
                    'message': '证书已重新生成',
                    'agent': serializer.data
                })
            else:
                # 只更新verify_ssl选项
                agent.verify_ssl = verify_ssl
                agent.save()
                
                # 记录日志
                create_log_entry(
                    log_type='agent',
                    level='info',
                    title=f'更新Agent SSL验证选项: {agent.server.name}',
                    content=f'SSL验证选项已更新为: {verify_ssl}',
                    user=request.user,
                    server=agent.server,
                    related_id=agent.id,
                    related_type='agent'
                )
                
                serializer = self.get_serializer(agent)
                return Response({
                    'success': True,
                    'message': 'SSL验证选项已更新',
                    'agent': serializer.data
                })
        except Exception as e:
            logger.error(f'更新Agent证书失败: {e}', exc_info=True)
            return Response({
                'error': f'更新证书失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """重新部署Agent"""
        agent = self.get_object()
        server = agent.server

        # 创建部署任务
        from apps.deployments.models import Deployment
        from django.utils import timezone
        
        deployment = Deployment.objects.create(
            name=f"重新部署Agent - {server.name}",
            server=server,
            deployment_type='agent',
            connection_method='agent' if (server.connection_method == 'agent' and agent.status == 'online') else 'ssh',
            deployment_target=server.deployment_target or 'host',
            status='running',
            started_at=timezone.now(),
            created_by=request.user
        )

        # 根据服务器连接方式选择部署方法
        if server.connection_method == 'agent' and agent.status == 'online':
            # 如果已经是Agent连接且Agent在线，通过Agent执行重新部署
            from .command_queue import CommandQueue
            from django.conf import settings
            import os
            import time
            
            # 获取API URL用于上报进度和下载文件
            api_url = os.getenv('AGENT_API_URL', getattr(settings, 'AGENT_API_URL', None))
            if not api_url:
                # 从request构建API URL
                scheme = 'https' if request.is_secure() else 'http'
                host = request.get_host()
                api_url = f"{scheme}://{host}/api/agents"
            
            # 从模板文件加载脚本
            script_template_path = os.path.join(
                os.path.dirname(__file__),
                'scripts',
                'agent_redeploy.sh.template'
            )
            with open(script_template_path, 'r', encoding='utf-8') as f:
                redeploy_script = f.read()
            
            # 替换占位符（注意顺序：先替换 DEPLOYMENT_ID，因为 LOG_FILE 中也包含它）
            redeploy_script = redeploy_script.replace('{DEPLOYMENT_ID}', str(deployment.id))
            redeploy_script = redeploy_script.replace('{API_URL}', api_url)
            redeploy_script = redeploy_script.replace('{AGENT_TOKEN}', str(agent.token))
            
            # 使用deployment_id作为日志文件路径的唯一标识
            log_file = f'/tmp/agent_redeploy_{deployment.id}.log'
            script_file = f'/tmp/agent_redeploy_script_{deployment.id}.sh'
            
            # 生成唯一的服务名称
            service_name = f'myx-agent-redeploy-{deployment.id}-{int(time.time())}'
            
            # 构建部署命令：使用heredoc写入脚本文件，然后使用systemd-run执行
            # 使用单引号包裹heredoc标记，避免脚本内容中的特殊字符被shell解析
            deploy_command = f'''bash -c 'cat > "{script_file}" << '\''SCRIPT_EOF'\''
{redeploy_script}
SCRIPT_EOF
chmod +x "{script_file}"
systemd-run --unit={service_name} --service-type=oneshot --no-block --property=StandardOutput=file:{log_file} --property=StandardError=file:{log_file} bash "{script_file}"
echo $?' '''
            
            logger.info(f'[redeploy] 创建重新部署命令: deployment_id={deployment.id}, script_file={script_file}, log_file={log_file}')
            logger.debug(f'[redeploy] 命令长度: {len(deploy_command)} 字符')
            
            # 使用systemd-run创建临时服务执行脚本，确保独立于Agent进程运行
            cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', deploy_command],
                timeout=600
            )
            
            logger.info(f'[redeploy] 命令已添加到队列: command_id={cmd.id}, agent_id={agent.id}')
            
            # 不需要启动单独的监控线程，全局调度器会自动检查
            # 初始化部署日志
            deployment.log = f"[开始] Agent重新部署已启动，命令ID: {cmd.id}\n"
            deployment.log += f"[信息] 日志文件: {log_file}\n"
            deployment.log += f"[信息] 脚本文件: {script_file}\n"
            deployment.save()
            
            # 记录Agent重新部署开始日志
            create_log_entry(
                log_type='agent',
                level='info',
                title=f'开始重新部署Agent: {server.name}',
                content=f'Agent重新部署已启动，部署任务ID: {deployment.id}，命令ID: {cmd.id}',
                user=request.user,
                server=server,
                related_id=deployment.id,
                related_type='deployment'
            )
            
            return Response({
                'message': 'Agent重新部署已启动，请查看部署任务',
                'deployment_id': deployment.id,
                'command_id': cmd.id
            }, status=status.HTTP_202_ACCEPTED)
        
        # 使用SSH重新部署（如果Agent不在线或未配置Agent连接）
        # 检查服务器是否有SSH凭据
        if not server.password and not server.private_key:
            # 部署任务已创建，更新状态为失败
            deployment.status = 'failed'
            deployment.error_message = '服务器缺少SSH凭据，无法重新部署。请先配置SSH密码或私钥。'
            deployment.completed_at = timezone.now()
            deployment.save()
            return Response({'error': '服务器缺少SSH凭据，无法重新部署。请先配置SSH密码或私钥。'}, status=status.HTTP_400_BAD_REQUEST)

        # 异步执行部署
        from apps.deployments.tasks import install_agent_via_ssh
        import threading
        def _deploy():
            try:
                install_agent_via_ssh(server, deployment)
                # 等待Agent启动
                from apps.deployments.tasks import wait_for_agent_startup
                agent = wait_for_agent_startup(server, timeout=60, deployment=deployment)
                if agent and agent.rpc_supported:
                    deployment.status = 'success'
                    deployment.completed_at = timezone.now()
                else:
                    deployment.status = 'failed'
                    deployment.error_message = 'Agent启动超时或RPC不支持'
                    deployment.completed_at = timezone.now()
            except Exception as e:
                deployment.status = 'failed'
                deployment.error_message = f'部署失败: {str(e)}'
                deployment.completed_at = timezone.now()
            finally:
                deployment.save()

        thread = threading.Thread(target=_deploy)
        thread.daemon = True
        thread.start()
        
        # 记录Agent重新部署开始日志（通过SSH）
        create_log_entry(
            log_type='agent',
            level='info',
            title=f'开始重新部署Agent（通过SSH）: {server.name}',
            content=f'Agent重新部署已启动（通过SSH），部署任务ID: {deployment.id}',
            user=request.user,
            server=server,
            related_id=deployment.id,
            related_type='deployment'
        )

        return Response({
            'message': 'Agent重新部署已启动（通过SSH）',
            'deployment_id': deployment.id
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止Agent服务"""
        agent = self.get_object()

        from .command_queue import CommandQueue
        cmd = CommandQueue.add_command(
            agent=agent,
            command='systemctl',
            args=['stop', 'myx-agent'],
            timeout=30
        )
        
        # 记录停止Agent命令日志
        create_log_entry(
            log_type='agent',
            level='info',
            title=f'停止Agent服务: {agent.server.name}',
            content=f'停止Agent服务命令已下发，命令ID: {cmd.id}',
            user=request.user,
            server=agent.server,
            related_id=cmd.id,
            related_type='command'
        )

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response({
            'message': '停止Agent命令已下发',
            'command': serializer.data
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """启动Agent服务"""
        agent = self.get_object()

        from .command_queue import CommandQueue
        cmd = CommandQueue.add_command(
            agent=agent,
            command='systemctl',
            args=['start', 'myx-agent'],
            timeout=30
        )
        
        # 记录启动Agent命令日志
        create_log_entry(
            log_type='agent',
            level='info',
            title=f'启动Agent服务: {agent.server.name}',
            content=f'启动Agent服务命令已下发，命令ID: {cmd.id}',
            user=request.user,
            server=agent.server,
            related_id=cmd.id,
            related_type='command'
        )

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response({
            'message': '启动Agent命令已下发',
            'command': serializer.data
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def commands(self, request, pk=None):
        """获取Agent的命令历史"""
        agent = self.get_object()
        from .models import AgentCommand
        commands = AgentCommand.objects.filter(agent=agent).order_by('-created_at')[:50]

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(commands, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def check_status(self, request, pk=None):
        """手动检查Agent状态（拉取模式）"""
        agent = self.get_object()
        
        if agent.heartbeat_mode != 'pull':
            return Response({'error': '此Agent不是拉取模式'}, status=status.HTTP_400_BAD_REQUEST)
        
        from .tasks import check_agent_status
        # 只检查这个Agent
        try:
            server = agent.server
            connect_host = server.agent_connect_host or server.host
            connect_port = server.agent_connect_port or 8000
            
            import requests
            health_url = f"http://{connect_host}:{connect_port}/health"
            response = requests.get(health_url, timeout=5)
            
            if response.status_code == 200:
                agent.status = 'online'
                agent.last_check = timezone.now()
                agent.last_heartbeat = timezone.now()
            else:
                agent.status = 'offline'
                agent.last_check = timezone.now()
        except Exception as e:
            agent.status = 'offline'
            agent.last_check = timezone.now()
        
        agent.save()
        
        serializer = self.get_serializer(agent)
        return Response(serializer.data)


class CommandTemplateViewSet(viewsets.ModelViewSet):
    """命令模板视图集"""
    queryset = CommandTemplate.objects.all()
    serializer_class = CommandTemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CommandTemplate.objects.filter(created_by=self.request.user)


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_register(request):
    """Agent注册接口"""
    logger.info(f'[agent_register] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}')
    serializer = AgentRegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    server_token = serializer.validated_data['server_token']
    
    try:
        # 通过server的id查找服务器
        # server_token可以是UUID字符串或整数ID
        import uuid
        try:
            # 尝试作为UUID解析
            server_id = uuid.UUID(str(server_token))
            server = Server.objects.get(id=server_id)
        except (ValueError, Server.DoesNotExist):
            # 如果不是UUID，尝试作为整数ID
            try:
                server = Server.objects.get(id=int(server_token))
            except (ValueError, Server.DoesNotExist):
                return Response({'error': '服务器不存在'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'查找服务器失败: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

    # 检查是否已有Agent
    # 获取心跳模式（从服务器配置或默认值）
    heartbeat_mode = 'push'  # 默认推送模式
    # 如果服务器已有Agent，使用现有心跳模式；否则使用默认值
    try:
        existing_agent = Agent.objects.get(server=server)
        heartbeat_mode = existing_agent.heartbeat_mode
    except Agent.DoesNotExist:
        pass
    
    # 生成随机RPC端口（如果不存在）
    import random
    import socket
    def generate_rpc_port():
        excluded_ports = {22, 80, 443, 8000, 8443, 3306, 5432, 6379, 8080, 9000}
        for _ in range(100):
            port = random.randint(8000, 65535)
            if port in excluded_ports:
                continue
            # 检查端口是否已被使用
            try:
                existing = Agent.objects.filter(rpc_port=port).exists()
                if existing:
                    continue
            except:
                pass
            return port
        return None
    
    agent, created = Agent.objects.get_or_create(
        server=server,
        defaults={
            'token': secrets.token_urlsafe(32),  # 生成token
            'secret_key': secrets.token_urlsafe(32),  # 生成加密密钥
            'status': 'online',
            'version': serializer.validated_data.get('version', ''),
            'last_heartbeat': timezone.now(),
            'heartbeat_mode': heartbeat_mode,
            'web_service_enabled': True,  # 默认启用Web服务
            'web_service_port': 8443,  # 默认端口
            'rpc_port': generate_rpc_port()  # 生成随机RPC端口
        }
    )
    
    # 如果Agent已存在但没有token或secret_key，生成它们
    if not agent.token:
        import uuid
        agent.token = uuid.uuid4().hex
    if not agent.secret_key:
        agent.secret_key = secrets.token_urlsafe(32)
    if not agent.token or not agent.secret_key:
        agent.save()

    if not created:
        # 更新现有Agent
        agent.status = 'online'
        agent.last_heartbeat = timezone.now()
        if serializer.validated_data.get('version'):
            agent.version = serializer.validated_data['version']
        # 如果RPC端口未设置，生成一个（但不会更改已存在的端口）
        if not agent.rpc_port:
            agent.rpc_port = generate_rpc_port()
        # 保持现有心跳模式，不覆盖
        agent.save()
        
        # 记录Agent重新注册日志
        create_log_entry(
            log_type='agent',
            level='info',
            title=f'Agent重新注册: {server.name}',
            content=f'Agent已重新注册，Token: {agent.token}',
            user=server.created_by,
            server=server,
            related_id=agent.id,
            related_type='agent'
        )
    else:
        # 记录Agent首次注册日志
        create_log_entry(
            log_type='agent',
            level='success',
            title=f'Agent注册成功: {server.name}',
            content=f'Agent首次注册成功，Token: {agent.token}，版本: {agent.version or "未知"}',
            user=server.created_by,
            server=server,
            related_id=agent.id,
            related_type='agent'
        )

    # 确保secret_key存在
    if not agent.secret_key:
        agent.secret_key = secrets.token_urlsafe(32)
        agent.save(update_fields=['secret_key'])
    
    return Response({
        'token': str(agent.token),
        'secret_key': agent.secret_key,  # 返回加密密钥
        'server_id': server.id,
        'heartbeat_mode': agent.heartbeat_mode  # 返回心跳模式
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_heartbeat(request):
    """Agent心跳接口"""
    logger.info(f'[agent_heartbeat] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}')
    
    token = request.headers.get('X-Agent-Token')
    token_display = token[:10] + "..." if token and len(token) > 10 else (token or "None")
    logger.info(f'[agent_heartbeat] Token: {token_display}')
    
    if not token:
        logger.warning('[agent_heartbeat] ✗ 缺少Agent Token - 返回401 Unauthorized')
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
        logger.info(f'[agent_heartbeat] ✓ Agent找到: ID={agent.id}, Server={agent.server.name if agent.server else "None"}')
    except Agent.DoesNotExist:
        logger.error(f'[agent_heartbeat] ✗ Agent不存在 - Token: {token_display} - 返回404（这是视图函数返回的404，不是路由404！URL匹配成功）')
        return Response({'error': 'Agent不存在', 'detail': f'Token: {token_display}', 'note': '这是视图函数返回的404，URL匹配成功'}, status=status.HTTP_404_NOT_FOUND)

    serializer = AgentHeartbeatSerializer(data=request.data)
    if serializer.is_valid():
        if serializer.validated_data.get('status'):
            agent.status = serializer.validated_data['status']
        if serializer.validated_data.get('version'):
            agent.version = serializer.validated_data['version']
    
    # 处理RPC端口（从请求数据中获取，如果提供）
    rpc_port = request.data.get('rpc_port')
    if rpc_port and not agent.rpc_port:
        # 只有在端口未设置时才设置（不可更改已存在的端口）
        agent.rpc_port = rpc_port
        logger.info(f"Agent {agent.id} 设置RPC端口: {rpc_port}")

    agent.last_heartbeat = timezone.now()
    agent.status = 'online'
    agent.save()

    # 检查是否有待执行的命令
    from .command_queue import CommandQueue
    from .models import AgentCommand
    pending_count = AgentCommand.objects.filter(agent=agent, status='pending').count()
    
    # 返回配置信息
    from django.conf import settings
    response_data = {
        'status': 'ok',
        'heartbeat_mode': agent.heartbeat_mode,  # 返回心跳模式
        'config': {
            'heartbeat_min_interval': getattr(settings, 'AGENT_HEARTBEAT_MIN_INTERVAL', 30),
            'heartbeat_max_interval': getattr(settings, 'AGENT_HEARTBEAT_MAX_INTERVAL', 300),
            'poll_min_interval': getattr(settings, 'AGENT_POLL_MIN_INTERVAL', 5),
            'poll_max_interval': getattr(settings, 'AGENT_POLL_MAX_INTERVAL', 60),
        }
    }
    
    # 如果有待执行的命令，告诉Agent立即轮询（不返回命令，让Agent通过轮询获取）
    if pending_count > 0:
        logger.info(f'[agent_heartbeat] Agent {agent.id} 心跳时发现 {pending_count} 条待执行命令，通知立即轮询')
        response_data['urgent_poll'] = True  # 标志：需要立即轮询
        # 部署时加速轮询：临时缩短轮询间隔
        response_data['config']['poll_min_interval'] = 1  # 部署时最短1秒
        response_data['config']['poll_max_interval'] = 3   # 部署时最长3秒
    
    return Response(response_data)


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_command(request):
    """Agent命令执行接口"""
    logger.info(f'[agent_command] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}')
    token = request.headers.get('X-Agent-Token')
    token_display = token[:10] + "..." if token and len(token) > 10 else (token or "None")
    logger.info(f'[agent_command] Token: {token_display}')
    
    if not token:
        logger.warning('[agent_command] ✗ 缺少Agent Token - 返回401 Unauthorized')
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
        logger.info(f'[agent_command] ✓ Agent找到: ID={agent.id}, Server={agent.server.name if agent.server else "None"}')
    except Agent.DoesNotExist:
        logger.error(f'[agent_command] ✗ Agent不存在 - Token: {token_display} - 返回404（这是视图函数返回的404，不是路由404！URL匹配成功）')
        return Response({'error': 'Agent不存在', 'detail': f'Token: {token_display}', 'note': '这是视图函数返回的404，URL匹配成功'}, status=status.HTTP_404_NOT_FOUND)

    serializer = AgentCommandSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # 这里返回命令，实际执行由Agent完成
    # Agent会轮询或通过WebSocket获取命令
    return Response({
        'command': serializer.validated_data['command'],
        'args': serializer.validated_data.get('args', []),
        'timeout': serializer.validated_data.get('timeout', 300)
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def agent_poll_commands(request):
    """Agent轮询命令接口"""
    logger.info(f'[agent_poll_commands] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}')
    
    token = request.headers.get('X-Agent-Token')
    token_display = token[:10] + "..." if token and len(token) > 10 else (token or "None")
    logger.info(f'[agent_poll_commands] Token: {token_display}')
    
    if not token:
        logger.warning('[agent_poll_commands] ✗ 缺少Agent Token - 返回401 Unauthorized')
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
        logger.info(f'[agent_poll_commands] ✓ Agent找到: ID={agent.id}, Server={agent.server.name if agent.server else "None"}')
    except Agent.DoesNotExist:
        logger.error(f'[agent_poll_commands] ✗ Agent不存在 - Token: {token_display} - 返回404（这是视图函数返回的404，不是路由404！URL匹配成功）')
        return Response({'error': 'Agent不存在', 'detail': f'Token: {token_display}', 'note': '这是视图函数返回的404，URL匹配成功'}, status=status.HTTP_404_NOT_FOUND)

    # 更新心跳
    agent.last_heartbeat = timezone.now()
    agent.status = 'online'
    agent.save()

    # 从命令队列获取待执行的命令
    from .command_queue import CommandQueue
    commands = CommandQueue.get_pending_commands(agent)

    # 调试：记录获取到的命令
    logger.info(f'[agent_poll_commands] Agent {agent.id} 获取到 {len(commands)} 条待执行命令')
    if commands:
        command_ids = [cmd['id'] for cmd in commands]
        logger.info(f'[agent_poll_commands] 命令ID列表: {command_ids}')

    # 返回命令和配置信息
    from django.conf import settings
    return Response({
        'commands': commands,
        'status': 'ok',
        'heartbeat_mode': agent.heartbeat_mode,  # 返回心跳模式
        'config': {
            'heartbeat_min_interval': getattr(settings, 'AGENT_HEARTBEAT_MIN_INTERVAL', 30),
            'heartbeat_max_interval': getattr(settings, 'AGENT_HEARTBEAT_MAX_INTERVAL', 300),
            'poll_min_interval': getattr(settings, 'AGENT_POLL_MIN_INTERVAL', 5),
            'poll_max_interval': getattr(settings, 'AGENT_POLL_MAX_INTERVAL', 60),
        }
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_command_result(request, command_id):
    """Agent命令执行结果接口"""
    logger.info(f'[agent_command_result] ✓ URL匹配成功 - 收到请求: {request.method} {request.path}, command_id={command_id}')
    token = request.headers.get('X-Agent-Token')
    token_display = token[:10] + "..." if token and len(token) > 10 else (token or "None")
    logger.info(f'[agent_command_result] Token: {token_display}')
    
    if not token:
        logger.warning('[agent_command_result] ✗ 缺少Agent Token - 返回401 Unauthorized')
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
        logger.info(f'[agent_command_result] ✓ Agent找到: ID={agent.id}, Server={agent.server.name if agent.server else "None"}')
    except Agent.DoesNotExist:
        logger.error(f'[agent_command_result] ✗ Agent不存在 - Token: {token_display} - 返回404（这是视图函数返回的404，不是路由404！URL匹配成功）')
        return Response({'error': 'Agent不存在', 'detail': f'Token: {token_display}', 'note': '这是视图函数返回的404，URL匹配成功'}, status=status.HTTP_404_NOT_FOUND)
    from .command_queue import CommandQueue
    
    success = request.data.get('success', False)
    result = request.data.get('stdout', '')
    error = request.data.get('error') or request.data.get('stderr', '')
    append = request.data.get('append', False)  # 默认为最终结果，不追加
    
    try:
        from .command_queue import CommandQueue
        from .models import AgentCommand
        cmd = AgentCommand.objects.get(id=command_id, agent=agent)
        CommandQueue.update_command_result(command_id, success, result, error, append=append)
        
        # 记录命令执行结果日志
        log_level = 'success' if success else 'error'
        log_title = f'命令执行{"成功" if success else "失败"}: {agent.server.name}'
        log_content = f'命令: {cmd.command} {", ".join(str(arg) for arg in cmd.args) if cmd.args else ""}\n'
        if success:
            # 不截断结果，完整显示（会自动解码base64）
            log_content += f'\n执行结果:\n{result}'
        else:
            # 不截断错误，完整显示（会自动解码base64）
            log_content += f'\n错误信息:\n{error}'
        
        create_log_entry(
            log_type='command',
            level=log_level,
            title=log_title,
            content=log_content,
            user=agent.server.created_by,
            server=agent.server,
            related_id=cmd.id,
            related_type='command',
            decode_base64=True  # 自动解码base64内容
        )
        
        return Response({'status': 'ok'})
    except Exception as e:
        logger.error(f'[agent_command_result] ✗ 错误: {str(e)}')
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_command_progress(request, command_id):
    """Agent命令执行进度接口（实时上报增量输出）"""
    logger.debug(f'[agent_command_progress] 收到命令进度更新: command_id={command_id}')
    token = request.headers.get('X-Agent-Token')
    
    if not token:
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent不存在'}, status=status.HTTP_404_NOT_FOUND)
    
    stdout = request.data.get('stdout', '')
    stderr = request.data.get('stderr', '')
    append = request.data.get('append', True)  # 默认为增量更新
    
    try:
        from .command_queue import CommandQueue
        from .models import AgentCommand
        cmd = AgentCommand.objects.get(id=command_id, agent=agent)
        
        # 更新命令结果（增量追加）
        CommandQueue.update_command_result(command_id, None, stdout, stderr, append=True)
        
        logger.debug(f'[agent_command_progress] 命令进度已更新: command_id={command_id}, stdout_len={len(stdout)}, stderr_len={len(stderr)}')
        
        return Response({'status': 'ok'})
    except AgentCommand.DoesNotExist:
        return Response({'error': '命令不存在'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f'[agent_command_progress] 错误: {str(e)}')
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def agent_report_progress(request, deployment_id):
    """Agent上报部署进度接口"""
    token = request.headers.get('X-Agent-Token')
    if not token:
        return Response({'error': '缺少Agent Token'}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        agent = get_agent_by_token(token)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent不存在'}, status=status.HTTP_404_NOT_FOUND)
    
    try:
        from apps.deployments.models import Deployment
        deployment = Deployment.objects.get(id=deployment_id, server=agent.server)
    except Deployment.DoesNotExist:
        return Response({'error': '部署任务不存在'}, status=status.HTTP_404_NOT_FOUND)
    
    # 更新部署日志
    progress_log = request.data.get('log', '')
    if progress_log:
        deployment.log = (deployment.log or '') + progress_log
        deployment.save()
    
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([AllowAny])  # Agent需要访问，所以允许匿名
def agent_file_download(request, filename):
    """提供Agent文件下载"""
    # 只允许下载特定文件（main.py已包含Web服务功能，不再需要单独的web_server.py）
    allowed_files = ['main.py', 'requirements.txt']
    if filename not in allowed_files:
        return Response({'error': '文件不存在'}, status=status.HTTP_404_NOT_FOUND)
    
    # 获取Agent文件路径（从deployment-tool目录）
    # __file__ 是 backend/apps/agents/views.py
    # 需要回到项目根目录: backend/apps/agents -> backend/apps -> backend -> 项目根
    base_dir = Path(__file__).resolve().parent.parent.parent
    agent_dir = base_dir / 'deployment-tool' / 'agent'
    file_path = agent_dir / filename
    
    if not file_path.exists():
        return Response({'error': '文件不存在'}, status=status.HTTP_404_NOT_FOUND)
    
    # 读取文件内容
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # 根据文件类型设置Content-Type
        if filename.endswith('.py'):
            content_type = 'text/x-python; charset=utf-8'
        elif filename.endswith('.txt'):
            content_type = 'text/plain; charset=utf-8'
        else:
            content_type = 'application/octet-stream'
        
        response = HttpResponse(content, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.error(f'下载Agent文件失败: {e}')
        return Response({'error': '文件读取失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

