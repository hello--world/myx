import time
import json
import base64
from django.utils import timezone
from .models import Deployment
from apps.agents.models import Agent
from apps.agents.command_queue import CommandQueue
from apps.agents.utils import execute_script_via_agent
from apps.servers.models import Server
from .deployment_tool import AGENT_DEPLOYMENT_TOOL_DIR
import logging

logger = logging.getLogger(__name__)


def deploy_via_agent(deployment: Deployment, deployment_target: str = 'host'):
    """通过Agent部署
    
    Args:
        deployment: 部署任务
        deployment_target: 部署目标 ('host' 或 'docker')
        注意：Caddy 目前只支持宿主机部署，即使 deployment_target 为 'docker' 也会部署到宿主机
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

        # Caddy 目前只支持宿主机部署，强制使用 'host'
        if deployment.deployment_type == 'caddy':
            deployment_target = 'host'
            deployment.log = (deployment.log or '') + "[信息] Caddy 仅支持宿主机部署，忽略部署目标设置\n"
            deployment.save()

        # 构建部署命令（根据部署目标选择不同的命令）
        if deployment_target == 'docker':
            # Docker 部署命令（支持重复安装）
            if deployment.deployment_type == 'xray':
                docker_script = """#!/bin/bash
set -e

# 检查容器是否已存在
if docker ps -a --format '{{.Names}}' | grep -q '^xray$'; then
    echo "Xray 容器已存在，停止并删除..."
    docker stop xray || true
    docker rm xray || true
fi

# 创建配置目录
mkdir -p /etc/xray

# 运行 Xray 容器
docker run -d \\
    --name xray \\
    --restart=always \\
    -v /etc/xray:/etc/xray \\
    -p 443:443 \\
    teddysun/xray

echo "Xray Docker 容器部署完成"
"""
                cmd = execute_script_via_agent(agent, docker_script, timeout=600, script_name='xray_docker.sh')
            elif deployment.deployment_type == 'caddy':
                docker_script = """#!/bin/bash
set -e

# 检查容器是否已存在
if docker ps -a --format '{{.Names}}' | grep -q '^caddy$'; then
    echo "Caddy 容器已存在，停止并删除..."
    docker stop caddy || true
    docker rm caddy || true
fi

# 创建配置目录
mkdir -p /etc/caddy

# 运行 Caddy 容器
docker run -d \\
    --name caddy \\
    --restart=always \\
    -v /etc/caddy:/etc/caddy \\
    -p 80:80 \\
    -p 443:443 \\
    caddy:latest

echo "Caddy Docker 容器部署完成"
"""
                cmd = execute_script_via_agent(agent, docker_script, timeout=300, script_name='caddy_docker.sh')
            else:  # both
                xray_script = """#!/bin/bash
set -e
if docker ps -a --format '{{.Names}}' | grep -q '^xray$'; then
    docker stop xray || true
    docker rm xray || true
fi
mkdir -p /etc/xray
docker run -d --name xray --restart=always -v /etc/xray:/etc/xray -p 443:443 teddysun/xray
echo "Xray 完成"
"""
                cmd1 = execute_script_via_agent(agent, xray_script, timeout=600, script_name='xray_docker.sh')
                
                # 等待 Xray 部署完成
                max_wait = 600
                wait_time = 0
                while wait_time < max_wait:
                    cmd1.refresh_from_db()
                    if cmd1.status in ['success', 'failed']:
                        break
                    time.sleep(2)
                    wait_time += 2
                
                caddy_script = """#!/bin/bash
set -e
if docker ps -a --format '{{.Names}}' | grep -q '^caddy$'; then
    docker stop caddy || true
    docker rm caddy || true
fi
mkdir -p /etc/caddy
docker run -d --name caddy --restart=always -v /etc/caddy:/etc/caddy -p 80:80 -p 443:443 caddy:latest
echo "Caddy 完成"
"""
                cmd2 = execute_script_via_agent(agent, caddy_script, timeout=300, script_name='caddy_docker.sh')
                cmd = cmd2
        else:  # host 宿主机部署
            if deployment.deployment_type == 'xray':
                # 支持重复安装的 Xray 安装脚本
                install_script = """#!/bin/bash
set -e

