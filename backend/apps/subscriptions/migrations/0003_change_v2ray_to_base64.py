# Generated manually to change v2ray format to base64

from django.db import migrations, models


def update_v2ray_to_base64(apps, schema_editor):
    """将现有的 v2ray 格式订阅更新为 base64"""
    Subscription = apps.get_model('subscriptions', 'Subscription')
    Subscription.objects.filter(format='v2ray').update(format='base64')


def reverse_update(apps, schema_editor):
    """回滚：将 base64 格式订阅改回 v2ray"""
    Subscription = apps.get_model('subscriptions', 'Subscription')
    Subscription.objects.filter(format='base64').update(format='v2ray')


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0002_subscription_proxy_ids'),
    ]

    operations = [
        # 先更新现有数据
        migrations.RunPython(update_v2ray_to_base64, reverse_update),
        
        # 然后修改字段的 choices 和默认值
        migrations.AlterField(
            model_name='subscription',
            name='format',
            field=models.CharField(
                choices=[('base64', 'Base64'), ('clash', 'Clash')],
                default='base64',
                max_length=20,
                verbose_name='订阅格式'
            ),
        ),
    ]

