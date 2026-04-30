from django.shortcuts import render
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import requests
import json
import logging
import os
from datetime import datetime
from .models import Lead, ChatWhatsApp, MensajeWhatsApp

logger = logging.getLogger(__name__)

# Credenciales internas de Owen para la API (nuevo microservicio whatsapp-web.js)
EVOLUTION_API_URL = "http://localhost:8081"
API_KEY = ""  # No se requiere API key en el nuevo servicio
INSTANCE_NAME = "APPO_CRM"

def enviar_whatsapp(telefono: str, mensaje: str, jid_override: str = None) -> bool:
    """Envía un mensaje de WhatsApp usando Evolution API.
    Siempre usa el número de teléfono real (no LID) para el envío.
    """
    import requests
    import logging
    logger = logging.getLogger(__name__)

    # Siempre usar el número de teléfono real, ignorar @lid
    # Si el teléfono tiene formato lid_XXXX o @lid, no podemos enviar directamente
    numero = telefono.replace("+", "").replace(" ", "")
    es_jid_real = False
    es_jid_lid = False
    
    # Si jid_override es un JID real (@s.whatsapp.net), usarlo directamente
    if jid_override and '@s.whatsapp.net' in jid_override:
        numero = jid_override  # Usar JID completo
        es_jid_real = True
        logger.info(f'[ENVIAR_WA] Usando JID real de jid_override: {numero}')
        # Opcional: actualizar DB para mapear LID a número real
        if telefono.startswith('lid_'):
            lid_raw = telefono.replace('lid_', '')
            from .models import ChatWhatsApp
            chat = ChatWhatsApp.objects.using('leads_db').filter(
                chat_id=lid_raw + '@lid'
            ).first()
            if chat:
                chat.phone = '+' + jid_override.split('@')[0]
                chat.save(using='leads_db')
                logger.info(f'[ENVIAR_WA] Actualizado chat.phone a {chat.phone}')
    
    # Si jid_override es un JID LID (@lid), usarlo directamente también
    if jid_override and '@lid' in jid_override:
        numero = jid_override  # Usar JID LID completo
        es_jid_lid = True
        es_jid_real = True  # Tratar como JID para evitar normalización
        logger.info(f'[ENVIAR_WA] Usando JID LID de jid_override: {numero}')
    
    if not es_jid_real and (numero.startswith('lid_') or '@lid' in str(jid_override or '')):
        # Si el teléfono es un LID, buscar el número real en la DB o en el chat
        lid_raw = numero.replace('lid_', '') if numero.startswith('lid_') else ''
        if not lid_raw and jid_override and '@lid' in jid_override:
            lid_raw = jid_override.split('@')[0]
        # Buscar en ChatWhatsApp si hay número real mapeado
        if lid_raw:
            from .models import ChatWhatsApp
            chat = ChatWhatsApp.objects.using('leads_db').filter(
                chat_id=lid_raw + '@lid'
            ).first()
            if chat and chat.phone and not chat.phone.startswith('lid_'):
                numero = chat.phone.replace('+', '')
                logger.info(f'[ENVIAR_WA] LID resuelto via DB: {lid_raw} -> {numero}')
            else:
                # No hay mapeo, pero podemos intentar enviar al LID directamente
                # (WhatsApp entregará al número correcto)
                if jid_override and '@lid' in jid_override:
                    numero = jid_override
                    es_jid_real = True
                    logger.info(f'[ENVIAR_WA] Enviando directamente al LID (sin mapeo): {numero}')
                else:
                    logger.error(f'[ENVIAR_WA] No se puede enviar a LID sin número real: {telefono}. Usa número tradicional.')
                    return False
        else:
            logger.error(f'[ENVIAR_WA] Número LID sin resolver: {telefono}')
            return False
    
    # Normalizar número colombiano (solo si no es JID real y no es LID)
    if not es_jid_real and not numero.startswith('57') and not es_jid_lid:
        if numero.startswith('3') and len(numero) == 10:
            numero = '57' + numero
        elif len(numero) >= 7:
            numero = '57' + numero
    
    logger.info(f'[ENVIAR_WA] Enviando a: {numero} | Msg: {mensaje[:50]}...')
    logger.error(f'[DIAG] enviar_whatsapp: numero={numero}, jid_override={jid_override}')
    
    # Nuevo microservicio no requiere API key
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "number": numero,
        "textMessage": {
            "text": mensaje
        }
    }
    try:
        resp = requests.post(
            f"{EVOLUTION_API_URL}/message/sendText/{INSTANCE_NAME}",
            headers=headers, json=payload, timeout=15
        )
        resp.raise_for_status()
        resp_json = resp.json()
        logger.error(f'[DIAG] enviar_whatsapp response: {resp_json}')
        logger.info(f"WhatsApp enviado a {numero}. key={resp_json.get('key',{}).get('id','?')}")
        return True
    except Exception as e:
        logger.error(f"Error enviando WhatsApp a {telefono}: {e}")
        return False