echo "[1/4] 检查 Xray 是否已安装..."
if command -v xray &> /dev/null; then
    echo "[信息] Xray 已安装，当前版本: $(xray version | head -n 1)"
    echo "[2/4] 开始更新 Xray..."
    curl -LsSf https://github.com/XTLS/Xray-install/raw/main/install-release.sh | bash -s -- install || {
        echo "[警告] 更新失败，但 Xray 已存在，继续..."
    }
    echo "[2/4] Xray 更新完成"
else
    echo "[信息] Xray 未安装，开始安装..."
    echo "[2/4] 正在从 GitHub 下载 Xray 安装脚本..."
    curl -LsSf https://github.com/XTLS/Xray-install/raw/main/install-release.sh | bash
    echo "[2/4] Xray 安装完成"
fi

echo "[3/4] 配置 Xray 服务..."
systemctl enable xray || true
echo "[3/4] 服务已启用"

echo "[4/4] 启动 Xray 服务..."
systemctl start xray || service xray start || true
if systemctl is-active --quiet xray; then
    echo "[4/4] Xray 服务已启动"
else
    echo "[警告] Xray 服务启动可能失败，请检查服务状态"
fi

echo "[完成] Xray 安装/更新流程完成"
"""
                cmd = execute_script_via_agent(agent, install_script, timeout=600, script_name='xray_install.sh')
            elif deployment.deployment_type == 'caddy':
                # 支持重复安装的 Caddy 安装脚本
                install_script = """#!/bin/bash
set +e  # 不因错误退出，允许某些命令失败

echo "[开始] Caddy 安装/更新流程"

# 检查 Caddy 是否已安装
if command -v caddy &> /dev/null; then
    echo "[信息] Caddy 已安装，当前版本:"
    caddy version 2>&1 || echo "无法获取版本信息"
    echo "[信息] 尝试更新 Caddy..."
    curl -LsSf --max-time 60 https://caddyserver.com/api/download?os=linux&arch=amd64&id=standard | tar -xz -C /usr/local/bin caddy
    if [ $? -eq 0 ]; then
        echo "[成功] Caddy 更新完成"
    else
        echo "[警告] Caddy 更新失败，但已存在的版本将继续使用"
    fi
    chmod +x /usr/local/bin/caddy || true
else
    echo "[信息] Caddy 未安装，开始安装..."
    curl -LsSf --max-time 60 https://caddyserver.com/api/download?os=linux&arch=amd64&id=standard | tar -xz -C /usr/local/bin caddy
    if [ $? -ne 0 ]; then
        echo "[错误] Caddy 下载失败"
        exit 1
    fi
    chmod +x /usr/local/bin/caddy
    if [ $? -ne 0 ]; then
        echo "[错误] 设置 Caddy 可执行权限失败"
        exit 1
    fi
    echo "[成功] Caddy 安装完成"
fi

# 验证 Caddy 是否可用
if ! command -v caddy &> /dev/null; then
    echo "[错误] Caddy 安装后仍不可用"
    exit 1
fi

echo "[信息] Caddy 二进制文件位置: $(which caddy)"
echo "[信息] Caddy 版本:"
caddy version 2>&1 || echo "无法获取版本信息"

# 创建 systemd 服务（如果不存在）
if [ ! -f /etc/systemd/system/caddy.service ]; then
    echo "[信息] 创建 systemd 服务文件..."
    cat > /etc/systemd/system/caddy.service << 'EOF'
[Unit]
Description=Caddy
Documentation=https://caddyserver.com/docs/
After=network.target network-online.target
Requires=network-online.target

[Service]
Type=notify
User=root
Group=root
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile --force
TimeoutStopSec=5s
LimitNOFILE=1048576
LimitNPROC=512
PrivateTmp=true
ProtectSystem=full
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF
    if [ $? -ne 0 ]; then
        echo "[错误] 创建 systemd 服务文件失败"
        exit 1
    fi
    systemctl daemon-reload
    if [ $? -ne 0 ]; then
        echo "[错误] systemd daemon-reload 失败"
        exit 1
    fi
    echo "[成功] systemd 服务文件已创建"
else
    echo "[信息] systemd 服务文件已存在，跳过创建"
fi

# 确保服务已启用
echo "[信息] 启用 Caddy 服务..."
systemctl enable caddy
if [ $? -ne 0 ]; then
    echo "[警告] 启用 Caddy 服务失败，但继续执行"
fi

# 确保 Caddyfile 存在（如果不存在，创建最简单的配置）
if [ ! -f /etc/caddy/Caddyfile ]; then
    echo "[信息] Caddyfile 不存在，创建默认配置..."
    mkdir -p /etc/caddy
    cat > /etc/caddy/Caddyfile << 'EOF'
