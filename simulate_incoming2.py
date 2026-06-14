import sys
import django
import os

sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')
django.setup()

from leads_admin.models import Lead, LeadConversacion
from leads_admin.prospector_agent import ProspectorAgent
from django.utils import timezone

phone = '3117451274'
lead = Lead.objects.filter(telefono=phone).first()
print(f'Lead: {lead}')

conv, created = LeadConversacion.objects.get_or_create(lead=lead)
print(f'Conversation: {conv}')

user_message = "Hola, ¿cuánto cuesta el servicio?"
print(f'User message: {user_message}')

conv.mensajes.append({
    'role': 'user',
    'content': user_message,
    'timestamp': timezone.now().isoformat(),
})

agent = ProspectorAgent()
historial = conv.mensajes[:-1]
respuesta = agent.generar_respuesta(historial, user_message)
print(f'Agent response: {respuesta}')

if respuesta:
    conv.mensajes.append({
        'role': 'assistant',
        'content': respuesta,
        'timestamp': timezone.now().isoformat(),
    })
else:
    conv.mensajes.append({
        'role': 'assistant',
        'content': 'Gracias por tu interés. Nuestros planes empiezan desde $49.900 COP al mes.',
        'timestamp': timezone.now().isoformat(),
    })

conv.ultimo_contacto = timezone.now()
conv.save()
print('Conversation saved')