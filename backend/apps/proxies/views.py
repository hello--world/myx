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
import json
import logging
from pathlib import Path

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
        
        # 如果启用了自动配置域名，执行域名配置
        auto_setup_domain = request.data.get('auto_setup_domain', False)
        zone_id = request.data.get('zone_id')
        if auto_setup_domain:
            try:
                from .proxy_domain_utils import auto_setup_proxy_with_domain
                from apps.settings.models import CloudflareZone
                
                zone = None
                if zone_id:
                    try:
                        zone = CloudflareZone.objects.get(id=zone_id, is_active=True)
                    except CloudflareZone.DoesNotExist:
                        logger.warning(f'指定的 Cloudflare Zone 不存在: zone_id={zone_id}')
                
                result = auto_setup_proxy_with_domain(proxy, zone)
                if result['success']:
                    logger.info(f'代理 {proxy.id} 自动配置域名成功: {result.get("domain")}')
                    # 域名配置成功，继续部署流程
                else:
                    logger.warning(f'代理 {proxy.id} 自动配置域名失败: {result.get("error")}')
                    # 域名配置失败，但不阻止代理创建和部署
            except Exception as e:
                logger.error(f'自动配置域名时出错: {str(e)}', exc_info=True)
                # 出错时不阻止代理创建和部署
        
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
    def test_proxy(self, request, pk=None):
        """测试代理节点连接（使用xray客户端自测）"""
        logger.info(f'[test_proxy] 收到测试请求: proxy_id={pk}, user={request.user.username}')
        
        try:
            proxy = self.get_object()
            logger.info(f'[test_proxy] 找到代理: id={proxy.id}, name={proxy.name}, server={proxy.server.name}')
        except NotFound:
            logger.error(f'[test_proxy] 代理不存在: proxy_id={pk}, user={request.user.username}')
            return Response({
                'error': '代理不存在',
                'detail': f'代理 ID {pk} 不存在或无权访问'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f'[test_proxy] 获取代理失败: proxy_id={pk}, error={str(e)}', exc_info=True)
            return Response({
                'error': '获取代理失败',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        server = proxy.server
        logger.info(f'[test_proxy] 代理服务器: id={server.id}, name={server.name}, host={server.host}')
        
        # 检查是否有 Agent
        from apps.agents.models import Agent
        try:
            agent = Agent.objects.get(server=server)
            logger.info(f'[test_proxy] 找到Agent: id={agent.id}, status={agent.status}, rpc_port={agent.rpc_port}')
            if agent.status != 'online':
                logger.warning(f'[test_proxy] Agent不在线: agent_id={agent.id}, status={agent.status}')
                return Response({'error': 'Agent不在线'}, status=status.HTTP_400_BAD_REQUEST)
        except Agent.DoesNotExist:
            logger.error(f'[test_proxy] 服务器未安装Agent: server_id={server.id}, server_name={server.name}')
            return Response({'error': '服务器未安装Agent'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'[test_proxy] 获取Agent失败: server_id={server.id}, error={str(e)}', exc_info=True)
            return Response({
                'error': '获取Agent失败',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # 检查代理是否已部署
        logger.info(f'[test_proxy] 检查部署状态: deployment_status={proxy.deployment_status}')
        if proxy.deployment_status != 'success':
            logger.warning(f'[test_proxy] 代理未部署成功: proxy_id={proxy.id}, deployment_status={proxy.deployment_status}')
            return Response({
                'error': '代理节点尚未部署成功，无法测试',
                'deployment_status': proxy.deployment_status
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 生成客户端测试配置
            # Agent节点自测：客户端连接到本地127.0.0.1，因为代理节点和测试客户端都在同一台服务器上
            logger.info(f'[test_proxy] 开始生成客户端配置: protocol={proxy.protocol}, port={proxy.port}')
            from utils.xray_config import generate_xray_client_config
            
            server_host = '127.0.0.1'  # 本地测试，使用127.0.0.1
            client_config = generate_xray_client_config(proxy, server_host)
            logger.info(f'[test_proxy] 客户端配置生成成功')
            
            # 将配置转换为JSON字符串
            test_config_json = json.dumps(client_config, indent=2)
            logger.info(f'[test_proxy] 配置JSON长度: {len(test_config_json)} 字符')
            
            # 读取Python测试脚本（从服务器本地读取，不依赖Agent上的文件）
            # 脚本会通过execute_script_via_agent上传到Agent执行
            # 使用与deployment_tool.py相同的路径计算逻辑
            from apps.deployments.deployment_tool import DEPLOYMENT_TOOL_DIR
            
            script_path = DEPLOYMENT_TOOL_DIR / 'scripts' / 'test_proxy.py'
            logger.info(f'[test_proxy] 脚本路径: {script_path}')
            
            if not script_path.exists():
                logger.error(f'[test_proxy] 测试脚本文件不存在: {script_path}')
                return Response({
                    'error': '测试脚本文件不存在',
                    'detail': f'找不到脚本文件: {script_path}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            logger.info(f'[test_proxy] 读取测试脚本: {script_path}')
            with open(script_path, 'r', encoding='utf-8') as f:
                python_script = f.read()
            logger.info(f'[test_proxy] 脚本读取成功，长度: {len(python_script)} 字符')
            
            # 修改脚本，将配置JSON嵌入到脚本中（而不是通过命令行参数）
            # 替换脚本中的配置读取逻辑
            logger.info(f'[test_proxy] 开始嵌入配置到脚本中...')
            try:
                python_script = python_script.replace(
                    'if len(sys.argv) < 2:',
                    'if False:  # 配置已嵌入，跳过参数检查'
                )
                python_script = python_script.replace(
                    'config_json = sys.argv[1]',
                    f'config_json = """{test_config_json}"""'
                )
                logger.info(f'[test_proxy] 配置嵌入成功，脚本长度: {len(python_script)} 字符')
            except Exception as e:
                logger.error(f'[test_proxy] 嵌入配置失败: error={str(e)}', exc_info=True)
                return Response({
                    'error': '嵌入配置到脚本失败',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # 通过Agent执行Python脚本
            logger.info(f'[test_proxy] 开始通过Agent执行脚本: agent_id={agent.id}')
            try:
                cmd = execute_script_via_agent(agent, python_script, timeout=30, script_name='test_proxy.py')
                logger.info(f'[test_proxy] 命令已提交: command_id={cmd.id}, agent_id={agent.id}')
            except Exception as e:
                logger.error(f'[test_proxy] 提交命令失败: agent_id={agent.id}, error={str(e)}', exc_info=True)
                return Response({
                    'error': '提交测试命令失败',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # 等待命令执行完成
            logger.info(f'[test_proxy] 开始等待代理测试完成: proxy_id={proxy.id}, command_id={cmd.id}')
            max_wait = 30
            wait_time = 0
            while wait_time < max_wait:
                try:
                    cmd.refresh_from_db()
                    if cmd.status in ['success', 'failed']:
                        logger.info(f'[test_proxy] 代理测试完成: proxy_id={proxy.id}, command_id={cmd.id}, status={cmd.status}, wait_time={wait_time}秒')
                        break
                    time.sleep(1)
                    wait_time += 1
                    
                    # 每5秒记录一次等待状态
                    if wait_time % 5 == 0:
                        logger.info(f'[test_proxy] 等待代理测试完成: proxy_id={proxy.id}, command_id={cmd.id}, 已等待{wait_time}秒, 当前状态={cmd.status}')
                except Exception as e:
                    logger.error(f'[test_proxy] 等待过程中出错: command_id={cmd.id}, error={str(e)}', exc_info=True)
                    return Response({
                        'error': '等待测试完成时出错',
                        'detail': str(e)
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            if wait_time >= max_wait:
                logger.warning(f'[test_proxy] 代理测试超时: proxy_id={proxy.id}, command_id={cmd.id}, 等待时间超过{max_wait}秒')
                return Response({
                    'error': f'测试超时（超过{max_wait}秒）',
                    'result': cmd.result or '',
                    'success': False
                }, status=status.HTTP_408_REQUEST_TIMEOUT)
            
            if cmd.status == 'success':
                logger.info(f'[test_proxy] 代理测试成功: proxy_id={proxy.id}, command_id={cmd.id}')
                result_output = cmd.result or ''
                logger.info(f'[test_proxy] 测试结果输出长度: {len(result_output)} 字符')
                if result_output:
                    if len(result_output) > 1000:
                        logger.info(f'[test_proxy] 测试结果输出（前1000字符）:\n{result_output[:1000]}...')
                        logger.info(f'[test_proxy] 测试结果输出（后500字符）:\n...{result_output[-500:]}')
                    else:
                        logger.info(f'[test_proxy] 测试结果完整输出:\n{result_output}')
                else:
                    logger.warning(f'[test_proxy] 测试成功但结果为空: proxy_id={proxy.id}, command_id={cmd.id}')
                return Response({
                    'message': '代理节点测试成功',
                    'result': result_output,
                    'success': True
                })
            else:
                # 获取完整的执行结果
                result_output = cmd.result or ''
                error_output = cmd.error or ''
                
                logger.error(f'[test_proxy] 代理测试失败: proxy_id={proxy.id}, command_id={cmd.id}')
                logger.error(f'[test_proxy] 命令状态: {cmd.status}')
                logger.error(f'[test_proxy] error字段: {error_output if error_output else "(空)"}')
                logger.error(f'[test_proxy] result字段长度: {len(result_output)} 字符')
                
                # 如果error为空，尝试从result中提取错误信息
                if not error_output and result_output:
                    # 检查result中是否包含错误信息
                    if '错误' in result_output or '失败' in result_output or 'error' in result_output.lower():
                        error_output = result_output
                        logger.info(f'[test_proxy] 从result中提取错误信息')
                
                # 记录完整的输出（用于调试）
                if result_output:
                    if len(result_output) > 1000:
                        logger.error(f'[test_proxy] 测试结果输出（前1000字符）:\n{result_output[:1000]}...')
                        logger.error(f'[test_proxy] 测试结果输出（后500字符）:\n...{result_output[-500:]}')
                    else:
                        logger.error(f'[test_proxy] 测试结果完整输出:\n{result_output}')
                
                if error_output:
                    if len(error_output) > 1000:
                        logger.error(f'[test_proxy] 错误信息（前1000字符）:\n{error_output[:1000]}...')
                    else:
                        logger.error(f'[test_proxy] 错误信息完整输出:\n{error_output}')
                
                # 构建错误消息
                if error_output:
                    error_msg = error_output
                elif result_output:
                    # 如果只有result，使用result作为错误信息
                    error_msg = result_output[:500] + ('...' if len(result_output) > 500 else '')
                else:
                    error_msg = '代理节点测试失败（无详细错误信息）'
                
                logger.error(f'[test_proxy] 最终错误消息: {error_msg[:200]}...' if len(error_msg) > 200 else f'[test_proxy] 最终错误消息: {error_msg}')
                
                return Response({
                    'error': error_msg,
                    'result': result_output,
                    'error_detail': error_output,
                    'success': False
                }, status=status.HTTP_400_BAD_REQUEST)
        
        except Exception as e:
            logger.error(f'[test_proxy] 测试过程发生异常: proxy_id={proxy.id}, error={str(e)}', exc_info=True)
            return Response({
                'error': '测试过程发生异常',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        
        # 创建读取命令（同时获取文件修改时间）
        read_script = """#!/bin/bash
if [ -f /etc/caddy/Caddyfile ]; then
    echo "===CONTENT==="
    cat /etc/caddy/Caddyfile
    echo "===MTIME==="
    stat -c %y /etc/caddy/Caddyfile 2>/dev/null || stat -f "%Sm" /etc/caddy/Caddyfile 2>/dev/null || echo ""
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
            result = cmd.result or ''
            content = ''
            mtime = None
            
            # 解析结果，分离内容和修改时间
            if '===CONTENT===' in result and '===MTIME===' in result:
                parts = result.split('===CONTENT===')
                if len(parts) > 1:
                    content_part = parts[1].split('===MTIME===')
                    content = content_part[0].strip() if content_part else ''
                    if len(content_part) > 1:
                        mtime_str = content_part[1].strip()
                        if mtime_str:
                            mtime = mtime_str
            else:
                # 兼容旧格式（没有分隔符的情况）
                content = result
            
            return Response({
                'content': content,
                'mtime': mtime,  # 文件修改时间
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
        
        # 创建更新脚本（先保存到临时文件，验证通过后再写入正式文件）
        import uuid
        temp_file = f"/tmp/caddyfile_{uuid.uuid4().hex[:8]}"
        
        update_script = f"""#!/bin/bash
set -e

# 备份原文件
if [ -f /etc/caddy/Caddyfile ]; then
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%Y%m%d_%H%M%S)
fi

# 先写入临时文件
cat > {temp_file} << 'CADDYFILE_EOF'
{content}
CADDYFILE_EOF

# 验证临时文件配置
VALIDATE_OUTPUT=$(caddy validate --config {temp_file} 2>&1)
VALIDATE_EXIT=$?

if [ $VALIDATE_EXIT -eq 0 ]; then
    # 验证通过，写入正式文件
    cp {temp_file} /etc/caddy/Caddyfile
    rm -f {temp_file}
    echo "配置验证成功，文件已保存"
    exit 0
else
    # 验证失败，删除临时文件，保留原文件
    rm -f {temp_file}
    echo "配置验证失败："
    echo "$VALIDATE_OUTPUT"
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
            # 保存历史版本（只有验证通过并成功保存后才创建历史记录）
            from .models import CaddyfileHistory
            # 先创建历史记录
            CaddyfileHistory.objects.create(
                proxy=proxy,
                content=content,
                created_by=request.user
            )
            # 保留最近30个版本，删除更早的版本
            histories = CaddyfileHistory.objects.filter(proxy=proxy).order_by('-created_at')
            if histories.count() > 30:
                # 删除第30个之后的版本
                for old_history in histories[30:]:
                    old_history.delete()
            
            return Response({
                'message': 'Caddyfile更新成功（已通过验证）',
                'result': cmd.result or ''
            })
        else:
            # 验证失败，返回详细错误信息
            error_msg = cmd.error or 'Caddyfile更新失败'
            result_output = cmd.result or ''
            
            # 如果结果中包含验证错误信息，提取出来
            if '配置验证失败' in result_output:
                # 提取验证错误的具体信息
                lines = result_output.split('\n')
                validation_errors = []
                in_error_section = False
                for line in lines:
                    if '配置验证失败' in line:
                        in_error_section = True
                        continue
                    if in_error_section and line.strip():
                        validation_errors.append(line)
                
                if validation_errors:
                    error_msg = 'Caddyfile配置验证失败：\n' + '\n'.join(validation_errors)
            
            return Response({
                'error': error_msg,
                'result': result_output,
                'validation_failed': True
            }, status=status.HTTP_400_BAD_REQUEST)

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
        seen_certs = set()  # 用于去重
        
        # 匹配简单格式: tls /path/to/cert.pem /path/to/key.key
        # 支持 .pem, .crt, .key 等扩展名
        tls_pattern = r'tls\s+([^\s{}]+\.(pem|crt|key))\s+([^\s{}]+\.(pem|crt|key))'
        matches = re.finditer(tls_pattern, caddyfile_content, re.MULTILINE)
        for match in matches:
            cert_path = match.group(1).strip()
            key_path = match.group(3).strip()
            
            # 确保第一个是证书文件，第二个是密钥文件
            if cert_path.endswith('.key') and key_path.endswith(('.pem', '.crt')):
                # 如果顺序反了，交换
                cert_path, key_path = key_path, cert_path
            
            # 提取域名（从证书文件名推断，去掉扩展名）
            cert_filename = cert_path.split('/')[-1]
            domain = cert_filename.replace('.pem', '').replace('.crt', '').replace('.key', '')
            
            # 尝试从上下文提取域名（查找该 tls 行之前的域名行）
            lines_before = caddyfile_content[:match.start()].split('\n')
            for i in range(len(lines_before) - 1, max(0, len(lines_before) - 10), -1):
                line = lines_before[i].strip()
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                # 如果找到域名行（不以 { 开头，不包含空格或包含点号）
                if '{' not in line and ('.' in line or not ' ' in line):
                    # 提取域名（去掉端口号）
                    potential_domain = line.split()[0] if ' ' in line else line
                    potential_domain = potential_domain.split(':')[0]  # 去掉端口
                    if '.' in potential_domain or potential_domain.startswith('localhost'):
                        domain = potential_domain
                        break
            
            cert_key = (cert_path, key_path)
            if cert_key not in seen_certs:
                seen_certs.add(cert_key)
            certificates.append({
                'domain': domain,
                'cert_path': cert_path,
                'key_path': key_path,
                    'line': caddyfile_content[:match.start()].count('\n') + 1,
                    'format': 'simple'
            })
        
        # 匹配块格式: tls { certificate ... key ... }
        block_pattern = r'tls\s*\{[^}]*certificate\s+([^\s{}]+\.(pem|crt|key))[^}]*key\s+([^\s{}]+\.(pem|crt|key))[^}]*\}'
        block_matches = re.finditer(block_pattern, caddyfile_content, re.MULTILINE | re.DOTALL)
        for match in block_matches:
            cert_path = match.group(1).strip()
            key_path = match.group(3).strip()
            
            # 确保第一个是证书文件，第二个是密钥文件
            if cert_path.endswith('.key') and key_path.endswith(('.pem', '.crt')):
                cert_path, key_path = key_path, cert_path
            
            cert_filename = cert_path.split('/')[-1]
            domain = cert_filename.replace('.pem', '').replace('.crt', '').replace('.key', '')
            
            # 尝试从上下文提取域名
            lines_before = caddyfile_content[:match.start()].split('\n')
            for i in range(len(lines_before) - 1, max(0, len(lines_before) - 10), -1):
                line = lines_before[i].strip()
                if not line or line.startswith('#'):
                    continue
                if '{' not in line and ('.' in line or not ' ' in line):
                    potential_domain = line.split()[0] if ' ' in line else line
                    potential_domain = potential_domain.split(':')[0]
                    if '.' in potential_domain or potential_domain.startswith('localhost'):
                        domain = potential_domain
                        break
            
            cert_key = (cert_path, key_path)
            if cert_key not in seen_certs:
                seen_certs.add(cert_key)
            certificates.append({
                'domain': domain,
                'cert_path': cert_path,
                'key_path': key_path,
                    'line': caddyfile_content[:match.start()].count('\n') + 1,
                    'format': 'block'
                })
        
        # 从数据库读取手动上传的证书（即使 Caddyfile 中没有配置）
        from .models import Certificate
        db_certificates = Certificate.objects.filter(server=server).values(
            'id', 'domain', 'cert_path', 'key_path', 'created_at', 'updated_at'
        )
        
        # 将数据库中的证书添加到列表中（如果不在 Caddyfile 中）
        seen_paths = {(c['cert_path'], c['key_path']) for c in certificates}
        for db_cert in db_certificates:
            cert_key = (db_cert['cert_path'], db_cert['key_path'])
            if cert_key not in seen_paths:
                certificates.append({
                    'id': db_cert['id'],
                    'domain': db_cert['domain'] or db_cert['cert_path'].split('/')[-1].replace('.pem', '').replace('.crt', ''),
                    'cert_path': db_cert['cert_path'],
                    'key_path': db_cert['key_path'],
                    'line': None,  # 数据库中的证书没有行号
                    'format': 'database',  # 标记为数据库存储
                    'created_at': db_cert['created_at'].isoformat() if db_cert['created_at'] else None,
                    'updated_at': db_cert['updated_at'].isoformat() if db_cert['updated_at'] else None
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
            # 保存证书信息到数据库
            from .models import Certificate
            domain = request.data.get('domain', '')
            remark = request.data.get('remark', '')
            
            # 检查是否已存在相同的证书路径
            cert, created = Certificate.objects.update_or_create(
                server=server,
                cert_path=cert_path,
                key_path=key_path,
                defaults={
                    'domain': domain or None,
                    'remark': remark or None,
                    'created_by': request.user
                }
            )
            
            return Response({
                'message': '证书上传成功',
                'result': cmd.result or '',
                'certificate_id': cert.id,
                'created': created
            })
        else:
            return Response({
                'error': cmd.error or '证书上传失败',
                'result': cmd.result or ''
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def list_caddyfile_history(self, request, pk=None):
        """列出Caddyfile历史版本"""
        proxy = self.get_object()
        
        from .models import CaddyfileHistory
        from django.core.paginator import Paginator
        
        histories = CaddyfileHistory.objects.filter(proxy=proxy).order_by('-created_at')
        
        # 分页（可选）
        page = request.query_params.get('page', 1)
        page_size = request.query_params.get('page_size', 30)
        paginator = Paginator(histories, page_size)
        page_obj = paginator.get_page(page)
        
        history_list = []
        for history in page_obj:
            history_list.append({
                'id': history.id,
                'content': history.content,
                'created_at': history.created_at.isoformat(),
                'created_by': history.created_by.username if history.created_by else None
            })
        
        return Response({
            'count': paginator.count,
            'results': history_list,
            'page': page_obj.number,
            'pages': paginator.num_pages
        })

    @action(detail=True, methods=['get'], url_path='caddyfile_history/(?P<history_id>[^/.]+)')
    def get_caddyfile_history(self, request, pk=None, history_id=None):
        """获取指定历史版本的Caddyfile内容"""
        proxy = self.get_object()
        
        from .models import CaddyfileHistory
        try:
            history = CaddyfileHistory.objects.get(id=history_id, proxy=proxy)
            return Response({
                'id': history.id,
                'content': history.content,
                'created_at': history.created_at.isoformat(),
                'created_by': history.created_by.username if history.created_by else None
            })
        except CaddyfileHistory.DoesNotExist:
            return Response({
                'error': '历史版本不存在'
            }, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['delete'], url_path='certificates/(?P<cert_id>[^/.]+)/delete_record')
    def delete_certificate_record(self, request, pk=None, cert_id=None):
        """删除证书记录（仅删除数据库记录，不删除服务器上的文件）"""
        proxy = self.get_object()
        server = proxy.server
        
        from .models import Certificate
        try:
            cert = Certificate.objects.get(id=cert_id, server=server)
            cert.delete()
            return Response({
                'message': '证书记录已删除'
            }, status=status.HTTP_204_NO_CONTENT)
        except Certificate.DoesNotExist:
            return Response({
                'error': '证书记录不存在'
            }, status=status.HTTP_404_NOT_FOUND)

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

    @action(detail=True, methods=['post'], url_path='setup-domain')
    def setup_domain(self, request, pk=None):
        """为代理自动设置域名、DNS 记录、证书和 Caddyfile"""
        proxy = self.get_object()
        
        # 检查权限
        if proxy.created_by != request.user:
            return Response({
                'error': '无权操作此代理',
                'detail': '此代理不属于当前用户'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # 获取可选的 zone_id
        zone_id = request.data.get('zone_id')
        zone = None
        if zone_id:
            from apps.settings.models import CloudflareZone
            try:
                zone = CloudflareZone.objects.get(id=zone_id, is_active=True)
            except CloudflareZone.DoesNotExist:
                return Response({
                    'error': '指定的 Cloudflare Zone 不存在或未激活'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # 调用自动配置函数
        from .proxy_domain_utils import auto_setup_proxy_with_domain
        
        try:
            result = auto_setup_proxy_with_domain(proxy, zone)
            
            if result['success']:
                # 如果配置成功，尝试更新 Caddyfile
                caddyfile_config = result.get('caddyfile_config')
                if caddyfile_config:
                    # 读取现有 Caddyfile
                    from apps.agents.models import Agent
                    try:
                        agent = Agent.objects.get(server=proxy.server)
                        if agent.status == 'online':
                            # 获取现有 Caddyfile
                            get_caddyfile_script = """#!/bin/bash
if [ -f /etc/caddy/Caddyfile ]; then
    cat /etc/caddy/Caddyfile
else
    echo ""
fi
"""
                            cmd = execute_script_via_agent(agent, get_caddyfile_script, timeout=10)
                            if cmd.status == 'success':
                                existing_content = cmd.result.strip() if cmd.result else ''
                                
                                # 合并配置
                                domain = result['domain']
                                import re
                                # 检查是否已存在该域名的配置
                                pattern = rf'{re.escape(domain)}\s*\{{[^}}]*\}}'
                                if re.search(pattern, existing_content, re.MULTILINE | re.DOTALL):
                                    # 替换现有配置
                                    updated_content = re.sub(pattern, caddyfile_config, existing_content, flags=re.MULTILINE | re.DOTALL)
                                else:
                                    # 追加新配置
                                    if existing_content:
                                        updated_content = f"{existing_content}\n\n{caddyfile_config}"
                                    else:
                                        updated_content = caddyfile_config
                                
                                # 更新 Caddyfile
                                update_response = self.update_caddyfile(
                                    request=type('Request', (), {
                                        'data': {'content': updated_content},
                                        'user': request.user
                                    })(),
                                    pk=proxy.id
                                )
                                
                                if update_response.status_code != 200:
                                    logger.warning(f'更新 Caddyfile 失败: {update_response.data}')
                    except Agent.DoesNotExist:
                        logger.warning('服务器未安装 Agent，跳过 Caddyfile 更新')
                    except Exception as e:
                        logger.warning(f'更新 Caddyfile 时出错: {str(e)}')
                
                # 记录日志
                create_log_entry(
                    log_type='proxy',
                    level='info',
                    title=f'自动配置代理域名: {proxy.name}',
                    content=f'为代理 {proxy.name} 自动配置域名 {result["domain"]}，DNS 记录和证书已创建',
                    user=request.user,
                    server=proxy.server,
                    related_id=proxy.id,
                    related_type='proxy'
                )
                
                return Response({
                    'success': True,
                    'message': result['message'],
                    'domain': result['domain'],
                    'dns_record_id': result['dns_record'].id if result.get('dns_record') else None,
                    'cert_id': result['certificate']['cert_id'] if result.get('certificate') else None,
                })
            else:
                return Response({
                    'success': False,
                    'error': result.get('error', '未知错误'),
                    'message': result.get('message', '自动配置失败')
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f'自动配置代理域名失败: {str(e)}', exc_info=True)
            return Response({
                'success': False,
                'error': str(e),
                'message': f'自动配置失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, *args, **kwargs):
        """删除代理节点并同步删除已部署的配置（同步操作，会提示用户）"""
        proxy = self.get_object()
        
        # 检查权限
        if proxy.created_by != request.user:
            return Response({
                'error': '无权删除此代理',
                'detail': '此代理不属于当前用户'
            }, status=status.HTTP_403_FORBIDDEN)
        
        server = proxy.server
        proxy_name = proxy.name
        proxy_port = proxy.port
        
        # 检查服务器是否有 Agent 且在线
        from apps.agents.models import Agent
        agent = None
        try:
            agent = Agent.objects.get(server=server)
            if agent.status != 'online':
                agent = None  # Agent 不在线，无法删除配置
        except Agent.DoesNotExist:
            pass  # 没有 Agent，无法删除配置
        
        # 如果 Agent 在线，先删除已部署的配置（重新部署剩余代理的配置）
        if agent:
            try:
                from apps.deployments.agent_deployer import deploy_xray_config_via_agent as _deploy_config
                from utils.xray_config import generate_xray_config_json_for_proxies
                
                # 获取删除后剩余的启用的代理（排除当前要删除的代理）
                remaining_proxies = Proxy.objects.filter(
                    server=server,
                    status='active',
                    enable=True
                ).exclude(id=proxy.id).order_by('id')
                
                # 生成新的 Xray 配置（不包含要删除的代理）
                if remaining_proxies.exists():
                    config_json = generate_xray_config_json_for_proxies(list(remaining_proxies))
                    # 同步部署新配置（删除当前代理的配置）
                    success, message = _deploy_config(server, config_json)
                    if not success:
                        logger.warning(f'删除代理节点时重新部署配置失败: proxy_id={proxy.id}, error={message}')
                        # 即使重新部署失败，也继续删除代理节点
                else:
                    # 没有剩余代理，删除整个 Xray 配置
                    # 生成一个空的配置（只包含基础结构）
                    empty_config = {
                        "log": {
                            "loglevel": "warning"
                        },
                        "inbounds": [],
                        "outbounds": [
                            {
                                "protocol": "freedom",
                                "tag": "direct"
                            }
                        ],
                        "routing": {
                            "domainStrategy": "AsIs",
                            "rules": []
                        }
                    }
                    success, message = _deploy_config(server, json.dumps(empty_config, indent=2))
                    if not success:
                        logger.warning(f'删除代理节点时清空配置失败: proxy_id={proxy.id}, error={message}')
                
                # 记录删除配置日志
                create_log_entry(
                    log_type='proxy',
                    level='info',
                    title=f'删除代理节点配置: {proxy_name}',
                    content=f'已从服务器 {server.name} 删除代理节点 {proxy_name} (端口: {proxy_port}) 的配置',
                    user=request.user,
                    server=server,
                    related_id=proxy.id,
                    related_type='proxy'
                )
            except Exception as e:
                logger.error(f'删除代理节点时处理配置失败: proxy_id={proxy.id}, error={str(e)}', exc_info=True)
                # 即使处理配置失败，也继续删除代理节点
        
        # 删除代理节点
        proxy.delete()
        
        # 记录删除日志
        create_log_entry(
            log_type='proxy',
            level='info',
            title=f'删除代理节点: {proxy_name}',
            content=f'代理节点 {proxy_name} (端口: {proxy_port}) 已删除',
            user=request.user,
            server=server,
            related_type='proxy'
        )
        
        return Response({
            'message': '代理节点已删除，已同步删除服务器上的配置',
            'deleted_proxy': {
                'name': proxy_name,
                'port': proxy_port
            }
        }, status=status.HTTP_200_OK)
