# Generated migration for Agent RPC Support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0010_merge_rpc_port_and_web_service'),
    ]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='rpc_supported',
            field=models.BooleanField(
                default=False,
                verbose_name='支持JSON-RPC',
                help_text='Agent是否支持JSON-RPC协议'
            ),
        ),
        migrations.AddField(
            model_name='agent',
            name='rpc_last_check',
            field=models.DateTimeField(
                null=True,
                blank=True,
                verbose_name='RPC支持检查时间',
                help_text='最后一次检查Agent是否支持JSON-RPC的时间'
            ),
        ),
        migrations.AddField(
            model_name='agent',
            name='rpc_last_success',
            field=models.DateTimeField(
                null=True,
                blank=True,
                verbose_name='RPC最后成功时间',
                help_text='最后一次成功通过JSON-RPC连接的时间'
            ),
        ),
    ]

