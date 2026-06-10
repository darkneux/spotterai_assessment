"""
Django settings for the Fuel Route Optimization API.

Configuration is environment-driven (django-environ) so that the vehicle model,
corridor width, routing/geocoding providers, planner strategy, and cache backend
can all be tuned per environment without code changes. Every value has a default
that lets the project run with zero configuration on SQLite + an offline routing
provider, which keeps the project trivially runnable for reviewers.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    SECRET_KEY=(str, "dev-insecure-change-me"),
    ALLOWED_HOSTS=(list, ["*"]),
    FUEL_MAX_RANGE_MILES=(float, 500.0),
    FUEL_MILES_PER_GALLON=(float, 10.0),
    ROUTE_CORRIDOR_WIDTH_KM=(float, 30.0),
    FUEL_PLANNER_STRATEGY=(str, "greedy"),
    ROUTING_PROVIDER=(str, "offline"),
    ORS_API_KEY=(str, ""),
    ORS_BASE_URL=(str, "https://api.openrouteservice.org"),
    OSRM_BASE_URL=(str, "http://router.project-osrm.org"),
    GEOCODING_PROVIDER=(str, "offline"),
    NOMINATIM_BASE_URL=(str, "https://nominatim.openstreetmap.org"),
    REDIS_URL=(str, ""),
    ROUTING_CACHE_TTL_SECONDS=(int, 86400),
    DATABASE_URL=(str, ""),
)

# Load a .env file if present (optional).
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

# --- Core ---
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "fuelstations",
    "routing",
    "planner",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "api.middleware.RequestIDMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database ---
# Default: SQLite (no external service). Override with DATABASE_URL for Postgres.
_database_url = env("DATABASE_URL")
if _database_url:
    DATABASES = {"default": env.db_url_config(_database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / "db.sqlite3"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "static/"

# --- Cache (route + plan caching) ---
_redis_url = env("REDIS_URL")
if _redis_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _redis_url,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fuelroute-cache",
        }
    }

# --- Django REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "api.exceptions.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # The service runs unauthenticated in a trusted environment (design §26);
    # auth is intentionally disabled so django.contrib.auth is not required.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel Route Optimization API",
    "DESCRIPTION": (
        "Given a US start and end location, returns the driving route, the "
        "cost-optimal fuel stops from the provided fuel-price dataset, and the "
        "total fuel cost (500-mile range, 10 mpg vehicle model)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Domain configuration (read once, injected into services) ---
FUEL_MAX_RANGE_MILES = env("FUEL_MAX_RANGE_MILES")
FUEL_MILES_PER_GALLON = env("FUEL_MILES_PER_GALLON")
ROUTE_CORRIDOR_WIDTH_KM = env("ROUTE_CORRIDOR_WIDTH_KM")
FUEL_PLANNER_STRATEGY = env("FUEL_PLANNER_STRATEGY")
ROUTING_PROVIDER = env("ROUTING_PROVIDER")
ORS_API_KEY = env("ORS_API_KEY")
ORS_BASE_URL = env("ORS_BASE_URL")
OSRM_BASE_URL = env("OSRM_BASE_URL")
GEOCODING_PROVIDER = env("GEOCODING_PROVIDER")
NOMINATIM_BASE_URL = env("NOMINATIM_BASE_URL")
ROUTING_CACHE_TTL_SECONDS = env("ROUTING_CACHE_TTL_SECONDS")

# --- Logging: structured-ish console logs with request correlation IDs ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "fuelroute": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