def is_superadmin(user):
    return user.is_authenticated and user.is_superuser

@user_passes_test(is_superadmin)
def crm_dashboard(request):
    """Vista principal del CRM de Leads"""
    # Obtenemos los leads asignados a APPO desde la DB secundaria
    leads = Lead.objects.using('leads_db').filter(proyecto='APPO').order_by('-prioridad', '-fecha_ingreso')
    
    # Obtener estado de conexión de WhatsApp
    connection_state = 'close'
    try:
        headers = {'apikey': API_KEY}
        state_response = requests.get(f"{EVOLUTION_API_URL}/instance/connectionState/{INSTANCE_NAME}", headers=headers, timeout=5)
        if state_response.status_code == 200:
            state_data = state_response.json()
            connection_state = state_data.get('instance', {}).get('state', 'close')
    except Exception as e:
        logger.error(f'Error obteniendo estado de conexión: {e}')
    
    context = {
        'leads': leads,
        'instance_name': INSTANCE_NAME,
        'whatsapp_connected': connection_state == 'open',
        'connection_state': connection_state,
    }
    return render(request, 'leads_admin/crm.html', context)

@user_passes_test(is_superadmin)
def conectar_whatsapp(request):
    """Genera o recupera el QR para conectar la cuenta (nuevo microservicio whatsapp-web.js)"""
    try:
        # Verificar estado de conexión
        state_resp = requests.get(f"{EVOLUTION_API_URL}/instance/connectionState/{INSTANCE_NAME}")
        if state_resp.status_code != 200:
            return JsonResponse({'error': 'No se pudo obtener estado de la instancia'}, status=500)
        state_data = state_resp.json()
        
        # Si ya está conectado
        if state_data.get('instance', {}).get('state') == 'open':
            return JsonResponse({'status': 'CONNECTED'})
        
        # Obtener QR base64
        qr_resp = requests.get(f"{EVOLUTION_API_URL}/instance/qrBase64/{INSTANCE_NAME}")
        if qr_resp.status_code != 200:
            return JsonResponse({'error': 'No se pudo obtener QR'}, status=500)
        qr_data = qr_resp.json()
        
        # El nuevo servicio devuelve QR base64 en campo 'qr'
        base64_qr = qr_data.get('qr')
        if base64_qr:
            return JsonResponse({'base64': base64_qr})
        
        # Fallback: devolver datos crudos
        return JsonResponse(qr_data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@user_passes_test(is_superadmin)
def qr_proxy(request):
    """Proxy al microservicio para evitar CORS en el frontend."""
    try:
        # Primero verificar si ya está conectado
        state_r = requests.get(
            f'{EVOLUTION_API_URL}/instance/connectionState/{INSTANCE_NAME}',
            timeout=5
        )
        state = state_r.json().get('instance', {}).get('state', 'close')
        if state == 'open':
            return JsonResponse({'state': 'open'})

        # Si no, devolver el QR
        qr_r = requests.get(
            f'{EVOLUTION_API_URL}/instance/qrBase64/{INSTANCE_NAME}',
            timeout=5
        )
        qr_data = qr_r.json()
        # Asegurar que el campo se llama 'base64' (el servicio lo llama 'qr')
        raw = qr_data.get('qr') or qr_data.get('base64') or qr_data.get('qrCode', '')
        if raw and not raw.startswith('data:'):
            raw = f'data:image/png;base64,{raw}'
        qr_data['base64'] = raw
        return JsonResponse(qr_data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse

@csrf_exempt
def webhook_evolution(request):
    """Recibe webhooks de Evolution API para mensajes de WhatsApp"""
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)
    
    # Log headers y body crudo
    headers = dict(request.headers)
    logger.info(f'Webhook headers: {headers}')
    raw_body = request.body.decode('utf-8') if request.body else ''
    logger.info(f'Webhook raw body (first 2000 chars): {raw_body[:2000]}')
    # DEBUG: Guardar payload en archivo para inspección
    import os, traceback
    try:
        import json
        payload_debug = json.loads(raw_body) if raw_body.strip() else {}
        with open('/tmp/webhook_debug.json', 'w') as f:
            json.dump(payload_debug, f, indent=2, ensure_ascii=False)
        logger.info(f'DEBUG: Payload guardado en /tmp/webhook_debug.json')
    except Exception as debug_e:
        logger.error(f'DEBUG error: {debug_e}')
    
    try:
        payload = json.loads(raw_body) if raw_body.strip() else {}
        logger.info(f'Webhook payload type: {type(payload)}')
        logger.info(f'Webhook payload: {json.dumps(payload, indent=2)[:1000]}')
        
        # Procesar según tipo de evento
        event_type = payload.get('event') or headers.get('X-Webhook-Event')
        logger.info(f'Event type detected: {event_type}')
        logger.error(f'[DIAG] Webhook recibido: event={event_type}, instance={payload.get("instance")}')
        
        # Si es MESSAGES_UPSERT, extraer mensaje
        if event_type in ('MESSAGES_UPSERT', 'messages.upsert') or 'messages' in str(event_type or '').lower():
            # Evolution API 1.x: data es un objeto único o lista
            data_raw = payload.get('data', {})
            if isinstance(data_raw, list):
                messages = data_raw
            elif isinstance(data_raw, dict) and 'key' in data_raw:
                # Objeto único de mensaje
                messages = [data_raw]
            else:
                messages = data_raw.get('messages', []) or payload.get('messages', [])
            logger.info(f'Messages found: {len(messages)}')
            logger.error(f'[DIAG] Messages extracted: {len(messages)}')
            for msg in messages:
                logger.info(f'Message: {msg}')
                logger.error(f'[DIAG] Message remote_jid={msg.get("key", {}).get("remoteJid", "")}, fromMe={msg.get("key", {}).get("fromMe", False)}')
                # Procesar mensaje entrante
                try:
                    # Extraer datos del mensaje
                    key = msg.get('key', {})
                    remote_jid = key.get('remoteJid', '')
                    from_me = key.get('fromMe', False)
                    
                    # Procesar mensajes directos: @s.whatsapp.net Y @lid (nuevo sistema WA)
                    is_group = remote_jid.endswith('@g.us') or remote_jid.endswith('@broadcast')
                    if not from_me and remote_jid and not is_group:
                        # Extraer número de teléfono
                        # @s.whatsapp.net -> número directo
                        # @lid -> usar pushName del payload o buscar en contacts
                        raw_id = remote_jid.split('@')[0]
                        if remote_jid.endswith('@lid'):
                            # Intentar resolver @lid a número via Evolution API
                            push_name = msg.get('pushName', '')
                            try:
                                contact_resp = requests.get(
                                    f"{EVOLUTION_API_URL}/chat/findContacts/{INSTANCE_NAME}",
                                    headers={'apikey': API_KEY},
                                    params={'where': f'{{"id":"{remote_jid}"}}'},
                                    timeout=3
                                )
                                contacts = contact_resp.json() if contact_resp.ok else []
                                if contacts and isinstance(contacts, list) and contacts[0].get('id'):
                                    resolved = contacts[0].get('id','').split('@')[0]
                                    phone = '+' + resolved if resolved.startswith('57') else '+57' + resolved
                                else:
                                    # Fallback: usar el LID como identificador único
                                    phone = f'lid_{raw_id}'
                            except Exception:
                                phone = f'lid_{raw_id}'
                        else:
                            phone = '+' + raw_id if raw_id.startswith('57') else raw_id
                            if not phone.startswith('+'):
                                phone = '+57' + phone
                        
                        # Extraer número real del sender si está presente
                        real_sender_jid = payload.get('sender')
                        real_phone = None
                        if real_sender_jid and '@s.whatsapp.net' in real_sender_jid:
                            real_phone = '+' + real_sender_jid.split('@')[0]
                            logger.info(f'[WEBHOOK] Número real obtenido del sender: {real_phone}')
                        
                        # Extraer texto del mensaje
                        message_content = ''
                        message_obj = msg.get('message', {})
                        if 'conversation' in message_obj:
                            message_content = message_obj.get('conversation', '')
                        elif 'extendedTextMessage' in message_obj:
                            message_content = message_obj.get('extendedTextMessage', {}).get('text', '')
                        
                        logger.info(f'Procesando mensaje de {phone}: {message_content[:100]}')
                        logger.info(f'[WEBHOOK] Mensaje recibido de {phone}: "{message_content[:50]}"')
                        
                        # Buscar o crear lead en la base de datos leads_db, o crear lead virtual temporal para números no registrados
                        from .models import Lead, ChatWhatsApp, MensajeWhatsApp, LeadConversacion
                        
                        lead = None
                        created = False
                        
                        try:
                            # Primero intentar buscar por teléfono
                            lead = Lead.objects.using('leads_db').get(telefono=phone)
                            logger.info(f'Lead existente encontrado: {lead.nombre_establecimiento}')
                        except Lead.DoesNotExist:
                            # No existe lead para este número
                            # Crear un objeto lead virtual temporal para procesar la respuesta
                            # SIN guardarlo en la base de datos
                            lead = Lead(
                                id=0,  # ID temporal
                                nombre_establecimiento=f'Cliente WhatsApp {phone}',
                                telefono=phone,
                                ciudad='Desconocida',
                                proyecto='APPO',
                                prioridad=1,
                                estado='Nuevo',
                                tiene_web=False,
                                fecha_ingreso=datetime.now()
                            )
                            created = True
                            logger.info(f'Número no registrado {phone} - creado lead virtual temporal')
                        
                        # Si es un lead real (guardado en BD), continuar con conversación normal
                        # Si es lead virtual, solo procesar respuesta sin guardar nada
                        
                        # Si es lead real (guardado en BD), crear/obtener conversación
                        # Si es lead virtual temporal, usar conversación dummy
                        if lead.id > 0:  # Lead real (con ID en BD)
                            conversacion, conv_created = LeadConversacion.objects.using('leads_db').get_or_create(
                                lead=lead,
                                defaults={'mensajes': [], 'estado': 'nuevo'}
                            )
                            if conv_created:
                                logger.info(f'Conversación creada en leads_db para lead {lead.id}')
                            conversacion_id = lead.id  # Usar ID real para procesar_lead
                        else:
                            # Lead virtual: crear conversación dummy con historial vacío
                            conversacion = None
                            conversacion_id = -1  # ID especial para indicar lead virtual
                            logger.info(f'Lead virtual {phone} - no se guardará conversación en BD')
                        
                        # Guardar mensaje en base de datos local para historial
                        try:
                            chat, _ = ChatWhatsApp.objects.using('leads_db').get_or_create(
                                chat_id=remote_jid,
                                defaults={
                                    'phone': real_phone if real_phone else phone,
                                    'last_message': message_content,
                                    'last_message_timestamp': datetime.now()
                                }
                            )
                            # Update chat if exists
                            chat.last_message = message_content
                            chat.last_message_timestamp = datetime.now()
                            chat.save(using='leads_db')
                            
                            if real_phone and chat.phone != real_phone:
                                chat.phone = real_phone
                                chat.save(using='leads_db')
                            
                            # Guardar mensaje
                            MensajeWhatsApp.objects.using('leads_db').get_or_create(
                                message_key=f"{remote_jid}_{datetime.now().timestamp()}",
                                defaults=dict(
                                    chat=chat,
                                    raw_payload=msg,
                                    sender=phone,
                                    from_me=from_me,
                                    message_text=message_content,
                                )
                            )
                            logger.info(f'Mensaje guardado localmente para chat {remote_jid}')

                            # Notificar en tiempo real al panel CRM vía WebSocket
                            try:
                                from asgiref.sync import async_to_sync
                                from channels.layers import get_channel_layer
                                channel_layer = get_channel_layer()
                                if channel_layer:
                                    async_to_sync(channel_layer.group_send)(
                                        'crm_whatsapp',
                                        {
                                            'type': 'chat_message',
                                            'chat_id': remote_jid,
                                            'phone': phone,
                                            'text': message_content,
                                            'from_me': False,
                                            'timestamp': datetime.now().isoformat(),
                                            'sender': phone,
                                            'lead_name': lead.nombre_establecimiento,
                                        }
                                    )
                            except Exception as ws_err:
                                logger.warning(f'No se pudo notificar WebSocket: {ws_err}')

                            # Respuesta automática del agente en thread separado
                            # (evitar bloquear el webhook - responder 200 inmediatamente)
                            import threading
                            _chat_ref = chat
                            def _responder_async(lead_id, msg_content, tel, chat_obj, jid):
                                import time, random
                                from leads_admin.models import MensajeWhatsApp
                                MAX_RETRIES = 2
                                for attempt in range(MAX_RETRIES):
                                    try:
                                        import time, random
                                        logger.error(f'[DIAG] Entrando a respuesta automática. phone={tel}, message={msg_content[:50]}')

                                        from leads_admin.prospector_agent import procesar_lead
                                        logger.error(f'[DIAG] procesar_lead importado. lead.id={lead_id}')

                                        respuesta = procesar_lead(lead_id, mensaje_entrante=msg_content)
                                        logger.error(f'[DIAG] Respuesta generada: {str(respuesta)[:100]}')

                                        if respuesta:
                                            partes = [p.strip() for p in respuesta.split('\n\n') if p.strip()]
                                            logger.error(f'[DIAG] Partes a enviar: {len(partes)}')
                                            for i, parte in enumerate(partes):
                                                logger.error(f'[DIAG] Enviando parte {i+1}/{len(partes)} a {tel}')
                                                resultado = enviar_whatsapp(tel, parte, jid_override=jid)
                                                logger.error(f'[DIAG] Resultado envío parte {i+1}: {resultado}')
                                                time.sleep(random.uniform(2, 4))
                                        else:
                                            logger.error(f'[DIAG] procesar_lead devolvió None o vacío')
                                        return  # éxito
                                    except Exception as ex:
                                        logger.error(f'[AGENTE] Intento {attempt+1}/{MAX_RETRIES} fallido: {ex}')
                                        if attempt < MAX_RETRIES - 1:
                                            time.sleep(5)
                                        else:
                                            logger.error(f'[AGENTE] Agotados reintentos para {tel}')
                            phone_for_response = real_phone if real_phone else phone
                            jid_for_response = real_sender_jid if real_sender_jid else remote_jid
                            threading.Thread(
                                target=_responder_async,
                                args=(lead.id, message_content, phone_for_response, _chat_ref, jid_for_response),
                                daemon=True
                            ).start()
                            logger.info(f'[WEBHOOK] Thread iniciado para {phone_for_response}')
                        except Exception as e:
                            logger.error(f'Error guardando mensaje en base local: {e}')
                        
                        # Aquí podríamos crear un registro en chat_mensaje (de tablas originales)
                        
                except Exception as e:
                    logger.error(f'Error procesando mensaje individual: {e}', exc_info=True)
        
        # Manejar CONTACTS_UPSERT/UPDATE: guardar mapping LID->número real
        elif event_type in ('CONTACTS_UPSERT', 'contacts.upsert', 'CONTACTS_UPDATE', 'contacts.update'):
            contacts = payload.get('data', [])
            if isinstance(contacts, dict):
                contacts = [contacts]
            for contact in (contacts if isinstance(contacts, list) else []):
                jid = contact.get('id', '') or contact.get('remoteJid', '')
                phone_number = contact.get('number') or contact.get('phone')
                name = contact.get('name') or contact.get('pushName') or contact.get('notify', '')
                if jid and phone_number:
                    # Guardar mapping JID->número en ChatWhatsApp
                    from .models import ChatWhatsApp
                    chat = ChatWhatsApp.objects.using('leads_db').filter(chat_id=jid).first()
                    if chat and chat.phone != phone_number:
                        chat.phone = phone_number
                        chat.contact_name = name
                        chat.save(using='leads_db')
                        logger.info(f'[CONTACT] Mapeado {jid} -> {phone_number} ({name})')

        # QRCODE_UPDATED: guardar QR para mostrar al admin
        elif event_type in ('QRCODE_UPDATED', 'qrcode.updated'):
            import base64 as b64lib
            def _find_b64(obj):
                if isinstance(obj, dict):
                    if 'base64' in obj and isinstance(obj['base64'], str) and len(obj['base64']) > 100:
                        return obj['base64']
                    for v in obj.values():
                        r = _find_b64(v)
                        if r: return r
                return None
            b64 = _find_b64(payload)
            if b64:
                data = b64.split(',', 1)[1] if ',' in b64 else b64
                with open('/root/.openclaw/workspace/qr_appo_v2.png', 'wb') as fqr:
                    fqr.write(b64lib.b64decode(data))
                logger.info('[QR] QR v2 guardado en /root/.openclaw/workspace/qr_appo_v2.png')
            else:
                logger.warning(f'[QR] QRCODE_UPDATED sin base64: {str(payload)[:200]}')

        # CONNECTION_UPDATE: detectar desconexiones
        elif event_type in ('CONNECTION_UPDATE', 'connection.update'):
            state = payload.get('data', {}).get('state', '')
            logger.info(f'[CONNECTION] Estado Evolution: {state}')
            if state in ('close', 'connecting'):
                logger.warning(f'[CONNECTION] Evolution desconectado/reconectando: {state}')

        return HttpResponse('OK', status=200)
    except json.JSONDecodeError as e:
        logger.error(f'JSON inválido: {e}, raw body: {raw_body[:500]}')
        return HttpResponse('Invalid JSON', status=400)
    except Exception as e:
        logger.error(f'Error procesando webhook: {e}', exc_info=True)
        return HttpResponse('Error', status=500)


# Funciones para almacenaje local de mensajes
from datetime import datetime

def guardar_mensaje_whatsapp(payload):
    """Guardar mensaje entrante en base de datos local"""
    try:
        # Ejemplo de extracción de datos del payload de Evolution API
        # Este código debe adaptarse al esquema exacto del webhook de Evolution API
        # Si es un JSON de Evolution API:
        #   - chat['id'] = remoteJid
        #   - chat['name'] = nombre del contacto (podrías obtenerlo de Evolution API)
        #   - message_text = conversation | extendedTextMessage.text | etc.
        #   - sender = remoteJid.extractedPhone
        #   - timestamp = messageTimestamp
        
        chat_id = payload.get('data', {}).get('messages', [{}])[0].get('key', {}).get('remoteJid', '')
        # ... lógica de guardado en la base de datos local con Django ORM ...
    
        logger.info(f'Guardando mensaje para chat {chat_id}')
        
        # Simulación de guardado exitoso
        return True
        
    except Exception as e:
        logger.error(f'Error guardando mensaje: {e}')
        return False
    

@user_passes_test(is_superadmin)
def obtener_chats_local(request):
    """Obtener chats desde base de datos local (leads_db)"""
    try:
        from .models import ChatWhatsApp, MensajeWhatsApp
        chats_qs = ChatWhatsApp.objects.using('leads_db').order_by('-updated_at')[:50]
        chats = []
        for c in chats_qs:
            # Obtener último mensaje
            last_msg = MensajeWhatsApp.objects.using('leads_db').filter(chat=c).order_by('-created_at').first()
            # Determinar nombre: usar número de teléfono limpio
            phone = c.phone or c.chat_id.split('@')[0]
            if phone.startswith('lid_'):
                phone = phone.replace('lid_', '')
            lead_name = c.contact_name or ''
            chats.append({
                'chat_id': c.chat_id,
                'phone': phone,
                'lead_name': lead_name,
                'last_message': last_msg.message_text[:60] if last_msg else '',
                'timestamp': last_msg.created_at.isoformat() if last_msg else c.updated_at.isoformat(),
                'unread': 0,
            })
        return JsonResponse({'chats': chats})
    except Exception as e:
        logger.error(f'Error obteniendo chats local: {e}', exc_info=True)
        return JsonResponse({'error': 'Internal error'}, status=500)

@user_passes_test(is_superadmin)
def obtener_mensajes_local(request, chat_id):
    """Obtener mensajes de un chat específico desde base local"""
    try:
        from .models import ChatWhatsApp, MensajeWhatsApp
        chat = ChatWhatsApp.objects.using('leads_db').filter(chat_id=chat_id).first()
        if not chat:
            return JsonResponse({'messages': []})
        msgs = MensajeWhatsApp.objects.using('leads_db').filter(chat=chat).order_by('created_at')[:200]
        messages = [{
            'id': m.id,
            'text': m.message_text,
            'from_me': m.from_me,
            'sender': m.sender,
            'timestamp': m.created_at.isoformat(),
        } for m in msgs]
        return JsonResponse({'messages': messages})
    except Exception as e:
        logger.error(f'Error obteniendo mensajes local: {e}', exc_info=True)
        return JsonResponse({'error': 'Internal error'}, status=500)


@user_passes_test(is_superadmin)
def obtener_estado_conexion(request):
    """Devuelve estado de conexión de WhatsApp"""
    try:
        headers = {'apikey': API_KEY}
        response = requests.get(f"{EVOLUTION_API_URL}/instance/connectionState/{INSTANCE_NAME}", headers=headers, timeout=5)
        if response.status_code == 200:
            state_data = response.json()
            estado = state_data.get('instance', {}).get('state', 'close')
            return JsonResponse({'conectado': estado == 'open', 'estado': estado})
        else:
            return JsonResponse({'conectado': False, 'estado': 'error'})
    except Exception as e:
        logger.error(f'Error obteniendo estado: {e}')
        return JsonResponse({'conectado': False, 'estado': 'error'})


@user_passes_test(is_superadmin)
def obtener_chats(request):
    """Obtiene chats reales de WhatsApp desde Evolution API"""
    try:
        headers = {'apikey': API_KEY}
        response = requests.get(f"{EVOLUTION_API_URL}/chat/findChats/{INSTANCE_NAME}", headers=headers, timeout=10)
        if response.status_code == 200:
            chats = response.json()
            # Estructura real: [{id, owner, lastMsgTimestamp?}, ...]
            if not isinstance(chats, list):
                chats = [chats]
            
            # Procesar chats
            processed_chats = []
            for chat in chats:
                chat_id = chat.get('id', '')
                # Intentar extraer nombre del ID (si es número de teléfono)
                name = 'Desconocido'
                if '@s.whatsapp.net' in chat_id:
                    # Es número individual
                    name = chat_id.split('@')[0]
                elif '@lid' in chat_id:
                    # Es lista de difusión (broadcast list)
                    name = f'Lista {chat_id[:8]}...'
                elif '@g.us' in chat_id:
                    # Es grupo
                    name = f'Grupo {chat_id[:8]}...'
                
                processed_chats.append({
                    'id': chat_id,
                    'name': name,
                    'unread_count': 0,  # No disponible en este endpoint
                    'last_message': {},
                    'timestamp': chat.get('lastMsgTimestamp', 0),
                    'is_group': '@g.us' in chat_id or '@lid' in chat_id
                })
            return JsonResponse({'chats': processed_chats})
        else:
            return JsonResponse({'error': 'No se pudieron obtener chats', 'status': response.status_code}, status=500)
    except Exception as e:
        logger.error(f'Error obteniendo chats: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@user_passes_test(is_superadmin)
def obtener_mensajes(request, chat_id):
    """Obtiene mensajes de un chat específico"""
    # TEMPORAL: Evolution API no expone endpoint claro para mensajes históricos
    # Los mensajes llegan via webhook y se almacenarán en futura versión
    logger.info(f'Solicitud de mensajes para chat {chat_id} - endpoint no implementado aún')
    return JsonResponse({'messages': [], 'note': 'Los mensajes históricos no están disponibles aún. Los mensajes nuevos aparecerán cuando lleguen por WhatsApp.'})
