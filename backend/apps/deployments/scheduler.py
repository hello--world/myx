"""
部署任务监控调度器
在Django应用启动时自动启动后台线程，定期检查所有运行中的部署任务
"""
import threading
import time
import logging
from .monitor import check_running_deployments

logger = logging.getLogger(__name__)

# 检查间隔（秒）
CHECK_INTERVAL = 5  # 每5秒检查一次

# 全局调度器线程
_scheduler_thread = None


def start_scheduler():
    """启动部署任务监控调度器"""
    global _scheduler_thread
    
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info('部署任务监控调度器已在运行')
        return
    
    def _scheduler_loop():
        """调度器主循环"""
        logger.info(f'部署任务监控调度器已启动，检查间隔: {CHECK_INTERVAL}秒')
        
        while True:
            try:
                # 检查所有运行中的部署任务
                check_running_deployments()
                
                # 等待指定时间后再次检查
                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f'部署任务监控调度器错误: {str(e)}', exc_info=True)
                # 出错后等待一段时间再继续
                time.sleep(CHECK_INTERVAL)
    
    # 创建并启动守护线程
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name='DeploymentMonitor')
    _scheduler_thread.start()
    logger.info('部署任务监控调度器线程已启动')


def stop_scheduler():
    """停止部署任务监控调度器（通常不需要手动调用）"""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info('停止部署任务监控调度器')
        _scheduler_thread = None

