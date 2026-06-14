#!/usr/bin/env python3
"""
Test de integración del webhook usando el test client de Django.
Ejecutar desde el directorio del proyecto con el entorno virtual activado.
"""
import os
import sys
import django
import json

# Configurar entorno Django
sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')
django.setup()

from django.test import RequestFactory
from leads_admin.views import webhook_evolution

def test_webhook():
    """Simula una petición POST al webhook"""
    factory = RequestFactory()
    
    # Payload similar al de Evolution API
    payload = {
        "event": "MESSAGES_UPSERT",
        "data": {
            "messages": [
                {
                    "key": {
                        "remoteJid": "573117451274@s.whatsapp.net",
                        "fromMe": False
                    },
                    "message": {
                        "conversation": "Hola, quiero saber más sobre Appo"
                    }
                }
            ]
        }
    }
    
    request = factory.post(
        '/leads/webhook/',
        data=json.dumps(payload),
        content_type='application/json',
        HTTP_X_WEBHOOK_EVENT='MESSAGES_UPSERT'
    )
    
    # Llamar a la vista
    from django.core.handlers.wsgi import WSGIRequest
    if not isinstance(request, WSGIRequest):
        # Ajustar para que tenga atributos esperados
        request.META['CONTENT_TYPE'] = 'application/json'
    
    print("Enviando request al webhook...")
    response = webhook_evolution(request)
    
    print(f"Status code: {response.status_code}")
    print(f"Response content: {response.content.decode()}")
    
    # Verificar que no haya errores en la ejecución
    # (los errores se registrarán en los logs)
    return response.status_code == 200

if __name__ == '__main__':
    try:
        success = test_webhook()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error durante la prueba: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)