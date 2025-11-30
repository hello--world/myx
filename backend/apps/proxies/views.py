from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import Proxy
from .serializers import ProxySerializer
from .tasks import auto_deploy_proxy
from apps.logs.utils import create_log_entry
from apps.agents.utils import execute_script_via_agent
import time
import re
import os
import base64
import logging

logger = logging.getLogger(__name__)


class ProxyViewSet(viewsets.ModelViewSet):
    """代理节点视图集"""
    queryset = Proxy.objects.all()
    serializer_class = ProxySerializer

    def get_queryset(self):
        return Proxy.objects.filter(created_by=self.request.user)
    
    @action(detail=False, methods=['get'])
    def check_port(self, request):
        """检查端口是否可用"""
        port = request.query_params.get('port')
        if not port:
            return Response({'error': '请提供端口号'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            port = int(port)
        except ValueError:
            return Response({'error': '端口号必须是数字'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查端口是否已被使用（从数据库查询）
        proxy_id = request.query_params.get('proxy_id')  # 编辑时排除自己
        queryset = Proxy.objects.filter(port=port)
        if proxy_id:
            queryset = queryset.exclude(pk=proxy_id)
        
        if queryset.exists():
            return Response({
                'available': False,
                'message': f'端口{port}已被其他代理节点使用'
            })
        
        return Response({
            'available': True,
            'message': f'端口{port}可用'
        })
    
    @action(detail=False, methods=['get'])
    def random_port(self, request):
        """获取一个随机可用的端口（从1024开始）"""
        import random
        
        # 从数据库查询所有已使用的端口
        used_ports = set(Proxy.objects.values_list('port', flat=True))
        
        # 从1024开始，到65535结束
        min_port = 1024
        max_port = 65535
        
        # 尝试最多100次找到可用端口
        max_attempts = 100
        for _ in range(max_attempts):
            port = random.randint(min_port, max_port)
            if port not in used_ports:
                return Response({
                    'port': port,
                    'message': f'已分配端口{port}'
                })
        
        # 如果随机找不到，尝试顺序查找
        for port in range(min_port, max_port + 1):
            if port not in used_ports:
                return Response({
                    'port': port,
                    'message': f'已分配端口{port}'
                })
        
        # 如果所有端口都被使用（理论上不可能）
        return Response({
            'error': '没有可用的端口'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request, *args, **kwargs):
        """创建代理并自动部署"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # 获取心跳模式（如果提供）
        heartbeat_mode = request.data.get('heartbeat_mode', 'push')
        agent_connect_host = request.data.get('agent_connect_host')
        agent_connect_port = request.data.get('agent_connect_port')
        
        # 创建代理
        proxy = serializer.save()
        
        # 记录代理创建日志
        create_log_entry(
            log_type='proxy',
            level='info',
            title=f'创建代理节点: {proxy.name}',
            content=f'代理名称: {proxy.name}\n协议: {proxy.get_protocol_display()}\n端口: {proxy.port}\n服务器: {proxy.server.name}',
            user=request.user,
            server=proxy.server,
            related_id=proxy.id,
            related_type='proxy'
        )
        
        # 如果提供了Agent连接信息，更新服务器
        if agent_connect_host or agent_connect_port:
            server = proxy.server
            if agent_connect_host:
                server.agent_connect_host = agent_connect_host
            if agent_connect_port:
                server.agent_connect_port = agent_connect_port
            server.save()
        
        # 如果服务器已有Agent，更新心跳模式
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=proxy.server)
            agent.heartbeat_mode = heartbeat_mode
            agent.save()
        except Agent.DoesNotExist:
            # Agent还未创建，将在部署时创建，此时心跳模式会在注册时设置
            pass
        
        # 异步启动自动部署（传递心跳模式）
        auto_deploy_proxy(proxy.id, heartbeat_mode=heartbeat_mode)
        
        # 记录部署开始日志
        create_log_entry(
            log_type='proxy',
            level='info',
            title=f'开始部署代理节点: {proxy.name}',
            content=f'代理节点 {proxy.name} 的自动部署已启动',
            user=request.user,
            server=proxy.server,
            related_id=proxy.id,
            related_type='proxy'
        )
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """重新部署代理"""
        logger.info(f'[redeploy] 收到重新部署请求: proxy_id={pk}, user={request.user.username}')
        
        try:
            proxy = self.get_object()
            logger.info(f'[redeploy] 找到代理: id={proxy.id}, name={proxy.name}, created_by={proxy.created_by.username}')
        except NotFound:
            logger.warning(f'[redeploy] 代理不存在: proxy_id={pk}, user={request.user.username}')
            return Response({
                'error': '代理不存在',
                'detail': f'代理 ID {pk} 不存在或无权访问'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f'[redeploy] 获取代理失败: proxy_id={pk}, error={str(e)}')
            return Response({
                'error': '获取代理失败',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # 检查权限：确保代理属于当前用户
        if proxy.created_by != request.user:
            logger.warning(f'[redeploy] 权限不足: proxy_id={pk}, proxy_owner={proxy.created_by.username}, current_user={request.user.username}')
            return Response({
                'error': '无权访问此代理',
                'detail': '此代理不属于当前用户'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # 重置部署状态
        proxy.deployment_status = 'pending'
        proxy.deployment_log = ''
        proxy.deployed_at = None
        proxy.save()
        
        logger.info(f'[redeploy] 启动重新部署: proxy_id={proxy.id}')
        
        # 记录重新部署开始日志
        create_log_entry(
            log_type='proxy',
            level='info',
            title=f'开始重新部署代理节点: {proxy.name}',
            content=f'代理节点 {proxy.name} 的重新部署已启动',
            user=request.user,
            server=proxy.server,
            related_id=proxy.id,
            related_type='proxy'
        )
        
        # 异步启动重新部署
        auto_deploy_proxy(proxy.id)
        
        return Response({
            'message': '重新部署已启动',
            'deployment_status': proxy.deployment_status
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def stop_deployment(self, request, pk=None):
        """停止部署"""
        proxy = self.get_object()
        
        if proxy.deployment_status != 'running':
            return Response({
                'message': '当前没有正在运行的部署任务',
                'deployment_status': proxy.deployment_status
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 停止部署：将状态改为失败，并记录停止信息
        proxy.deployment_status = 'failed'
        proxy.deployment_log = (proxy.deployment_log or '') + f"\n⚠️ 部署已被用户手动停止\n"
        proxy.save()
        
        return Response({
            'message': '部署已停止',
            'deployment_status': proxy.deployment_status
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_caddyfile(self, request, pk=None):
        """获取 Caddyfile 内容"""
        proxy = self.get_object()
        server = proxy.server
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 通过 Agent 读取 Caddyfile
        from apps.agents.command_queue import CommandQueue
        import base64
        
        # 创建读取命令
        read_script = """#!/bin/bash
if [ -f /etc/caddy/Caddyfile ]; then
    cat /etc/caddy/Caddyfile
else
    echo "Caddyfile不存在"
    exit 1
fi
"""
        cmd = execute_script_via_agent(agent, read_script, timeout=30, script_name='read_caddyfile.sh')
        
        # 等待命令执行完成
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
            return Response({
                'content': cmd.result or '',
                'message': '读取成功'
            })
        else:
            return Response({
                'error': cmd.error or '读取失败',
                'content': ''
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def update_caddyfile(self, request, pk=None):
        """更新 Caddyfile 内容"""
        proxy = self.get_object()
        server = proxy.server
        
        content = request.data.get('content', '')
        if not content:
            return Response({'error': 'Caddyfile内容不能为空'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 通过 Agent 更新 Caddyfile
        from apps.agents.command_queue import CommandQueue
        
        # 创建更新脚本（直接使用内容，不需要base64编码）
        update_script = f"""#!/bin/bash
set -e

# 备份原文件
if [ -f /etc/caddy/Caddyfile ]; then
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%Y%m%d_%H%M%S)
fi

# 写入新文件
cat > /etc/caddy/Caddyfile << 'CADDYFILE_EOF'
{content}
CADDYFILE_EOF

# 验证配置
if caddy validate --config /etc/caddy/Caddyfile 2>&1; then
    echo "配置验证成功"
    exit 0
else
    echo "配置验证失败，已恢复备份"
    LATEST_BAK=$(ls -t /etc/caddy/Caddyfile.bak.* 2>/dev/null | head -1)
    if [ -n "$LATEST_BAK" ]; then
        cp "$LATEST_BAK" /etc/caddy/Caddyfile
    fi
    exit 1
fi
"""
        cmd = execute_script_via_agent(agent, update_script, timeout=60, script_name='update_caddyfile.sh')
        
        # 等待命令执行完成
        import time
        max_wait = 60
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status == 'success':
            return Response({
                'message': 'Caddyfile更新成功',
                'result': cmd.result or ''
            })
        else:
            return Response({
                'error': cmd.error or 'Caddyfile更新失败',
                'result': cmd.result or ''
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def validate_caddyfile(self, request, pk=None):
        """验证 Caddyfile 配置"""
        proxy = self.get_object()
        server = proxy.server
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 通过 Agent 验证 Caddyfile
        from apps.agents.command_queue import CommandQueue
        import base64
        
        validate_script = """#!/bin/bash
if caddy validate --config /etc/caddy/Caddyfile 2>&1; then
    echo "配置验证成功"
    exit 0
else
    echo "配置验证失败"
    exit 1
fi
"""
        cmd = execute_script_via_agent(agent, validate_script, timeout=30, script_name='validate_caddyfile.sh')
        
        # 等待命令执行完成
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
            return Response({
                'valid': True,
                'message': '配置验证成功',
                'result': cmd.result or ''
            })
        else:
            return Response({
                'valid': False,
                'error': cmd.error or '配置验证失败',
                'result': cmd.result or ''
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reload_caddy(self, request, pk=None):
        """重载 Caddy 配置"""
        proxy = self.get_object()
        server = proxy.server
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 通过 Agent 重载 Caddy
        from apps.agents.command_queue import CommandQueue
        import base64
        
        reload_script = """#!/bin/bash
# 重载 Caddy 配置
if systemctl reload caddy 2>&1; then
    echo "Caddy重载成功"
    exit 0
elif systemctl restart caddy 2>&1; then
    echo "Caddy重启成功（reload不支持，已使用restart）"
    exit 0
else
    echo "Caddy重载失败"
    exit 1
fi
"""
        cmd = execute_script_via_agent(agent, reload_script, timeout=30, script_name='reload_caddy.sh')
        
        # 等待命令执行完成
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
            return Response({
                'message': 'Caddy重载成功',
                'result': cmd.result or ''
            })
        else:
            return Response({
                'error': cmd.error or 'Caddy重载失败',
                'result': cmd.result or ''
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def list_certificates(self, request, pk=None):
        """列出 Caddyfile 中使用的所有 TLS 证书"""
        proxy = self.get_object()
        server = proxy.server
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 先读取 Caddyfile
        from apps.agents.command_queue import CommandQueue
        
        read_script = """#!/bin/bash
if [ -f /etc/caddy/Caddyfile ]; then
    cat /etc/caddy/Caddyfile
else
    echo ""
fi
"""
        cmd = execute_script_via_agent(agent, read_script, timeout=30, script_name='read_caddyfile_certs.sh')
        
        # 等待命令执行完成
        max_wait = 30
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status != 'success':
            return Response({'error': '读取 Caddyfile 失败', 'certificates': []}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        caddyfile_content = cmd.result or ''
        
        # 解析 TLS 证书路径
        certificates = []
        
        # 匹配简单格式: tls /path/to/cert.pem /path/to/key.key
        tls_pattern = r'tls\s+([^\s]+\.(pem|crt))\s+([^\s]+\.(key|pem))'
        matches = re.finditer(tls_pattern, caddyfile_content, re.MULTILINE)
        for match in matches:
            cert_path = match.group(1)
            key_path = match.group(3)
            # 提取域名（从上下文或路径推断）
            domain = cert_path.split('/')[-1].replace('.pem', '').replace('.crt', '')
            certificates.append({
                'domain': domain,
                'cert_path': cert_path,
                'key_path': key_path,
                'line': caddyfile_content[:match.start()].count('\n') + 1
            })
        
        # 匹配块格式: tls { certificate ... key ... }
        block_pattern = r'tls\s*\{[^}]*certificate\s+([^\s]+\.(pem|crt))[^}]*key\s+([^\s]+\.(key|pem))[^}]*\}'
        block_matches = re.finditer(block_pattern, caddyfile_content, re.MULTILINE | re.DOTALL)
        for match in block_matches:
            cert_path = match.group(1)
            key_path = match.group(3)
            domain = cert_path.split('/')[-1].replace('.pem', '').replace('.crt', '')
            certificates.append({
                'domain': domain,
                'cert_path': cert_path,
                'key_path': key_path,
                'line': caddyfile_content[:match.start()].count('\n') + 1
            })
        
        return Response({
            'certificates': certificates,
            'caddyfile_content': caddyfile_content
        })

    @action(detail=True, methods=['post'])
    def upload_certificate(self, request, pk=None):
        """上传 TLS 证书文件"""
        proxy = self.get_object()
        server = proxy.server
        
        cert_path = request.data.get('cert_path')
        key_path = request.data.get('key_path')
        cert_content = request.data.get('cert_content')
        key_content = request.data.get('key_content')
        
        if not cert_path or not key_path:
            return Response({'error': '证书路径和密钥路径不能为空'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not cert_content or not key_content:
            return Response({'error': '证书内容和密钥内容不能为空'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 通过 Agent 上传证书
        from apps.agents.command_queue import CommandQueue
        
        # 创建上传脚本
        cert_dir = os.path.dirname(cert_path)
        key_dir = os.path.dirname(key_path)
        
        # 创建上传脚本（直接使用内容，不需要base64编码）
        upload_script = f"""#!/bin/bash
set -e

# 创建目录（如果不存在）
mkdir -p "{cert_dir}"
mkdir -p "{key_dir}"

# 写入证书文件
cat > "{cert_path}" << 'CERT_EOF'
{cert_content}
CERT_EOF

cat > "{key_path}" << 'KEY_EOF'
{key_content}
KEY_EOF

# 设置权限
chmod 600 "{cert_path}"
chmod 600 "{key_path}"

echo "证书上传成功"
"""
        cmd = execute_script_via_agent(agent, upload_script, timeout=30, script_name='upload_cert.sh')
        
        # 等待命令执行完成
        max_wait = 30
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status == 'success':
            return Response({
                'message': '证书上传成功',
                'result': cmd.result or ''
            })
        else:
            return Response({
                'error': cmd.error or '证书上传失败',
                'result': cmd.result or ''
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def get_certificate(self, request, pk=None):
        """读取证书文件内容"""
        proxy = self.get_object()
        server = proxy.server
        
        cert_path = request.query_params.get('cert_path')
        key_path = request.query_params.get('key_path')
        
        if not cert_path or not key_path:
            return Response({'error': '证书路径和密钥路径不能为空'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 通过 Agent 读取证书
        from apps.agents.command_queue import CommandQueue
        
        read_script = f"""#!/bin/bash
if [ -f "{cert_path}" ] && [ -f "{key_path}" ]; then
    echo "===CERT==="
    cat "{cert_path}"
    echo "===KEY==="
    cat "{key_path}"
else
    echo "证书文件不存在"
    exit 1
fi
"""
        cmd = execute_script_via_agent(agent, read_script, timeout=30, script_name='read_cert.sh')
        
        # 等待命令执行完成
        max_wait = 30
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status == 'success':
            result = cmd.result or ''
            # 解析证书和密钥
            if '===CERT===' in result and '===KEY===' in result:
                parts = result.split('===KEY===')
                cert_content = parts[0].replace('===CERT===', '').strip()
                key_content = parts[1].strip() if len(parts) > 1 else ''
                return Response({
                    'cert_content': cert_content,
                    'key_content': key_content
                })
            else:
                return Response({
                    'error': '解析证书内容失败',
                    'cert_content': '',
                    'key_content': ''
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({
                'error': cmd.error or '读取证书失败',
                'cert_content': '',
                'key_content': ''
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['delete'])
    def delete_certificate(self, request, pk=None):
        """删除证书文件"""
        proxy = self.get_object()
        server = proxy.server
        
        cert_path = request.data.get('cert_path')
        key_path = request.data.get('key_path')
        
        if not cert_path or not key_path:
            return Response({'error': '证书路径和密钥路径不能为空'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 通过 Agent 删除证书
        from apps.agents.command_queue import CommandQueue
        
        delete_script = f"""#!/bin/bash
# 删除证书文件
rm -f "{cert_path}" "{key_path}"
echo "证书删除成功"
"""
        cmd = execute_script_via_agent(agent, delete_script, timeout=30, script_name='delete_cert.sh')
        
        # 等待命令执行完成
        max_wait = 30
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if cmd.status == 'success':
            return Response({
                'message': '证书删除成功',
                'result': cmd.result or ''
            })
        else:
            return Response({
                'error': cmd.error or '证书删除失败',
                'result': cmd.result or ''
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
