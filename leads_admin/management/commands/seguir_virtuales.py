"""
Management command: seguimiento automático de leads virtuales (inbound WhatsApp).
Detecta conversaciones estancadas y envía follow-ups para cerrar al lead.
Respeta horario laboral: Lun–Sáb 8-18, Dom 9-17 (hora Colombia).
"""
import time
import random
import requests
import logging
import pytz
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from leads_admin.models import ChatWhatsApp, MensajeWhatsApp
from leads_admin.prospector_agent import get_prospector_agent

logger = logging.getLogger(__name__)

WHATSAPP_SERVICE = "http://localhost:8081/message/sendText/APPO_CRM"
MAX_FOLLOWUPS = 1  # Máximo de follow-ups consecutivos antes de rendirse

# Etapas de follow-up (tiempo desde último mensaje del bot sin respuesta)
# Solo 1 etapa: recordatorio_30min. Si no responde, no insistir más.
FOLLOWUP_STAGES = [
    {
        'name': 'recordatorio_30min',
        'min_wait': timedelta(minutes=15),
        'max_wait': timedelta(hours=48),
        'message': (
            "¿Sigues por ahí? 😊 Cualquier duda sobre Appo dime y te ayudo "
            "sin compromiso. La capa gratis es para siempre, sin tarjeta."
        ),
    },
]


