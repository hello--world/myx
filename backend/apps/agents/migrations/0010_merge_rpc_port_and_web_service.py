# Generated migration to merge 0009_add_rpc_port and 0009_alter_agent_web_service_enabled

from django.db import migrations
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
        if not hasattr(agent, 'rpc_port') or not agent.rpc_port:
            agent.rpc_port = generate_random_port()
            agent.save(update_fields=['rpc_port'])


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0009_add_rpc_port'),
        ('agents', '0009_alter_agent_web_service_enabled'),
    ]

    operations = [
        migrations.RunPython(set_initial_rpc_ports, migrations.RunPython.noop),
    ]

