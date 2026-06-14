import os
import sys
import django

sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')
django.setup()

from leads_admin.models import Lead, LeadConversacion
from leads_admin.prospector_agent import ProspectorAgent
from django.utils import timezone

# Teléfono del lead de prueba
phone = '3117451274'

# Obtener lead
lead = Lead.objects.filter(telefono=phone).first()
if not lead:
    print(f"Lead con teléfono {phone} no encontrado")
    sys.exit(1)

print(f"Lead encontrado: {lead.nombre_establecimiento} (ID: {lead.id})")

# Obtener conversación
conv, created = LeadConversacion.objects.get_or_create(lead=lead)
print(f"Conversación {'creada' if created else 'existente'}. Estado: {conv.estado}")

# Mensaje simulado del usuario
user_message = "Hola, ¿cuánto cuesta el servicio?"
print(f"\n📨 Mensaje entrante simulado: {user_message}")

# Agregar mensaje del usuario a la conversación
conv.mensajes.append({
    'role': 'user',
    'content': user_message,
    'timestamp': timezone.now().isoformat(),
})

# Inicializar agente
agent = ProspectorAgent()

# Generar respuesta
historial = conv.mensajes[:-1]  # todos menos el último (que es el user)
respuesta = agent.generar_respuesta(historial, user_message)

if respuesta:
    print(f"🤖 Respuesta generada por agente: {respuesta}")
    # Agregar respuesta a la conversación
    conv.mensajes.append({
        'role': 'assistant',
        'content': respuesta,
        'timestamp': timezone.now().isoformat(),
    })
    conv.ultimo_contacto = timezone.now()
    conv.save()
    print("✅ Conversación actualizada en base de datos")
else:
    print("❌ El agente no pudo generar respuesta")
    # Fallback
    fallback = "Gracias por tu interés. Te comparto que nuestros planes empiezan desde $49.900 COP al mes. ¿Te gustaría agendar una demo gratuita para mostrarte todas las funcionalidades?"
    print(f"🔄 Fallback: {fallback}")
    conv.mensajes.append({
        'role': 'assistant',
        'content': fallback,
        'timestamp': timezone.now().isoformat(),
    })
    conv.ultimo_contacto = timezone.now()
    conv.save()

# Mostrar historial completo
print("\n📜 Historial de conversación:")
for i, msg in enumerate(conv.mensajes):
    prefix = "👤" if msg['role'] == 'user' else "🤖"
    print(f"{prefix} {msg['role']}: {msg['content']}")