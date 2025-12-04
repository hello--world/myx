# Generated manually
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settings', '0005_cloudflareaccount'),
    ]

    operations = [
        migrations.CreateModel(
            name='CloudflareZone',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('zone_id', models.CharField(max_length=100, unique=True, verbose_name='Zone ID')),
                ('zone_name', models.CharField(max_length=255, verbose_name='域名', help_text='例如: example.com')),
                ('status', models.CharField(blank=True, max_length=50, null=True, verbose_name='状态')),
                ('is_active', models.BooleanField(default=True, verbose_name='启用')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='zones', to='settings.cloudflareaccount', verbose_name='账户')),
            ],
            options={
                'verbose_name': 'Cloudflare Zone',
                'verbose_name_plural': 'Cloudflare Zones',
                'ordering': ['-created_at'],
                'unique_together': {('account', 'zone_id')},
            },
        ),
        migrations.CreateModel(
            name='CloudflareDNSRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('record_id', models.CharField(max_length=100, unique=True, verbose_name='记录ID')),
                ('record_type', models.CharField(choices=[('A', 'A'), ('AAAA', 'AAAA'), ('CNAME', 'CNAME'), ('MX', 'MX'), ('TXT', 'TXT'), ('NS', 'NS'), ('SRV', 'SRV')], max_length=10, verbose_name='记录类型')),
                ('name', models.CharField(help_text='例如: agent1.example.com', max_length=255, verbose_name='记录名称')),
                ('content', models.CharField(help_text='IP 地址或 CNAME 目标', max_length=255, verbose_name='记录内容')),
                ('ttl', models.IntegerField(default=1, help_text='1 = 自动，其他值表示秒数', verbose_name='TTL')),
                ('proxied', models.BooleanField(default=False, help_text='是否通过 Cloudflare CDN', verbose_name='启用代理')),
                ('is_active', models.BooleanField(default=True, verbose_name='启用')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('zone', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dns_records', to='settings.cloudflarezone', verbose_name='Zone')),
            ],
            options={
                'verbose_name': 'Cloudflare DNS 记录',
                'verbose_name_plural': 'Cloudflare DNS 记录',
                'ordering': ['-created_at'],
                'unique_together': {('zone', 'record_id')},
            },
        ),
    ]

