"""
Django production settings for webvirtcloud project.
"""
try:
    from .base import *
except ImportError:
    pass

DEBUG = False
ADMIN_ENABLED = True

# DB connections
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'webvirtcloud',
        'USER': os.environ.get('DB_USER', 'root'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'root'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# Celery settings
CELERY_BROKER_URL = os.environ.get('BROKER_URL', 'amqp://guest:guest@localhost:5672')
