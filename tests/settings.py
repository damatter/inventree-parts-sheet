from pathlib import Path

SECRET_KEY = "isolated-test-settings-not-for-deployment"
DEBUG = True
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
BASE_DIR = Path(__file__).parent
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "djmoney",
    "djmoney.contrib.exchange",
    "part",
    "company",
    "stock",
    "parts_sheet",
    "inventree_customer_pricing",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "test.sqlite3"),
        "OPTIONS": {"timeout": 30},
        "TEST": {"NAME": str(BASE_DIR / "test-run.sqlite3")},
    }
}
MIGRATION_MODULES = {
    "part": None,
    "company": None,
    "stock": None,
    "parts_sheet": None,
    "inventree_customer_pricing": None,
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
ROOT_URLCONF = "urls"
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.csrf"]},
    }
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
