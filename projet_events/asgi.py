"""Configuration ASGI (utile si déploiement asynchrone plus tard)."""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "projet_events.settings")

application = get_asgi_application()
