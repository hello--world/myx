from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Proxy
from .serializers import ProxySerializer
from .tasks import auto_deploy_proxy
import time
import re
import os
import base64


class ProxyViewSet(viewsets.ModelViewSet):
    """代理节点视图集"""
    queryset = Proxy.objects.all()
    serializer_class = ProxySerializer

    def get_queryset(self):
        return Proxy.objects.filter(created_by=self.request.user)

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
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """重新部署代理"""
        proxy = self.get_object()
        
        # 重置部署状态
        proxy.deployment_status = 'pending'
        proxy.deployment_log = ''
        proxy.deployed_at = None
        proxy.save()
        
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
        script_b64 = base64.b64encode(read_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=30
        )
        
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
        import base64
        
        # 创建更新脚本
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        update_script = f"""#!/bin/bash
set -e

# 解码内容
CADDYFILE_CONTENT=$(echo '{content_b64}' | base64 -d)

# 备份原文件
if [ -f /etc/caddy/Caddyfile ]; then
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%Y%m%d_%H%M%S)
fi

# 写入新文件
echo "$CADDYFILE_CONTENT" > /etc/caddy/Caddyfile

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
        script_b64 = base64.b64encode(update_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=60
        )
        
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
        script_b64 = base64.b64encode(validate_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=30
        )
        
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
        script_b64 = base64.b64encode(reload_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=30
        )
        
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
        script_b64 = base64.b64encode(read_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=30
        )
        
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
        
        cert_content_b64 = base64.b64encode(cert_content.encode('utf-8')).decode('utf-8')
        key_content_b64 = base64.b64encode(key_content.encode('utf-8')).decode('utf-8')
        
        upload_script = f"""#!/bin/bash
set -e

# 解码证书内容
CERT_CONTENT=$(echo '{cert_content_b64}' | base64 -d)
KEY_CONTENT=$(echo '{key_content_b64}' | base64 -d)

# 创建目录（如果不存在）
mkdir -p "{cert_dir}"
mkdir -p "{key_dir}"

# 写入证书文件
echo "$CERT_CONTENT" > "{cert_path}"
echo "$KEY_CONTENT" > "{key_path}"

# 设置权限
chmod 600 "{cert_path}"
chmod 600 "{key_path}"

echo "证书上传成功"
"""
        script_b64 = base64.b64encode(upload_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=30
        )
        
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
        script_b64 = base64.b64encode(read_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=30
        )
        
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
        script_b64 = base64.b64encode(delete_script.encode('utf-8')).decode('utf-8')
        
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=30
        )
        
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
