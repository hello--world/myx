"""
管理命令：初始化默认子域名词库
用法: python manage.py init_subdomain_words
"""
from django.core.management.base import BaseCommand
from apps.settings.models import SubdomainWord
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '初始化默认子域名词库'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='强制初始化，即使已有数据也会添加缺失的词',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        
        # 常用子域名词列表
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
        
        # 检查是否已有数据
        existing_count = SubdomainWord.objects.count()
        if existing_count > 0 and not force:
            self.stdout.write(
                self.style.WARNING(
                    f'子域名词库已有 {existing_count} 个词，跳过初始化。'
                    '使用 --force 参数强制初始化（会添加缺失的词）。'
                )
            )
            return
        
        # 批量创建
        created_count = 0
        skipped_count = 0
        
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
                self.stdout.write(
                    self.style.SUCCESS(f'✓ 创建词: {word_data["word"]} ({word_data["category"]})')
                )
            else:
                skipped_count += 1
                if force:
                    self.stdout.write(
                        self.style.WARNING(f'- 跳过词（已存在）: {word_data["word"]}')
                    )
        
        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n初始化完成：成功创建 {created_count} 个词'
                    + (f'，跳过 {skipped_count} 个（已存在）' if skipped_count > 0 else '')
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING('所有词都已存在，无需初始化')
            )

