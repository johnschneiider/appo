#!/usr/bin/env python3
"""
Prueba de envío de WhatsApp usando Twilio.
Ejecutar con: cd /var/www/appo.com.co && venv/bin/python test_whatsapp_twilio.py
"""
import os
import json
import sys
from twilio.rest import Client

# Número de prueba Colombia
TARGET_PHONE = '+573117451274'  # 3117451274 con código país

def main():
    # Obtener credenciales de entorno
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    whatsapp_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
    template_sid = os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE')
    template_var_key = os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE_VAR_KEY', '1')
    
    print("=== PRUEBA DE WHATSAPP CON TWILIO ===")
    print(f"Desde: {whatsapp_number}")
    print(f"Hacia: {TARGET_PHONE}")
    print(f"Template SID: {template_sid}")
    print(f"Variable key: {template_var_key}")
    print()
    
    if not all([account_sid, auth_token, whatsapp_number]):
        print("❌ Credenciales Twilio incompletas en entorno")
        sys.exit(1)
    
    try:
        client = Client(account_sid, auth_token)
    except Exception as e:
        print(f"❌ Error inicializando cliente Twilio: {e}")
        sys.exit(1)
    
    # PRUEBA 1: Mensaje simple (solo funciona dentro de ventana de 24h)
    print("1. Probando mensaje simple (texto libre)...")
    try:
        message = client.messages.create(
            from_=f'whatsapp:{whatsapp_number}',
            body='🔧 PRUEBA TÉCNICA APPO\n\nEste es un mensaje de prueba del sistema de prospección automática de leads.\n\nSi recibes este mensaje, el sistema funciona correctamente.\n\nPor favor ignora este mensaje.',
            to=f'whatsapp:{TARGET_PHONE}'
        )
        print(f"   ✅ Mensaje simple enviado!")
        print(f"   SID: {message.sid}")
        print(f"   Estado: {message.status}")
        print(f"   Precio: {message.price if hasattr(message, 'price') else 'N/A'}")
        return True
    except Exception as e:
        print(f"   ❌ Error mensaje simple: {e}")
    
    # PRUEBA 2: Template (requerido fuera de ventana de 24h)
    print("\n2. Probando con template pre-aprobado...")
    if not template_sid:
        print("   ❌ No hay template configurado")
        return False
    
    try:
        # Según documentación de Twilio para templates
        # https://www.twilio.com/docs/whatsapp/twilio-cli/whatsapp-templates
        message = client.messages.create(
            from_=f'whatsapp:{whatsapp_number}',
            content_sid=template_sid,
            content_variables=json.dumps({
                template_var_key: 'Este es un mensaje de prueba del sistema de prospección automática de leads APPO. Por favor ignora este mensaje.'
            }),
            to=f'whatsapp:{TARGET_PHONE}'
        )
        print(f"   ✅ Template enviado!")
        print(f"   SID: {message.sid}")
        print(f"   Estado: {message.status}")
        return True
    except Exception as e:
        print(f"   ❌ Error con template: {e}")
    
    # PRUEBA 3: Usar Messaging API con otro enfoque
    print("\n3. Probando con método alternativo...")
    try:
        # Algunos templates tienen nombre en lugar de SID
        message = client.messages.create(
            from_=f'whatsapp:{whatsapp_number}',
            to=f'whatsapp:{TARGET_PHONE}',
            body='Hola, esto es una prueba de APPO. Por favor ignora.'
        )
        print(f"   ✅ Método alternativo funcionó!")
        print(f"   SID: {message.sid}")
        return True
    except Exception as e:
        print(f"   ❌ Error método alternativo: {e}")
    
    print("\n⚠️  Todas las pruebas fallaron. Posibles causas:")
    print("   - Template no aprobado o no existe")
    print("   - Número no tiene sesión activa en últimas 24h")
    print("   - Credenciales incorrectas")
    print("   - Número de Twilio no configurado para WhatsApp")
    print("   - Restricciones de política de WhatsApp")
    return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)