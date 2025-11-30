"""
Django settings for MyX project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# ALLOWED_HOSTS: 允许访问的主机列表
# 从环境变量读取，如果没有设置则使用默认值
# 如果设置了环境变量，会追加到默认值后面（支持追加模式）
# 支持逗号分隔的多个主机，例如: localhost,127.0.0.1,your-domain.com
default_allowed_hosts = ['localhost', '127.0.0.1']
env_allowed_hosts = os.getenv('ALLOWED_HOSTS', '')
if env_allowed_hosts:
    # 追加模式：将环境变量中的主机追加到默认值
    additional_hosts = [h.strip() for h in env_allowed_hosts.split(',') if h.strip()]
    ALLOWED_HOSTS = default_allowed_hosts + additional_hosts
else:
    # 如果没有设置环境变量，只使用默认值
    ALLOWED_HOSTS = default_allowed_hosts

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'apps.accounts',
    'apps.servers',
    'apps.proxies',
    'apps.subscriptions',
    'apps.deployments',
    'apps.agents',
    'apps.health',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# CORS settings
# 从环境变量读取，如果没有设置则使用默认值
# 如果设置了环境变量，会追加到默认值后面（支持追加模式）
# 支持逗号分隔的多个源，例如: http://localhost:5173,http://your-domain.com
default_cors_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
env_cors_origins = os.getenv('CORS_ALLOWED_ORIGINS', '')
if env_cors_origins:
    # 追加模式：将环境变量中的源追加到默认值
    additional_origins = [origin.strip() for origin in env_cors_origins.split(',') if origin.strip()]
    CORS_ALLOWED_ORIGINS = default_cors_origins + additional_origins
else:
    # 如果没有设置环境变量，只使用默认值
    CORS_ALLOWED_ORIGINS = default_cors_origins

CORS_ALLOW_CREDENTIALS = True

# Session settings
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
# CSRF Trusted Origins
# 从环境变量读取，如果没有设置则使用默认值
# 如果设置了环境变量，会追加到默认值后面（支持追加模式）
# 支持逗号分隔的多个源，例如: http://localhost:5173,https://your-domain.com
default_csrf_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
env_csrf_origins = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if env_csrf_origins:
    # 追加模式：将环境变量中的源追加到默认值
    additional_origins = [origin.strip() for origin in env_csrf_origins.split(',') if origin.strip()]
    CSRF_TRUSTED_ORIGINS = default_csrf_origins + additional_origins
else:
    # 如果没有设置环境变量，只使用默认值
    CSRF_TRUSTED_ORIGINS = default_csrf_origins

# Agent API URL (用于Agent注册)
# 如果设置为 localhost，Agent 将无法从远程服务器连接
# 应该设置为可以从目标服务器访问的地址，例如: http://your-server-ip:8000/api/agents
AGENT_API_URL = os.getenv('AGENT_API_URL', 'http://localhost:8000/api/agents')

# Backend Host (用于构建 Agent API URL)
# 如果 AGENT_API_URL 包含 localhost，将使用此值替换
# 例如: your-domain.com 或 192.168.1.100
BACKEND_HOST = os.getenv('BACKEND_HOST', None)

# GitHub Repository (用于下载Agent二进制文件)
# 格式: owner/repo
GITHUB_REPO = os.getenv('GITHUB_REPO', 'hello--world/myx')