# 默认 Caddyfile 配置
# 可以根据需要修改
:80 {
    respond "Hello from Caddy"
}
EOF
    if [ $? -eq 0 ]; then
        echo "[成功] 默认 Caddyfile 已创建"
    else
        echo "[警告] 创建默认 Caddyfile 失败，但继续执行"
    fi
fi

# 尝试启动服务（如果未运行）
echo "[信息] 检查 Caddy 服务状态..."
if systemctl is-active --quiet caddy; then
    echo "[信息] Caddy 服务已在运行"
    echo "[完成] Caddy 安装/更新流程完成"
    exit 0
fi

echo "[信息] 启动 Caddy 服务..."
# 直接启动服务，不等待结果（避免卡住）
systemctl start caddy 2>&1 &
START_PID=$!

# 等待最多5秒
for i in {1..5}; do
    if ! kill -0 $START_PID 2>/dev/null; then
        # 进程已结束
        wait $START_PID 2>/dev/null || true
        break
    fi
    sleep 1
done

# 如果进程还在运行，强制终止（不等待）
if kill -0 $START_PID 2>/dev/null; then
    kill $START_PID 2>/dev/null || true
    kill -9 $START_PID 2>/dev/null || true
fi

# 等待1秒让服务有时间启动
sleep 1

# 检查服务是否实际已启动
if systemctl is-active --quiet caddy; then
    echo "[成功] Caddy 服务已启动"
    echo "[完成] Caddy 安装/更新流程完成"
    exit 0
else
    echo "[警告] Caddy 服务启动失败，检查服务状态..."
    systemctl status caddy --no-pager -l 2>&1 | head -20 || true
    # 即使启动失败，也不退出（因为可能是配置问题，但安装本身成功）
    echo "[信息] Caddy 已安装，但服务启动失败（可能需要检查配置）"
    echo "[完成] Caddy 安装/更新流程完成（服务未启动，请检查配置）"
    exit 0
fi

# 等待一下确保服务启动成功
sleep 2
if systemctl is-active --quiet caddy; then
    echo "[成功] Caddy 服务运行正常"
else
    echo "[警告] Caddy 服务启动后未保持运行状态（可能是配置问题）"
    systemctl status caddy --no-pager -l 2>&1 | head -20 || true
    # 不退出，因为安装本身可能成功，只是服务启动有问题
fi

echo "[完成] Caddy 安装/更新流程完成"
exit 0
"""
                cmd = execute_script_via_agent(agent, install_script, timeout=600, script_name='caddy_install.sh')
            else:  # both
                # 安装 Xray
                xray_script = """#!/bin/bash
set -e
if command -v xray &> /dev/null; then
    echo "Xray 已安装，尝试更新..."
    curl -LsSf https://github.com/XTLS/Xray-install/raw/main/install-release.sh | bash -s -- install || true
else
    curl -LsSf https://github.com/XTLS/Xray-install/raw/main/install-release.sh | bash
fi
systemctl enable xray || true
systemctl start xray || service xray start || true
echo "Xray 完成"
"""
                cmd1 = execute_script_via_agent(agent, xray_script, timeout=600, script_name='xray_install.sh')
                
                # 等待 Xray 安装完成
                max_wait = 600
                wait_time = 0
                while wait_time < max_wait:
                    cmd1.refresh_from_db()
                    if cmd1.status in ['success', 'failed']:
                        break
                    time.sleep(2)
                    wait_time += 2
                
                # 安装 Caddy
                caddy_script = """#!/bin/bash
set -e
if command -v caddy &> /dev/null; then
    echo "Caddy 已安装，尝试更新..."
    curl -LsSf https://caddyserver.com/api/download?os=linux&arch=amd64&id=standard | tar -xz -C /usr/local/bin caddy || true
else
    curl -LsSf https://caddyserver.com/api/download?os=linux&arch=amd64&id=standard | tar -xz -C /usr/local/bin caddy
    chmod +x /usr/local/bin/caddy
fi
if [ ! -f /etc/systemd/system/caddy.service ]; then
    cat > /etc/systemd/system/caddy.service << 'EOF'
