#!/usr/bin/env python3
"""
Prueba directa de Twilio WhatsApp cargando .env
"""
import os
import sys
from pathlib import Path

# Cargar .env manualmente
env_path = Path('/var/www/appo.com.co/.env')
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip()
                # Remover comillas
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                os.environ.setdefault(key, val)

# Ahora las variables deben estar en os.environ
required_vars = ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_NUMBER']
for var in required_vars:
    if not os.getenv(var):
        print(f"❌ Variable faltante: {var}")
        sys.exit(1)

# Importar Twilio después de establecer credenciales
from twilio.rest import Client

def main():
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    whatsapp_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
    template_sid = os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE')
    template_var_key = os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE_VAR_KEY', '1')
    
    target = '+573117451274'
    
    print("=== PRUEBA DIRECTA TWILIO ===")
    print(f"De: {whatsapp_number}")
    print(f"Para: {target}")
    print(f"Template SID: {template_sid}")
    print()
    
    client = Client(account_sid, auth_token)
    
    # INTENTO 1: Mensaje simple (ventana 24h)
    print("1. Enviando mensaje simple...")
    try:
        message = client.messages.create(
            from_=f'whatsapp:{whatsapp_number}',
            body='🔧 PRUEBA TÉCNICA APPO\n\nEste es un mensaje de prueba del sistema de prospección automática de leads.\n\nSi recibes este mensaje, el sistema funciona correctamente.\n\nPor favor ignora este mensaje.',
            to=f'whatsapp:{target}'
        )
        print(f"   ✅ Éxito! SID: {message.sid}")
        print(f"   Estado: {message.status}")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # INTENTO 2: Template (fuera de ventana 24h)
    if template_sid:
        print("\n2. Enviando template...")
        import json
        try:
            message = client.messages.create(
                from_=f'whatsapp:{whatsapp_number}',
                content_sid=template_sid,
                content_variables=json.dumps({
                    template_var_key: 'Este es un mensaje de prueba del sistema de prospección automática de leads APPO. Por favor ignora este mensaje.'
                }),
                to=f'whatsapp:{target}'
            )
            print(f"   ✅ Template enviado! SID: {message.sid}")
            print(f"   Estado: {message.status}")
            return True
        except Exception as e:
            print(f"   ❌ Error template: {e}")
    
    # INTENTO 3: Usar API diferente (sin content_sid)
    print("\n3. Probando método alternativo...")
    try:
        message = client.messages.create(
            from_=f'whatsapp:{whatsapp_number}',
            to=f'whatsapp:{target}',
            body='Hola, esto es una prueba de APPO. Por favor ignora.'
        )
        print(f"   ✅ Alternativo funcionó! SID: {message.sid}")
        return True
    except Exception as e:
        print(f"   ❌ Error alternativo: {e}")
    
    print("\n⚠️  Todos los intentos fallaron.")
    print("   - Verifica que el número de Twilio tenga WhatsApp habilitado")
    print("   - Verifica que el template esté aprobado")
    print("   - Verifica que el número destino sea válido")
    print("   - El número puede no tener sesión activa en 24h")
    return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)