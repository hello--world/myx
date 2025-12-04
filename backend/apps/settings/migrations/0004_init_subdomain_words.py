# Generated manually to initialize default subdomain words
from django.db import migrations


def init_default_words(apps, schema_editor):
    """初始化默认子域名词库"""
    SubdomainWord = apps.get_model('settings', 'SubdomainWord')
    
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
    
    # 批量创建（如果不存在）
    for word_data in default_words:
        SubdomainWord.objects.get_or_create(
            word=word_data['word'],
            defaults={
                'category': word_data['category'],
                'is_active': True
            }
        )


def reverse_init_default_words(apps, schema_editor):
    """回滚：删除默认词"""
    SubdomainWord = apps.get_model('settings', 'SubdomainWord')
    
    default_words = [
        'www', 'api', 'app', 'web', 'site',
        'chat', 'mail', 'ftp', 'ssh', 'vpn', 'proxy', 'agent', 'node', 'server', 'cdn',
        'admin', 'dashboard', 'panel', 'portal', 'console',
        'test', 'dev', 'staging', 'demo'
    ]
    
    SubdomainWord.objects.filter(word__in=default_words).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('settings', '0003_subdomainword'),
    ]

    operations = [
        migrations.RunPython(init_default_words, reverse_init_default_words),
    ]

