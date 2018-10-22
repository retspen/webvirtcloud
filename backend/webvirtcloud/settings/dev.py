"""
Django development settings for webvirtcloud project.

"""
try:
    from .base import *
except ImportError:
    pass

DEBUG = True
ADMIN_ENABLED = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS += [
    'corsheaders',
    'debug_toolbar',
    'rest_framework_swagger',
]

MIDDLEWARE += [
    'corsheaders.middleware.CorsMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',
]

# DebugToolBar
INTERNAL_IPS = (
    '127.0.0.1',
)
DEBUG_TOOLBAR_CONFIG = {
    'INTERCEPT_REDIRECTS': False,
}

# CORS settings
CORS_ORIGIN_WHITELIST = (
    'localhost:8080',
    'localhost:3000',
)

# Swagger settings
SWAGGER_SETTINGS = {
    'VALIDATOR_URL': None,
    'JSON_EDITOR': True,
    'USE_SESSION_AUTH': True,
    'SHOW_REQUEST_HEADERS': True,
    'DOC_EXPANSION': 'list',
    'APIS_SORTER': 'alpha',
    'SECURITY_DEFINITIONS': None,
}

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
