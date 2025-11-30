from django.db import models
from django.conf import settings as django_settings


class AppSettings(models.Model):
    """应用设置模型（单例模式）"""
    site_title = models.CharField(max_length=200, default='MyX - 科学技术管理平台', verbose_name='网站标题')
    site_subtitle = models.CharField(max_length=200, blank=True, default='', verbose_name='网站副标题')
    site_icon = models.TextField(blank=True, default='', verbose_name='网站图标（SVG）')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '应用设置'
        verbose_name_plural = '应用设置'

    def __str__(self):
        return '应用设置'

    @classmethod
    def get_settings(cls):
        """获取设置（单例）"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        """确保只有一个设置实例"""
        self.pk = 1
        super().save(*args, **kwargs)

