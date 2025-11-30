"""
Agent状态检查调度器
在Django应用启动时自动启动后台线程，定期检查Agent状态（拉取模式）
"""
import threading
import time
import logging
from django.utils import timezone
from .tasks import check_agent_status

logger = logging.getLogger(__name__)

# 检查间隔（秒，可从settings配置）
def get_check_interval():
    """获取检查间隔（秒）"""
    from django.conf import settings
    return getattr(settings, 'AGENT_STATUS_CHECK_INTERVAL', 30)

# 全局调度器实例
_scheduler = None
_scheduler_thread = None


def start_scheduler():
    """启动Agent状态检查调度器"""
    global _scheduler, _scheduler_thread
    
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info('Agent状态检查调度器已在运行')
        return
    
    def _scheduler_loop():
        """调度器主循环"""
        check_interval = get_check_interval()
        logger.info(f'Agent状态检查调度器已启动，检查间隔: {check_interval}秒')
        
        while True:
            try:
                # 检查所有使用拉取模式的Agent状态
                check_agent_status()
                
                # 等待指定时间后再次检查
                time.sleep(check_interval)
            except Exception as e:
                logger.error(f'Agent状态检查调度器错误: {str(e)}', exc_info=True)
                # 出错后等待一段时间再继续
                time.sleep(check_interval)
    
    # 创建并启动守护线程
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name='AgentStatusChecker')
    _scheduler_thread.start()
    logger.info('Agent状态检查调度器线程已启动')


def stop_scheduler():
    """停止Agent状态检查调度器（通常不需要手动调用）"""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info('停止Agent状态检查调度器')
        # 由于是守护线程，主进程退出时会自动停止
        _scheduler_thread = None

