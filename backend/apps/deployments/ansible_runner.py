import os
import subprocess
import tempfile
from pathlib import Path
from apps.servers.models import Server


def run_ansible_playbook(server: Server, playbook_name: str):
    """运行Ansible playbook"""
    BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
    # 统一使用deployment-tool/playbooks/中的playbook
    playbook_path = BASE_DIR / 'deployment-tool' / 'playbooks' / playbook_name

    if not playbook_path.exists():
        return {
            'success': False,
            'error': f'Playbook文件不存在: {playbook_path}',
            'log': ''
        }

    # 创建临时inventory文件
    inventory_content = f"""[target]
{server.host} ansible_host={server.host} ansible_port={server.port} ansible_user={server.username}
"""
    key_file_path = None
    if server.password:
        inventory_content += f" ansible_ssh_pass={server.password}"
    if server.private_key:
        # 如果使用私钥，需要先保存到临时文件
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key') as key_file:
            key_file.write(server.private_key)
            key_file_path = key_file.name
        inventory_content += f" ansible_ssh_private_key_file={key_file_path}"

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.ini') as f:
        f.write(inventory_content)
        inventory_file = f.name

    try:
        # 运行ansible-playbook命令
        cmd = [
            'ansible-playbook',
            '-i', inventory_file,
            str(playbook_path),
            '--become',
            '--become-method=sudo'
        ]

        if server.password:
            cmd.extend(['--ask-pass'])
            env = os.environ.copy()
            env['ANSIBLE_SSH_PASS'] = server.password
        else:
            env = os.environ.copy()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10分钟超时
                env=env
            )

            log_output = result.stdout + result.stderr

            if result.returncode == 0:
                return {
                    'success': True,
                    'log': log_output,
                    'error': None
                }
            else:
                return {
                    'success': False,
                    'error': f'Ansible执行失败，退出码: {result.returncode}',
                    'log': log_output
                }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': '部署超时（超过10分钟）',
                'log': '部署任务执行超时'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'log': ''
            }
    finally:
        os.unlink(inventory_file)
        if key_file_path and os.path.exists(key_file_path):
            os.unlink(key_file_path)

