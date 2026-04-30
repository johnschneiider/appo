import os
import logging
import requests
import concurrent.futures
import random
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from leads_admin.models import Lead, LeadConversacion
from leads_admin.prospector_agent import get_prospector_agent, procesar_lead_inicial, procesar_lead
from datetime import datetime, timedelta
import pytz
import re

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Prospecta leads vía WhatsApp usando LLM y Twilio'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Simula el envío sin enviar mensajes reales',
        )
        parser.add_argument(
            '--ignore-hours',
            action='store_true',
            dest='ignore_hours',
            help='Ignora la restricción de horario laboral (para pruebas)',
        )
        parser.add_argument(
            '--test-mode',
            action='store_true',
            dest='test_mode',
            help='Modo prueba: ignora horas y usa template de Twilio',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Limitar número de leads a procesar (0 = todos)',
        )
    
    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        ignore_hours = options.get('ignore_hours', False)
        test_mode = options.get('test_mode', False)
        
        mode_desc = []
        if dry_run:
            mode_desc.append('DRY RUN')
        if ignore_hours:
            mode_desc.append('IGNORE HOURS')
        if test_mode:
            mode_desc.append('TEST MODE')
        
        self.stdout.write(f"Iniciando prospección de leads ({' | '.join(mode_desc) if mode_desc else 'PRODUCCIÓN'})")
        
        # 1. Verificar hora laboral (8 AM–8 PM, hora Colombia)
        if not ignore_hours and not self._es_hora_laboral():
            self.stdout.write("Fuera de horario laboral (8 AM–8 PM). Abortando.")
            return
        
        # Límite de 10 leads por día (24 horas)
        contactados_24h = self._leads_contactados_ultimas_24h()
        if contactados_24h >= 10:
            logger.info(f"Límite diario alcanzado: {contactados_24h}/10 leads contactados en últimas 24h")
            return
        
        # 2. Obtener agentes
        try:
            agent = get_prospector_agent()
        except Exception as e:
            self.stderr.write(f"Error al inicializar agente LLM: {e}")
            return
        
        # 3. Seleccionar leads para contactar
        conversaciones_pendientes = self._obtener_leads_pendientes()
        self.stdout.write(f"Conversaciones pendientes encontradas: {len(conversaciones_pendientes)}")
        
        # Aplicar límite si se especificó
        limit = options.get('limit', 0)
        if limit > 0 and len(conversaciones_pendientes) > limit:
            self.stdout.write(f"Aplicando límite de {limit} leads")
            conversaciones_pendientes = conversaciones_pendientes[:limit]
        
        if not conversaciones_pendientes:
            self.stdout.write("No hay leads pendientes. Nada que hacer.")
            return
        
        # 4. Función helper para procesar una conversación en un thread
        def procesar_conversacion_thread(item):
            """Procesa una conversación (lead + etapa), captura excepciones"""
            lead = item['lead']
            conversacion = item.get('conversacion')
            etapa = item.get('etapa', 'initial')
            try:
                self._procesar_lead(lead, conversacion, etapa, agent, dry_run)
                return (True, lead.id)
            except Exception as e:
                logger.error(f"Error procesando lead {lead.id} (etapa {etapa}): {e}")
                return (False, lead.id, str(e))
        
        # 5. Procesar conversaciones en paralelo (máximo 3 workers simultáneos)
        enviados = 0
        errores = 0
        max_workers = min(3, len(conversaciones_pendientes))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Mapear cada conversación a un futuro
            future_to_item = {executor.submit(procesar_conversacion_thread, item): item 
                              for item in conversaciones_pendientes}
            
            # Recoger resultados a medida que completan
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                lead = item['lead']
                etapa = item.get('etapa', 'initial')
                try:
                    result = future.result()
                    if result[0]:  # éxito
                        enviados += 1
                        self.stdout.write(f"  ✅ Lead {lead.id} procesado exitosamente (etapa: {etapa})")
                    else:
                        errores += 1
                        error_msg = result[2] if len(result) > 2 else "Error desconocido"
                        self.stderr.write(f"  ❌ Error con lead {lead.id} (etapa {etapa}): {error_msg}")
                except Exception as exc:
                    logger.error(f"Excepción inesperada procesando lead {lead.id}: {exc}")
                    errores += 1
                    self.stderr.write(f"  ❌ Error crítico con lead {lead.id}: {exc}")
        
        # 6. Resumen
        self.stdout.write(
            f"Proceso completado. "
            f"Enviados: {enviados}, Errores: {errores}, "
            f"Workers: {max_workers}, "
            f"Dry run: {dry_run}"
        )
    
    def _es_hora_laboral(self) -> bool:
        """Retorna True si es horario laboral (8 AM–6 PM, hora Colombia, lunes a viernes)."""
        # Zona horaria de Colombia (Bogotá)
        try:
            tz_col = pytz.timezone('America/Bogota')
        except:
            # Fallback a UTC-5
            tz_col = pytz.timezone('Etc/GMT+5')
        
        ahora = timezone.now().astimezone(tz_col)
        hora_actual = ahora.hour
        dia_semana = ahora.weekday()  # 0 = lunes, 6 = domingo
        
        # Lunes a viernes (0-4), horario 8 AM – 6 PM
        return 0 <= dia_semana <= 4 and 8 <= hora_actual < 18
    
    def _esperar_como_humano(self):
        """Pausa aleatoria entre 90 y 240 segundos para evitar baneo de Meta."""
        delay = random.randint(90, 240)
        self.stdout.write(f"  ⏳ Esperando {delay}s antes del siguiente envío...")
        time.sleep(delay)
    
    def _leads_contactados_ultimas_24h(self) -> int:
        """Retorna cuántos leads han sido contactados en las últimas 24 horas."""
        desde = timezone.now() - timedelta(hours=24)
        return LeadConversacion.objects.filter(
            ultimo_contacto__gte=desde
        ).count()
    
    def _obtener_leads_pendientes(self):
        """
        Retorna queryset de LeadConversacion que necesitan acción.
        Tres categorías:
        1. Leads nuevos (sin conversación) con estado 'Nuevo'/'pendiente'.
        2. Conversaciones en estado 'contactado' que requieren follow‑up 24h.
        3. Conversaciones en estado 'followup_24h' que requieren follow‑up 48h.
        Se excluyen conversaciones contactadas en las últimas 24h (para evitar spam).
        """
        ahora = timezone.now()
        hace_24h = ahora - timedelta(hours=24)
        hace_72h = ahora - timedelta(hours=72)  # contactado hace +24h = 24+48 = 72h para follow‑up 48h
        
        # Leads nuevos (sin conversación)
        leads_nuevos = Lead.objects.filter(
            estado__in=['Nuevo', 'pendiente', 'Pendiente'],
        )
        # Excluir leads que ya tienen conversación
        leads_con_conversacion = LeadConversacion.objects.values_list('lead_id', flat=True)
        leads_nuevos = leads_nuevos.exclude(id__in=leads_con_conversacion)
        
        # Filtrar manualmente los teléfonos válidos y construir lista de conversaciones
        conversaciones = []
        for lead in leads_nuevos:
            tel_clean = (lead.telefono or '').replace('+', '').replace(' ', '')
            if re.match(r'^\d{8,15}$', tel_clean):
                # Objeto dict con estructura similar a LeadConversacion pero sin pk
                conversaciones.append({
                    'lead': lead,
                    'conversacion': None,  # será creada
                    'etapa': 'initial'
                })
        
        # Conversaciones que necesitan follow‑up 24h
        # Estado 'contactado', último contacto hace más de 24h, pero menos de 72h (porque después va a follow‑up 48h)
        conv_followup_24h = LeadConversacion.objects.filter(
            estado='contactado',
            ultimo_contacto__lt=hace_24h,      # contacto hace más de 24h
            ultimo_contacto__gte=hace_72h,     # contacto hace menos de 72h
            lead__telefono__regex=r'^\d{8,15}$',
        )
        
        # Conversaciones que necesitan follow‑up 48h
        # Estado 'followup_24h', último contacto hace más de 48h (desde el follow‑up 24h)
        hace_48h = ahora - timedelta(hours=48)
        conv_followup_48h = LeadConversacion.objects.filter(
            estado='followup_24h',
            ultimo_contacto__lte=hace_48h,
            lead__telefono__regex=r'^\d{8,15}$',
        )
        
        # Conversaciones existentes para follow‑up
        for conv in conv_followup_24h:
            conversaciones.append({
                'lead': conv.lead,
                'conversacion': conv,
                'etapa': 'followup_24h'
            })
        
        for conv in conv_followup_48h:
            conversaciones.append({
                'lead': conv.lead,
                'conversacion': conv,
                'etapa': 'followup_48h'
            })
        
        # Ordenar por prioridad descendente del lead, luego fecha de ingreso
        conversaciones.sort(key=lambda x: (-x['lead'].prioridad, x['lead'].fecha_ingreso or datetime.min))
        return conversaciones
    
    def _procesar_lead(self, lead, conversacion, etapa: str, agent, dry_run: bool):
        """
        Procesa un lead según su etapa.
        etapas: 'initial', 'followup_24h', 'followup_48h'
        """
        self.stdout.write(f"Procesando lead {lead.id}: {lead.nombre_establecimiento} (etapa: {etapa})")
        
        # 1. Generar mensaje según etapa
        if etapa == 'initial':
            # Usar nuevo sistema de partes
            partes = procesar_lead_inicial(lead.id)
            mensaje_completo = "\n\n".join(partes)
        else:
            # Para followups, usar la lógica existente pero mantener formato de partes
            if etapa == 'followup_24h':
                mensaje = self._generar_mensaje_followup_24h(lead, conversacion, agent)
            elif etapa == 'followup_48h':
                mensaje = self._generar_mensaje_followup_48h(lead, conversacion, agent)
            else:
                raise ValueError(f"Etapa desconocida: {etapa}")
            # Dividir en partes por párrafos dobles
            partes = [p.strip() for p in mensaje.split('\n\n') if p.strip()]
            mensaje_completo = mensaje
        
        if not partes:
            raise ValueError(f"El agente no pudo generar mensaje para etapa {etapa}")
        
        self.stdout.write(f"  Partes generadas: {len(partes)}")
        
        # 2. Enviar vía Evolution API (si no es dry-run)
        if not dry_run:
            for i, parte in enumerate(partes):
                exito = self._enviar_whatsapp(lead.telefono, parte)
                if not exito:
                    raise ValueError(f"Error al enviar WhatsApp parte {i+1}")
                self.stdout.write(f"  ✅ Parte {i+1}/{len(partes)} enviada")
                if i < len(partes) - 1:
                    delay = random.uniform(2, 4)
                    time.sleep(delay)
            self._esperar_como_humano()
        else:
            self.stdout.write(f"  🧪 (Dry-run) Simulando envío de {len(partes)} partes a " + lead.telefono)
            for parte in partes:
                self.stdout.write(f"    🧪 Parte: {parte[:60]}...")
        
        # 3. Registrar conversación en base de datos (solo si no es initial, porque procesar_lead_inicial ya guardó)
        ahora = timezone.now()
        
        if etapa == 'initial':
            # La conversación ya fue creada/actualizada por procesar_lead_inicial
            # Solo actualizar estado del lead
            lead.estado = 'Contactado'
            lead.save()
            self.stdout.write(f"  🔄 Lead marcado como Contactado")
        else:
            # Actualizar conversación existente con mensaje completo
            conversacion.mensajes.append({
                'role': 'assistant',
                'content': mensaje_completo,
                'timestamp': ahora.isoformat(),
            })
            # Determinar nuevo estado según etapa
            if etapa == 'followup_24h':
                nuevo_estado = 'followup_24h'
            elif etapa == 'followup_48h':
                nuevo_estado = 'followup_48h'
            else:
                nuevo_estado = 'contactado'
            conversacion.estado = nuevo_estado
            conversacion.ultimo_contacto = ahora
            conversacion.save()
            self.stdout.write(f"  🔄 Conversación actualizada (nuevo estado: {nuevo_estado})")
            # Actualizar estado del lead
            lead.estado = 'Contactado'
            lead.save()
        
        self.stdout.write(f"  ✅ Lead actualizado y conversación registrada")
    
    def _generar_mensaje_inicial(self, lead, agent):
        """Genera el primer mensaje de prospección."""
        lead_info = {
            'nombre_establecimiento': lead.nombre_establecimiento,
            'ciudad': lead.ciudad,
            'telefono': lead.telefono,
            'proyecto': lead.proyecto,
        }
        return agent.generar_mensaje_inicial(lead_info)
    
    def _generar_mensaje_followup_24h(self, lead, conversacion, agent):
        """Genera mensaje de follow‑up después de 24h sin respuesta."""
        # Usar el historial de conversación para contextualizar
        historial = conversacion.mensajes if conversacion and conversacion.mensajes else []
        # Extraer último mensaje enviado por nosotros (si hay)
        ultimo_mensaje_asistente = None
        for msg in reversed(historial):
            if msg.get('role') == 'assistant':
                ultimo_mensaje_asistente = msg.get('content', '')
                break
        
        prompt = f"""Eres un asistente comercial de APPO. Hace 24h enviaste este mensaje a {lead.nombre_establecimiento} en {lead.ciudad}:

"{ultimo_mensaje_asistente[:200] if ultimo_mensaje_asistente else 'Saludo inicial'}"

El lead no ha respondido. Escribe un mensaje de follow‑up cordial que:
1. Pregunte si recibieron el mensaje anterior.
2. Reitere brevemente el valor de APPO (gestión de reservas, clientes, pagos).
3. Ofrezca una demo gratuita sin compromiso.
4. Sea conciso (2‑3 líneas).

Mensaje:"""
        
        messages = [
            {"role": "system", "content": "Eres un asistente comercial experto en follow‑ups por WhatsApp. Escribes mensajes persuasivos pero no intrusivos."},
            {"role": "user", "content": prompt}
        ]
        # Usar el método interno del agente
        return agent._call_api(messages)
    
    def _generar_mensaje_followup_48h(self, lead, conversacion, agent):
        """Genera mensaje de ruptura de hielo después de 48h adicionales sin respuesta."""
        prompt = f"""Eres un consultor de negocios para peluquerías y centros de estética. Te diriges a {lead.nombre_establecimiento} en {lead.ciudad}.

Objetivo: Romper el hielo con un ángulo diferente al comercial. No hables de precios ni demos. En cambio, haz una pregunta abierta sobre los desafíos de su negocio.

Ejemplos:
- "¿Cuál es el mayor dolor de cabeza al gestionar las reservas de tus clientes?"
- "¿Cómo manejas actualmente las citas que los clientes no asisten?"
- "¿Qué porcentaje de tu tiempo dedicas a la administración vs a atender clientes?"

Escribe UNA sola pregunta concisa y profesional (1‑2 líneas). No incluyas saludos genéricos."""
        
        messages = [
            {"role": "system", "content": "Eres un consultor estratégico que ayuda a negocios a optimizar sus operaciones. Formulas preguntas penetrantes que generan reflexión."},
            {"role": "user", "content": prompt}
        ]
        return agent._call_api(messages)
    
    def _enviar_whatsapp(self, telefono: str, mensaje: str) -> bool:
        """
        Envía un mensaje de WhatsApp usando el microservicio whatsapp‑web.js.
        Sin templates, sin aprobaciones.
        
        Args:
            telefono: Número del destinatario (con o sin +)
            mensaje: Contenido del mensaje
        """
        # Configuración microservicio whatsapp‑web.js
        MICROSERVICE_URL = "http://localhost:8081/message/sendText/APPO_CRM"
        
        # Formatear número (quitar + y espacios, agregar código de país si falta)
        numero = telefono.replace("+", "").replace(" ", "")
        if not numero.startswith("57"):
            numero = "57" + numero
        
        # Intentar dos formatos: primero con @lid (para números nuevos sin LID), luego con @s.whatsapp.net
        numero_formats = [
            f"{numero}@lid",      # Para números nuevos que no tienen LID
            f"{numero}@s.whatsapp.net"  # Formato estándar si ya tiene LID
        ]
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Intentar cada formato hasta que uno funcione
        for formato_numero in numero_formats:
            payload = {
                "number": formato_numero,
                "textMessage": {
                    "text": mensaje
                }
            }
            
            try:
                self.stdout.write(f"  🔄 Probando formato: {formato_numero}")
                r = requests.post(
                    MICROSERVICE_URL,
                    headers=headers,
                    json=payload,
                    timeout=15
                )
                r.raise_for_status()
                
                respuesta = r.json()
                logger.info(f"WhatsApp enviado a {formato_numero} via whatsapp‑web.js. Respuesta: {respuesta}")
                self.stdout.write(f"  📱 WhatsApp enviado via whatsapp‑web.js. Estado: {respuesta.get('status', 'ok')}")
                return True
                
            except requests.exceptions.HTTPError as e:
                if "500" in str(e) and "No LID" in str(e.response.text if hasattr(e, 'response') else ''):
                    logger.warning(f"Formato {formato_numero} falló: No LID. Probando siguiente formato.")
                    self.stdout.write(f"  ⚠️  {formato_numero} sin LID. Probando siguiente formato...")
                    continue
                else:
                    raise
            except Exception as e:
                # Para otros errores, romper y no probar más formatos
                logger.error(f"Error enviando WhatsApp a {formato_numero}: {e}")
                self.stdout.write(f"  ❌ Error con formato {formato_numero}: {e}")
                return False
        
        # Si llegamos aquí, todos los formatos fallaron
        logger.error(f"Todos los formatos fallaron para {telefono}")
        self.stdout.write(f"  ❌ Todos los formatos fallaron para {telefono}")
        return False