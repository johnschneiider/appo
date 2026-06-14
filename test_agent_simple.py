import os
import sys
sys.path.insert(0, '/var/www/appo.com.co')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')
import django
django.setup()

from leads_admin.prospector_agent import ProspectorAgent

agent = ProspectorAgent()
lead_info = {
    'nombre_establecimiento': 'Peluquería Test',
    'ciudad': 'Medellín',
    'telefono': '3001234567',
}
mensaje = agent.generar_mensaje_inicial(lead_info)
print(f'Mensaje generado: {mensaje}')

# Probar respuesta
historial = []
respuesta = agent.generar_respuesta(historial, '¿Cuánto cuesta?')
print(f'Respuesta: {respuesta}')