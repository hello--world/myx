# Generated manually to add SubdomainWord model
from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('settings', '0002_appsettings_site_icon'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubdomainWord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('word', models.CharField(help_text='例如: www, chat, api, mail 等', max_length=50, unique=True, verbose_name='子域名词')),
                ('category', models.CharField(blank=True, help_text='例如: common, service, app 等', max_length=50, null=True, verbose_name='分类')),
                ('is_active', models.BooleanField(default=True, help_text='是否在随机生成时使用', verbose_name='启用')),
                ('usage_count', models.IntegerField(default=0, help_text='记录该词被使用的次数', verbose_name='使用次数')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='创建者')),
            ],
            options={
                'verbose_name': '子域名词',
                'verbose_name_plural': '子域名词',
                'ordering': ['-usage_count', 'word'],
            },
        ),
    ]

