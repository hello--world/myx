# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0006_add_secret_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="deployment_tool_version",
            field=models.CharField(
                blank=True,
                help_text="Agent端部署工具的版本号",
                max_length=50,
                null=True,
                verbose_name="部署工具版本",
            ),
        ),
    ]

