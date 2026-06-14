#!/usr/bin/env python3
"""
Test del webhook de Evolution API simulando un mensaje entrante.
"""
import os
import sys
import json
import requests
import time

sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')

# URL del webhook (local)
WEBHOOK_URL = 'http://127.0.0.1:8888/leads_admin/webhook/'

# Payload simulado de un mensaje entrante (basado en el código de views.py)
payload = {
    "event": "MESSAGES_UPSERT",
    "data": {
        "messages": [
            {
                "key": {
                    "remoteJid": "573117451274@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {
                    "conversation": "Hola, me interesa saber más sobre Appo"
                },
                "messageTimestamp": int(time.time())
            }
        ]
    }
}

print(f"Enviando webhook simulado a {WEBHOOK_URL}")
print(f"Payload: {json.dumps(payload, indent=2)}")

try:
    response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    print(f"\nRespuesta HTTP: {response.status_code}")
    print(f"Contenido: {response.text}")
except Exception as e:
    print(f"Error: {e}")

# También probar con un formato alternativo
print("\n" + "="*50 + "\n")

# Segundo test con formato diferente (el que parece estar en el código)
payload2 = {
    "messages": [
        {
            "key": {
                "remoteJid": "573117451274@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {
                "conversation": "¿Cuánto cuesta?"
            }
        }
    ]
}

print(f"Enviando segundo webhook (formato alternativo)...")
try:
    response2 = requests.post(WEBHOOK_URL, json=payload2, timeout=10)
    print(f"Respuesta HTTP: {response2.status_code}")
    print(f"Contenido: {response2.text}")
except Exception as e:
    print(f"Error: {e}")