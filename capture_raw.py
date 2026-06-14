#!/usr/bin/env python3
import sys
import os
import json
import logging

# Agregar path
sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')

try:
    import django
    django.setup()
except Exception as e:
    print(f"Error Django setup: {e}")
    sys.exit(1)

from leads_admin.prospector_agent import ProspectorAgent
from datetime import datetime
import requests

# Monkey-patch requests.post para capturar el JSON
original_post = requests.post
captured_json = None

def capturing_post(*args, **kwargs):
    resp = original_post(*args, **kwargs)
    resp.raise_for_status()
    global captured_json
    captured_json = resp.json()
    return resp

requests.post = capturing_post

# Crear agente y llamar
agent = ProspectorAgent()
messages = [{"role": "user", "content": "Hola", "timestamp": datetime.now().isoformat()}]

print("Calling OpenRouter API...")
try:
    response = agent._call_api(messages, model=agent.FREE_MODELS[0])
    print(f"Response: {response}")
except Exception as e:
    print(f"Error during API call: {e}")

# Restaurar
requests.post = original_post

# Imprimir JSON capturado
if captured_json:
    print("\n" + "="*100)
    print("RAW JSON FROM OPENROUTER API:")
    print("="*100)
    print(json.dumps(captured_json, indent=2, ensure_ascii=False))
    print("="*100)
    
    # Análisis de estructura
    print("\nSTRUCTURE ANALYSIS:")
    if 'choices' in captured_json and len(captured_json['choices']) > 0:
        choice = captured_json['choices'][0]
        if 'message' in choice:
            message = choice['message']
            print(f"- Message keys: {list(message.keys())}")
            if 'content' in message:
                content = message['content']
                print(f"- Content length: {len(content)} chars")
                print(f"- First 500 chars of content:\n{content[:500]}")
            # Check for reasoning field
            for key in message:
                if 'reason' in key.lower():
                    print(f"- Found reasoning-like key: {key} = {message[key][:200]}")
    else:
        print("- No 'choices' found in response")
else:
    print("ERROR: No JSON captured")