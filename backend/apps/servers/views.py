from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Server
from .serializers import ServerSerializer, ServerTestSerializer
from .utils import test_ssh_connection
from apps.proxies.tasks import deploy_agent_and_services
from apps.agents.models import Agent
import paramiko
from io import StringIO
import os
import subprocess
import tempfile
import threading


class ServerViewSet(viewsets.ModelViewSet):
    """服务器视图集"""
    queryset = Server.objects.all()
    serializer_class = ServerSerializer

    def get_queryset(self):
        return Server.objects.filter(created_by=self.request.user)

    def _test_agent_connection(self, server):
        """测试Agent连接"""
        try:
            agent = Agent.objects.get(server=server)
            # 检查Agent是否在线（最近60秒内有心跳）
            if agent.status == 'online':
                # 检查最后心跳时间
                if agent.last_heartbeat:
                    time_since_heartbeat = timezone.now() - agent.last_heartbeat
                    if time_since_heartbeat.total_seconds() <= 60:
                        return {
                            'success': True,
                            'message': 'Agent连接成功',
                            'agent_status': 'online',
                            'last_heartbeat': agent.last_heartbeat
                        }
                    else:
                        return {
                            'success': False,
                            'error': f'Agent长时间未心跳（{int(time_since_heartbeat.total_seconds())}秒）',
                            'agent_status': 'offline'
                        }
                else:
                    return {
                        'success': False,
                        'error': 'Agent从未发送心跳',
                        'agent_status': 'offline'
                    }
            else:
                return {
                    'success': False,
                    'error': f'Agent状态为: {agent.status}',
                    'agent_status': agent.status
                }
        except Agent.DoesNotExist:
            return {
                'success': False,
                'error': '服务器未安装Agent',
                'agent_status': None
            }
        except Exception as e:
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
                    return Response({
                        'message': '连接成功',
                        'status': 'active',
                        'connection_method': 'ssh'
                    })
                else:
                    server.status = 'error'
                    server.last_check = timezone.now()
                    server.save()
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
                return Response(
                    {
                        'message': f"连接测试异常: {str(e)}",
                        'status': 'error',
                        'connection_method': 'ssh'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

    @action(detail=False, methods=['post'])
    def test(self, request):
        """测试连接（不保存，根据连接方式自动选择SSH或Agent）"""
        # 检查是否提供了服务器ID（用于Agent测试）
        server_id = request.data.get('server_id')
        connection_method = request.data.get('connection_method', 'ssh')
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
        """创建服务器，处理密码保存和SSH key生成"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        save_password = request.data.get('save_password', False)
        enable_ssh_key = request.data.get('enable_ssh_key', False)
        password = request.data.get('password', '')
        connection_method = request.data.get('connection_method', 'ssh')
        
        # 如果未开启保存密码，清空密码
        if not save_password:
            serializer.validated_data['password'] = None
        
        # 创建服务器
        server = serializer.save()
        
        # 如果启用SSH key登录，生成key并添加到服务器
        if enable_ssh_key and password:
            try:
                result = self._generate_and_add_ssh_key(server, password)
                if result['success']:
                    server.generated_public_key = result['public_key']
                    server.save()
            except Exception as e:
                # 记录错误但不阻止服务器创建
                pass
        
        # 如果连接方式选择为Agent，自动安装Agent
        if connection_method == 'agent':
            # 检查是否有SSH凭证（密码或私钥）
            if server.password or server.private_key:
                # 临时将连接方式设置为SSH，以便安装Agent
                original_connection_method = server.connection_method
                server.connection_method = 'ssh'
                server.save()
                
                # 在后台线程中安装Agent，不阻塞响应
                def install_agent_async():
                    try:
                        # 重新获取服务器对象（避免缓存问题）
                        server.refresh_from_db()
                        success, message = deploy_agent_and_services(
                            server=server,
                            user=request.user,
                            heartbeat_mode='push'
                        )
                        if success:
                            # 更新服务器状态和连接方式
                            server.refresh_from_db()
                            server.status = 'active'
                            server.connection_method = 'agent'
                            server.save()
                        else:
                            # 安装失败，记录错误但保持服务器创建
                            server.refresh_from_db()
                            server.status = 'error'
                            # 如果安装失败，保持为ssh连接方式
                            server.save()
                    except Exception as e:
                        # 安装异常，记录错误但保持服务器创建
                        server.refresh_from_db()
                        server.status = 'error'
                        server.save()
                
                # 启动后台线程安装Agent
                thread = threading.Thread(target=install_agent_async, daemon=True)
                thread.start()
            else:
                # 没有SSH凭证，无法安装Agent，返回警告
                return Response({
                    **serializer.data,
                    'warning': '选择了Agent连接方式，但缺少SSH凭证（密码或私钥），无法自动安装Agent。请先提供SSH凭证，然后手动安装Agent。'
                }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """更新服务器，处理密码保存和SSH key生成"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        save_password = request.data.get('save_password', False)
        enable_ssh_key = request.data.get('enable_ssh_key', False)
        password = request.data.get('password', '')
        
        # 如果未开启保存密码，清空密码
        if not save_password:
            serializer.validated_data['password'] = None
        
        # 更新服务器
        server = serializer.save()
        
        # 如果启用SSH key登录且提供了密码，生成key并添加到服务器
        if enable_ssh_key and password:
            try:
                result = self._generate_and_add_ssh_key(server, password)
                if result['success']:
                    server.generated_public_key = result['public_key']
                    server.save()
            except Exception as e:
                pass
        
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

