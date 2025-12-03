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
    """通过Agent部署（使用Python脚本）

    Args:
        deployment: 部署任务
        deployment_target: 部署目标 ('host' 或 'docker')
        注意：Caddy 目前只支持宿主机部署
    """
    try:
        agent = Agent.objects.get(server=deployment.server)
        if agent.status != 'online':
            deployment.status = 'failed'
            deployment.error_message = 'Agent不在线'
            deployment.save()
            return

        deployment.status = 'running'
        deployment.started_at = timezone.now()
        deployment.save()

        # 同步部署工具到Agent端
        try:
            logger.info(f"Agent {agent.id} 开始同步部署工具...")
            deployment.log = (deployment.log or '') + "[信息] 同步部署工具脚本到Agent...\n"
            deployment.save()
            sync_result = sync_deployment_tool_to_agent(agent)
            if not sync_result:
                logger.warning(f"同步部署工具到Agent {agent.id} 失败")
                deployment.log = (deployment.log or '') + "[警告] 同步部署工具失败，继续尝试部署\n"
                deployment.save()
            else:
                logger.info(f"Agent {agent.id} 部署工具同步成功")
                deployment.log = (deployment.log or '') + "[成功] 部署工具同步完成\n"
                deployment.save()
        except Exception as e:
            logger.warning(f"同步部署工具时出错: {e}", exc_info=True)
            deployment.log = (deployment.log or '') + f"[警告] 同步部署工具失败: {e}\n"
            deployment.save()

        # Caddy 只支持宿主机部署
        if deployment.deployment_type == 'caddy':
            deployment_target = 'host'
            deployment.log = (deployment.log or '') + "[信息] Caddy 仅支持宿主机部署\n"
            deployment.save()

        # 选择部署脚本
        if deployment.deployment_type == 'xray':
            if deployment_target == 'docker':
                script_name = 'deploy_xray_docker.py'
                log_prefix = "Xray (Docker)"
            else:
                script_name = 'deploy_xray.py'
                log_prefix = "Xray (宿主机)"
        elif deployment.deployment_type == 'caddy':
            script_name = 'deploy_caddy.py'
            log_prefix = "Caddy (宿主机)"
        else:
            deployment.status = 'failed'
            deployment.error_message = f'不支持的部署类型: {deployment.deployment_type}'
            deployment.save()
            return

        # 执行Python部署脚本
        script_path = f"{AGENT_DEPLOYMENT_TOOL_DIR}/scripts/{script_name}"
        deployment.log = (deployment.log or '') + f"[信息] 开始部署 {log_prefix}...\n"
        deployment.save()

        logger.info(f"执行部署脚本: {script_path}")

        # 直接使用python3执行脚本
        cmd = CommandQueue.add_command(
            agent=agent,
            command='python3',
            args=[script_path],
            timeout=600  # 10分钟超时
        )

        # 等待命令执行完成
        deployment.log = (deployment.log or '') + "[信息] 开始等待命令执行完成（超时时间: 1200秒）...\n"
        deployment.save()

        max_wait = 1200  # 20分钟
        wait_time = 0
        last_log_time = 0

        while wait_time < max_wait:
            cmd.refresh_from_db()

            # 定期输出等待状态
            if wait_time - last_log_time >= 10:
                status_info = f"等待命令执行完成... ({wait_time}秒, 命令状态: {cmd.status}"
                if cmd.status == 'running' and cmd.started_at:
                    elapsed = (timezone.now() - cmd.started_at).total_seconds()
                    status_info += f", 已执行: {int(elapsed)}秒"
                status_info += ")\n"
                deployment.log = (deployment.log or '') + status_info
                deployment.save()
                last_log_time = wait_time

            # 检查命令是否完成
            if cmd.status in ['success', 'failed']:
                break

            time.sleep(2)
            wait_time += 2

        # 处理执行结果
        if wait_time >= max_wait:
            # 超时
            deployment.status = 'failed'
            deployment.error_message = '部署超时（超过20分钟）'
            deployment.log = (deployment.log or '') + "\n[错误] 部署超时\n"
            deployment.completed_at = timezone.now()
            deployment.save()
            logger.error(f"部署超时: deployment_id={deployment.id}")
            return

        # 获取命令输出
        from apps.logs.utils import format_log_content
        result_output = format_log_content(cmd.result or '', decode_base64=True)
        error_output = format_log_content(cmd.error or '', decode_base64=True)

        deployment.log = (deployment.log or '') + "\n=== 部署脚本输出 ===\n"
        if result_output:
            deployment.log += result_output + "\n"
        if error_output:
            deployment.log += "=== 错误输出 ===\n" + error_output + "\n"
        deployment.save()

        # 判断是否成功
        # 安全地获取 exit_code（如果字段不存在，默认为 0 表示成功）
        exit_code = getattr(cmd, 'exit_code', 0 if cmd.status == 'success' else -1)
        
        if cmd.status == 'success' and exit_code == 0:
            # 额外验证：检查输出中是否包含成功标记
            if '部署完成' in result_output or 'SUCCESS' in result_output:
                deployment.status = 'success'
                deployment.log = (deployment.log or '') + f"\n[成功] {log_prefix} 部署成功\n"
                logger.info(f"部署成功: deployment_id={deployment.id}, type={deployment.deployment_type}")
            else:
                # 命令执行成功但可能有问题
                deployment.status = 'success'
                deployment.log = (deployment.log or '') + f"\n[完成] {log_prefix} 部署命令执行完成\n"
                logger.info(f"部署命令执行完成: deployment_id={deployment.id}")
        else:
            # 部署失败
            deployment.status = 'failed'
            deployment.error_message = f'部署失败（退出码: {exit_code}）'
            deployment.log = (deployment.log or '') + f"\n[失败] {log_prefix} 部署失败\n"
            logger.error(f"部署失败: deployment_id={deployment.id}, exit_code={exit_code}")

        deployment.completed_at = timezone.now()
        deployment.save()

    except Agent.DoesNotExist:
        deployment.status = 'failed'
        deployment.error_message = 'Agent不存在'
        deployment.completed_at = timezone.now()
        deployment.save()
        logger.error(f"Agent不存在: server_id={deployment.server.id}")
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
