# Generated manually to add Certificate model
from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('proxies', '0003_remove_proxy_enable_reality_remove_proxy_enable_tls_and_more'),
        ('servers', '0007_allow_blank_server_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='Certificate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(blank=True, help_text='证书关联的域名（可选）', max_length=255, null=True, verbose_name='域名')),
                ('cert_path', models.CharField(help_text='证书文件在服务器上的路径', max_length=500, verbose_name='证书路径')),
                ('key_path', models.CharField(help_text='密钥文件在服务器上的路径', max_length=500, verbose_name='密钥路径')),
                ('remark', models.TextField(blank=True, null=True, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='创建者')),
                ('server', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='certificates', to='servers.server', verbose_name='服务器')),
            ],
            options={
                'verbose_name': '证书',
                'verbose_name_plural': '证书',
                'ordering': ['-created_at'],
                'unique_together': {('server', 'cert_path', 'key_path')},
            },
        ),
    ]

