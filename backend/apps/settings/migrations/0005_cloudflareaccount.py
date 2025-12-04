# Generated manually
from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('settings', '0004_init_subdomain_words'),
    ]

    operations = [
        migrations.CreateModel(
            name='CloudflareAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='账户名称')),
                ('api_token', models.CharField(blank=True, help_text='Cloudflare API Token（推荐）', max_length=255, null=True, verbose_name='API Token')),
                ('api_key', models.CharField(blank=True, max_length=255, null=True, verbose_name='Global API Key')),
                ('api_email', models.CharField(blank=True, max_length=255, null=True, verbose_name='API Email')),
                ('account_id', models.CharField(blank=True, max_length=100, null=True, verbose_name='账户ID')),
                ('account_name', models.CharField(blank=True, max_length=255, null=True, verbose_name='账户名称')),
                ('is_active', models.BooleanField(default=True, verbose_name='启用')),
                ('last_check', models.DateTimeField(blank=True, null=True, verbose_name='最后检查时间')),
                ('last_check_status', models.CharField(blank=True, max_length=20, null=True, verbose_name='最后检查状态')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='创建者')),
            ],
            options={
                'verbose_name': 'Cloudflare 账户',
                'verbose_name_plural': 'Cloudflare 账户',
                'ordering': ['-created_at'],
            },
        ),
    ]