[Unit]
Description=Caddy
After=network.target network-online.target
Requires=network-online.target
[Service]
Type=notify
User=root
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
TimeoutStopSec=5s
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
fi
systemctl enable caddy || true
systemctl start caddy || true
echo "Caddy 完成"
"""
                cmd2 = execute_script_via_agent(agent, caddy_script, timeout=300, script_name='caddy_install.sh')
                cmd = cmd2

        # 等待命令执行完成（轮询），实时读取命令结果
        max_wait = max(cmd.timeout * 2, 600)  # 最多等待超时时间的2倍，或10分钟
        wait_time = 0
        last_result_length = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            
            # 实时读取命令输出（如果有新内容）
            if cmd.result and len(cmd.result) > last_result_length:
                new_output = cmd.result[last_result_length:]
                # 解码base64内容
                from apps.logs.utils import format_log_content
                formatted_output = format_log_content(new_output, decode_base64=True)
                deployment.log = (deployment.log or '') + formatted_output
                deployment.save()
                last_result_length = len(cmd.result)
            elif wait_time > 10 and wait_time % 10 == 0:
                # 即使没有新输出，也显示进度提示（避免用户以为卡住了）
                if cmd.status == 'running':
                    elapsed = (timezone.now() - cmd.started_at).total_seconds() if cmd.started_at else wait_time
                    deployment.log = (deployment.log or '') + f"[进度] 命令执行中... (已执行 {int(elapsed)}秒)\n"
                    deployment.save()
            
            time.sleep(2)
            wait_time += 2
            # 每10秒记录一次等待状态，并显示命令当前状态（更频繁的更新）
            if wait_time % 10 == 0:
                status_info = f"命令状态: {cmd.status}"
                if cmd.started_at:
                    elapsed = (timezone.now() - cmd.started_at).total_seconds()
                    status_info += f", 已执行: {int(elapsed)}秒"
                deployment.log = (deployment.log or '') + f"等待命令执行完成... ({wait_time}秒, {status_info})\n"
                deployment.save()
                
                # 如果命令执行时间超过超时时间，主动检查并可能标记为失败
                if cmd.started_at and cmd.timeout:
                    elapsed = (timezone.now() - cmd.started_at).total_seconds()
                    if elapsed > cmd.timeout:
                        deployment.log = (deployment.log or '') + f"[警告] 命令执行时间已超过超时时间（{cmd.timeout}秒），但状态仍为 {cmd.status}\n"
                        deployment.save()

        # 如果超时，检查命令状态
        if wait_time >= max_wait:
            cmd.refresh_from_db()
            if cmd.status not in ['success', 'failed']:
                deployment.status = 'failed'
                deployment.error_message = f'命令执行超时（{max_wait}秒），命令状态: {cmd.status}'
                deployment.log = (deployment.log or '') + f"\n[错误] 命令执行超时，最后状态: {cmd.status}\n"
                if cmd.started_at:
                    elapsed = (timezone.now() - cmd.started_at).total_seconds()
                    deployment.log = (deployment.log or '') + f"命令已执行时间: {int(elapsed)}秒，超时设置: {cmd.timeout}秒\n"
                if cmd.result:
                    # 解码base64内容
                    from apps.logs.utils import format_log_content
                    result_preview = cmd.result[-500:] if len(cmd.result) > 500 else cmd.result
                    formatted_result = format_log_content(result_preview, decode_base64=True)
                    deployment.log = (deployment.log or '') + f"命令输出（最后500字符）:\n{formatted_result}\n"
                if cmd.error:
                    # 解码base64内容
                    from apps.logs.utils import format_log_content
                    formatted_error = format_log_content(cmd.error, decode_base64=True)
                    deployment.log = (deployment.log or '') + f"错误信息:\n{formatted_error}\n"
                deployment.completed_at = timezone.now()
                deployment.save()
                return

        # 更新部署状态
        if cmd.status == 'success':
            deployment.status = 'success'
            # 解码base64内容
            from apps.logs.utils import format_log_content
            result_content = format_log_content(cmd.result or '部署成功', decode_base64=True)
            deployment.log = (deployment.log or '') + result_content
        else:
            deployment.status = 'failed'
            deployment.error_message = cmd.error or '部署失败'
            # 解码base64内容
            from apps.logs.utils import format_log_content
            result_content = format_log_content(cmd.result or '', decode_base64=True)
            deployment.log = (deployment.log or '') + result_content
            if cmd.error:
                error_content = format_log_content(cmd.error, decode_base64=True)
                deployment.log = (deployment.log or '') + f"\n错误信息:\n{error_content}"

        deployment.completed_at = timezone.now()
        deployment.save()

    except Agent.DoesNotExist:
        deployment.status = 'failed'
        deployment.error_message = '服务器未安装Agent，请先安装Agent'
        deployment.completed_at = timezone.now()
        deployment.save()
    except Exception as e:
        deployment.status = 'failed'
        deployment.error_message = str(e)
        deployment.completed_at = timezone.now()
        deployment.save()


def deploy_xray_config_via_agent(server: Server, config_json: str) -> bool:
    """通过Agent部署Xray配置（使用Ansible部署工具）
    
    Args:
        server: 服务器对象
        config_json: Xray配置的JSON字符串
        
    Returns:
        bool: 是否成功
    """
    import time
    import json
    import tempfile
    from apps.agents.models import Agent
    from apps.agents.utils import execute_script_via_agent
    from .deployment_tool import check_deployment_tool_version, sync_deployment_tool_to_agent
    
    try:
        agent = Agent.objects.get(server=server)
        if agent.status != 'online':
            return False
        
        # 检查并同步部署工具
        try:
            version_check = check_deployment_tool_version(agent)
            if not version_check:
                logger.info(f"Agent {agent.id} 部署工具版本不一致或不存在，开始同步...")
                sync_result = sync_deployment_tool_to_agent(agent)
                if not sync_result:
                    logger.warning(f"同步部署工具到Agent {agent.id} 失败，继续尝试部署（假设Agent端已有工具）")
            else:
                logger.info(f"Agent {agent.id} 部署工具版本一致，跳过同步")
        except Exception as e:
            logger.warning(f"检查/同步部署工具时出错: {e}，继续尝试部署", exc_info=True)
        
        # 将配置写入临时文件（通过Agent）
        # 使用base64编码JSON配置，避免特殊字符问题
        import base64
        config_json_base64 = base64.b64encode(config_json.encode('utf-8')).decode('ascii')
        config_file = f'/tmp/xray_config_{int(time.time())}.json'
        config_script = f"""#!/bin/bash
