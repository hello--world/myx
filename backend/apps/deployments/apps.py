from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class DeploymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.deployments'
    
    def ready(self):
        """应用启动时自动执行"""
        import os
        import sys
        
        # 避免在迁移、测试等非服务器模式下启动
        is_server = (
            'runserver' in sys.argv or
            'gunicorn' in sys.argv[0] or
            'uwsgi' in sys.argv[0] or
            os.environ.get('RUN_MAIN') == 'true'
        )
        
        if not is_server or 'migrate' in sys.argv or 'test' in sys.argv:
            return
        
        # 启动部署任务监控调度器
        try:
            from .scheduler import start_scheduler
            start_scheduler()
            logger.info('部署任务监控调度器已自动启动')
        except Exception as e:
            logger.error(f'启动部署任务监控调度器失败: {str(e)}', exc_info=True)

