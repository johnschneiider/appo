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
from leads_admin.prospector_agent import get_prospector_agent, procesar_lead_inicial, procesar_lead, formatear_saludo
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
            default=1,
            help='Limitar número de leads a procesar (0 = todos, default=1)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            dest='all_leads',
            help='Procesar todos los leads pendientes (sin límite)',
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
        
        # 1. Verificar hora laboral (8 AM–6 PM, hora Colombia, Lun–Sáb)
        if not ignore_hours and not self._es_hora_laboral():
            self.stdout.write("Fuera de horario laboral (8 AM–6 PM, Lun–Sáb). Abortando.")
            return
        
        # 2. Obtener agentes
        try:
            agent = get_prospector_agent()
        except Exception as e:
            self.stderr.write(f"Error al inicializar agente LLM: {e}")
            return
        
        # 3. Seleccionar leads para contactar
        conversaciones_pendientes = self._obtener_leads_pendientes()
        
        # Separar follow-ups (urgentes) de primeros contactos (cupo diario)
        followups = [c for c in conversaciones_pendientes if c.get('etapa') != 'initial']
        iniciales = [c for c in conversaciones_pendientes if c.get('etapa') == 'initial']
        
        self.stdout.write(f"Pendientes: {len(iniciales)} nuevos + {len(followups)} follow-ups")
        
        # 0. Verificar límite diario SOLO para primeros contactos (follow-ups no cuentan)
        if self._limite_diario_alcanzado():
            iniciales = []  # sin cupo para nuevos
            if not followups:
                self.stdout.write("Límite diario alcanzado y sin follow-ups pendientes.")
                return
        
        # Aplicar límite del comando
        # --all sobreescribe cualquier --limit, procesa todos
        all_leads = options.get('all_leads', False)
        limit = 0 if all_leads else options.get('limit', 1)
        if limit > 0:
            # Con --limit N: procesar primero follow-ups, luego nuevos hasta completar N
            resultado = []
            resultado.extend(followups[:limit])
            remaining = limit - len(resultado)
            if remaining > 0:
                resultado.extend(iniciales[:remaining])
            conversaciones_pendientes = resultado
            self.stdout.write(f"Aplicando limite {limit}: {len(resultado)} leads ({len([x for x in resultado if x.get('etapa')!='initial'])} follow-ups + {len([x for x in resultado if x.get('etapa')=='initial'])} nuevos)")
        else:
            # Sin limite: todos los follow-ups + nuevos que quepan en el cupo diario
            conversaciones_pendientes = followups + iniciales
        
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
        
        # 5. Procesar conversaciones secuencialmente (1 a la vez, más seguro para Meta)
        enviados = 0
        errores = 0
        max_workers = 1
        
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
        """Retorna True si es horario laboral.
        Lun–Sáb: 8:00–18:00 (hora Colombia)
        Dom:     9:00–17:00
        """
        try:
            tz_col = pytz.timezone('America/Bogota')
        except:
            tz_col = pytz.timezone('Etc/GMT+5')
        
        ahora = timezone.now().astimezone(tz_col)
        hora_actual = ahora.hour
        dia_semana = ahora.weekday()  # 0=Lunes, 6=Domingo
        
        if dia_semana == 6:  # Domingo
            return 9 <= hora_actual < 17  # 9:00–16:59
        return 8 <= hora_actual < 18  # Lun–Sáb: 8:00–17:59
    
    def _esperar_como_humano(self):
        """Pausa entre leads — el cron ya espacia 1h entre ejecuciones."""
        delay = random.randint(45, 90)
        self.stdout.write(f"  ⏳ Esperando {delay}s antes del siguiente envío...")
        time.sleep(delay)
    
    def _leads_procesados_hoy(self) -> int:
        """Cuenta SOLO primeros contactos nuevos hoy (no follow-ups ni respuestas automáticas)."""
        desde = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # Solo contar leads contactados por PRIMERA VEZ hoy: tienen estado 'contactado' y 0 mensajes de usuario
        total = 0
        for conv in LeadConversacion.objects.using('leads_db').filter(ultimo_contacto__gte=desde):
            msgs = conv.mensajes if isinstance(conv.mensajes, list) else []
            user_msgs = [m for m in msgs if m.get('role') == 'user']
            if len(user_msgs) == 0:
                total += 1
        return total
    
    # Fecha en que el número de WhatsApp empezó a enviar (anclaje de calentamiento).
    # El número APPO_CRM arrancó prospección el 2026-06-08.
    WARMUP_START = datetime(2026, 6, 8)

    def _cupo_diario(self) -> int:
        """Cupo diario de PRIMEROS contactos según rampa de calentamiento.

        El cold outreach por WhatsApp no oficial es lo más propenso a baneos de Meta.
        En vez de un número fijo, escalamos el volumen con la edad del número para
        construir reputación. Configurable vía env LEADS_DAILY_CAP (override duro).
        Domingo: -30%. Los follow-ups NO cuentan contra este cupo.
        """
        override = os.getenv('LEADS_DAILY_CAP')
        tz_col = pytz.timezone('America/Bogota')
        ahora = timezone.now().astimezone(tz_col)
        if override and override.isdigit():
            cupo = int(override)
        else:
            dias = max(0, (ahora.date() - self.WARMUP_START.date()).days)
            # Rampa: semana 1 → 15/día, sem 2 → 25, sem 3 → 40, sem 4+ → 60 (techo)
            if dias < 7:
                cupo = 15
            elif dias < 14:
                cupo = 25
            elif dias < 21:
                cupo = 40
            else:
                cupo = 60
        if ahora.weekday() == 6:  # Domingo, más suave
            cupo = int(cupo * 0.7)
        return cupo

    def _limite_diario_alcanzado(self) -> bool:
        """Límite diario por rampa de calentamiento (ver _cupo_diario)."""
        hoy = self._leads_procesados_hoy()
        max_diario = self._cupo_diario()
        if hoy >= max_diario:
            self.stdout.write(f'Límite diario alcanzado: {hoy}/{max_diario} leads contactados hoy.')
            return True
        return False
    
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
        
        # Leads nuevos (sin conversación) - EXCLUIR rechazos permanentes/no contactar
        leads_nuevos = Lead.objects.filter(
            estado__in=['Nuevo', 'pendiente', 'Pendiente'],
        ).exclude(
            estado__in=['rechazo_permanente', 'no_contactar', 'no_respondio']
        )
        # Excluir leads que ya tienen conversación
        leads_con_conversacion = LeadConversacion.objects.values_list('lead_id', flat=True)
        leads_nuevos = leads_nuevos.exclude(id__in=leads_con_conversacion)
        
        # Filtrar manualmente los teléfonos válidos y construir lista de conversaciones
        conversaciones = []
        for lead in leads_nuevos:
            tel_clean = (lead.telefono or '').replace('+', '').replace(' ', '')
            # Solo móviles colombianos: 10 dígitos (3XX...) o 12 dígitos (573XX...)
            if re.match(r'^3\d{9}$', tel_clean) or re.match(r'^573\d{9}$', tel_clean):
                # Objeto dict con estructura similar a LeadConversacion pero sin pk
                conversaciones.append({
                    'lead': lead,
                    'conversacion': None,  # será creada
                    'etapa': 'initial'
                })
        
        # Conversaciones que necesitan follow‑up 24h
        # Estado 'contactado', último contacto hace más de 24h
        # EXCLUIR leads con estado 'respondio', rechazo_permanente, no_contactar
        conv_followup_24h = LeadConversacion.objects.filter(
            estado='contactado',
            ultimo_contacto__lt=hace_24h,
            lead__telefono__regex=r'^\d{8,15}$',
        ).exclude(
            lead__estado__in=['rechazo_permanente', 'no_contactar', 'no_respondio']
        )
        
        # Conversaciones existentes para follow‑up
        for conv in conv_followup_24h:
            msgs = conv.mensajes if isinstance(conv.mensajes, list) else []
            user_msgs = [m for m in msgs if m.get('role') == 'user' and m.get('content', '').strip()]
            if len(user_msgs) > 0:
                logger.info(f'[FOLLOWUP] Lead {conv.lead.id} ({conv.lead.nombre_establecimiento}) ya respondió, saltando follow-up 24h')
                continue
            # ═══ FIX 4d: Detectar leads que NUNCA respondieron después del followup_24h ═══
            # Si la conversación está en estado 'contactado' y el último contacto
            # fue hace más de 48h → marcar como 'no_respondio'
            if conv.ultimo_contacto and (ahora - conv.ultimo_contacto) > timedelta(hours=48):
                logger.info(f'[NO_RESPONDIO] Lead {conv.lead.id} ({conv.lead.nombre_establecimiento}) no respondió en 48h, archivando')
                conv.estado = 'no_respondio'
                conv.save(using='leads_db')
                continue
            conversaciones.append({
                'lead': conv.lead,
                'conversacion': conv,
                'etapa': 'followup_24h'
            })
        
        # ═══ FIX 4d: leads en estado 'no_respondio' con +90 días → archivar ═══
        hace_90dias = ahora - timedelta(days=90)
        leads_no_respondio_antiguos = LeadConversacion.objects.filter(
            estado='no_respondio',
            ultimo_contacto__lt=hace_90dias,
        )
        for conv in leads_no_respondio_antiguos:
            logger.info(f'[ARCHIVAR] Lead {conv.lead.id} ({conv.lead.nombre_establecimiento}) no respondió hace 90 días, archivando')
            # Por ahora solo log, se podría marcar para borrado lógico
        
        # Ordenar por prioridad descendente del lead, luego fecha de ingreso
        default_date = timezone.make_aware(datetime(2024, 1, 1))
        conversaciones.sort(key=lambda x: (-x['lead'].prioridad, x['lead'].fecha_ingreso or default_date))
        return conversaciones
    
    def _procesar_lead(self, lead, conversacion, etapa: str, agent, dry_run: bool):
        """
        Procesa un lead según su etapa.
        etapas: 'initial', 'followup_24h', 'followup_48h'
        
        FLUJO MEJORADO (FIX 4a):
        Para etapa 'initial':
        1. Crear conversación en BD CON estado 'pendiente_envio' (ATÓMICO, antes de enviar)
        2. Guardar mensaje assistant como pendiente
        3. ENVIAR WhatsApp
        4. Si éxito: cambiar estado a 'contactado'
        5. Si falla: marcar lead como error, limpiar mensaje pendiente
        """
        self.stdout.write(f"Procesando lead {lead.id}: {lead.nombre_establecimiento} (etapa: {etapa})")
        
        # ═══ GUARDIA ANTI-DUPLICADOS: verificar DB justo antes de enviar ═══
        if etapa == 'initial':
            conv_existente = LeadConversacion.objects.using('leads_db').filter(lead=lead).first()
            if conv_existente:
                msgs = conv_existente.mensajes if isinstance(conv_existente.mensajes, list) else []
                ya_saludado = any('¿Aquí es' in m.get('content', '') for m in msgs if m.get('role') == 'assistant')
                if ya_saludado:
                    self.stdout.write(f"  ⚠️ Lead {lead.id} ya tiene saludo enviado. Saltando (anti-duplicado).")
                    logger.warning(f'[DEDUP] Lead {lead.id} ({lead.nombre_establecimiento}) ya tiene saludo - evitando duplicado')
                    return
        
        # 1. Generar mensaje según etapa
        if etapa == 'initial':
            partes = formatear_saludo(lead.nombre_establecimiento or 'amigo')
            mensaje_completo = "\n\n".join(partes)
        else:
            if etapa == 'followup_24h':
                mensaje = self._generar_mensaje_followup_24h(lead, conversacion, agent)
            elif etapa == 'followup_48h':
                mensaje = self._generar_mensaje_followup_48h(lead, conversacion, agent)
            else:
                raise ValueError(f"Etapa desconocida: {etapa}")
            # Para followup_48h, si el mensaje es None, no enviar nada
            if etapa == 'followup_48h' and mensaje is None:
                self.stdout.write(f"  ⏭️ Follow-up 48h: No se genera (máximo 1 follow-up configurado)")
                return
            partes = [p.strip() for p in mensaje.split('\n\n') if p.strip()]
            mensaje_completo = mensaje
        
        if not partes:
            raise ValueError(f"El agente no pudo generar mensaje para etapa {etapa}")
        
        self.stdout.write(f"  Partes generadas: {len(partes)}")
        
        if dry_run:
            self.stdout.write(f"  🧪 (Dry-run) Simulando envío de {len(partes)} partes a " + lead.telefono)
            for parte in partes:
                self.stdout.write(f"    🧪 Parte: {parte[:60]}...")
            self.stdout.write(f"  🧪 (Dry-run) No se modifica la base de datos")
            return
        
        ahora = timezone.now()
        
        # ═══ PASO 2: SAVE ANTES DE ENVIAR (FIX 4a) ═══
        if etapa == 'initial':
            # 1. Crear/obtener conversación con estado pendiente_envio
            conv, created = LeadConversacion.objects.using('leads_db').get_or_create(
                lead=lead,
                defaults={'mensajes': [], 'estado': 'pendiente_envio'}
            )
            # Si ya existía pero sin saludo, resetear estado
            if conv.estado in ('nuevo', 'pendiente_envio'):
                # Guardar mensaje assistant como pendiente
                conv.mensajes.append({
                    'role': 'assistant',
                    'content': mensaje_completo,
                    'timestamp': ahora.isoformat(),
                })
                conv.estado = 'pendiente_envio'
                conv.ultimo_contacto = ahora
                conv.save(using='leads_db')
                self.stdout.write(f"  📦 Conversación creada con estado 'pendiente_envio'")
            else:
                # Estado ya avanzado, no debería llegar aquí por la guardia anti-duplicado
                self.stdout.write(f"  ⚠️ Conversación ya en estado {conv.estado}, no se modifica")
                return
        
        # 2. ENVIAR WhatsApp
        exito_completo = True
        for i, parte in enumerate(partes):
            exito = self._enviar_whatsapp(lead.telefono, parte)
            if not exito:
                self.stdout.write(f"  ❌ Error al enviar WhatsApp parte {i+1}")
                exito_completo = False
                break
            self.stdout.write(f"  ✅ Parte {i+1}/{len(partes)} enviada")
            if i < len(partes) - 1:
                delay = random.uniform(2, 4)
                time.sleep(delay)
        
        # 3. Marcar éxito o error en BD
        if exito_completo:
            if etapa == 'initial':
                conv.estado = 'contactado'
                conv.ultimo_contacto = ahora
                conv.save(using='leads_db')
                lead.estado = 'Contactado'
                lead.save(using='leads_db')
                self.stdout.write(f"  ✅ Conversación marcada como 'contactado' + lead actualizado")
                self._esperar_como_humano()
            else:
                # follow-ups
                conversacion.mensajes.append({
                    'role': 'assistant',
                    'content': mensaje_completo,
                    'timestamp': ahora.isoformat(),
                })
                if etapa == 'followup_24h':
                    nuevo_estado = 'followup_24h'
                else:
                    nuevo_estado = 'contactado'
                conversacion.estado = nuevo_estado
                conversacion.ultimo_contacto = ahora
                conversacion.save(using='leads_db')
                lead.estado = 'Contactado'
                lead.save(using='leads_db')
                self.stdout.write(f"  🔄 Conversación actualizada (nuevo estado: {nuevo_estado})")
        else:
            # ⛔ Error: revertir estado pendiente
            if etapa == 'initial':
                # Eliminar el mensaje pendiente que no se pudo enviar
                if conv.mensajes:
                    conv.mensajes.pop()
                conv.estado = 'error_envio'
                conv.save(using='leads_db')
                self.stdout.write(f"  ❌ Lead marcado como error_envio. Conversación revertida.")
                logger.error(f'[ENVIO] Error enviando WhatsApp a lead {lead.id}, conversación en estado error_envio')
            raise ValueError(f"Error al enviar WhatsApp a lead {lead.id}")
    
    def _generar_mensaje_inicial(self, lead):
        """Genera el primer mensaje estático de prospección."""
        return formatear_saludo(lead.nombre_establecimiento)
    
    def _generar_mensaje_followup_24h(self, lead, conversacion, agent):
        """Genera follow-up 24h vía LLM — contextual, relajado, persuasivo."""
        nombre = lead.nombre_establecimiento or "amigo"
        historial = list(conversacion.mensajes) if conversacion and conversacion.mensajes else []
        llm_respuesta = agent.generar_followup(historial, 'followup_24h', nombre)
        if llm_respuesta:
            return llm_respuesta
        # Fallback si el LLM falla
        logger.warning(f'[FOLLOWUP] Fallback estático para lead {lead.id} (24h)')
        return (
            f"Hola 👋 De nuevo Juan. Te decía que con Appo tus clientes agendan solos "
            f"24/7, sin WhatsApp, sin llamadas. Ya hay más de 11 barberías en Colombia "
            f"ahorrándose como 30 min diarios en puro celular. "
            f"La capa gratis es para siempre, sin tarjeta. ¿Te parece si lo ves?"
        )
    
    def _generar_mensaje_followup_48h(self, lead, conversacion, agent):
        """Genera follow-up 48h vía LLM — último intento, respetuoso, sin presión."""
        nombre = lead.nombre_establecimiento or "amigo"
        historial = list(conversacion.mensajes) if conversacion and conversacion.mensajes else []
        llm_respuesta = agent.generar_followup(historial, 'followup_48h', nombre)
        if llm_respuesta:
            return llm_respuesta
        # Fallback si el LLM falla
        logger.warning(f'[FOLLOWUP] Fallback estático para lead {lead.id} (48h)')
        return (
            f"Juan acá de nuevo, y esta es la última, tranqui. "
            f"Te dejo el dato directo: appo.com.co, 30 días gratis, sin tarjeta, sin permanencia. "
            f"Entrás, lo probás, y si no te sirve, nada pasa. "
            f"A veces uno no sabe lo que le hace falta hasta que lo prueba. "
            f"¡Buen día! 🙌"
        )
    
    def _validar_numero_whatsapp(self, numero: str) -> bool:
        """
        Valida si un número está registrado en WhatsApp usando el microservicio.
        Retorna True si el número existe en WhatsApp.
        """
        VALIDATE_URL = "http://localhost:8081/number/check/APPO_CRM"
        headers = {"Content-Type": "application/json"}
        payload = {"number": f"{numero}@c.us"}
        
        try:
            r = requests.post(VALIDATE_URL, headers=headers, json=payload, timeout=10)
            if r.status_code == 200:
                data = r.json()
                is_registered = data.get('registered', False) or data.get('exists', False)
                if is_registered:
                    return True
                logger.info(f"Número {numero} no registrado en WhatsApp")
                return False
            logger.warning(f"Validación WhatsApp para {numero}: HTTP {r.status_code}")
            return True  # Si el endpoint falla, intentar enviar igual (fail-open)
        except Exception as e:
            logger.warning(f"Error validando {numero}: {e}. Se intentará enviar igual.")
            return True  # Fail-open: si no podemos validar, intentamos enviar
    
    def _enviar_whatsapp(self, telefono: str, mensaje: str) -> bool:
        """
        Envía un mensaje de WhatsApp usando el microservicio whatsapp‑web.js.
        El microservicio maneja internamente la estrategia multi-formato (@c.us, @s.whatsapp.net, @lid).
        
        Args:
            telefono: Número del destinatario (con o sin +)
            mensaje: Contenido del mensaje
        """
        MICROSERVICE_URL = "http://localhost:8081/message/sendText/APPO_CRM"
        
        # Formatear número: quitar +, espacios, y código país si falta
        numero = telefono.replace("+", "").replace(" ", "")
        if not numero.startswith("57"):
            numero = "57" + numero
        
        # Enviar formato simple @c.us — el microservicio maneja los fallbacks
        payload = {
            "number": f"{numero}@c.us",
            "textMessage": {"text": mensaje}
        }
        
        try:
            self.stdout.write(f"  📱 Enviando a {numero}...")
            r = requests.post(
                MICROSERVICE_URL,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=20
            )
            r.raise_for_status()
            
            respuesta = r.json()
            msg_id = respuesta.get('key', {}).get('id', 'unknown')
            logger.info(f"WhatsApp enviado a {numero} via whatsapp‑web.js. ID: {msg_id}")
            self.stdout.write(f"  ✅ Enviado (ID: {msg_id})")
            return True
            
        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = e.response.text[:200] if hasattr(e, 'response') else ""
            except:
                pass
            logger.error(f"Error enviando WhatsApp a {numero}: HTTP {e.response.status_code if hasattr(e, 'response') else '?'} - {error_body}")
            self.stdout.write(f"  ❌ Error: {error_body[:100]}")
            return False
        except Exception as e:
            logger.error(f"Error enviando WhatsApp a {numero}: {e}")
            self.stdout.write(f"  ❌ Error: {e}")
            return False
    
    def _enviar_imagen_planes(self, telefono: str) -> bool:
        """Envía la imagen de planes de Appo al lead."""
        MEDIA_URL = "http://localhost:8081/message/sendMedia/APPO_CRM"
        IMAGEN_URL = "https://appo.com.co/media/galeria_negocio/planes-appo.png"
        CAPTION = (
            "Estos son los planes de Appo 🚀\n\n"
            "✅ Capa Gratuita: para siempre, sin tarjeta, sin límite\n"
            "✅ Plan Pro: $49.000/barbero/mes, 30 días gratis\n\n"
            "Cancelás cuando quieras · appo.com.co"
        )
        
        numero = telefono.replace("+", "").replace(" ", "")
        if not numero.startswith("57"):
            numero = "57" + numero
        
        payload = {
            "number": f"{numero}@c.us",
            "mediaMessage": {
                "mediatype": "image",
                "media": IMAGEN_URL,
                "caption": CAPTION
            }
        }
        
        try:
            r = requests.post(
                MEDIA_URL,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30
            )
            r.raise_for_status()
            self.stdout.write(f"  🖼️ Imagen enviada a {numero}")
            return True
        except Exception as e:
            logger.error(f"Error enviando imagen a {numero}: {e}")
            self.stdout.write(self.style.WARNING(f"  ⚠️ Error enviando imagen: {e}"))
            return False