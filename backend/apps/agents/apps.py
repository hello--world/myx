from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class AgentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.agents'
    
    def ready(self):
        """应用启动时自动执行"""
        import os
        import sys
        
        # 避免在迁移、测试等非服务器模式下启动
        # 检查是否在运行服务器（runserver, gunicorn, uwsgi等）
        is_server = (
            'runserver' in sys.argv or
            'gunicorn' in sys.argv[0] or
            'uwsgi' in sys.argv[0] or
            os.environ.get('RUN_MAIN') == 'true'  # Django开发服务器主进程
        )
        
        # 如果是迁移、测试等命令，不启动调度器
        if not is_server or 'migrate' in sys.argv or 'test' in sys.argv:
            return
        
        # 启动Agent心跳调度器（服务器主动向Agent发送心跳）
        try:
            from .scheduler import start_scheduler
            start_scheduler()
            logger.info('Agent心跳调度器已自动启动（服务器主动模式）')
        except Exception as e:
            logger.error(f'启动Agent心跳调度器失败: {str(e)}', exc_info=True)

