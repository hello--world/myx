# Generated manually

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0002_agent_heartbeat_mode_agent_last_check"),
    ]

    operations = [
        # 先添加新字段，使用默认值
        migrations.AddField(
            model_name="agent",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                verbose_name="创建时间"
            ),
            preserve_default=False,
        ),
        # 如果有数据，将 registered_at 的值复制到 created_at
        migrations.RunSQL(
            sql="UPDATE agents_agent SET created_at = registered_at WHERE registered_at IS NOT NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # 删除旧字段
        migrations.RemoveField(
            model_name="agent",
            name="registered_at",
        ),
    ]

