"""
Django管理命令：定时检查Agent状态（拉取模式）
使用方法：
    python manage.py check_agent_status

可以配合cron或systemd timer使用，例如每30秒执行一次：
    */30 * * * * cd /path/to/project && python manage.py check_agent_status
"""
from django.core.management.base import BaseCommand
from apps.agents.tasks import check_agent_status
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '检查所有使用拉取模式的Agent状态'

    def handle(self, *args, **options):
        self.stdout.write('开始检查Agent状态（拉取模式）...')
        try:
            check_agent_status()
            self.stdout.write(self.style.SUCCESS('Agent状态检查完成'))
        except Exception as e:
            logger.error(f'检查Agent状态失败: {str(e)}')
            self.stdout.write(self.style.ERROR(f'检查失败: {str(e)}'))

