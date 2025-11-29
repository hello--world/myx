import paramiko
from io import StringIO


def test_ssh_connection(host, port, username, password=None, private_key=None):
    """测试SSH连接"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if private_key:
            # 使用私钥认证
            key_file = StringIO(private_key)
            try:
                private_key_obj = paramiko.RSAKey.from_private_key(key_file)
            except:
                key_file.seek(0)
                private_key_obj = paramiko.Ed25519Key.from_private_key(key_file)
            ssh.connect(hostname=host, port=port, username=username, pkey=private_key_obj, timeout=10)
        elif password:
            # 使用密码认证
            ssh.connect(hostname=host, port=port, username=username, password=password, timeout=10)
        else:
            return {'success': False, 'error': '必须提供密码或私钥'}

        # 测试执行命令
        stdin, stdout, stderr = ssh.exec_command('echo "test"')
        exit_status = stdout.channel.recv_exit_status()

        ssh.close()

        if exit_status == 0:
            return {'success': True}
        else:
            return {'success': False, 'error': f'命令执行失败，退出码: {exit_status}'}

    except paramiko.AuthenticationException:
        return {'success': False, 'error': '认证失败，请检查用户名、密码或私钥'}
    except paramiko.SSHException as e:
        return {'success': False, 'error': f'SSH连接错误: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'连接异常: {str(e)}'}

