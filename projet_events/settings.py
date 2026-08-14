

"""
Configuration Django pour le projet projet_events.
----------------------------------------------------
PRODUCTION-READY — toutes les valeurs sensibles sont
lues depuis les variables d'environnement (fichier .env
ou variables du serveur). Ne jamais committer de vraies
valeurs dans ce fichier.

Variables d'environnement requises :
  SECRET_KEY               — clé secrète Django (longue et aléatoire)
  DEBUG                    — "True" en dev uniquement, absent/False en prod
  ALLOWED_HOSTS            — domaines autorisés, séparés par virgule
                             ex : "lessougode.pythonanywhere.com"
  CSRF_TRUSTED_ORIGINS     — origines HTTPS de confiance, séparées par virgule
                             ex : "https://lessougode.pythonanywhere.com"
  DB_NAME                  — nom de la base PostgreSQL
  DB_USER                  — utilisateur PostgreSQL
  DB_PASSWORD              — mot de passe PostgreSQL
  DB_HOST                  — hôte PostgreSQL (ex : localhost)
  DB_PORT                  — port PostgreSQL (défaut : 5432)
  EMAIL_HOST               — serveur SMTP (ex : smtp.gmail.com)
  EMAIL_PORT               — port SMTP (ex : 587)
  EMAIL_USE_TLS            — True ou False
  EMAIL_HOST_USER          — adresse Gmail/SMTP
  EMAIL_HOST_PASSWORD      — mot de passe d'application Gmail
"""

from pathlib import Path
from decouple import config, Csv

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Sécurité de base
# ---------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY")

# En production, DEBUG doit être absent du .env (ou valoir "False").
DEBUG = config("DEBUG", default=False, cast=bool)

# Domaines autorisés — Csv() gère les virgules et les espaces proprement.
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())


# ---------------------------------------------------------------------------
# Sécurité HTTPS
# Ces paramètres s'activent automatiquement quand DEBUG=False (production).
# En développement local (DEBUG=True), ils sont désactivés automatiquement.
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT          = not DEBUG
SESSION_COOKIE_SECURE        = not DEBUG
CSRF_COOKIE_SECURE           = not DEBUG
SECURE_HSTS_SECONDS          = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD          = not DEBUG
X_FRAME_OPTIONS              = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF  = True

# Domaines de confiance pour les requêtes POST (requis derrière un proxy HTTPS).
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())


# ---------------------------------------------------------------------------
# Applications installées
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "events",
]


# ---------------------------------------------------------------------------
# Middlewares
# WhiteNoise (juste après SecurityMiddleware) sert les fichiers statiques
# sans avoir besoin de Nginx — parfait pour PythonAnywhere.
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ---------------------------------------------------------------------------
# URLs & WSGI
# ---------------------------------------------------------------------------
ROOT_URLCONF = "projet_events.urls"
WSGI_APPLICATION = "projet_events.wsgi.application"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Base de données — PostgreSQL
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Base de données
# SQLite en développement, PostgreSQL en production
# ---------------------------------------------------------------------------
#  POUR LES PLANS PAYANTS PYTHONANYWHERE, IL FAUT UTILISER POSTGRESQL.
# if DEBUG:
#     DATABASES = {
#         "default": {
#             "ENGINE": "django.db.backends.sqlite3",
#             "NAME": BASE_DIR / "db.sqlite3",
#         }
#     }
# else:
#     DATABASES = {
#         "default": {
#             "ENGINE": "django.db.backends.postgresql",
#             "NAME":     config("DB_NAME",     default="events_db"),
#             "USER":     config("DB_USER",     default="events_user"),
#             "PASSWORD": config("DB_PASSWORD", default=""),
#             "HOST":     config("DB_HOST",     default="localhost"),
#             "PORT":     config("DB_PORT",     default="5432"),
#             "CONN_MAX_AGE": 600,
#         }
#     }

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
# ---------------------------------------------------------------------------
# Validation des mots de passe
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalisation
# Africa/Abidjan = UTC+0, stable toute l'année (pas de changement d'heure).
# USE_TZ=True stocke tout en UTC en base — correct et recommandé.
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "fr"
TIME_ZONE     = "Africa/Abidjan"
USE_I18N      = True
USE_TZ        = True


# ---------------------------------------------------------------------------
# Fichiers statiques
# STATIC_ROOT = dossier cible de `python manage.py collectstatic`.
# WhiteNoise sert ensuite ces fichiers avec compression et cache long durée.
# ---------------------------------------------------------------------------
STATIC_URL       = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT      = BASE_DIR / "staticfiles"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# ---------------------------------------------------------------------------
# Fichiers media (uploads utilisateurs)
# ---------------------------------------------------------------------------
MEDIA_URL  = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ---------------------------------------------------------------------------
# Configuration email — Gmail SMTP
# En développement, remplacer EMAIL_BACKEND par :
#   "django.core.mail.backends.console.EmailBackend"
# ---------------------------------------------------------------------------
EMAIL_BACKEND       = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST          = config("EMAIL_HOST")
EMAIL_PORT          = config("EMAIL_PORT", cast=int)
EMAIL_USE_TLS       = config("EMAIL_USE_TLS", cast=bool)
EMAIL_HOST_USER     = config("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL  = config("EMAIL_HOST_USER")


# ---------------------------------------------------------------------------
# CinetPay (paiement en ligne — abonnements organisateurs + inscriptions
# payantes). Laisser vide si vous n'utilisez pas encore CinetPay : le moyen
# de paiement CinetPay peut être désactivé depuis /admin/ (MoyenPaiement)
# sans que l'application ne plante.
# ---------------------------------------------------------------------------
CINETPAY_API_KEY = config("CINETPAY_API_KEY", default="")
CINETPAY_SITE_ID = config("CINETPAY_SITE_ID", default="")
CINETPAY_SECRET_KEY = config("CINETPAY_SECRET_KEY", default="")


# ---------------------------------------------------------------------------
# Authentification organisateur
# ---------------------------------------------------------------------------
LOGIN_URL           = "connexion"
LOGIN_REDIRECT_URL  = "dashboard_organisateur"
LOGOUT_REDIRECT_URL = "liste_evenements"


# ---------------------------------------------------------------------------
# Logs — erreurs visibles en production même sans DEBUG
# ---------------------------------------------------------------------------
import os
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "ERROR"),
            "propagate": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Divers
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
