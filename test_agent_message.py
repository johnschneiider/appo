#!/usr/bin/env python3
"""
Prueba del agente LLM para generar mensaje de prospección.
"""
import os
import sys
import django

sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')
try:
    django.setup()
except Exception as e:
    # Workaround para vitalmix_pro
    import importlib.util
    import tempfile
    # Crear módulo dummy vitalmix_pro.settings si no existe
    spec = importlib.util.find_spec('vitalmix_pro.settings')
    if spec is None:
        # Crear temporalmente
        import site
        site_packages = site.getsitepackages()[0]
        vitalmix_dir = os.path.join(site_packages, 'vitalmix_pro')
        os.makedirs(vitalmix_dir, exist_ok=True)
        open(os.path.join(vitalmix_dir, '__init__.py'), 'w').close()
        with open(os.path.join(vitalmix_dir, 'settings.py'), 'w') as f:
            f.write('DEBUG = False\n')
        # Reintentar
        django.setup()

from leads_admin.prospector_agent import get_prospector_agent

def main():
    print("=== PRUEBA AGENTE LLM ===")
    
    try:
        agent = get_prospector_agent()
        print("✅ Agente inicializado")
    except Exception as e:
        print(f"❌ Error inicializando agente: {e}")
        return False
    
    # Información del lead (de prueba)
    lead_info = {
        'nombre_establecimiento': 'NEGOCIO DE PRUEBA',
        'ciudad': 'Bogotá',
        'telefono': '3117451274',
        'proyecto': 'Prueba WhatsApp',
    }
    
    print(f"Generando mensaje para: {lead_info['nombre_establecimiento']} en {lead_info['ciudad']}")
    
    try:
        mensaje = agent.generar_mensaje_inicial(lead_info)
        if mensaje:
            print(f"✅ Mensaje generado:\n---\n{mensaje}\n---")
            return True
        else:
            print("❌ Agente no generó mensaje")
            return False
    except Exception as e:
        print(f"❌ Error generando mensaje: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)