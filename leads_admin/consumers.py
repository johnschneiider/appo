"""
WebSocket consumer para el CRM de WhatsApp en tiempo real.
Permite ver mensajes entrantes/salientes sin refrescar la página.
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)

# Nombre del grupo global del CRM (todos los admins conectados lo reciben)
CRM_GROUP = "crm_whatsapp"


class CRMConsumer(AsyncWebsocketConsumer):
    """
    Consumer WebSocket para el panel CRM de WhatsApp.
    - Se une al grupo 'crm_whatsapp' al conectar
    - Recibe eventos push cuando llega un mensaje nuevo (enviado desde el webhook)
    - Permite enviar mensajes manuales desde el panel
    """

    async def connect(self):
        # Solo superadmins
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not user.is_superuser:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(CRM_GROUP, self.channel_name)
        await self.accept()
        logger.info(f"[CRM WS] Conectado: {user.username} / {self.channel_name}")

        # Enviar historial reciente al conectar
        chats = await self.get_recent_chats()
        await self.send(text_data=json.dumps({
            "type": "init",
            "chats": chats,
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(CRM_GROUP, self.channel_name)
        logger.info(f"[CRM WS] Desconectado: code={close_code}")

    async def receive(self, text_data):
        """Mensajes desde el navegador hacia el servidor."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")

        if msg_type == "send_message":
            # Admin envía un mensaje manual desde el panel
            chat_id = data.get("chat_id", "")
            phone = data.get("phone", "")
            text = data.get("text", "").strip()
            if not text or not phone:
                return

            success = await self.send_whatsapp_message(phone, text)
            if success:
                # Guardar en DB y notificar a todos los paneles
                await self.save_outgoing_message(chat_id, phone, text)
                await self.channel_layer.group_send(
                    CRM_GROUP,
                    {
                        "type": "chat_message",
                        "chat_id": chat_id,
                        "phone": phone,
                        "text": text,
                        "from_me": True,
                        "timestamp": timezone.now().isoformat(),
                        "sender": "admin",
                    }
                )
            else:
                await self.send(text_data=json.dumps({
                    "type": "error",
                    "message": "Error al enviar mensaje. Revisa la conexión de WhatsApp.",
                }))

        elif msg_type == "get_messages":
            # Pedir historial de un chat específico
            chat_id = data.get("chat_id", "")
            messages = await self.get_chat_messages(chat_id)
            await self.send(text_data=json.dumps({
                "type": "messages_history",
                "chat_id": chat_id,
                "messages": messages,
            }))

        elif msg_type == "mark_read":
            chat_id = data.get("chat_id", "")
            await self.mark_chat_read(chat_id)

    # ── Handlers de eventos de grupo ──────────────────────────────────────

    async def chat_message(self, event):
        """Nuevo mensaje (entrante o saliente) — reenviar al WebSocket del cliente."""
        await self.send(text_data=json.dumps({
            "type": "chat_message",
            "chat_id": event.get("chat_id"),
            "phone": event.get("phone"),
            "text": event.get("text"),
            "from_me": event.get("from_me", False),
            "timestamp": event.get("timestamp"),
            "sender": event.get("sender"),
            "lead_name": event.get("lead_name", ""),
        }))

    async def lead_update(self, event):
        """Actualización de estado de un lead."""
        await self.send(text_data=json.dumps({
            "type": "lead_update",
            "lead_id": event.get("lead_id"),
            "estado": event.get("estado"),
            "nombre": event.get("nombre"),
        }))

    async def chat_list_update(self, event):
        """Lista de chats actualizada (nuevo chat o conteo de no leídos)."""
        await self.send(text_data=json.dumps({
            "type": "chat_list_update",
            "chats": event.get("chats", []),
        }))

    # ── Helpers de DB ─────────────────────────────────────────────────────

    @database_sync_to_async
    def get_recent_chats(self):
        from leads_admin.models import ChatWhatsApp, MensajeWhatsApp, Lead
        chats = []
        for chat in ChatWhatsApp.objects.using('leads_db').order_by('-last_message_timestamp')[:50]:
            # Buscar lead asociado
            lead_name = ""
            try:
                lead = Lead.objects.using('leads_db').get(telefono=chat.phone)
                lead_name = lead.nombre_establecimiento
            except Lead.DoesNotExist:
                lead_name = chat.phone or ""

            # Contar mensajes no leídos
            unread = MensajeWhatsApp.objects.using('leads_db').filter(
                chat=chat, from_me=False
            ).count()

            chats.append({
                "chat_id": chat.chat_id,
                "phone": chat.phone,
                "lead_name": lead_name,
                "last_message": chat.last_message or "",
                "timestamp": chat.last_message_timestamp.isoformat() if chat.last_message_timestamp else "",
                "unread_count": unread,
            })
        return chats

    @database_sync_to_async
    def get_chat_messages(self, chat_id):
        from leads_admin.models import ChatWhatsApp, MensajeWhatsApp
        try:
            chat = ChatWhatsApp.objects.using('leads_db').get(chat_id=chat_id)
        except ChatWhatsApp.DoesNotExist:
            return []

        msgs = []
        for m in MensajeWhatsApp.objects.using('leads_db').filter(chat=chat).order_by('created_at'):
            msgs.append({
                "id": m.id,
                "text": m.message_text,
                "from_me": m.from_me,
                "sender": m.sender or "",
                "timestamp": m.created_at.isoformat(),
            })
        return msgs

    @database_sync_to_async
    def save_outgoing_message(self, chat_id, phone, text):
        from leads_admin.models import ChatWhatsApp, MensajeWhatsApp
        import time as _time
        chat, _ = ChatWhatsApp.objects.using('leads_db').get_or_create(
            chat_id=chat_id,
            defaults={"phone": phone}
        )
        chat.last_message = text
        chat.last_message_timestamp = timezone.now()
        chat.save(using='leads_db')

        key = f"{chat_id}_out_{_time.time()}"
        MensajeWhatsApp.objects.using('leads_db').create(
            chat=chat,
            message_key=key,
            raw_payload={},
            sender="admin",
            from_me=True,
            message_text=text,
        )

    @database_sync_to_async
    def send_whatsapp_message(self, phone, text):
        from leads_admin.views import enviar_whatsapp
        return enviar_whatsapp(phone, text)

    @database_sync_to_async
    def mark_chat_read(self, chat_id):
        from leads_admin.models import ChatWhatsApp
        try:
            chat = ChatWhatsApp.objects.using('leads_db').get(chat_id=chat_id)
            chat.unread_count = 0
            chat.is_new_chat = False
            chat.save(using='leads_db')
        except ChatWhatsApp.DoesNotExist:
            pass
