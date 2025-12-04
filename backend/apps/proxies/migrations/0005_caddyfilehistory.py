# Generated manually to add CaddyfileHistory model
from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('proxies', '0004_certificate'),
    ]

    operations = [
        migrations.CreateModel(
            name='CaddyfileHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField(verbose_name='Caddyfile内容')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='创建者')),
                ('proxy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='caddyfile_histories', to='proxies.proxy', verbose_name='代理节点')),
            ],
            options={
                'verbose_name': 'Caddyfile历史版本',
                'verbose_name_plural': 'Caddyfile历史版本',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='caddyfilehistory',
            index=models.Index(fields=['-created_at'], name='proxies_cad_created_idx'),
        ),
    ]

