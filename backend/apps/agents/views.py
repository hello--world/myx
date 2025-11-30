import secrets
import logging
from datetime import datetime, timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from .models import Agent, CommandTemplate
from .serializers import (
    AgentSerializer, AgentRegisterSerializer,
    AgentHeartbeatSerializer, AgentCommandSerializer,
    AgentCommandDetailSerializer, CommandTemplateSerializer
)
from apps.servers.models import Server

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
        
        agent.heartbeat_mode = heartbeat_mode
        agent.save()
        
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

        from .serializers import AgentCommandDetailSerializer
        serializer = AgentCommandDetailSerializer(cmd)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

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
            import threading
            
            github_repo = os.getenv('GITHUB_REPO', getattr(settings, 'GITHUB_REPO', 'hello--world/myx'))
            
            # 通过Agent执行重新部署脚本
            # 注意：脚本会在停止Agent前先完成下载和准备，然后快速替换并启动
            redeploy_script = f"""#!/bin/bash
set -e

# 检测系统
OS_NAME=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ARCH="amd64"
elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    ARCH="arm64"
fi

BINARY_NAME="myx-agent-${{OS_NAME}}-${{ARCH}}"
GITHUB_URL="https://github.com/{github_repo}/releases/download/latest/${{BINARY_NAME}}"

echo "[1/5] 正在从 GitHub 下载最新 Agent..."
if ! curl -L -f -o /tmp/myx-agent "${{GITHUB_URL}}"; then
    echo "Agent 下载失败"
    exit 1
fi

echo "[2/5] Agent 下载成功，准备替换..."
chmod +x /tmp/myx-agent

echo "[3/5] 正在停止Agent服务..."
systemctl stop myx-agent || true

echo "[4/5] 正在替换Agent二进制文件..."
mv /tmp/myx-agent /opt/myx-agent/myx-agent
chmod +x /opt/myx-agent/myx-agent

# 重新注册Agent（如果需要）
API_URL=$(grep -oP '"APIURL":\\s*"\\K[^"]+' /etc/myx-agent/config.json || echo "")
if [ -n "$API_URL" ]; then
    SERVER_TOKEN=$(grep -oP '"ServerToken":\\s*"\\K[^"]+' /etc/myx-agent/config.json || echo "")
    if [ -n "$SERVER_TOKEN" ]; then
        echo "[5/5] 正在启动Agent服务并重新注册..."
        systemctl start myx-agent
        sleep 2
        /opt/myx-agent/myx-agent -token "$SERVER_TOKEN" -api "$API_URL" || true
    else
        echo "[5/5] 正在启动Agent服务..."
        systemctl start myx-agent
    fi
else
    echo "[5/5] 正在启动Agent服务..."
    systemctl start myx-agent
fi

systemctl status myx-agent --no-pager || true
echo "Agent重新部署完成"
"""
            
            import base64
            script_b64 = base64.b64encode(redeploy_script.encode('utf-8')).decode('utf-8')
            cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
                timeout=600
            )

            # 启动后台线程监控命令执行（支持Agent重启场景）
            def _monitor_command():
                import time
                import logging
                logger = logging.getLogger(__name__)
                max_wait = 600  # 最多等待10分钟
                start_time = time.time()
                agent_offline_detected = False
                agent_offline_time = None
                
                while time.time() - start_time < max_wait:
                    try:
                        # 检查Agent状态
                        agent.refresh_from_db()
                        if agent.status == 'offline' and not agent_offline_detected:
                            agent_offline_detected = True
                            agent_offline_time = time.time()
                            deployment.log = (deployment.log or '') + f"\n[进度] Agent已停止，等待重新启动...\n"
                            deployment.save()
                        
                        # 如果Agent重新上线，继续监控
                        if agent_offline_detected and agent.status == 'online':
                            deployment.log = (deployment.log or '') + f"\n[进度] Agent已重新上线，继续监控...\n"
                            deployment.save()
                            agent_offline_detected = False
                            agent_offline_time = None
                        
                        # 检查命令状态
                        cmd.refresh_from_db()
                        if cmd.status in ['success', 'failed']:
                            # 命令执行完成，更新部署任务状态
                            deployment.log = (deployment.log or '') + f"\n[完成] 命令执行完成\n状态: {cmd.status}\n"
                            if cmd.result:
                                deployment.log = (deployment.log or '') + f"输出:\n{cmd.result}\n"
                            if cmd.error:
                                deployment.log = (deployment.log or '') + f"错误:\n{cmd.error}\n"
                            
                            if cmd.status == 'success':
                                deployment.status = 'success'
                            else:
                                deployment.status = 'failed'
                                deployment.error_message = cmd.error or '重新部署失败'
                            
                            deployment.completed_at = timezone.now()
                            deployment.save()
                            break
                        
                        # 如果Agent离线超过2分钟，尝试通过SSH检查
                        if agent_offline_detected and agent_offline_time and (time.time() - agent_offline_time) > 120:
                            # 尝试通过SSH检查Agent服务状态
                            try:
                                from apps.servers.utils import test_ssh_connection
                                ssh_result = test_ssh_connection(
                                    host=server.host,
                                    port=server.port,
                                    username=server.username,
                                    password=server.password,
                                    private_key=server.private_key
                                )
                                if ssh_result['success']:
                                    # SSH连接成功，检查Agent服务状态
                                    import paramiko
                                    ssh = paramiko.SSHClient()
                                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                                    ssh.connect(
                                        server.host,
                                        port=server.port,
                                        username=server.username,
                                        password=server.password,
                                        key_filename=None,
                                        pkey=server.private_key if server.private_key else None,
                                        timeout=10
                                    )
                                    stdin, stdout, stderr = ssh.exec_command('systemctl is-active myx-agent')
                                    service_status = stdout.read().decode().strip()
                                    ssh.close()
                                    
                                    deployment.log = (deployment.log or '') + f"\n[检查] 通过SSH检查Agent服务状态: {service_status}\n"
                                    deployment.save()
                                    
                                    # 如果服务已启动，等待Agent重新注册
                                    if service_status == 'active':
                                        deployment.log = (deployment.log or '') + f"\n[进度] Agent服务已启动，等待Agent重新注册...\n"
                                        deployment.save()
                                        # 重置离线检测，等待Agent重新上线
                                        agent_offline_detected = False
                                        agent_offline_time = None
                            except Exception as e:
                                logger.debug(f'通过SSH检查Agent状态失败: {str(e)}')
                        
                        # 更新进度日志
                        elapsed = int(time.time() - start_time)
                        if elapsed % 30 == 0:  # 每30秒更新一次进度
                            deployment.log = (deployment.log or '') + f"\n[进度] 已等待 {elapsed} 秒，继续监控...\n"
                            deployment.save()
                            
                    except Exception as e:
                        logger.error(f'监控Agent重新部署命令失败: {str(e)}')
                    
                    time.sleep(5)  # 每5秒检查一次
                
                # 如果超时仍未完成
                if deployment.status == 'running':
                    try:
                        cmd.refresh_from_db()
                        if cmd.status not in ['success', 'failed']:
                            deployment.status = 'failed'
                            deployment.error_message = '重新部署超时'
                            deployment.completed_at = timezone.now()
                            deployment.log = (deployment.log or '') + f"\n[超时] 重新部署超时（超过10分钟）\n"
                            deployment.save()
                    except:
                        pass

            thread = threading.Thread(target=_monitor_command)
            thread.daemon = True
            thread.start()
            
            return Response({
                'message': 'Agent重新部署已启动，请查看部署任务',
                'deployment_id': deployment.id,
                'command_id': cmd.id
            }, status=status.HTTP_202_ACCEPTED)
        else:
            # 使用SSH重新部署
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
                    # 等待Agent注册
                    from apps.deployments.tasks import wait_for_agent_registration
                    agent_registered = wait_for_agent_registration(server, timeout=60)
                    if agent_registered:
                        deployment.status = 'success'
                        deployment.completed_at = timezone.now()
                    else:
                        deployment.status = 'failed'
                        deployment.error_message = 'Agent注册超时'
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

            return Response({
                'message': 'Agent重新部署已启动（通过SSH）',
                'deployment_id': deployment.id
            }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def upgrade(self, request, pk=None):
        """升级Agent"""
        agent = self.get_object()
        server = agent.server

        # 创建部署任务
        from apps.deployments.models import Deployment
        from django.utils import timezone
        
        deployment = Deployment.objects.create(
            name=f"升级Agent - {server.name}",
            server=server,
            deployment_type='agent',
            connection_method='agent',
            deployment_target=server.deployment_target or 'host',
            status='running',
            started_at=timezone.now(),
            created_by=request.user
        )

        # 通过Agent执行升级命令
        from .command_queue import CommandQueue
        from django.conf import settings
        import os
        import threading

        github_repo = os.getenv('GITHUB_REPO', getattr(settings, 'GITHUB_REPO', 'hello--world/myx'))
        
        upgrade_script = f"""#!/bin/bash
set -e

# 检测系统
OS_NAME=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ARCH="amd64"
elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    ARCH="arm64"
fi

BINARY_NAME="myx-agent-${{OS_NAME}}-${{ARCH}}"
GITHUB_URL="https://github.com/{github_repo}/releases/download/latest/${{BINARY_NAME}}"

echo "[1/4] 正在从 GitHub 下载最新 Agent..."
if ! curl -L -f -o /tmp/myx-agent "${{GITHUB_URL}}"; then
    echo "Agent 下载失败"
    exit 1
fi

echo "[2/4] Agent 下载成功，准备替换..."
chmod +x /tmp/myx-agent

echo "[3/4] 正在停止Agent服务并替换..."
systemctl stop myx-agent || true
mv /tmp/myx-agent /opt/myx-agent/myx-agent
chmod +x /opt/myx-agent/myx-agent

echo "[4/4] 正在启动Agent服务..."
systemctl start myx-agent
systemctl status myx-agent --no-pager || true
echo "Agent 升级完成"
"""

        import base64
        script_b64 = base64.b64encode(upgrade_script.encode('utf-8')).decode('utf-8')
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=600
        )

        # 启动后台线程监控命令执行（支持Agent重启场景）
        def _monitor_command():
            import time
            import logging
            logger = logging.getLogger(__name__)
            max_wait = 600  # 最多等待10分钟
            start_time = time.time()
            agent_offline_detected = False
            agent_offline_time = None
            
            while time.time() - start_time < max_wait:
                try:
                    # 检查Agent状态
                    agent.refresh_from_db()
                    if agent.status == 'offline' and not agent_offline_detected:
                        agent_offline_detected = True
                        agent_offline_time = time.time()
                        deployment.log = (deployment.log or '') + f"\n[进度] Agent已停止，等待重新启动...\n"
                        deployment.save()
                    
                    # 如果Agent重新上线，继续监控
                    if agent_offline_detected and agent.status == 'online':
                        deployment.log = (deployment.log or '') + f"\n[进度] Agent已重新上线，继续监控...\n"
                        deployment.save()
                        agent_offline_detected = False
                        agent_offline_time = None
                    
                    # 检查命令状态
                    cmd.refresh_from_db()
                    if cmd.status in ['success', 'failed']:
                        # 命令执行完成，更新部署任务状态
                        deployment.log = (deployment.log or '') + f"\n[完成] 命令执行完成\n状态: {cmd.status}\n"
                        if cmd.result:
                            deployment.log = (deployment.log or '') + f"输出:\n{cmd.result}\n"
                        if cmd.error:
                            deployment.log = (deployment.log or '') + f"错误:\n{cmd.error}\n"
                        
                        if cmd.status == 'success':
                            deployment.status = 'success'
                        else:
                            deployment.status = 'failed'
                            deployment.error_message = cmd.error or '升级失败'
                        
                        deployment.completed_at = timezone.now()
                        deployment.save()
                        break
                    
                    # 如果Agent离线超过2分钟，尝试通过SSH检查
                    if agent_offline_detected and agent_offline_time and (time.time() - agent_offline_time) > 120:
                        # 尝试通过SSH检查Agent服务状态
                        try:
                            from apps.servers.utils import test_ssh_connection
                            ssh_result = test_ssh_connection(
                                host=server.host,
                                port=server.port,
                                username=server.username,
                                password=server.password,
                                private_key=server.private_key
                            )
                            if ssh_result['success']:
                                # SSH连接成功，检查Agent服务状态
                                import paramiko
                                ssh = paramiko.SSHClient()
                                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                                ssh.connect(
                                    server.host,
                                    port=server.port,
                                    username=server.username,
                                    password=server.password,
                                    key_filename=None,
                                    pkey=server.private_key if server.private_key else None,
                                    timeout=10
                                )
                                stdin, stdout, stderr = ssh.exec_command('systemctl is-active myx-agent')
                                service_status = stdout.read().decode().strip()
                                ssh.close()
                                
                                deployment.log = (deployment.log or '') + f"\n[检查] 通过SSH检查Agent服务状态: {service_status}\n"
                                deployment.save()
                                
                                # 如果服务已启动，等待Agent重新注册
                                if service_status == 'active':
                                    deployment.log = (deployment.log or '') + f"\n[进度] Agent服务已启动，等待Agent重新注册...\n"
                                    deployment.save()
                                    # 重置离线检测，等待Agent重新上线
                                    agent_offline_detected = False
                                    agent_offline_time = None
                        except Exception as e:
                            logger.debug(f'通过SSH检查Agent状态失败: {str(e)}')
                    
                    # 更新进度日志
                    elapsed = int(time.time() - start_time)
                    if elapsed % 30 == 0:  # 每30秒更新一次进度
                        deployment.log = (deployment.log or '') + f"\n[进度] 已等待 {elapsed} 秒，继续监控...\n"
                        deployment.save()
                        
                except Exception as e:
                    logger.error(f'监控Agent升级命令失败: {str(e)}')
                
                time.sleep(5)  # 每5秒检查一次
            
            # 如果超时仍未完成
            if deployment.status == 'running':
                try:
                    cmd.refresh_from_db()
                    if cmd.status not in ['success', 'failed']:
                        deployment.status = 'failed'
                        deployment.error_message = '升级超时'
                        deployment.completed_at = timezone.now()
                        deployment.log = (deployment.log or '') + f"\n[超时] 升级超时（超过10分钟）\n"
                        deployment.save()
                except:
                    pass

        thread = threading.Thread(target=_monitor_command)
        thread.daemon = True
        thread.start()

        return Response({
            'message': 'Agent升级已启动，请查看部署任务',
            'deployment_id': deployment.id,
            'command_id': cmd.id
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
    
    agent, created = Agent.objects.get_or_create(
        server=server,
        defaults={
            'token': secrets.token_urlsafe(32),  # 生成token
            'secret_key': secrets.token_urlsafe(32),  # 生成加密密钥
            'status': 'online',
            'version': serializer.validated_data.get('version', ''),
            'last_heartbeat': timezone.now(),
            'heartbeat_mode': heartbeat_mode
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
        # 保持现有心跳模式，不覆盖
        agent.save()

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

    agent.last_heartbeat = timezone.now()
    agent.status = 'online'
    agent.save()

    # 返回配置信息（让 Agent 可以动态调整间隔）
    from django.conf import settings
    return Response({
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
    
    try:
        CommandQueue.update_command_result(command_id, success, result, error)
        return Response({'status': 'ok'})
    except Exception as e:
        logger.error(f'[agent_command_result] ✗ 错误: {str(e)}')
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

