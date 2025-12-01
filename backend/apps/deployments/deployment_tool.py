"""
部署工具管理模块
负责版本检查、工具同步等功能
"""
import os
import tarfile
import tempfile
import logging
from pathlib import Path
from django.conf import settings
from apps.agents.models import Agent
from apps.agents.utils import execute_script_via_agent

logger = logging.getLogger(__name__)

# 部署工具目录
# 使用BASE_DIR来确保路径正确
def _get_base_dir():
    """获取项目根目录"""
    try:
        from django.conf import settings
        if hasattr(settings, 'BASE_DIR'):
            # settings.BASE_DIR 指向 backend 目录的父目录（项目根目录）
            return Path(settings.BASE_DIR).resolve()
    except Exception as e:
        logger.warning(f"无法从settings获取BASE_DIR: {e}")
    # 如果无法从settings获取，使用相对路径
    # __file__ 是 backend/apps/deployments/deployment_tool.py
    # 需要回到项目根目录: backend/apps/deployments -> backend/apps -> backend -> 项目根
    return Path(__file__).resolve().parent.parent.parent

BASE_DIR = _get_base_dir()
DEPLOYMENT_TOOL_DIR = BASE_DIR / 'deployment-tool'
DEPLOYMENT_TOOL_VERSION_FILE = DEPLOYMENT_TOOL_DIR / 'VERSION'
AGENT_DEPLOYMENT_TOOL_DIR = '/opt/myx-deployment-tool'


def get_deployment_tool_version():
    """获取当前部署工具版本"""
    try:
        if DEPLOYMENT_TOOL_VERSION_FILE.exists():
            with open(DEPLOYMENT_TOOL_VERSION_FILE, 'r', encoding='utf-8') as f:
                version = f.read().strip()
                if version:
                    logger.debug(f"读取到部署工具版本: {version}")
                    return version
                else:
                    logger.warning(f"版本文件为空: {DEPLOYMENT_TOOL_VERSION_FILE}")
        else:
            logger.warning(f"版本文件不存在: {DEPLOYMENT_TOOL_VERSION_FILE}")
            logger.warning(f"部署工具目录: {DEPLOYMENT_TOOL_DIR}, 存在: {DEPLOYMENT_TOOL_DIR.exists()}")
    except Exception as e:
        logger.error(f"读取部署工具版本失败: {e}", exc_info=True)
    return None


def check_deployment_tool_version(agent: Agent) -> bool:
    """
    检查Agent端的部署工具版本是否与当前版本一致
    
    Returns:
        bool: True表示版本一致，False表示不一致或需要同步
    """
    current_version = get_deployment_tool_version()
    if not current_version:
        logger.warning("无法获取当前部署工具版本")
        return False
    
    # 如果Agent端没有版本记录，认为需要同步
    if not agent.deployment_tool_version:
        logger.info(f"Agent {agent.id} 没有部署工具版本记录，需要同步")
        return False
    
    # 比较版本
    if agent.deployment_tool_version != current_version:
        logger.info(f"Agent {agent.id} 部署工具版本不一致: Agent={agent.deployment_tool_version}, 当前={current_version}")
        return False
    
    return True


def sync_deployment_tool_to_agent(agent: Agent) -> bool:
    """
    将部署工具同步到Agent端
    
    Returns:
        bool: 是否成功
    """
    try:
        current_version = get_deployment_tool_version()
        if not current_version:
            logger.error("无法获取部署工具版本，无法同步")
            return False
        
        # 检查部署工具目录是否存在
        if not DEPLOYMENT_TOOL_DIR.exists():
            logger.error(f"部署工具目录不存在: {DEPLOYMENT_TOOL_DIR}")
            return False
        
        # 创建临时tar.gz文件
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp_file:
            tar_path = tmp_file.name
        
        try:
            # 打包部署工具目录
            logger.info(f"打包部署工具目录: {DEPLOYMENT_TOOL_DIR}")
            with tarfile.open(tar_path, 'w:gz') as tar:
                tar.add(DEPLOYMENT_TOOL_DIR, arcname='deployment-tool', filter=lambda tarinfo: None if '.git' in tarinfo.name or '__pycache__' in tarinfo.name else tarinfo)
            
            # 读取tar.gz文件内容
            with open(tar_path, 'rb') as f:
                tar_content = f.read()
            
            # 将tar.gz文件上传到Agent端
            logger.info(f"上传部署工具到Agent {agent.id}")
            
            # 将tar.gz内容进行base64编码
            import base64
            tar_base64 = base64.b64encode(tar_content).decode('ascii')
            
            upload_script = f"""#!/bin/bash
set -e

# 创建部署工具目录
mkdir -p {AGENT_DEPLOYMENT_TOOL_DIR}

# 将base64编码的tar.gz内容解码并解压
echo "{tar_base64}" | base64 -d > /tmp/deployment-tool.tar.gz

# 解压到目标目录
cd {AGENT_DEPLOYMENT_TOOL_DIR}
tar -xzf /tmp/deployment-tool.tar.gz --strip-components=1

# 设置权限
chmod -R 755 {AGENT_DEPLOYMENT_TOOL_DIR}

# 清理临时文件
rm -f /tmp/deployment-tool.tar.gz

# 验证版本
if [ -f {AGENT_DEPLOYMENT_TOOL_DIR}/VERSION ]; then
    echo "部署工具同步成功，版本: $(cat {AGENT_DEPLOYMENT_TOOL_DIR}/VERSION)"
    exit 0
else
    echo "错误: 版本文件不存在"
    exit 1
fi
"""
            
            # 执行上传脚本
            from apps.agents.utils import execute_script_via_agent
            cmd = execute_script_via_agent(agent, upload_script, timeout=300, script_name='sync_deployment_tool.sh')
            
            # 等待命令执行完成
            import time
            max_wait = 300
            wait_time = 0
            while wait_time < max_wait:
                cmd.refresh_from_db()
                if cmd.status in ['success', 'failed']:
                    break
                time.sleep(2)
                wait_time += 2
            
            if cmd.status == 'success':
                # 更新Agent的部署工具版本
                agent.deployment_tool_version = current_version
                agent.save(update_fields=['deployment_tool_version'])
                logger.info(f"部署工具同步成功: Agent {agent.id}, 版本 {current_version}")
                return True
            else:
                logger.error(f"部署工具同步失败: Agent {agent.id}, 错误: {cmd.error}")
                return False
                
        finally:
            # 清理临时文件
            if os.path.exists(tar_path):
                os.unlink(tar_path)
                
    except Exception as e:
        logger.error(f"同步部署工具到Agent失败: {e}", exc_info=True)
        return False

