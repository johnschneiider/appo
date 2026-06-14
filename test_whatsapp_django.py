#!/usr/bin/env python3
"""
Prueba de envío de WhatsApp usando Django settings.
"""
import os
import sys
import django

# Configurar Django
sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')
django.setup()

from django.conf import settings
import json

def main():
    print("=== PRUEBA WHATSAPP VÍA DJANGO ===")
    
    # Obtener config de Twilio desde settings
    try:
        from django.conf import settings
        twilio_config = {
            'account_sid': settings.TWILIO_ACCOUNT_SID,
            'auth_token': settings.TWILIO_AUTH_TOKEN,
            'whatsapp_number': settings.TWILIO_WHATSAPP_NUMBER,
            'template_texto_libre': settings.TWILIO_TEMPLATE_TEXTO_LIBRE,
            'template_var_key': settings.TWILIO_TEMPLATE_TEXTO_LIBRE_VAR_KEY,
            'enabled': settings.TWILIO_WHATSAPP_ENABLED,
        }
    except AttributeError as e:
        print(f"❌ Configuración faltante en settings: {e}")
        # Intentar desde entorno
        twilio_config = {
            'account_sid': os.getenv('TWILIO_ACCOUNT_SID'),
            'auth_token': os.getenv('TWILIO_AUTH_TOKEN'),
            'whatsapp_number': os.getenv('TWILIO_WHATSAPP_NUMBER'),
            'template_texto_libre': os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE'),
            'template_var_key': os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE_VAR_KEY', '1'),
            'enabled': os.getenv('TWILIO_WHATSAPP_ENABLED', 'TRUE'),
        }
    
    print("Configuración Twilio:")
    for key, val in twilio_config.items():
        if key == 'auth_token' and val:
            print(f"  {key}: {'***' + val[-4:] if val else 'None'}")
        else:
            print(f"  {key}: {val}")
    
    if not all([twilio_config['account_sid'], twilio_config['auth_token'], twilio_config['whatsapp_number']]):
        print("❌ Credenciales Twilio incompletas")
        return False
    
    if twilio_config['enabled'] not in ['TRUE', 'True', 'true', True]:
        print("❌ WhatsApp no está habilitado")
        return False
    
    # Número de prueba
    target = '+573117451274'
    
    print(f"\nObjetivo: {target}")
    
    # Usar el servicio existente de WhatsApp
    try:
        from clientes.whatsapp_service import whatsapp_service
        
        print("\nUsando WhatsAppService...")
        if not whatsapp_service.is_enabled():
            print("❌ WhatsAppService reporta no habilitado")
            # Continuar de todos modos
        
        # Mensaje de prueba
        mensaje = "🔧 PRUEBA TÉCNICA APPO\n\nEste es un mensaje de prueba del sistema de prospección automática de leads.\n\nSi recibes este mensaje, el sistema funciona correctamente.\n\nPor favor ignora este mensaje."
        
        print(f"Enviando mensaje personalizado...")
        success = whatsapp_service.send_custom_message('3117451274', mensaje)
        
        if success:
            print("✅ WhatsAppService envió mensaje exitosamente")
            return True
        else:
            print("❌ WhatsAppService falló con mensaje personalizado")
            
            # Intentar con template
            print("Intentando con template 'texto_libre'...")
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": mensaje}
                    ]
                }
            ]
            success_template = whatsapp_service.send_template_message(
                '3117451274',
                'texto_libre',
                components=components
            )
            if success_template:
                print("✅ Template enviado exitosamente")
                return True
            else:
                print("❌ También falló el template")
                return False
                
    except Exception as e:
        print(f"❌ Error usando WhatsAppService: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)