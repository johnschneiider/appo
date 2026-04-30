from django.db import models

class Lead(models.Model):
    fecha_ingreso = models.DateTimeField(null=True, blank=True)
    nombre_establecimiento = models.CharField(max_length=255)
    ciudad = models.CharField(max_length=100)
    departamento = models.CharField(max_length=100)
    telefono = models.CharField(max_length=50)
    proyecto = models.CharField(max_length=100)
    prioridad = models.IntegerField(default=0)
    estado = models.CharField(max_length=50, default='Nuevo')
    tiene_web = models.BooleanField(default=False)
    direccion = models.TextField(null=True, blank=True)
    notas = models.TextField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'leads'
        verbose_name = 'Lead de Prospección'
        verbose_name_plural = 'Leads de Prospección'

    def __str__(self):
        return f"{self.nombre_establecimiento} - {self.ciudad}"


class ChatWhatsApp(models.Model):
    """Conversaciones de WhatsApp capturadas desde webhooks"""
    chat_id = models.CharField(max_length=200, unique=True, db_index=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    contact_name = models.CharField(max_length=200, null=True, blank=True)
    last_message = models.TextField(null=True, blank=True)
    last_message_timestamp = models.DateTimeField(null=True, blank=True)
    unread_count = models.IntegerField(default=0)
    is_group = models.BooleanField(default=False)
    is_new_chat = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = True
        db_table = 'chat_whatsapp'
        ordering = ['-last_message_timestamp']
        verbose_name = 'Chat WhatsApp'
        verbose_name_plural = 'Chats WhatsApp'
    
    def __str__(self):
        contact = self.contact_name or self.phone
        return f"ChatWhatsApp {self.chat_id} ({contact or 'Desconocido'})"


class MensajeWhatsApp(models.Model):
    """Mensaje de WhatsApp guardado del webhook"""
    chat = models.ForeignKey(ChatWhatsApp, on_delete=models.CASCADE)
    message_key = models.CharField(max_length=100, unique=True)
    # remoteJid, fromMe, etc
    raw_payload = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    # Campos derivados
    sender = models.CharField(max_length=20, null=True, blank=True)
    from_me = models.BooleanField(default=False)
    message_text = models.TextField()
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = True
        db_table = 'mensaje_whatsapp'
        verbose_name = 'Mensaje WhatsApp'
        verbose_name_plural = 'Mensajes WhatsApp'
    
    def __str__(self):
        text_preview = self.message_text[:30] + ('...' if len(self.message_text) > 30 else '')
        return f"WhatsApp {self.sender}: {text_preview}"



class LeadConversacion(models.Model):
    lead = models.ForeignKey('Lead', on_delete=models.CASCADE, related_name='conversaciones')
    mensajes = models.JSONField(default=list)
    # Formato de cada mensaje en el array:
    # {"role": "assistant"|"user", "content": "...", "timestamp": "ISO8601"}
    ultimo_contacto = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=30, default='nuevo', choices=[
        ('nuevo', 'Nuevo'),
        ('contactado', 'Contactado'),
        ('en_seguimiento', 'En seguimiento'),
        ('followup_24h', 'Follow‑up 24h'),
        ('followup_48h', 'Follow‑up 48h'),
        ('no_respondio', 'No respondió'),
        ('convertido', 'Convertido'),
    ])
    followup_enviado = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lead_conversacion'
        verbose_name = 'Conversación de Lead'
        verbose_name_plural = 'Conversaciones de Leads'

    def __str__(self):
        return f"Conversación de {self.lead.nombre_establecimiento} ({self.estado})"