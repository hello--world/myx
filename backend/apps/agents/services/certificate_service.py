"""
证书服务

负责SSL证书的生成、更新、上传等操作
"""
import logging
import base64
from typing import Tuple
from apps.agents.models import Agent
from apps.logs.utils import create_log_entry

logger = logging.getLogger(__name__)


class CertificateService:
    """证书业务服务"""

    @staticmethod
    def generate_certificate(host: str, token: str) -> Tuple[bytes, bytes]:
        """
        生成SSL自签名证书

        Args:
            host: 主机名
            token: Agent Token

        Returns:
            Tuple[bytes, bytes]: (证书内容, 私钥内容)
        """
        from apps.deployments.tasks import generate_ssl_certificate
        return generate_ssl_certificate(host, token)

    @staticmethod
    def regenerate_agent_certificate(agent: Agent, verify_ssl: bool = False, user=None) -> Tuple[bool, str]:
        """
        重新生成Agent的SSL证书

        Args:
            agent: Agent对象
            verify_ssl: 是否验证SSL
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            # 生成证书
            cert_bytes, key_bytes = CertificateService.generate_certificate(
                agent.server.host,
                agent.token
            )

            # 存储证书到数据库
            agent.certificate_content = cert_bytes.decode('utf-8')
            agent.private_key_content = key_bytes.decode('utf-8')
            agent.certificate_path = '/etc/myx-agent/ssl/agent.crt'
            agent.private_key_path = '/etc/myx-agent/ssl/agent.key'
            agent.verify_ssl = verify_ssl
            agent.save()

            logger.info(f'Agent证书已重新生成: agent_id={agent.id}')

            # 如果Agent在线，上传证书
            if agent.status == 'online' and agent.rpc_port:
                success, msg = CertificateService.upload_certificate_to_agent(agent)
                if success:
                    # 重启Agent服务以使用新证书
                    from apps.agents.services.agent_service import AgentService
                    AgentService.send_command(
                        agent,
                        'systemctl',
                        ['restart', 'myx-agent'],
                        timeout=30,
                        user=user
                    )

            # 记录日志
            if user:
                create_log_entry(
                    log_type='agent',
                    level='info',
                    title=f'更新Agent SSL证书: {agent.server.name}',
                    content=f'SSL证书已重新生成并{"已上传到Agent服务器" if agent.status == "online" else "等待Agent上线后上传"}',
                    user=user,
                    server=agent.server,
                    related_id=agent.id,
                    related_type='agent'
                )

            return True, '证书已重新生成'

        except Exception as e:
            logger.error(f'更新Agent证书失败: {e}', exc_info=True)
            return False, f'更新证书失败: {str(e)}'

    @staticmethod
    def upload_certificate_to_agent(agent: Agent) -> Tuple[bool, str]:
        """
        上传证书到Agent服务器

        Args:
            agent: Agent对象

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            if not agent.certificate_content or not agent.private_key_content:
                return False, '证书内容为空'

            # 编码证书内容
            cert_b64 = base64.b64encode(agent.certificate_content.encode('utf-8')).decode('ascii')
            key_b64 = base64.b64encode(agent.private_key_content.encode('utf-8')).decode('ascii')

            # 创建上传脚本
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
            from apps.agents.utils import execute_script_via_agent
            cmd = execute_script_via_agent(
                agent,
                upload_script,
                timeout=30,
                script_name='update_certificate.py'
            )

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
                logger.info(f'Agent证书已上传: agent_id={agent.id}')
                return True, '证书已上传'
            else:
                logger.warning(f'Agent证书上传失败: agent_id={agent.id}, error={cmd.error}')
                return False, f'上传失败: {cmd.error}'

        except Exception as e:
            logger.error(f'上传证书到Agent失败: {e}', exc_info=True)
            return False, f'上传失败: {str(e)}'

    @staticmethod
    def update_verify_ssl(agent: Agent, verify_ssl: bool, user=None) -> Tuple[bool, str]:
        """
        更新SSL验证选项

        Args:
            agent: Agent对象
            verify_ssl: 是否验证SSL
            user: 执行用户

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            agent.verify_ssl = verify_ssl
            agent.save()

            # 记录日志
            if user:
                create_log_entry(
                    log_type='agent',
                    level='info',
                    title=f'更新Agent SSL验证选项: {agent.server.name}',
                    content=f'SSL验证选项已更新为: {verify_ssl}',
                    user=user,
                    server=agent.server,
                    related_id=agent.id,
                    related_type='agent'
                )

            return True, 'SSL验证选项已更新'

        except Exception as e:
            logger.error(f'更新SSL验证选项失败: {e}', exc_info=True)
            return False, f'更新失败: {str(e)}'
