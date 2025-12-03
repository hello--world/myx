# Generated migration for Agent RPC Port

from django.db import migrations, models
import random


def generate_random_port():
    """生成随机端口（8000-65535，排除常用端口）"""
    excluded_ports = {22, 80, 443, 8000, 8443, 3306, 5432, 6379, 8080, 9000}
    while True:
        port = random.randint(8000, 65535)
        if port not in excluded_ports:
            return port


def set_initial_rpc_ports(apps, schema_editor):
    """为现有Agent设置随机RPC端口"""
    Agent = apps.get_model('agents', 'Agent')
    for agent in Agent.objects.all():
        if not agent.rpc_port:
            agent.rpc_port = generate_random_port()
            agent.save(update_fields=['rpc_port'])


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0008_add_web_service_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='rpc_port',
            field=models.IntegerField(
                null=True,
                blank=True,
                unique=True,
                verbose_name='RPC端口',
                help_text='Agent JSON-RPC服务端口（首次部署时确定，不可更改）'
            ),
        ),
        migrations.RunPython(set_initial_rpc_ports, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='agent',
            name='rpc_port',
            field=models.IntegerField(
                unique=True,
                verbose_name='RPC端口',
                help_text='Agent JSON-RPC服务端口（首次部署时确定，不可更改）'
            ),
        ),
    ]

