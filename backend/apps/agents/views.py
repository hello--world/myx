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
            
            # 获取API URL用于上报进度
            api_url = os.getenv('AGENT_API_URL', getattr(settings, 'AGENT_API_URL', None))
            if not api_url:
                # 从request构建API URL
                scheme = 'https' if request.is_secure() else 'http'
                host = request.get_host()
                api_url = f"{scheme}://{host}/api/agents"
            
            # 通过Agent执行重新部署脚本（包含备份和恢复机制）
            redeploy_script = f"""#!/bin/bash
# 不使用 set -e，改为手动检查关键命令的返回值
set +e

# 配置
API_URL="{api_url}"
DEPLOYMENT_ID={deployment.id}
AGENT_TOKEN="{agent.token}"
BACKUP_DIR="/opt/myx-agent/backup"
BACKUP_FILE="${{BACKUP_DIR}}/myx-agent-$(date +%Y%m%d_%H%M%S)"
CONFIG_BACKUP="${{BACKUP_DIR}}/config-$(date +%Y%m%d_%H%M%S).json"
LOG_FILE="/tmp/agent_redeploy_$$.log"

# 上报进度函数（即使curl失败也继续执行）
report_progress() {{
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local log_entry="[$timestamp] $message"
    # 始终写入日志文件
    echo "$log_entry" | tee -a "$LOG_FILE"
    # 尝试上报到后端（失败不影响执行）
    curl -s -X POST "${{API_URL}}/deployments/${{DEPLOYMENT_ID}}/progress/" \\
        -H "X-Agent-Token: ${{AGENT_TOKEN}}" \\
        -H "Content-Type: application/json" \\
        -d "{{\\"log\\": \\"$log_entry\\\\n\\"}}" > /dev/null 2>&1 || true
}}

# 恢复备份函数
restore_backup() {{
    local latest_binary=$(ls -t "${{BACKUP_DIR}}"/myx-agent-* 2>/dev/null | head -1)
    local latest_config=$(ls -t "${{BACKUP_DIR}}"/config-* 2>/dev/null | head -1)
    
    if [ -n "$latest_binary" ] && [ -f "$latest_binary" ]; then
        report_progress "[恢复] 正在恢复备份..."
        report_progress "[恢复] 备份文件: $latest_binary"
        
        # 停止Agent服务
        systemctl stop myx-agent || true
        sleep 2
        
        # 恢复二进制文件
        cp "$latest_binary" /opt/myx-agent/myx-agent
        chmod +x /opt/myx-agent/myx-agent
        report_progress "[恢复] 二进制文件已恢复"
        
        # 恢复配置文件（如果存在）
        if [ -n "$latest_config" ] && [ -f "$latest_config" ]; then
            cp "$latest_config" /etc/myx-agent/config.json
            report_progress "[恢复] 配置文件已恢复"
        fi
        
        # 确保systemd服务文件存在
        if [ ! -f /etc/systemd/system/myx-agent.service ]; then
            report_progress "[恢复] 创建systemd服务文件..."
            cat > /etc/systemd/system/myx-agent.service << 'EOFSERVICE'
[Unit]
Description=MyX Agent
After=network.target

[Service]
Type=simple
User=root
ExecStart=/opt/myx-agent/myx-agent
Restart=always
RestartSec=10
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOFSERVICE
            report_progress "[恢复] systemd服务文件已创建"
        fi
        
        # 重新加载systemd并启用服务
        systemctl daemon-reload || true
        systemctl enable myx-agent || true
        
        # 启动服务并检查返回值
        report_progress "[恢复] 正在启动Agent服务..."
        if systemctl start myx-agent; then
            report_progress "[恢复] systemctl start 命令执行成功"
        else
            local start_error=$(systemctl status myx-agent --no-pager -l 2>&1 | tail -10)
            report_progress "[错误] systemctl start 命令执行失败"
            report_progress "[错误] $start_error"
        fi
        
        # 等待服务启动
        sleep 5
        
        # 验证服务状态（重试机制）
        local retry_count=0
        local max_retries=6
        while [ $retry_count -lt $max_retries ]; do
            local service_status=$(systemctl is-active myx-agent 2>&1 || echo "inactive")
            if [ "$service_status" = "active" ]; then
                report_progress "[恢复] Agent服务已启动"
                
                # 尝试重新注册Agent（如果配置存在）
                if [ -f /etc/myx-agent/config.json ]; then
                    API_URL_CONFIG=$(grep -oP '"APIURL":\\s*"\\K[^"]+' /etc/myx-agent/config.json 2>/dev/null || echo "")
                    SERVER_TOKEN=$(grep -oP '"ServerToken":\\s*"\\K[^"]+' /etc/myx-agent/config.json 2>/dev/null || echo "")
                    if [ -n "$API_URL_CONFIG" ] && [ -n "$SERVER_TOKEN" ]; then
                        report_progress "[恢复] 正在重新注册Agent..."
                        /opt/myx-agent/myx-agent -token "$SERVER_TOKEN" -api "$API_URL_CONFIG" > /dev/null 2>&1 || true
                        sleep 2
                    fi
                fi
                
                # 最终验证
                if systemctl is-active --quiet myx-agent; then
                    report_progress "[恢复] 备份已恢复，Agent服务运行正常"
                    return 0
                fi
            else
                report_progress "[恢复] 服务状态: $service_status"
            fi
            
            retry_count=$((retry_count + 1))
            report_progress "[恢复] 等待Agent服务启动... ($retry_count/$max_retries)"
            sleep 2
        done
        
        # 如果仍然无法启动，检查服务状态和日志
        local service_status=$(systemctl is-active myx-agent 2>&1 || echo "inactive")
        local service_error=$(systemctl status myx-agent --no-pager -l 2>&1 | tail -10)
        local journal_log=$(journalctl -u myx-agent --no-pager -n 20 2>&1 | tail -10)
        report_progress "[错误] 恢复后Agent服务仍无法启动"
        report_progress "[错误] 服务状态: $service_status"
        report_progress "[错误] 服务状态详情: $service_error"
        report_progress "[错误] 服务日志: $journal_log"
        return 1
    else
        report_progress "[错误] 未找到备份文件，无法恢复"
        return 1
    fi
}}

# 检测系统
OS_NAME=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ARCH="amd64"
elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    ARCH="arm64"
fi

BINARY_NAME="myx-agent-${{OS_NAME}}-${{ARCH}}"
GITHUB_URL="https://github.com/{github_repo}/releases/latest/download/${{BINARY_NAME}}"

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 步骤1: 备份现有Agent和配置
report_progress "[1/7] 正在备份现有Agent和配置..."
if [ -f /opt/myx-agent/myx-agent ]; then
    cp /opt/myx-agent/myx-agent "$BACKUP_FILE"
    chmod +x "$BACKUP_FILE"
    report_progress "[1/7] Agent二进制备份完成: $BACKUP_FILE"
else
    report_progress "[1/7] 警告: 未找到现有Agent，跳过备份"
fi

if [ -f /etc/myx-agent/config.json ]; then
    cp /etc/myx-agent/config.json "$CONFIG_BACKUP"
    report_progress "[1/7] 配置文件备份完成: $CONFIG_BACKUP"
fi

# 步骤2: 下载新版本
report_progress "[2/7] 正在从 GitHub 下载最新 Agent..."
if ! curl -L -f -o /tmp/myx-agent "${{GITHUB_URL}}"; then
    report_progress "[错误] Agent 下载失败"
    restore_backup || true
    # 读取完整日志并输出
    if [ -f "$LOG_FILE" ]; then
        echo "=== 完整执行日志 ==="
        cat "$LOG_FILE"
    fi
    exit 1
fi
report_progress "[2/7] Agent 下载成功"

# 步骤3: 验证新版本
report_progress "[3/7] 正在验证新版本..."
chmod +x /tmp/myx-agent
# 检查文件是否存在、可执行，并尝试运行（不检查返回值，因为Agent可能没有-version参数）
if [ ! -f /tmp/myx-agent ] || [ ! -x /tmp/myx-agent ]; then
    report_progress "[错误] 新版本文件不存在或不可执行"
    restore_backup || true
    # 读取完整日志并输出
    if [ -f "$LOG_FILE" ]; then
        echo "=== 完整执行日志 ==="
        cat "$LOG_FILE"
    fi
    exit 1
fi
# 尝试运行Agent（即使失败也继续，因为Agent可能没有-version参数）
/tmp/myx-agent -help > /dev/null 2>&1 || /tmp/myx-agent > /dev/null 2>&1 || true
report_progress "[3/7] 新版本验证成功（文件存在且可执行）"

# 步骤4: 停止Agent服务
report_progress "[4/7] 正在停止Agent服务..."
systemctl stop myx-agent || true
sleep 2

# 步骤5: 替换二进制文件
report_progress "[5/7] 正在替换Agent二进制文件..."
mv /tmp/myx-agent /opt/myx-agent/myx-agent
chmod +x /opt/myx-agent/myx-agent

# 步骤6: 重新注册Agent（如果需要）
API_URL_CONFIG=$(grep -oP '"APIURL":\\s*"\\K[^"]+' /etc/myx-agent/config.json 2>/dev/null || echo "")
if [ -n "$API_URL_CONFIG" ]; then
    SERVER_TOKEN=$(grep -oP '"ServerToken":\\s*"\\K[^"]+' /etc/myx-agent/config.json 2>/dev/null || echo "")
    if [ -n "$SERVER_TOKEN" ]; then
        report_progress "[6/7] 正在启动Agent服务并重新注册..."
        systemctl start myx-agent
        sleep 2
        /opt/myx-agent/myx-agent -token "$SERVER_TOKEN" -api "$API_URL_CONFIG" || true
    else
        report_progress "[6/7] 正在启动Agent服务..."
        systemctl start myx-agent
    fi
else
    report_progress "[6/7] 正在启动Agent服务..."
    systemctl start myx-agent
fi

# 步骤7: 验证Agent服务
report_progress "[7/7] 正在验证Agent服务..."
sleep 3
if systemctl is-active --quiet myx-agent; then
    report_progress "[完成] Agent重新部署成功，服务运行正常"
    # 清理旧备份（保留最近5个）
    ls -t "${{BACKUP_DIR}}"/myx-agent-* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
    ls -t "${{BACKUP_DIR}}"/config-* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
    # 读取完整日志并输出（供命令结果接口收集）
    if [ -f "$LOG_FILE" ]; then
        echo "=== 完整执行日志 ==="
        cat "$LOG_FILE"
    fi
    exit 0
else
    report_progress "[错误] Agent服务启动失败，状态异常"
    restore_backup || true
    # 读取完整日志并输出（供命令结果接口收集）
    if [ -f "$LOG_FILE" ]; then
        echo "=== 完整执行日志 ==="
        cat "$LOG_FILE"
    fi
    exit 1
fi
"""
            
            import base64
            script_b64 = base64.b64encode(redeploy_script.encode('utf-8')).decode('utf-8')
            # 使用nohup在后台执行，并重定向输出到日志文件
            cmd = CommandQueue.add_command(
                agent=agent,
                command='bash',
                args=['-c', f'echo "{script_b64}" | base64 -d | nohup bash > /tmp/agent_redeploy.log 2>&1 & echo $!'],
                timeout=600
            )

            # 启动后台线程监控命令执行（支持Agent重启场景）
            def _monitor_command():
                import time
                import logging
                import os
                logger = logging.getLogger(__name__)
                max_wait = 600  # 最多等待10分钟
                start_time = time.time()
                agent_offline_detected = False
                agent_offline_time = None
                last_log_size = 0
                log_file_path = '/tmp/agent_redeploy.log'
                
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
                        
                        # 定期读取日志文件（每10秒读取一次）
                        if os.path.exists(log_file_path):
                            try:
                                current_log_size = os.path.getsize(log_file_path)
                                if current_log_size > last_log_size:
                                    # 读取新增的日志内容
                                    with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        f.seek(last_log_size)
                                        new_log_content = f.read()
                                        if new_log_content.strip():
                                            deployment.log = (deployment.log or '') + new_log_content
                                            deployment.save()
                                        last_log_size = current_log_size
                            except Exception as e:
                                logger.debug(f'读取日志文件失败: {str(e)}')
                        
                        # 检查命令状态（脚本通过API上报进度，这里主要检查最终状态）
                        cmd.refresh_from_db()
                        if cmd.status in ['success', 'failed']:
                            # 命令执行完成，读取完整日志文件
                            if os.path.exists(log_file_path):
                                try:
                                    with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        full_log = f.read()
                                        if full_log.strip():
                                            deployment.log = (deployment.log or '') + f"\n=== 完整执行日志 ===\n{full_log}\n"
                                except Exception as e:
                                    logger.debug(f'读取完整日志文件失败: {str(e)}')
                            
                            # 更新部署任务状态
                            deployment.log = (deployment.log or '') + f"\n[完成] 命令执行完成\n状态: {cmd.status}\n"
                            if cmd.result:
                                deployment.log = (deployment.log or '') + f"输出:\n{cmd.result}\n"
                            if cmd.error:
                                deployment.log = (deployment.log or '') + f"错误:\n{cmd.error}\n"
                            
                            # 验证Agent是否正常运行
                            agent.refresh_from_db()
                            if agent.status == 'online':
                                deployment.status = 'success' if cmd.status == 'success' else 'failed'
                            else:
                                # 即使命令成功，如果Agent未上线，标记为失败
                                deployment.status = 'failed'
                                deployment.error_message = 'Agent重新部署后未正常上线'
                            
                            if cmd.status == 'failed':
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
                                    from io import StringIO
                                    ssh = paramiko.SSHClient()
                                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                                    # 使用私钥或密码连接
                                    if server.private_key:
                                        key_file = StringIO(server.private_key)
                                        try:
                                            pkey = paramiko.RSAKey.from_private_key(key_file)
                                        except:
                                            key_file.seek(0)
                                            try:
                                                pkey = paramiko.Ed25519Key.from_private_key(key_file)
                                            except:
                                                key_file.seek(0)
                                                pkey = paramiko.ECDSAKey.from_private_key(key_file)
                                        ssh.connect(
                                            server.host,
                                            port=server.port,
                                            username=server.username,
                                            pkey=pkey,
                                            timeout=10
                                        )
                                    else:
                                        ssh.connect(
                                            server.host,
                                            port=server.port,
                                            username=server.username,
                                            password=server.password,
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
        
        # 获取API URL用于上报进度
        from django.conf import settings
        import os
        api_url = os.getenv('AGENT_API_URL', getattr(settings, 'AGENT_API_URL', None))
        if not api_url:
            # 从request构建API URL
            scheme = 'https' if request.is_secure() else 'http'
            host = request.get_host()
            api_url = f"{scheme}://{host}/api/agents"
        
            upgrade_script = f"""#!/bin/bash
# 不使用 set -e，改为手动检查关键命令的返回值
set +e

# 配置
API_URL="{api_url}"
DEPLOYMENT_ID={deployment.id}
AGENT_TOKEN="{agent.token}"
BACKUP_DIR="/opt/myx-agent/backup"
BACKUP_FILE="${{BACKUP_DIR}}/myx-agent-$(date +%Y%m%d_%H%M%S)"
LOG_FILE="/tmp/agent_upgrade_$$.log"

# 上报进度函数（即使curl失败也继续执行）
report_progress() {{
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local log_entry="[$timestamp] $message"
    # 始终写入日志文件
    echo "$log_entry" | tee -a "$LOG_FILE"
    # 尝试上报到后端（失败不影响执行）
    curl -s -X POST "${{API_URL}}/deployments/${{DEPLOYMENT_ID}}/progress/" \\
        -H "X-Agent-Token: ${{AGENT_TOKEN}}" \\
        -H "Content-Type: application/json" \\
        -d "{{\\"log\\": \\"$log_entry\\\\n\\"}}" > /dev/null 2>&1 || true
}}

# 恢复备份函数（使用 set +e 确保即使失败也继续执行）
restore_backup() {{
    set +e  # 在函数内部禁用立即退出
    local restore_success=0
    
    local latest_backup=$(ls -t "${{BACKUP_DIR}}"/myx-agent-* 2>/dev/null | head -1)
    if [ -n "$latest_backup" ] && [ -f "$latest_backup" ]; then
        report_progress "[恢复] 正在恢复备份: $latest_backup"
        
        # 停止Agent服务
        systemctl stop myx-agent || true
        sleep 2
        
        # 恢复二进制文件
        cp "$latest_backup" /opt/myx-agent/myx-agent
        chmod +x /opt/myx-agent/myx-agent
        report_progress "[恢复] 二进制文件已恢复"
        
        # 确保systemd服务文件存在
        if [ ! -f /etc/systemd/system/myx-agent.service ]; then
            report_progress "[恢复] 创建systemd服务文件..."
            cat > /etc/systemd/system/myx-agent.service << 'EOFSERVICE'
[Unit]
Description=MyX Agent
After=network.target

[Service]
Type=simple
User=root
ExecStart=/opt/myx-agent/myx-agent
Restart=always
RestartSec=10
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOFSERVICE
            report_progress "[恢复] systemd服务文件已创建"
        fi
        
        # 重新加载systemd并启用服务
        systemctl daemon-reload || true
        systemctl enable myx-agent || true
        
        # 启动服务并检查返回值
        report_progress "[恢复] 正在启动Agent服务..."
        if systemctl start myx-agent; then
            report_progress "[恢复] systemctl start 命令执行成功"
        else
            local start_error=$(systemctl status myx-agent --no-pager -l 2>&1 | tail -10)
            report_progress "[错误] systemctl start 命令执行失败"
            report_progress "[错误] $start_error"
        fi
        
        # 等待服务启动
        sleep 5
        
        # 验证服务状态（重试机制）
        local retry_count=0
        local max_retries=6
        while [ $retry_count -lt $max_retries ]; do
            local service_status=$(systemctl is-active myx-agent 2>&1 || echo "inactive")
            if [ "$service_status" = "active" ]; then
                report_progress "[恢复] Agent服务已启动"
                
                # 尝试重新注册Agent（如果配置存在）
                if [ -f /etc/myx-agent/config.json ]; then
                    API_URL_CONFIG=$(grep -oP '"APIURL":\\s*"\\K[^"]+' /etc/myx-agent/config.json 2>/dev/null || echo "")
                    SERVER_TOKEN=$(grep -oP '"ServerToken":\\s*"\\K[^"]+' /etc/myx-agent/config.json 2>/dev/null || echo "")
                    if [ -n "$API_URL_CONFIG" ] && [ -n "$SERVER_TOKEN" ]; then
                        report_progress "[恢复] 正在重新注册Agent..."
                        /opt/myx-agent/myx-agent -token "$SERVER_TOKEN" -api "$API_URL_CONFIG" > /dev/null 2>&1 || true
                        sleep 2
                    fi
                fi
                
                # 最终验证
                if systemctl is-active --quiet myx-agent; then
                    report_progress "[恢复] 备份已恢复，Agent服务运行正常"
                    return 0
                fi
            else
                report_progress "[恢复] 服务状态: $service_status"
            fi
            
            retry_count=$((retry_count + 1))
            report_progress "[恢复] 等待Agent服务启动... ($retry_count/$max_retries)"
            sleep 2
        done
        
        # 如果仍然无法启动，检查服务状态和日志
        local service_status=$(systemctl is-active myx-agent 2>&1 || echo "inactive")
        local service_error=$(systemctl status myx-agent --no-pager -l 2>&1 | tail -10)
        local journal_log=$(journalctl -u myx-agent --no-pager -n 20 2>&1 | tail -10)
        report_progress "[错误] 恢复后Agent服务仍无法启动"
        report_progress "[错误] 服务状态: $service_status"
        report_progress "[错误] 服务状态详情: $service_error"
        report_progress "[错误] 服务日志: $journal_log"
        return 1
    else
        report_progress "[错误] 未找到备份文件，无法恢复"
        return 1
    fi
}}

# 检测系统
OS_NAME=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ARCH="amd64"
elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    ARCH="arm64"
fi

BINARY_NAME="myx-agent-${{OS_NAME}}-${{ARCH}}"
GITHUB_URL="https://github.com/{github_repo}/releases/latest/download/${{BINARY_NAME}}"

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 步骤1: 备份现有Agent
report_progress "[1/6] 正在备份现有Agent..."
if [ -f /opt/myx-agent/myx-agent ]; then
    cp /opt/myx-agent/myx-agent "$BACKUP_FILE"
    chmod +x "$BACKUP_FILE"
    report_progress "[1/6] 备份完成: $BACKUP_FILE"
else
    report_progress "[1/6] 警告: 未找到现有Agent，跳过备份"
fi

# 步骤2: 下载新版本
report_progress "[2/6] 正在从 GitHub 下载最新 Agent..."
if ! curl -L -f -o /tmp/myx-agent "${{GITHUB_URL}}"; then
    report_progress "[错误] Agent 下载失败"
    restore_backup || true
    # 读取完整日志并输出
    if [ -f "$LOG_FILE" ]; then
        echo "=== 完整执行日志 ==="
        cat "$LOG_FILE"
    fi
    exit 1
fi
report_progress "[2/6] Agent 下载成功"

# 步骤3: 验证新版本
report_progress "[3/6] 正在验证新版本..."
chmod +x /tmp/myx-agent
# 检查文件是否存在、可执行，并尝试运行（不检查返回值，因为Agent可能没有-version参数）
if [ ! -f /tmp/myx-agent ] || [ ! -x /tmp/myx-agent ]; then
    report_progress "[错误] 新版本文件不存在或不可执行"
    restore_backup || true
    # 读取完整日志并输出
    if [ -f "$LOG_FILE" ]; then
        echo "=== 完整执行日志 ==="
        cat "$LOG_FILE"
    fi
    exit 1
fi
# 尝试运行Agent（即使失败也继续，因为Agent可能没有-version参数）
/tmp/myx-agent -help > /dev/null 2>&1 || /tmp/myx-agent > /dev/null 2>&1 || true
report_progress "[3/6] 新版本验证成功（文件存在且可执行）"

# 步骤4: 停止Agent服务
report_progress "[4/6] 正在停止Agent服务..."
systemctl stop myx-agent || true
sleep 2

# 步骤5: 替换二进制文件
report_progress "[5/6] 正在替换Agent二进制文件..."
mv /tmp/myx-agent /opt/myx-agent/myx-agent
chmod +x /opt/myx-agent/myx-agent

# 步骤6: 启动Agent服务
report_progress "[6/6] 正在启动Agent服务..."
if systemctl start myx-agent; then
    sleep 3
    if systemctl is-active --quiet myx-agent; then
        report_progress "[完成] Agent升级成功，服务运行正常"
        # 清理旧备份（保留最近5个）
        ls -t "${{BACKUP_DIR}}"/myx-agent-* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
        # 读取完整日志并输出（供命令结果接口收集）
        if [ -f "$LOG_FILE" ]; then
            echo "=== 完整执行日志 ==="
            cat "$LOG_FILE"
        fi
        exit 0
    else
        report_progress "[错误] Agent服务启动失败，状态异常"
        restore_backup || true
        # 读取完整日志并输出（供命令结果接口收集）
        if [ -f "$LOG_FILE" ]; then
            echo "=== 完整执行日志 ==="
            cat "$LOG_FILE"
        fi
        exit 1
    fi
else
    report_progress "[错误] 无法启动Agent服务"
    restore_backup || true
    # 读取完整日志并输出（供命令结果接口收集）
    if [ -f "$LOG_FILE" ]; then
        echo "=== 完整执行日志 ==="
        cat "$LOG_FILE"
    fi
    exit 1
fi
"""
        
        import base64
        script_b64 = base64.b64encode(upgrade_script.encode('utf-8')).decode('utf-8')
        # 使用nohup在后台执行，并重定向输出到日志文件
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | nohup bash > /tmp/agent_upgrade.log 2>&1 & echo $!'],
            timeout=600
        )

        # 启动后台线程监控命令执行和Agent状态
        def _monitor_command():
            import time
            import logging
            import os
            logger = logging.getLogger(__name__)
            max_wait = 600  # 最多等待10分钟
            start_time = time.time()
            agent_offline_detected = False
            agent_offline_time = None
            last_check_time = 0
            last_log_size = 0
            log_file_path = '/tmp/agent_upgrade.log'
            
            while time.time() - start_time < max_wait:
                try:
                    # 检查Agent状态（每10秒检查一次）
                    current_time = time.time()
                    if current_time - last_check_time >= 10:
                        agent.refresh_from_db()
                        last_check_time = current_time
                        
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
                    
                    # 定期读取日志文件（每10秒读取一次）
                    if os.path.exists(log_file_path):
                        try:
                            current_log_size = os.path.getsize(log_file_path)
                            if current_log_size > last_log_size:
                                # 读取新增的日志内容
                                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    f.seek(last_log_size)
                                    new_log_content = f.read()
                                    if new_log_content.strip():
                                        deployment.log = (deployment.log or '') + new_log_content
                                        deployment.save()
                                    last_log_size = current_log_size
                        except Exception as e:
                            logger.debug(f'读取日志文件失败: {str(e)}')
                    
                    # 检查命令状态（脚本通过API上报进度，这里主要检查最终状态）
                    cmd.refresh_from_db()
                    if cmd.status in ['success', 'failed']:
                        # 命令执行完成，读取完整日志文件
                        if os.path.exists(log_file_path):
                            try:
                                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    full_log = f.read()
                                    if full_log.strip():
                                        deployment.log = (deployment.log or '') + f"\n=== 完整执行日志 ===\n{full_log}\n"
                            except Exception as e:
                                logger.debug(f'读取完整日志文件失败: {str(e)}')
                        
                        # 更新部署任务状态
                        deployment.log = (deployment.log or '') + f"\n[完成] 命令执行完成\n状态: {cmd.status}\n"
                        if cmd.result:
                            deployment.log = (deployment.log or '') + f"输出:\n{cmd.result}\n"
                        if cmd.error:
                            deployment.log = (deployment.log or '') + f"错误:\n{cmd.error}\n"
                        
                        # 验证Agent是否正常运行
                        agent.refresh_from_db()
                        if agent.status == 'online':
                            deployment.status = 'success' if cmd.status == 'success' else 'failed'
                        else:
                            # 即使命令成功，如果Agent未上线，标记为失败
                            deployment.status = 'failed'
                            deployment.error_message = 'Agent升级后未正常上线'
                        
                        if cmd.status == 'failed':
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
                                from io import StringIO
                                ssh = paramiko.SSHClient()
                                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                                # 使用私钥或密码连接
                                if server.private_key:
                                    key_file = StringIO(server.private_key)
                                    try:
                                        pkey = paramiko.RSAKey.from_private_key(key_file)
                                    except:
                                        key_file.seek(0)
                                        try:
                                            pkey = paramiko.Ed25519Key.from_private_key(key_file)
                                        except:
                                            key_file.seek(0)
                                            pkey = paramiko.ECDSAKey.from_private_key(key_file)
                                    ssh.connect(
                                        server.host,
                                        port=server.port,
                                        username=server.username,
                                        pkey=pkey,
                                        timeout=10
                                    )
                                else:
                                    ssh.connect(
                                        server.host,
                                        port=server.port,
                                        username=server.username,
                                        password=server.password,
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

