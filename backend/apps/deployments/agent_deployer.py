import time
import json
import base64
from django.utils import timezone
from .models import Deployment
from apps.agents.models import Agent
from apps.agents.command_queue import CommandQueue
from apps.servers.models import Server


def deploy_via_agent(deployment: Deployment, deployment_target: str = 'host'):
    """通过Agent部署
    
    Args:
        deployment: 部署任务
        deployment_target: 部署目标 ('host' 或 'docker')
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
                script_b64 = base64.b64encode(docker_script.encode('utf-8')).decode('utf-8')
                cmd = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
                    timeout=600
                )
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
                script_b64 = base64.b64encode(docker_script.encode('utf-8')).decode('utf-8')
                cmd = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
                    timeout=300
                )
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
                xray_b64 = base64.b64encode(xray_script.encode('utf-8')).decode('utf-8')
                cmd1 = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{xray_b64}" | base64 -d | bash'],
                    timeout=600
                )
                
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
                caddy_b64 = base64.b64encode(caddy_script.encode('utf-8')).decode('utf-8')
                cmd2 = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{caddy_b64}" | base64 -d | bash'],
                    timeout=300
                )
                cmd = cmd2
        else:  # host 宿主机部署
            if deployment.deployment_type == 'xray':
                # 支持重复安装的 Xray 安装脚本
                install_script = """#!/bin/bash
set -e

# 检查 Xray 是否已安装
if command -v xray &> /dev/null; then
    echo "Xray 已安装，版本: $(xray version | head -n 1)"
    # 如果已安装，尝试更新
    curl -LsSf https://github.com/XTLS/Xray-install/raw/main/install-release.sh | bash -s -- install || {
        echo "更新失败，但 Xray 已存在，继续..."
    }
else
    # 未安装，执行安装
    curl -LsSf https://github.com/XTLS/Xray-install/raw/main/install-release.sh | bash
fi

# 确保服务已启动
systemctl enable xray || true
systemctl start xray || service xray start || true

echo "Xray 安装/更新完成"
"""
                script_b64 = base64.b64encode(install_script.encode('utf-8')).decode('utf-8')
                cmd = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
                    timeout=600
                )
            elif deployment.deployment_type == 'caddy':
                # 支持重复安装的 Caddy 安装脚本
                install_script = """#!/bin/bash
set -e

# 检查 Caddy 是否已安装
if command -v caddy &> /dev/null; then
    echo "Caddy 已安装，版本: $(caddy version)"
    # 如果已安装，尝试更新
    curl -LsSf https://caddyserver.com/api/download?os=linux&arch=amd64&id=standard | tar -xz -C /usr/local/bin caddy || {
        echo "更新失败，但 Caddy 已存在，继续..."
    }
else
    # 未安装，执行安装
    curl -LsSf https://caddyserver.com/api/download?os=linux&arch=amd64&id=standard | tar -xz -C /usr/local/bin caddy
    chmod +x /usr/local/bin/caddy
fi

# 创建 systemd 服务（如果不存在）
if [ ! -f /etc/systemd/system/caddy.service ]; then
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
    systemctl daemon-reload
fi

# 确保服务已启动
systemctl enable caddy || true
systemctl start caddy || true

echo "Caddy 安装/更新完成"
"""
                script_b64 = base64.b64encode(install_script.encode('utf-8')).decode('utf-8')
                cmd = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
                    timeout=300
                )
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
                xray_b64 = base64.b64encode(xray_script.encode('utf-8')).decode('utf-8')
                cmd1 = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{xray_b64}" | base64 -d | bash'],
                    timeout=600
                )
                
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
                caddy_b64 = base64.b64encode(caddy_script.encode('utf-8')).decode('utf-8')
                cmd2 = CommandQueue.add_command(
                    agent=agent,
                    command='bash',
                    args=['-c', f'echo "{caddy_b64}" | base64 -d | bash'],
                    timeout=300
                )
                cmd = cmd2

        # 等待命令执行完成（轮询）
        max_wait = 600  # 最多等待10分钟
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(2)
            wait_time += 2

        # 更新部署状态
        if cmd.status == 'success':
            deployment.status = 'success'
            deployment.log = cmd.result or '部署成功'
        else:
            deployment.status = 'failed'
            deployment.error_message = cmd.error or '部署失败'
            deployment.log = cmd.result or ''

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
    """通过Agent部署Xray配置
    
    Args:
        server: 服务器对象
        config_json: Xray配置的JSON字符串
        
    Returns:
        bool: 是否成功
    """
    try:
        agent = Agent.objects.get(server=server)
        if agent.status != 'online':
            return False
        
        # 将配置写入临时文件，然后移动到目标位置
        # 使用base64编码避免特殊字符问题
        config_b64 = base64.b64encode(config_json.encode('utf-8')).decode('utf-8')
        
        # 创建部署脚本
        deploy_script = f"""#!/bin/bash
set -e

# 解码配置
CONFIG_JSON=$(echo '{config_b64}' | base64 -d)

# 创建配置目录
mkdir -p /usr/local/etc/xray

# 写入配置文件
echo "$CONFIG_JSON" > /usr/local/etc/xray/config.json

# 验证配置
if /usr/local/bin/xray -test -config /usr/local/etc/xray/config.json 2>&1; then
    echo "配置验证成功"
    # 重启Xray服务
    systemctl restart xray || service xray restart || true
    echo "Xray服务已重启"
    exit 0
else
    echo "配置验证失败"
    exit 1
fi
"""
        
        # 将脚本编码为base64
        script_b64 = base64.b64encode(deploy_script.encode('utf-8')).decode('utf-8')
        
        # 通过Agent执行脚本
        cmd = CommandQueue.add_command(
            agent=agent,
            command='bash',
            args=['-c', f'echo "{script_b64}" | base64 -d | bash'],
            timeout=60
        )
        
        # 等待命令执行完成
        max_wait = 60
        wait_time = 0
        while wait_time < max_wait:
            cmd.refresh_from_db()
            if cmd.status in ['success', 'failed']:
                break
            time.sleep(2)
            wait_time += 2
        
        return cmd.status == 'success'
        
    except Agent.DoesNotExist:
        return False
    except Exception as e:
        return False
