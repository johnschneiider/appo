#!/usr/bin/env python3
"""
Test del webhook de Evolution API en la ruta correcta: /leads/webhook/
"""
import os
import sys
import json
import requests
import time

sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')

# URL del webhook (local)
WEBHOOK_URL = 'http://127.0.0.1:8888/leads/webhook/'

# Payload simulado de un mensaje entrante (basado en el código de views.py)
# Formato que espera el código: payload.get('messages', [])
payload = {
    "messages": [
        {
            "key": {
                "remoteJid": "573117451274@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {
                "conversation": "Hola, quiero saber el precio de Appo"
            }
        }
    ]
}

print(f"Enviando webhook simulado a {WEBHOOK_URL}")
print(f"Payload: {json.dumps(payload, indent=2)}")

try:
    response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    print(f"\nRespuesta HTTP: {response.status_code}")
    print(f"Contenido: {response.text}")
except Exception as e:
    print(f"Error: {e}")

# También probar con el primer formato (con 'event' y 'data')
payload2 = {
    "event": "MESSAGES_UPSERT",
    "data": {
        "messages": [
            {
                "key": {
                    "remoteJid": "573117451274@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {
                    "conversation": "¿Cuánto cuesta el plan Pro?"
                }
            }
        ]
    }
}

print("\n" + "="*50 + "\n")
print(f"Enviando segundo webhook con formato event/data...")
try:
    response2 = requests.post(WEBHOOK_URL, json=payload2, timeout=10)
    print(f"Respuesta HTTP: {response2.status_code}")
    print(f"Contenido: {response2.text}")
except Exception as e:
    print(f"Error: {e}")