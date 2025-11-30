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
        
        # 创建服务器（先保存密码，即使save_password=False，也需要临时保存用于安装Agent）
        # 安装完成后，如果save_password=False，再清空密码
        server = serializer.save()
        
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
                    from apps.deployments.tasks import install_agent_via_ssh, wait_for_agent_registration
                    
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
                        
                        # 如果用户未选择保存密码，清空密码
                        if not should_save_password:
                            server.refresh_from_db()
                            server.password = None
                            server.save()
                            create_log_entry(
                                log_type='server',
                                level='info',
                                title=f'已清理密码: {server.name}',
                                content=f'Agent安装失败，已清理服务器密码（未选择保存密码）',
                                user=request.user,
                                server=server
                            )
                        return
                    
                    # 等待Agent注册
                    deployment.log = (deployment.log or '') + "等待Agent注册...\n"
                    deployment.save()
                    
                    agent = wait_for_agent_registration(server, timeout=120)
                    if not agent:
                        deployment.status = 'failed'
                        deployment.error_message = 'Agent注册超时'
                        deployment.completed_at = timezone.now()
                        deployment.save()
                        
                        # 更新服务器状态
                        server.refresh_from_db()
                        server.status = 'error'
                        if original_connection_method == 'agent':
                            server.connection_method = 'ssh'
                        server.save()
                        
                        # 记录Agent注册超时日志
                        create_log_entry(
                            log_type='agent',
                            level='error',
                            title=f'Agent注册超时: {server.name}',
                            content=f'Agent安装完成但注册超时，部署任务ID: {deployment.id}',
                            user=request.user,
                            server=server,
                            related_id=deployment.id,
                            related_type='deployment'
                        )
                        
                        # 如果用户未选择保存密码，清空密码
                        if not should_save_password:
                            server.refresh_from_db()
                            server.password = None
                            server.save()
                            create_log_entry(
                                log_type='server',
                                level='info',
                                title=f'已清理密码: {server.name}',
                                content=f'Agent注册超时，已清理服务器密码（未选择保存密码）',
                                user=request.user,
                                server=server
                            )
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
                    
                    # 如果用户未选择保存密码，安装完成后清空密码
                    if not should_save_password:
                        server.refresh_from_db()
                        server.password = None
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
                    # 如果用户未选择保存密码，清空密码
                    if not should_save_password:
                        server.password = None
                    server.save()
                    
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

