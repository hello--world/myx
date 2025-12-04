from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class SettingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.settings'
    verbose_name = '应用设置'
    
    def ready(self):
        """应用启动时自动执行"""
        import os
        import sys
        import threading
        from django.db.models.signals import post_migrate
        
        # 避免在迁移、测试等非服务器模式下启动
        is_server = (
            'runserver' in sys.argv or
            'gunicorn' in sys.argv[0] or
            'uwsgi' in sys.argv[0] or
            os.environ.get('RUN_MAIN') == 'true'
        )
        
        # 如果是迁移、测试等命令，不执行初始化
        if not is_server or 'migrate' in sys.argv or 'test' in sys.argv:
            logger.debug('跳过子域名词库自动初始化（非服务器模式）')
            return
        
        # Django 开发服务器会启动两次（主进程和重载进程），只在主进程执行
        # 使用环境变量 RUN_MAIN 来区分
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            logger.debug('跳过子域名词库自动初始化（Django 开发服务器子进程）')
            return
        
        # 使用 post_migrate 信号确保在迁移完成后执行
        def init_after_migrate(sender, **kwargs):
            """迁移完成后初始化"""
            if kwargs.get('app_config') and kwargs['app_config'].name == self.name:
                logger.info('迁移完成，开始自动初始化子域名词库...')
                try:
                    self.init_default_subdomain_words()
                except Exception as e:
                    logger.error(f'自动初始化子域名词库失败: {str(e)}', exc_info=True)
        
        # 连接信号
        post_migrate.connect(init_after_migrate, sender=self)
        
        # 延迟执行初始化检查，确保数据库连接已建立
        def delayed_init():
            import time
            time.sleep(1)  # 等待1秒，确保数据库连接已建立
            logger.info('检查子域名词库是否需要初始化...')
            try:
                self.init_default_subdomain_words()
            except Exception as e:
                # 如果失败（可能是表不存在），等待迁移完成
                logger.debug(f'初始化检查失败（可能表未创建）: {str(e)}')
        
        # 在后台线程中延迟执行
        thread = threading.Thread(target=delayed_init, daemon=True)
        thread.start()
    
    def init_default_subdomain_words(self):
        """初始化默认子域名词库"""
        from django.db import connection
        from django.core.exceptions import OperationalError
        from .models import SubdomainWord
        
        # 检查数据库表是否存在（避免在迁移前执行）
        try:
            # 使用 Django 的 connection 来检查表是否存在
            with connection.cursor() as cursor:
                if 'sqlite' in connection.settings_dict['ENGINE']:
                    cursor.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='table' AND name='settings_subdomainword'
                    """)
                else:
                    # PostgreSQL/MySQL 等其他数据库
                    cursor.execute("""
                        SELECT table_name FROM information_schema.tables 
                        WHERE table_name='settings_subdomainword'
                    """)
                table_exists = cursor.fetchone() is not None
                
                if not table_exists:
                    logger.info('子域名词表尚未创建，跳过自动初始化（等待迁移完成）')
                    return
        except OperationalError as e:
            logger.warning(f'检查数据库表时出错（可能是表不存在）: {str(e)}，跳过自动初始化')
            return
        except Exception as e:
            logger.warning(f'检查数据库表时出错: {str(e)}，尝试继续初始化')
        
        # 检查是否已经有数据
        try:
            word_count = SubdomainWord.objects.count()
            logger.info(f'当前子域名词库中有 {word_count} 个词')
            if word_count > 0:
                logger.info('子域名词库已有数据，跳过自动初始化')
                return
        except OperationalError as e:
            logger.warning(f'查询子域名词库数据时出错: {str(e)}，跳过自动初始化')
            return
        except Exception as e:
            logger.warning(f'检查子域名词库数据时出错: {str(e)}，跳过自动初始化')
            return
        
        # 常用子域名词列表（与迁移文件和视图中的保持一致）
        default_words = [
            # 通用类
            {'word': 'www', 'category': 'common'},
            {'word': 'api', 'category': 'common'},
            {'word': 'app', 'category': 'common'},
            {'word': 'web', 'category': 'common'},
            {'word': 'site', 'category': 'common'},
            
            # 服务类
            {'word': 'chat', 'category': 'service'},
            {'word': 'mail', 'category': 'service'},
            {'word': 'ftp', 'category': 'service'},
            {'word': 'ssh', 'category': 'service'},
            {'word': 'vpn', 'category': 'service'},
            {'word': 'proxy', 'category': 'service'},
            {'word': 'agent', 'category': 'service'},
            {'word': 'node', 'category': 'service'},
            {'word': 'server', 'category': 'service'},
            {'word': 'cdn', 'category': 'service'},
            
            # 应用类
            {'word': 'admin', 'category': 'app'},
            {'word': 'dashboard', 'category': 'app'},
            {'word': 'panel', 'category': 'app'},
            {'word': 'portal', 'category': 'app'},
            {'word': 'console', 'category': 'app'},
            
            # 其他
            {'word': 'test', 'category': 'other'},
            {'word': 'dev', 'category': 'other'},
            {'word': 'staging', 'category': 'other'},
            {'word': 'demo', 'category': 'other'},
        ]
        
        # 批量创建
        created_count = 0
        for word_data in default_words:
            word_obj, created = SubdomainWord.objects.get_or_create(
                word=word_data['word'],
                defaults={
                    'category': word_data['category'],
                    'is_active': True
                }
            )
            if created:
                created_count += 1
        
        if created_count > 0:
            logger.info(f'自动初始化子域名词库完成：成功创建 {created_count} 个默认词')
        else:
            logger.debug('子域名词库已存在，无需初始化')

