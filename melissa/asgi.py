"""
ASGI config for melissa project.
"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')

import django
django.setup()

# Ahora sí importar todo (Django ya está listo)
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import re_path

# Chat interno
from chat.consumers import ChatConsumer
# CRM WhatsApp
from leads_admin.consumers import CRMConsumer

websocket_urlpatterns = [
    re_path(r'^ws/chat/$', ChatConsumer.as_asgi()),
    re_path(r'^ws/crm/$', CRMConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
