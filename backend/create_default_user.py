"""
创建默认管理员账号的脚本
"""
import os
import django

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import User

def create_default_user():
    """创建默认管理员账号"""
    username = 'admin'
    password = 'admin123'
    email = 'admin@example.com'
    
    # 检查用户是否已存在
    if User.objects.filter(username=username).exists():
        print(f'用户 {username} 已存在')
        return
    
    # 创建超级用户
    User.objects.create_superuser(
        username=username,
        email=email,
        password=password
    )
    print(f'默认管理员账号创建成功！')
    print(f'用户名: {username}')
    print(f'密码: {password}')
    print('⚠️  请在生产环境中修改默认密码！')

if __name__ == '__main__':
    create_default_user()
