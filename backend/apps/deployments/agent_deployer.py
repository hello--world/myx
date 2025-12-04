import time
import logging
import base64
from django.utils import timezone
from .models import Deployment
from apps.agents.models import Agent
from apps.agents.command_queue import CommandQueue
from apps.agents.utils import execute_script_via_agent, AGENT_DEPLOYMENT_TOOL_DIR
from apps.servers.models import Server
from .deployment_tool import check_deployment_tool_version, sync_deployment_tool_to_agent

logger = logging.getLogger(__name__)


def deploy_via_agent(deployment: Deployment, deployment_target: str = 'host'):
    """通过Agent部署（已重构为调用DeploymentService）

    注意：保留此函数是为了向后兼容，内部已使用Service层重构

    Args:
        deployment: 部署任务
        deployment_target: 部署目标 ('host' 或 'docker')
        注意：Caddy 目前只支持宿主机部署
    """
    try:
        # 调用Service层的deploy_service
        from apps.deployments.services import DeploymentService

        deployment.status = 'running'
        deployment.started_at = timezone.now()
        deployment.save()

        success, message = DeploymentService.deploy_service(
            server=deployment.server,
            service_type=deployment.deployment_type,
            deployment_target=deployment_target,
            deployment=deployment,
            user=deployment.created_by if deployment else None
        )

        if success:
            deployment.status = 'success'
        else:
            deployment.status = 'failed'
            deployment.error_message = message

        deployment.completed_at = timezone.now()
        deployment.save()

    except Exception as e:
        deployment.status = 'failed'
        deployment.error_message = str(e)
        deployment.log = (deployment.log or '') + f"\n[异常] {str(e)}\n"
        deployment.completed_at = timezone.now()
        deployment.save()
        logger.error(f"部署异常: deployment_id={deployment.id}, error={e}", exc_info=True)


def deploy_xray_config_via_agent(server: Server, config_json: str) -> tuple:
    """通过Agent部署Xray配置
    
    Args:
        server: 服务器对象
        config_json: Xray配置JSON字符串
        
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        agent = Agent.objects.get(server=server)
        if agent.status != 'online':
            return False, 'Agent不在线'
        
        logger.info(f"开始通过Agent部署Xray配置到服务器 {server.name}")
        
        # 将配置JSON进行base64编码
        config_base64 = base64.b64encode(config_json.encode('utf-8')).decode('ascii')
        
        # 构建部署脚本：
        # 1. 解码配置并写入临时文件
        # 2. 执行Ansible playbook部署配置
        deploy_script = f'''#!/bin/bash
set -e

# 配置文件路径
CONFIG_FILE="/tmp/xray_config.json"
PLAYBOOK_PATH="{AGENT_DEPLOYMENT_TOOL_DIR}/playbooks/deploy_xray_config.yml"
INVENTORY_PATH="{AGENT_DEPLOYMENT_TOOL_DIR}/inventory/localhost.ini"

# 解码配置并写入临时文件
echo "{config_base64}" | base64 -d > "$CONFIG_FILE"

# 检查配置文件是否成功创建
if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: 配置文件创建失败"
    exit 1
fi

echo "配置文件已写入: $CONFIG_FILE"
echo "配置文件大小: $(wc -c < $CONFIG_FILE) bytes"

# 检查playbook是否存在
if [ ! -f "$PLAYBOOK_PATH" ]; then
    echo "ERROR: Playbook不存在: $PLAYBOOK_PATH"
    exit 1
fi

# 检查ansible-playbook命令是否可用
if ! command -v ansible-playbook &> /dev/null; then
    echo "ERROR: ansible-playbook命令不可用，请先安装Ansible"
    exit 1
fi

# 执行Ansible playbook部署配置
echo "执行Ansible playbook部署配置..."
ansible-playbook -i "$INVENTORY_PATH" "$PLAYBOOK_PATH" -e "config_file=$CONFIG_FILE" --become --become-method=sudo

# 检查执行结果
if [ $? -eq 0 ]; then
    echo "SUCCESS: Xray配置部署成功"
    # 清理临时文件
    rm -f "$CONFIG_FILE"
    exit 0
else
    echo "ERROR: Xray配置部署失败"
    # 清理临时文件
    rm -f "$CONFIG_FILE"
    exit 1
fi
'''
        
        # 通过Agent执行部署脚本
        cmd = execute_script_via_agent(
            agent=agent,
            script_content=deploy_script,
            timeout=120,  # 2分钟超时
            script_name='deploy_xray_config.sh'
        )
        
        # 等待命令执行完成
        max_wait = 120
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(2)
            wait_time += 2
        
        # 获取执行结果
        from apps.logs.utils import format_log_content
        result_output = format_log_content(cmd.result or '', decode_base64=True)
        error_output = format_log_content(cmd.error or '', decode_base64=True)
        
        # 安全地获取 exit_code（如果字段不存在，默认为 0 表示成功）
        exit_code = getattr(cmd, 'exit_code', 0 if cmd.status == 'success' else -1)
        
        if cmd.status == 'success' and exit_code == 0:
            if 'SUCCESS' in result_output or '部署成功' in result_output:
                logger.info(f"Xray配置部署成功: server={server.name}")
                return True, '配置部署成功'
            else:
                logger.info(f"Xray配置部署完成: server={server.name}")
                return True, '配置部署完成'
        else:
            error_msg = error_output or result_output or f'部署失败（退出码: {exit_code}）'
            logger.error(f"Xray配置部署失败: server={server.name}, error={error_msg}")
            return False, error_msg
            
    except Agent.DoesNotExist:
        logger.error(f"Agent不存在: server={server.name}")
        return False, 'Agent不存在'
    except Exception as e:
        logger.error(f"Xray配置部署异常: server={server.name}, error={e}", exc_info=True)
        return False, str(e)
