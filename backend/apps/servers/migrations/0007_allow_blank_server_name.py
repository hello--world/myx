# Generated manually to allow blank server name
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servers', '0006_alter_server_connection_method'),
    ]

    operations = [
        migrations.AlterField(
            model_name='server',
            name='name',
            field=models.CharField(blank=True, max_length=100, verbose_name='服务器名称'),
        ),
    ]

