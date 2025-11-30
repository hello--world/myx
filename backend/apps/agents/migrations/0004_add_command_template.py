# Generated manually

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0003_rename_registered_at_to_created_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CommandTemplate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, verbose_name="模板名称")),
                (
                    "description",
                    models.TextField(blank=True, null=True, verbose_name="描述"),
                ),
                ("command", models.CharField(max_length=255, verbose_name="命令")),
                (
                    "args",
                    models.JSONField(blank=True, default=list, verbose_name="参数"),
                ),
                (
                    "timeout",
                    models.IntegerField(default=300, verbose_name="超时时间（秒）"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="创建时间"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="更新时间"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="创建者",
                    ),
                ),
            ],
            options={
                "verbose_name": "命令模板",
                "verbose_name_plural": "命令模板",
                "ordering": ["-created_at"],
            },
        ),
    ]

