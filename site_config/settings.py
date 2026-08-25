from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta
import os
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


SECRET_KEY = os.getenv("SECRET_KEY")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # library app
    'rest_framework', 'drf_spectacular', 'rest_framework_simplejwt',
    'corsheaders', 'django_extensions', 'django_filters',
    'rest_framework_simplejwt.token_blacklist', 'django_json_widget', 'django_celery_results',

    # custom app
    'account', 'core.apps.CoreConfig', 'lead', 'intake',
]

if env_bool("USE_S3", False):
    INSTALLED_APPS.append("storages")

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ================================================================================
# ==================== Rest Frame Work Configurations Start====================
ENABLE_BROWSABLE_API = os.getenv('ENABLE_BROWSABLE_API', 'False') == 'True'
if ENABLE_BROWSABLE_API:
    DEFAULT_RENDERER_CLASSES_ = [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ]
else:
    DEFAULT_RENDERER_CLASSES_ = [
        'rest_framework.renderers.JSONRenderer'
    ]

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': DEFAULT_RENDERER_CLASSES_,
    
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    
    # 'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    # 'PAGE_SIZE': 5,
    
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),

    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    'AUTH_HEADER_TYPES': ('Bearer',),
    'BLACKLIST_AFTER_ROTATION': True,
    'ROTATE_REFRESH_TOKENS': True,
    # 'ROTATE_REFRESH_TOKENS': False,
    
    'ACCESS_TOKEN_LIFETIME': timedelta(days=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=60),
    "UPDATE_LAST_LOGIN": True,

    # "ALGORITHM": "HS256",
    # "SIGNING_KEY": SECRET_KEY,
    # "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ORIGIN_ALLOW_ALL = True

SPECTACULAR_SETTINGS = {
    'TITLE': 'TattooHysteria [Ink-Flow] API',
    'DESCRIPTION': 'API documentation for TattooHysteria [Ink-Flow] project',
    'VERSION': '1.0.0',
    'SECURITY': [{'BearerAuth': []}],
    'COMPONENTS': {
        'SECURITY_SCHEMES': {
            'BearerAuth': {
                'type': 'http',
                'scheme': 'bearer',
                'bearerFormat': 'JWT',
            }
        }
    },
}

# ==================== Rest Frame Work Configurations End====================
# ================================================================================

ROOT_URLCONF = 'site_config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'site_config.wsgi.application'

# Database
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "600")),
            ssl_require=env_bool("DATABASE_SSL_REQUIRE", False),
        )
    }
elif os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB"),
            "USER": os.getenv("POSTGRES_USER"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "600")),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


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
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ==========================================================================================
# =================Celery & Redis Config Start================================
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6380/0")
# CELERY_BROKER_URL = "redis://127.0.0.1:6379/0"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"

CELERY_RESULT_BACKEND = "django-db"

CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "True").strip().lower() in ("true", "1", "yes")
CELERY_TASK_EAGER_PROPAGATES = os.getenv("CELERY_TASK_EAGER_PROPAGATES", "True").strip().lower() in ("true", "1", "yes")

# =================Celery & Redis Config End================================
# ==========================================================================================


# ==========================================================================================
# =================Static & Media Config================================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = os.getenv('MEDIA_ROOT', default=os.path.join(BASE_DIR, 'media'))
MEDIA_BASE_URL = os.getenv('MEDIA_BASE_URL', 'https://55k6tr24-8007.inc1.devtunnels.ms/media/')

if env_bool("USE_S3", False):
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME")
    AWS_S3_CUSTOM_DOMAIN = os.getenv("AWS_S3_CUSTOM_DOMAIN", "")
    AWS_QUERYSTRING_AUTH = env_bool("AWS_QUERYSTRING_AUTH", False)
    AWS_DEFAULT_ACL = os.getenv("AWS_DEFAULT_ACL") or None
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": os.getenv("AWS_S3_CACHE_CONTROL", "max-age=86400")}
    AWS_LOCATION = os.getenv("AWS_LOCATION", "media")

    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_LOCATION}/"
    elif AWS_STORAGE_BUCKET_NAME and AWS_S3_REGION_NAME:
        MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{AWS_LOCATION}/"

    MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", MEDIA_URL)
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME,
            "location": AWS_LOCATION,
            "default_acl": AWS_DEFAULT_ACL,
            "querystring_auth": AWS_QUERYSTRING_AUTH,
        },
    }
# =================Static & Media Config================================
# ==========================================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'account.User'



# default is ~2.5 MB; bump to e.g. 20 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024



# ==========================================================================================
# =================API Extra Security================================
FRONTEND_APP_KEY=os.getenv("FRONTEND_APP_KEY")
# =================API Extra Security================================
# ==========================================================================================


# ==========================================================================================
# =================WhatsApp / Meta Config================================
WHATSAPP = {
    "VERIFY_TOKEN": os.getenv("META_VERIFY_TOKEN", ""),
    "APP_SECRET": os.getenv("META_APP_SECRET", ""),
    "API_VERSION": os.getenv("META_API_VERSION", "v22.0"),
}
# =================WhatsApp / Meta Config================================
# ==========================================================================================


# ==========================================================================================
# =================AI Service Config================================
AI_SERVICE = {
    "API_URL": os.getenv("AI_API_URL", ""),
    "SUMMARY_API_URL": os.getenv("AI_SUMMARY_API_URL", os.getenv("AI_SUMMAERY_API_URL", "")),
    "TIMEOUT": int(os.getenv("AI_API_TIMEOUT", "30")),
    "CHAT_HISTORY_LIMIT": int(os.getenv("AI_CHAT_HISTORY_LIMIT", "20")),
}

TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_REVIEW_CHAT_ID=os.getenv("TELEGRAM_REVIEW_CHAT_ID", "")
# =================AI Service Config================================
# ==========================================================================================


# ==========================================================================================
# =================Logging Config================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} | {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "core": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "lead": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
# =================Logging Config================================
# ==========================================================================================


