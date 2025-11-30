# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("servers", "0004_server_agent_connect_host_server_agent_connect_port"),
    ]

    operations = [
        migrations.AddField(
            model_name="server",
            name="save_password",
            field=models.BooleanField(default=False, verbose_name="保存密码"),
        ),
        migrations.AddField(
            model_name="server",
            name="enable_ssh_key",
            field=models.BooleanField(default=False, verbose_name="启用SSH Key登录"),
        ),
        migrations.AddField(
            model_name="server",
            name="generated_public_key",
            field=models.TextField(blank=True, null=True, verbose_name="生成的公钥"),
        ),
    ]

