"""Configuration WSGI pour le déploiement en production."""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "projet_events.settings")

application = get_wsgi_application()