set -e
# 将base64编码的JSON配置解码并写入文件
echo "{config_json_base64}" | base64 -d > {config_file}
if [ $? -eq 0 ]; then
    echo "配置文件已写入: {config_file}"
    # 验证JSON格式
    if command -v python3 &> /dev/null; then
        python3 -m json.tool {config_file} > /dev/null 2>&1 && echo "JSON格式验证通过" || echo "警告: JSON格式验证失败"
    elif command -v python &> /dev/null; then
        python -m json.tool {config_file} > /dev/null 2>&1 && echo "JSON格式验证通过" || echo "警告: JSON格式验证失败"
    fi
    exit 0
else
    echo "错误: 写入配置文件失败"
    exit 1
fi
"""
        
        # 写入配置文件
        write_cmd = execute_script_via_agent(agent, config_script, timeout=30, script_name='write_config.sh')
        max_wait = 30
        wait_time = 0
        while wait_time < max_wait:
            write_cmd.refresh_from_db()
            if write_cmd.status in ['success', 'failed']:
                break
            time.sleep(1)
            wait_time += 1
        
        if write_cmd.status != 'success':
            # 解码base64内容
            from apps.logs.utils import format_log_content
            error_msg = format_log_content(write_cmd.error or '未知错误', decode_base64=True)
            result_msg = format_log_content(write_cmd.result or '', decode_base64=True)
            logger.error(f"写入配置文件失败: {error_msg}")
            if result_msg:
                logger.error(f"写入配置文件输出: {result_msg}")
            return False
        
        # 执行Ansible playbook部署配置
        deploy_script = f"""#!/bin/bash
set -e

cd {AGENT_DEPLOYMENT_TOOL_DIR}

