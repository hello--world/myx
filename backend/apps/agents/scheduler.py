"""
Agent心跳调度器
在Django应用启动时自动启动后台线程，随机向Agent发送心跳（服务器主动模式）
"""
import threading
import time
import random
import logging
from .heartbeat_scheduler import check_all_agents_heartbeat

logger = logging.getLogger(__name__)

# 心跳间隔范围（秒，可从settings配置）
def get_heartbeat_interval_range():
    """获取心跳间隔范围（秒）"""
    from django.conf import settings
    min_interval = getattr(settings, 'AGENT_HEARTBEAT_MIN_INTERVAL', 20)
    max_interval = getattr(settings, 'AGENT_HEARTBEAT_MAX_INTERVAL', 60)
    return min_interval, max_interval

# 全局调度器实例
_scheduler_thread = None


def _random_interval(min_seconds: int, max_seconds: int) -> int:
    """生成随机间隔（秒）"""
    if min_seconds >= max_seconds:
        return min_seconds
    return random.randint(min_seconds, max_seconds)


def start_scheduler():
    """启动Agent心跳调度器"""
    global _scheduler_thread
    
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info('Agent心跳调度器已在运行')
        return
    
    def _scheduler_loop():
        """调度器主循环"""
        min_interval, max_interval = get_heartbeat_interval_range()
        logger.info(f'Agent心跳调度器已启动，心跳间隔: {min_interval}-{max_interval}秒（随机）')
        
        while True:
            try:
                # 向所有Agent发送心跳
                check_all_agents_heartbeat()
                
                # 随机等待一段时间后再次发送心跳
                interval = _random_interval(min_interval, max_interval)
                logger.debug(f'下次心跳将在 {interval} 秒后发送')
                time.sleep(interval)
            except Exception as e:
                logger.error(f'Agent心跳调度器错误: {str(e)}', exc_info=True)
                # 出错后随机等待一段时间再继续
                interval = _random_interval(min_interval, max_interval)
                time.sleep(interval)
    
    # 创建并启动守护线程
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name='AgentHeartbeatScheduler')
    _scheduler_thread.start()
    logger.info('Agent心跳调度器线程已启动')


def stop_scheduler():
    """停止Agent心跳调度器（通常不需要手动调用）"""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info('停止Agent心跳调度器')
        # 由于是守护线程，主进程退出时会自动停止
        _scheduler_thread = None