class Command(BaseCommand):
    help = 'Envía follow-ups a leads virtuales que dejaron de responder'

    def _es_hora_laboral(self) -> bool:
        """Retorna True si es horario laboral. Lun–Sáb 8:00–18:00, Dom 9:00–17:00."""
        try:
            tz_col = pytz.timezone('America/Bogota')
        except:
            tz_col = pytz.timezone('Etc/GMT+5')
        ahora = timezone.now().astimezone(tz_col)
        hora = ahora.hour
        dia = ahora.weekday()
        if dia == 6:  # Domingo
            return 9 <= hora < 17
        return 8 <= hora < 18

    def handle(self, *args, **options):
        # Respetar horario laboral
        if not self._es_hora_laboral():
            self.stdout.write('Fuera de horario laboral. Saltando.')
            return
        
        # Inicializar agente LLM
        try:
            agent = get_prospector_agent()
        except Exception as e:
            self.stderr.write(f'Error al inicializar agente LLM: {e}')
            return
        
        self.stdout.write('🔍 Buscando conversaciones virtuales estancadas...')
        ahora = timezone.now()
        
        # Obtener todos los chats virtuales (no grupos)
        chats = ChatWhatsApp.objects.using('leads_db').filter(is_group=False)
        
        # ── ANTI-DOBLE-FOLLOWUP ──
        # Los leads REALES (registrados en tabla Lead) los maneja prospectar_leads +
        # procesar_lead (pipeline LeadConversacion). Si seguir_virtuales también les
        # escribe, el lead recibe DOBLE follow-up. Construimos un set de teléfonos de
        # leads reales para saltarlos aquí.
        from leads_admin.models import Lead as _Lead
        telefonos_lead_real = set()
        for _t in _Lead.objects.using('leads_db').values_list('telefono', flat=True):
            if _t:
                tt = _t.replace('+', '').replace(' ', '')
                telefonos_lead_real.add(tt)
                telefonos_lead_real.add(tt[2:] if tt.startswith('57') else '57' + tt)
        
        seguimientos_enviados = 0
        
        for chat in chats:
            try:
                # Saltar chats que pertenecen a un lead real (los maneja prospectar_leads)
                ph_chat = (chat.phone or '').replace('+', '').replace(' ', '')
                if ph_chat and ph_chat in telefonos_lead_real:
                    continue
                # Obtener últimos mensajes ordenados por timestamp
                mensajes = list(MensajeWhatsApp.objects.using('leads_db')
                    .filter(chat=chat)
                    .order_by('-timestamp')[:20])
                
                if not mensajes:
                    continue
                
                # El más reciente
                ultimo = mensajes[0]
                
                # Solo hacer follow-up si el ÚLTIMO mensaje es del BOT (from_me=True)
                # Si el último es del lead, significa que estamos esperando respuesta DEL BOT
                if not ultimo.from_me:
                    continue
                
                # Si el último bot fue un CRUCE DE BARRERA de auto-reply (marcador invisible),
                # no insistir: ya lanzamos el anzuelo, esperamos a que conteste una persona.
                if '\u200b' in (ultimo.message_text or ''):
                    continue
                
                # Contar cuántos mensajes consecutivos del bot hay al final
                consecutive_bot = 0
                for m in mensajes:
                    if m.from_me:
                        consecutive_bot += 1
                    else:
                        break
                
                # Si ya enviamos demasiados follow-ups, saltar
                if consecutive_bot > MAX_FOLLOWUPS:
                    continue
                
                # El índice de follow-up: cuántos mensajes del bot sin respuesta
                followup_index = consecutive_bot - 1  # 1er follow-up = índice 0
                
                if followup_index >= len(FOLLOWUP_STAGES):
                    continue
                
                stage = FOLLOWUP_STAGES[followup_index]
                tiempo_desde_ultimo = ahora - ultimo.timestamp
                
                # Verificar si ya pasó el tiempo mínimo para esta etapa
                if tiempo_desde_ultimo < stage['min_wait']:
                    continue
                
                # Verificar si todavía está dentro del rango (no pasó max_wait sin follow-up)
                if tiempo_desde_ultimo > stage['max_wait']:
                    continue
                
                # ── Enviar follow-up (LLM dinámico) ──
                phone = chat.phone or ''
                self._enviar_followup(chat, phone, stage, followup_index, agent, mensajes)
                seguimientos_enviados += 1
                
                # Pequeña pausa entre envíos
                time.sleep(random.uniform(1, 3))
                
            except Exception as e:
                logger.error(f"Error procesando chat {chat.chat_id}: {e}")
                self.stdout.write(self.style.WARNING(f"  ⚠️ Error: {e}"))
        
        self.stdout.write(f"✅ {seguimientos_enviados} follow-ups enviados.")
    
    def _generar_msj_virtual(self, agent, mensajes_qs, stage_name, consecutive_bot):
        """Genera follow-up vía LLM para leads virtuales. Fallback a estático si falla."""
        # Convertir QuerySet a lista y ordenar cronológico
        historial = list(mensajes_qs)
        historial.sort(key=lambda m: m.timestamp)  # cronológico
        
        llm_respuesta = agent.generar_followup_virtual(historial, stage_name, consecutive_bot)
        if llm_respuesta:
            return llm_respuesta
        return None
    
    def _enviar_followup(self, chat, phone, stage, index, agent=None, mensajes_qs=None):
        """Envía un mensaje de follow-up y lo registra en el historial.
        Si hay agente e historial, genera mensaje vía LLM; si no, usa estático."""
        # Generar mensaje: priorizar LLM, fallback a estático
        if agent and mensajes_qs:
            llm_msg = self._generar_msj_virtual(agent, mensajes_qs, stage['name'], index + 1)
            mensaje = llm_msg if llm_msg else stage['message']
            if llm_msg:
                self.stdout.write(f"  🤖 Mensaje generado por IA")
            else:
                self.stdout.write(f"  📋 Usando mensaje estático (fallback)")
        else:
            mensaje = stage['message']
        
        numero = (phone or chat.phone or '').replace('+', '').replace(' ', '')
        
        # Validación anti-números corruptos: solo números colombianos válidos
        import re
        if not re.match(r'^3\d{9}$', numero) and not re.match(r'^573\d{9}$', numero):
            logger.warning(f'[SEGUIR] Número inválido detectado: {numero} (chat {chat.chat_id}) - saltando')
            self.stdout.write(f"  ⚠️ Número inválido {numero} - saltando")
            return
        
        if not numero.startswith('57'):
            numero = '57' + numero
        
        payload = {
            "number": f"{numero}@c.us",
            "textMessage": {"text": mensaje}
        }
        
        try:
            self.stdout.write(f"  📱 Follow-up {index+1}/{MAX_FOLLOWUPS} → {numero}: {mensaje[:60]}...")
            r = requests.post(
                WHATSAPP_SERVICE,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=20
            )
            r.raise_for_status()
            
            # Guardar en historial
            import uuid
            MensajeWhatsApp.objects.using('leads_db').create(
                chat=chat,
                message_key=f'fw_{chat.chat_id}_{uuid.uuid4().hex[:12]}',
                message_text=mensaje,
                from_me=True,
                timestamp=timezone.now()
            )
            
            self.stdout.write(self.style.SUCCESS(f"  ✅ Enviado"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  ⚠️ Error: {e}"))