# 确保Ansible已安装
if ! command -v ansible-playbook &> /dev/null; then
    echo "[信息] 检测到Ansible未安装，开始安装..."
    if command -v apt-get &> /dev/null; then
        echo "[信息] 使用apt-get安装Ansible..."
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ansible || {{
            echo "[错误] apt-get安装Ansible失败，尝试使用pip安装..."
            if command -v pip3 &> /dev/null; then
                pip3 install ansible
            elif command -v pip &> /dev/null; then
                pip install ansible
            else
                echo "[错误] 无法安装Ansible，请手动安装"
                exit 1
            fi
        }}
    elif command -v yum &> /dev/null; then
        echo "[信息] 使用yum安装Ansible..."
        yum install -y -q ansible || {{
            echo "[错误] yum安装Ansible失败，尝试使用pip安装..."
            if command -v pip3 &> /dev/null; then
                pip3 install ansible
            elif command -v pip &> /dev/null; then
                pip install ansible
            else
                echo "[错误] 无法安装Ansible，请手动安装"
                exit 1
            fi
        }}
    elif command -v pip3 &> /dev/null || command -v pip &> /dev/null; then
        echo "[信息] 使用pip安装Ansible..."
        if command -v pip3 &> /dev/null; then
            pip3 install ansible
        else
            pip install ansible
        fi
    else
        echo "[错误] 无法安装Ansible，请手动安装"
        exit 1
    fi
    
    # 验证安装
    if command -v ansible-playbook &> /dev/null; then
        echo "[成功] Ansible安装成功: $(ansible-playbook --version | head -1)"
    else
        echo "[错误] Ansible安装失败"
        exit 1
    fi
fi

# 检查部署工具目录是否存在
if [ ! -d "{AGENT_DEPLOYMENT_TOOL_DIR}" ]; then
    echo "[错误] 部署工具目录不存在: {AGENT_DEPLOYMENT_TOOL_DIR}"
    echo "[信息] 如果这是首次部署，请先同步部署工具"
    exit 1
fi

# 检查playbook文件是否存在
if [ ! -f "{AGENT_DEPLOYMENT_TOOL_DIR}/playbooks/deploy_xray_config.yml" ]; then
    echo "[错误] Playbook文件不存在: {AGENT_DEPLOYMENT_TOOL_DIR}/playbooks/deploy_xray_config.yml"
    echo "[信息] 部署工具可能未正确同步，请检查版本"
    exit 1
fi

# 执行playbook
echo "[信息] 开始执行Ansible playbook..."
ansible-playbook -i {AGENT_DEPLOYMENT_TOOL_DIR}/inventory/localhost.ini {AGENT_DEPLOYMENT_TOOL_DIR}/playbooks/deploy_xray_config.yml -e config_file={config_file} -v

EXIT_CODE=$?

# 清理临时配置文件
rm -f {config_file}

if [ $EXIT_CODE -eq 0 ]; then
    echo "[成功] Xray配置部署完成"
else
    echo "[错误] Xray配置部署失败，退出码: $EXIT_CODE"
fi

exit $EXIT_CODE
"""
        
        # 通过Agent执行部署脚本
        logger.info(f"开始执行Ansible playbook部署Xray配置...")
        cmd = execute_script_via_agent(agent, deploy_script, timeout=120, script_name='deploy_xray_config.sh')
        
        # 等待命令执行完成，实时记录日志
        max_wait = max(cmd.timeout * 2, 120)  # 最多等待超时时间的2倍，或2分钟
        wait_time = 0
        last_result_length = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            
            # 实时读取命令输出（如果有新内容）
            if cmd.result and len(cmd.result) > last_result_length:
                new_output = cmd.result[last_result_length:]
                # 解码base64内容
                from apps.logs.utils import format_log_content
                formatted_output = format_log_content(new_output, decode_base64=True)
                logger.info(f"Ansible部署输出: {formatted_output}")
                last_result_length = len(cmd.result)
            
            time.sleep(2)
            wait_time += 2
            if wait_time % 10 == 0:
                status_info = f"命令状态: {cmd.status}"
                if cmd.started_at:
                    elapsed = (timezone.now() - cmd.started_at).total_seconds()
                    status_info += f", 已执行: {int(elapsed)}秒"
                logger.info(f"等待Ansible部署完成... ({wait_time}秒, {status_info})")
        
        if cmd.status == 'success':
            logger.info(f"Xray配置部署成功")
            if cmd.result:
                logger.debug(f"部署结果: {cmd.result[:500]}...")  # 只记录前500字符
            return True
        else:
            logger.error(f"Xray配置部署失败: status={cmd.status}")
            if cmd.error:
                # 解码base64内容
                from apps.logs.utils import format_log_content
                formatted_error = format_log_content(cmd.error, decode_base64=True)
                logger.error(f"错误信息: {formatted_error}")
            if cmd.result:
                # 解码base64内容
                from apps.logs.utils import format_log_content
                formatted_result = format_log_content(cmd.result, decode_base64=True)
                logger.error(f"执行结果: {formatted_result}")
            return False
        
    except Agent.DoesNotExist:
        return False
    except Exception as e:
        logger.error(f"部署Xray配置失败: {e}", exc_info=True)
        return False
