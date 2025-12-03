# Generated migration for Agent Web Service

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0007_add_deployment_tool_version'),
    ]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='web_service_port',
            field=models.IntegerField(default=8443, verbose_name='Web服务端口', help_text='Agent Web服务监听的端口'),
        ),
        migrations.AddField(
            model_name='agent',
            name='web_service_enabled',
            field=models.BooleanField(default=True, verbose_name='启用Web服务', help_text='是否启用Agent Web服务模式'),
        ),
        migrations.AddField(
            model_name='agent',
            name='certificate_path',
            field=models.CharField(max_length=255, blank=True, null=True, verbose_name='证书路径', help_text='Agent Web服务使用的SSL证书路径'),
        ),
        migrations.AddField(
            model_name='agent',
            name='private_key_path',
            field=models.CharField(max_length=255, blank=True, null=True, verbose_name='私钥路径', help_text='Agent Web服务使用的SSL私钥路径'),
        ),
    ]

