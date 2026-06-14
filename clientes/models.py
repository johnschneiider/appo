from django.db import models
from negocios.models import Negocio, ServicioNegocio
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

class ActividadUsuario(models.Model):
    """Modelo para registrar todas las actividades de los usuarios"""
    TIPOS_ACTIVIDAD = [
        ('visita_negocio', 'Visita a negocio'),
        ('reserva_creada', 'Reserva creada'),
        ('reserva_cancelada', 'Reserva cancelada'),
        ('reserva_completada', 'Reserva completada'),
        ('calificacion_creada', 'Calificación creada'),
        ('busqueda_realizada', 'Búsqueda realizada'),
        ('login', 'Inicio de sesión'),
        ('logout', 'Cierre de sesión'),
        ('registro', 'Registro de usuario'),
        ('perfil_actualizado', 'Perfil actualizado'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='actividades')
    tipo = models.CharField(max_length=50, choices=TIPOS_ACTIVIDAD)
    objeto_id = models.PositiveIntegerField(null=True, blank=True, help_text='ID del objeto relacionado (negocio, reserva, etc.)')
    objeto_tipo = models.CharField(max_length=50, null=True, blank=True, help_text='Tipo de objeto relacionado')
    descripcion = models.TextField(blank=True)
    datos_adicionales = models.JSONField(default=dict, blank=True, help_text='Datos adicionales en formato JSON')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Actividad de Usuario'
        verbose_name_plural = 'Actividades de Usuario'
        indexes = [
            models.Index(fields=['usuario', 'tipo', '-fecha_creacion']),
            models.Index(fields=['objeto_tipo', 'objeto_id']),
        ]
    
    def __str__(self):
        return f"{self.usuario.username} - {self.get_tipo_display()} - {self.fecha_creacion}"
    
    @classmethod
    def registrar_actividad(cls, usuario, tipo, objeto_id=None, objeto_tipo=None, 
                          descripcion='', datos_adicionales=None, request=None):
        """Método de clase para registrar una actividad"""
        if not usuario.is_authenticated:
            return None
            
        # Limitar datos adicionales para evitar sobrecarga
        if datos_adicionales and len(str(datos_adicionales)) > 1000:
            datos_adicionales = {'error': 'Datos truncados por tamaño'}
        
        # Limpiar descripción si es muy larga
        if len(descripcion) > 500:
            descripcion = descripcion[:497] + '...'
        
        actividad = cls(
            usuario=usuario,
            tipo=tipo,
            objeto_id=objeto_id,
            objeto_tipo=objeto_tipo,
            descripcion=descripcion,
            datos_adicionales=datos_adicionales or {},
            ip_address=request.META.get('REMOTE_ADDR') if request else None,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500] if request else ''
        )
        actividad.save()
        return actividad

class ClienteProvisional(models.Model):
    """Modelo para almacenar clientes que no tienen cuenta en el sistema"""
    nombre = models.CharField(max_length=200, help_text='Nombre completo del cliente')
    telefono = models.CharField(max_length=15, help_text='Teléfono de contacto')
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='clientes_provisionales_creados',
        help_text='Usuario del negocio que creó este cliente provisional'
    )
    negocio = models.ForeignKey(
        Negocio,
        on_delete=models.CASCADE,
        related_name='clientes_provisionales',
        help_text='Negocio al que pertenece este cliente provisional'
    )
    notas = models.TextField(blank=True, help_text='Notas adicionales sobre el cliente')
    
    class Meta:
        verbose_name = 'Cliente Provisional'
        verbose_name_plural = 'Clientes Provisionales'
        ordering = ['-creado_en']
        indexes = [
            models.Index(fields=['negocio', '-creado_en']),
            models.Index(fields=['telefono']),
        ]
    
    def __str__(self):
        return f"{self.nombre} ({self.telefono})"
    
    def get_full_name(self):
        """Retorna el nombre completo del cliente"""
        return self.nombre

class Reserva(models.Model):
    cliente = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='reservas_cliente',
        null=True,
        blank=True,
        help_text='Cliente con cuenta en el sistema (opcional si es cliente provisional)'
    )
    cliente_provisional = models.ForeignKey(
        ClienteProvisional,
        on_delete=models.CASCADE,
        related_name='reservas',
        null=True,
        blank=True,
        help_text='Cliente provisional sin cuenta (opcional si es cliente con cuenta)'
    )
    peluquero = models.ForeignKey(Negocio, on_delete=models.CASCADE, related_name='reservas_peluquero')
    profesional = models.ForeignKey('profesionales.Profesional', on_delete=models.CASCADE, null=True, blank=True, related_name='reservas_profesional')
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    servicio = models.ForeignKey(ServicioNegocio, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservas_servicio')
    creado_en = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=[
        ('pendiente', 'Pendiente'),
        ('confirmado', 'Confirmado'),
        ('cancelado', 'Cancelado'),
        ('completado', 'Completado'),
        ('inasistencia', 'Inasistencia'),
    ], default='pendiente')
    notas = models.TextField(blank=True)
    
    # Campos para recordatorios
    recordatorio_dia_enviado = models.BooleanField(default=False, help_text='Recordatorio de 1 día antes enviado')
    recordatorio_tres_horas_enviado = models.BooleanField(default=False, help_text='Recordatorio de 3 horas antes enviado')
    
    # Imagen de referencia (para que el cliente muestre el corte que desea)
    imagen_referencia = models.ImageField(
        upload_to='reservas/referencias/',
        blank=True, null=True,
        help_text='Imagen de referencia del corte deseado'
    )
    
    # ========== SNAPSHOT DEL SERVICIO (captura valores al momento de la reserva) ==========
    # Esto asegura que si el negocio cambia precio/duración después, las reservas pasadas conservan sus valores
    
    duracion_servicio = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Duración del servicio en minutos al momento de la reserva'
    )
    precio_servicio = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Precio del servicio al momento de la reserva'
    )
    descuento = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Descuento aplicado'
    )
    total = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Total a pagar (precio_servicio - descuento)'
    )
    metodo_pago = models.CharField(
        max_length=50, blank=True, null=True,
        choices=[
            ('efectivo', 'Efectivo'),
            ('tarjeta', 'Tarjeta'),
            ('transferencia', 'Transferencia'),
            ('mixto', 'Mixto'),
            ('pendiente', 'Pendiente de pago'),
        ],
        default='pendiente'
    )
    pagado = models.BooleanField(default=False, help_text='¿El cliente ya pagó?')

    class Meta:
        ordering = ['fecha', 'hora_inicio']
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'
    
    def clean(self):
        """Validar que haya un cliente (con cuenta o provisional)"""
        from django.core.exceptions import ValidationError
        if not self.cliente and not self.cliente_provisional:
            raise ValidationError('Debe especificar un cliente con cuenta o un cliente provisional')
        if self.cliente and self.cliente_provisional:
            raise ValidationError('No puede tener cliente con cuenta y cliente provisional al mismo tiempo')
    
    def get_cliente_nombre(self):
        """Retorna el nombre del cliente (con cuenta o provisional)"""
        if self.cliente:
            return self.cliente.get_full_name() or self.cliente.username
        elif self.cliente_provisional:
            return self.cliente_provisional.nombre
        return "Cliente desconocido"
    
    def get_cliente_telefono(self):
        """Retorna el teléfono del cliente (con cuenta o provisional)"""
        if self.cliente:
            return self.cliente.telefono or ""
        elif self.cliente_provisional:
            return self.cliente_provisional.telefono
        return ""
    
    def get_cliente_username(self):
        """Retorna el username o nombre del cliente"""
        if self.cliente:
            return self.cliente.username
        elif self.cliente_provisional:
            return self.cliente_provisional.nombre
        return "Cliente desconocido"
    
    def es_cliente_provisional(self):
        """Retorna True si es un cliente provisional"""
        return self.cliente_provisional is not None

    def __str__(self):
        cliente_str = self.get_cliente_nombre()
        return f"Reserva de {cliente_str} con {self.profesional or self.peluquero} el {self.fecha} a las {self.hora_inicio}"
    
    def save(self, *args, **kwargs):
        """
        Guarda el precio y duración del servicio al momento de crear la reserva.
        Esto crea un 'snapshot' de los valores actuales, así si el negocio
        cambia el precio o duración después, las reservas pasadas conservan
        los valores que tenían cuando fueron creadas.
        """
        # Validar que haya un cliente
        self.clean()
        
        # Solo capturar valores si es una nueva reserva o si no tienen valores asignados
        if self.servicio:
            # Capturar precio si no está asignado
            if self.precio_servicio is None:
                self.precio_servicio = self.servicio.precio or 0
            
            # Capturar duración si no está asignada (usar is None para permitir 0)
            if self.duracion_servicio is None:
                duracion = self.servicio.duracion
                self.duracion_servicio = duracion if duracion is not None else 30  # Default 30 min solo si es None
        
        # Calcular total
        if self.precio_servicio is not None:
            self.total = self.precio_servicio - (self.descuento or 0)
        
        super().save(*args, **kwargs)
    
    def confirmar(self, notas_adicionales=""):
        """
        Confirma una reserva pendiente
        """
        if self.estado != 'pendiente':
            raise ValidationError(f"No se puede confirmar una reserva en estado '{self.estado}'")
        
        self.estado = 'confirmado'
        if notas_adicionales:
            self.notas = f"{self.notas}\n[Confirmado] {notas_adicionales}" if self.notas else f"[Confirmado] {notas_adicionales}"
        self.save()
        
        # Crear notificación para el cliente (solo si tiene cuenta)
        if self.cliente:
            self._crear_notificacion_cliente(
                'reserva',
                'Reserva Confirmada',
                f'Tu reserva del {self.fecha} a las {self.hora_inicio} ha sido confirmada.',
                '/clientes/mis_reservas/'
            )
        
        # Crear notificación para el profesional
        self._crear_notificacion_profesional(
            'reserva',
            'Reserva Confirmada',
            f'Nueva reserva confirmada para el {self.fecha} a las {self.hora_inicio} con {self.get_cliente_username()}.',
            '/profesionales/panel/'
        )
        
        return True
    
    def cancelar(self, motivo="", cancelado_por="sistema"):
        """
        Cancela una reserva (pendiente o confirmada)
        """
        logger = logging.getLogger(__name__)
        
        logger.info(f"Intentando cancelar reserva {self.id}, estado actual: {self.estado}")
        
        if self.estado not in ['pendiente', 'confirmado']:
            error_msg = f"No se puede cancelar una reserva en estado '{self.estado}'"
            logger.error(f"Error al cancelar reserva {self.id}: {error_msg}")
            raise ValidationError(error_msg)
        
        try:
            estado_anterior = self.estado
            self.estado = 'cancelado'
            
            # Agregar motivo de cancelación
            cancelacion_texto = f"\n[Cancelado por {cancelado_por}] {motivo}" if motivo else f"\n[Cancelado por {cancelado_por}]"
            self.notas = f"{self.notas}{cancelacion_texto}" if self.notas else cancelacion_texto
            
            logger.info(f"Guardando reserva {self.id} con estado cancelado")
            self.save()
            
            # Crear notificación para el cliente
            mensaje = f'Tu reserva del {self.fecha} a las {self.hora_inicio} ha sido cancelada.'
            if motivo:
                mensaje += f' Motivo: {motivo}'
            
            # Crear notificación para el cliente (solo si tiene cuenta)
            if self.cliente:
                logger.info(f"Creando notificación para cliente {self.get_cliente_username()}")
                self._crear_notificacion_cliente(
                    'reserva',
                    'Reserva Cancelada',
                    mensaje,
                    '/clientes/mis_reservas/'
                )
            
            # Crear notificación para el profesional
            mensaje_profesional = f'Reserva cancelada para el {self.fecha} a las {self.hora_inicio} con {self.get_cliente_username()}.'
            
            if motivo:
                mensaje_profesional += f' Motivo: {motivo}'
            
            logger.info(f"Creando notificación para profesional")
            self._crear_notificacion_profesional(
                'reserva',
                'Reserva Cancelada',
                mensaje_profesional,
                '/profesionales/panel/'
            )
            
            # Log de actividad
            from cuentas.utils import log_reservation_activity
            log_reservation_activity(
                user=self.cliente if self.cliente else None,
                reservation=self,
                action="reserva_cancelada",
                details=f"Cancelada por {cancelado_por}. Motivo: {motivo}"
            )
            
            logger.info(f"Reserva {self.id} cancelada exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"Error al cancelar reserva {self.id}: {str(e)}")
            raise
    
    def marcar_inasistencia(self, motivo=""):
        """
        Marca una reserva como inasistencia (solo para reservas pasadas)
        """
        logger = logging.getLogger(__name__)
        
        logger.info(f"Intentando marcar inasistencia en reserva {self.id}, estado actual: {self.estado}")
        
        # Verificar que la reserva ya pasó
        from .utils import is_fecha_pasada
        if not is_fecha_pasada(self.fecha, self.hora_fin):
            error_msg = "Solo se puede marcar inasistencia en reservas que ya pasaron"
            logger.error(f"Error al marcar inasistencia en reserva {self.id}: {error_msg}")
            raise ValidationError(error_msg)
        
        if self.estado not in ['pendiente', 'confirmado', 'completado']:
            error_msg = f"No se puede marcar inasistencia en una reserva en estado '{self.estado}'"
            logger.error(f"Error al marcar inasistencia en reserva {self.id}: {error_msg}")
            raise ValidationError(error_msg)
        
        try:
            estado_anterior = self.estado
            self.estado = 'inasistencia'
            
            # Agregar motivo de inasistencia
            inasistencia_texto = f"\n[Inasistencia marcada] {motivo}" if motivo else "\n[Inasistencia marcada]"
            self.notas = f"{self.notas}{inasistencia_texto}" if self.notas else inasistencia_texto
            
            logger.info(f"Guardando reserva {self.id} con estado inasistencia")
            self.save()
            
            # Crear notificación para el cliente
            mensaje = f'Tu reserva del {self.fecha} a las {self.hora_inicio} ha sido marcada como inasistencia.'
            if motivo:
                mensaje += f' Motivo: {motivo}'
            
            # Crear notificación para el cliente (solo si tiene cuenta)
            if self.cliente:
                logger.info(f"Creando notificación para cliente {self.get_cliente_username()}")
                self._crear_notificacion_cliente(
                    'reserva',
                    'Inasistencia Registrada',
                    mensaje,
                    '/clientes/mis_reservas/'
                )
            
            # Crear notificación para el profesional
            mensaje_profesional = f'Inasistencia registrada para el {self.fecha} a las {self.hora_inicio} con {self.get_cliente_username()}.'
            
            if motivo:
                mensaje_profesional += f' Motivo: {motivo}'
            
            logger.info(f"Creando notificación para profesional")
            self._crear_notificacion_profesional(
                'reserva',
                'Inasistencia Registrada',
                mensaje_profesional,
                '/profesionales/panel/'
            )
            
            # Verificar si se debe bloquear al cliente según la política del negocio
            self._verificar_y_aplicar_bloqueo()
            
            # Log de actividad
            from cuentas.utils import log_reservation_activity
            log_reservation_activity(
                user=self.cliente if self.cliente else None,
                reservation=self,
                action="reserva_inasistencia",
                details=f"Inasistencia marcada. Motivo: {motivo}"
            )
            
            logger.info(f"Reserva {self.id} marcada como inasistencia exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"Error al marcar inasistencia en reserva {self.id}: {str(e)}")
            raise
            if motivo:
                mensaje_profesional += f' Motivo: {motivo}'
            
            self._crear_notificacion_profesional(
                'reserva',
                'Reserva Cancelada',
                mensaje_profesional,
                '/profesionales/panel/'
            )
            
            logger.info(f"Reserva {self.id} cancelada exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"Error inesperado al cancelar reserva {self.id}: {str(e)}")
            raise
    
    def completar(self, notas_adicionales=""):
        """
        Marca una reserva confirmada como completada
        """
        if self.estado != 'confirmado':
            raise ValidationError(f"No se puede completar una reserva en estado '{self.estado}'")
        
        self.estado = 'completado'
        if notas_adicionales:
            self.notas = f"{self.notas}\n[Completado] {notas_adicionales}" if self.notas else f"[Completado] {notas_adicionales}"
        self.save()

    def _verificar_y_aplicar_bloqueo(self):
        """
        Verifica si el cliente debe ser bloqueado según la política de inasistencias del negocio
        y aplica el bloqueo si es necesario.
        """
        logger = logging.getLogger(__name__)
        
        try:
            # Obtener configuración del negocio
            config = getattr(self.peluquero, 'configuracion_inasistencias', {})
            max_inasistencias = config.get('max_inasistencias', 3)
            
            # Contar inasistencias del cliente en este negocio
            # Solo para clientes con cuenta (los provisionales no se bloquean automáticamente)
            if not self.cliente:
                return
            
            total_inasistencias = Reserva.objects.filter(
                cliente=self.cliente,
                peluquero=self.peluquero,
                estado='inasistencia'
            ).count()
            
            logger.info(f"Cliente {self.get_cliente_username()} tiene {total_inasistencias} inasistencias en {self.peluquero.nombre} (máximo permitido: {max_inasistencias})")
            
            # Si alcanza o supera el máximo, bloquear
            if total_inasistencias >= max_inasistencias:
                # Importar aquí para evitar importación circular (BloqueoCliente está definido después)
                from clientes.models import BloqueoCliente
                motivo = f"Cliente bloqueado por {total_inasistencias} inasistencias (máximo permitido: {max_inasistencias})"
                BloqueoCliente.crear_bloqueo(
                    cliente=self.cliente if self.cliente else None,
                    cliente_provisional=self.cliente_provisional if self.cliente_provisional else None,
                    negocio=self.peluquero,
                    motivo=motivo,
                    inasistencias_count=total_inasistencias
                )
                logger.info(f"Cliente {self.get_cliente_username()} bloqueado automáticamente en {self.peluquero.nombre}")
        except Exception as e:
            logger.error(f"Error al verificar bloqueo para cliente {self.get_cliente_username()}: {str(e)}")
            # No lanzar excepción para no interrumpir el flujo de marcar inasistencia
        
        # Crear notificación para el cliente (solo si tiene cuenta)
        if self.cliente:
            self._crear_notificacion_cliente(
                'reserva',
                'Reserva Completada',
                f'Tu reserva del {self.fecha} a las {self.hora_inicio} ha sido marcada como completada.',
                '/clientes/mis_reservas/'
            )
        
        # Crear notificación para el profesional
        self._crear_notificacion_profesional(
            'reserva',
            'Reserva Completada',
            f'Reserva completada para el {self.fecha} a las {self.hora_inicio} con {self.get_cliente_username()}.',
            '/profesionales/panel/'
        )
        
        return True
    
    def reagendar(self, nueva_fecha, nueva_hora_inicio, nueva_hora_fin, motivo=""):
        """
        Reagenda una reserva confirmada o pendiente
        """
        if self.estado not in ['pendiente', 'confirmado']:
            raise ValidationError(f"No se puede reagendar una reserva en estado '{self.estado}'")
        
        fecha_anterior = self.fecha
        hora_anterior = self.hora_inicio
        
        self.fecha = nueva_fecha
        self.hora_inicio = nueva_hora_inicio
        self.hora_fin = nueva_hora_fin
        self.estado = 'confirmado'  # Reagendar confirma la reserva
        
        if motivo:
            self.notas = f"{self.notas}\n[Reagendado] {motivo}" if self.notas else f"[Reagendado] {motivo}"
        
        self.save()
        
        # Crear notificación para el cliente (solo si tiene cuenta)
        if self.cliente:
            self._crear_notificacion_cliente(
                'reserva',
                'Reserva Reagendada',
                f'Tu reserva ha sido reagendada del {fecha_anterior} a las {hora_anterior} al {nueva_fecha} a las {nueva_hora_inicio}.',
                '/clientes/mis_reservas/'
            )
        
        # Crear notificación para el profesional
        self._crear_notificacion_profesional(
            'reserva',
            'Reserva Reagendada',
            f'Reserva reagendada de {fecha_anterior} a las {hora_anterior} al {nueva_fecha} a las {nueva_hora_inicio} con {self.get_cliente_username()}.',
            '/profesionales/panel/'
        )
        
        return True
    
    def _crear_notificacion_cliente(self, tipo, titulo, mensaje, url=""):
        """
        Método privado para crear notificaciones para el cliente
        """
        if not self.cliente:
            return  # Reservas sin cliente (datos legacy) - ignorar
        NotificacionCliente.objects.create(
            cliente=self.cliente,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            url_relacionada=url
        )
    
    def _crear_notificacion_profesional(self, tipo, titulo, mensaje, url=""):
        """
        Método privado para crear notificaciones para el profesional
        """
        if self.profesional:
            from profesionales.models import Notificacion
            Notificacion.objects.create(
                profesional=self.profesional,
                tipo=tipo,
                titulo=titulo,
                mensaje=mensaje,
                url_relacionada=url
            )
    
    @property
    def puede_ser_cancelada(self):
        """
        Verifica si la reserva puede ser cancelada
        """
        return self.estado in ['pendiente', 'confirmado']
    
    @property
    def puede_ser_completada(self):
        """
        Verifica si la reserva puede ser completada
        """
        return self.estado == 'confirmado'
    
    @property
    def puede_ser_reagendada(self):
        """
        Verifica si la reserva puede ser reagendada
        """
        return self.estado in ['pendiente', 'confirmado']
    
    @property
    def es_pasada(self):
        """
        Verifica si la reserva es de una fecha pasada
        """
        from django.utils import timezone
        return self.fecha < timezone.now().date()
    
    @property
    def es_hoy(self):
        """
        Verifica si la reserva es para hoy
        """
        from django.utils import timezone
        return self.fecha == timezone.now().date()

class Calificacion(models.Model):
    negocio = models.ForeignKey('negocios.Negocio', on_delete=models.CASCADE, related_name='calificaciones')
    profesional = models.ForeignKey('profesionales.Profesional', on_delete=models.CASCADE, related_name='calificaciones')
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='calificaciones')
    puntaje = models.PositiveSmallIntegerField(default=5)
    comentario = models.TextField(blank=True)
    fecha_calificacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_calificacion']
        verbose_name = 'Calificación'
        verbose_name_plural = 'Calificaciones'

    def __str__(self):
        return f"{self.negocio} - {self.profesional} - {self.puntaje}"

class MetricaCliente(models.Model):
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='metricas_cliente')
    fecha = models.DateField()
    total_turnos = models.IntegerField(default=0)
    turnos_completados = models.IntegerField(default=0)
    turnos_cancelados = models.IntegerField(default=0)
    servicios_mas_solicitados = models.CharField(max_length=200, blank=True)
    profesionales_mas_reservados = models.CharField(max_length=200, blank=True)
    class Meta:
        unique_together = ['cliente', 'fecha']
        ordering = ['-fecha']
    def __str__(self):
        return f"{str(self.cliente)} - {self.fecha}"

class NotificacionCliente(models.Model):
    TIPO_CHOICES = (
        ('reserva', 'Nueva Reserva'),
        ('sistema', 'Notificación del Sistema'),
    )
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notificaciones_cliente')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    titulo = models.CharField(max_length=200)
    mensaje = models.TextField()
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_lectura = models.DateTimeField(null=True, blank=True)
    url_relacionada = models.URLField(blank=True)

    class Meta:
        verbose_name = 'Notificación Cliente'
        verbose_name_plural = 'Notificaciones Cliente'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"{str(self.cliente)} - {self.titulo}"

    def marcar_como_leida(self):
        self.leida = True
        self.fecha_lectura = timezone.now()
        self.save()


class BloqueoCliente(models.Model):
    """
    Modelo para rastrear bloqueos de clientes por inasistencias en un negocio específico.
    El bloqueo impide que el cliente vea horarios disponibles al intentar agendar.
    """
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bloqueos_cliente')
    negocio = models.ForeignKey(Negocio, on_delete=models.CASCADE, related_name='bloqueos_negocio')
    fecha_bloqueo = models.DateTimeField(auto_now_add=True, help_text='Fecha en que se aplicó el bloqueo')
    fecha_desbloqueo = models.DateTimeField(null=True, blank=True, help_text='Fecha en que se desbloqueó (si es manual)')
    motivo = models.TextField(help_text='Motivo del bloqueo (ej: múltiples inasistencias)')
    inasistencias_que_causaron = models.IntegerField(default=0, help_text='Número de inasistencias que causaron el bloqueo')
    activo = models.BooleanField(default=True, help_text='Si el bloqueo está activo')
    desbloqueado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='bloqueos_desbloqueados',
        help_text='Usuario que desbloqueó manualmente'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Bloqueo de Cliente'
        verbose_name_plural = 'Bloqueos de Clientes'
        ordering = ['-fecha_creacion']
        unique_together = [['cliente', 'negocio', 'activo']]
        indexes = [
            models.Index(fields=['cliente', 'negocio', 'activo']),
            models.Index(fields=['negocio', 'activo']),
        ]

    def __str__(self):
        estado = "Activo" if self.activo else "Desbloqueado"
        return f"{self.cliente.username} - {self.negocio.nombre} ({estado})"

    def desbloquear(self, usuario=None):
        """Desbloquea al cliente manualmente"""
        self.activo = False
        self.fecha_desbloqueo = timezone.now()
        if usuario:
            self.desbloqueado_por = usuario
        self.save()

    @classmethod
    def esta_bloqueado(cls, cliente, negocio):
        """Verifica si un cliente está bloqueado para un negocio específico"""
        return cls.objects.filter(
            cliente=cliente,
            negocio=negocio,
            activo=True
        ).exists()

    @classmethod
    def crear_bloqueo(cls, cliente, negocio, motivo, inasistencias_count):
        """Crea un nuevo bloqueo para un cliente"""
        # Desactivar bloqueos anteriores si existen
        cls.objects.filter(cliente=cliente, negocio=negocio, activo=True).update(activo=False)
        
        # Crear nuevo bloqueo
        bloqueo = cls.objects.create(
            cliente=cliente,
            negocio=negocio,
            motivo=motivo,
            inasistencias_que_causaron=inasistencias_count,
            activo=True
        )
        return bloqueo

class RecuperacionCliente(models.Model):
    """
    Tracking anti-spam del sistema Win-Back (recuperación de clientes).
    Registra cada intento de recuperación enviado por WhatsApp para:
      - evitar reenviar al mismo cliente dentro de una ventana,
      - medir respuesta y reagende (conversión).
    Tipos:
      - no_show:  cliente con inasistencia reciente → invitar a reagendar.
      - inactivo: cliente que lleva varios días sin peluquearse → recordar que toca cita.
    """
    TIPO_CHOICES = [
        ('no_show', 'No-show (inasistencia)'),
        ('inactivo', 'Inactivo (toca peluquearse)'),
    ]

    cliente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recuperaciones',
        null=True, blank=True,
    )
    cliente_provisional = models.ForeignKey(
        ClienteProvisional,
        on_delete=models.CASCADE,
        related_name='recuperaciones',
        null=True, blank=True,
    )
    negocio = models.ForeignKey(
        Negocio,
        on_delete=models.CASCADE,
        related_name='recuperaciones',
    )
    # Reserva que originó el intento (para no_show); opcional para inactivo
    reserva_origen = models.ForeignKey(
        'Reserva',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='recuperaciones',
    )
    telefono = models.CharField(max_length=20, blank=True, help_text='Teléfono al que se envió')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    fecha_envio = models.DateTimeField(auto_now_add=True)
    enviado_ok = models.BooleanField(default=False, help_text='El envío por WhatsApp fue exitoso')
    respondio = models.BooleanField(default=False, help_text='El cliente respondió al mensaje')
    reagendo = models.BooleanField(default=False, help_text='El cliente volvió a reservar tras el mensaje')
    opt_out = models.BooleanField(default=False, help_text='El cliente pidió no recibir más mensajes')
    detalle = models.TextField(blank=True, help_text='Notas/errores del envío')

    class Meta:
        verbose_name = 'Recuperación de Cliente (Win-Back)'
        verbose_name_plural = 'Recuperaciones de Clientes (Win-Back)'
        ordering = ['-fecha_envio']
        indexes = [
            models.Index(fields=['negocio', 'tipo', 'fecha_envio']),
            models.Index(fields=['telefono', 'fecha_envio']),
            models.Index(fields=['cliente', 'tipo']),
            models.Index(fields=['cliente_provisional', 'tipo']),
        ]

    def __str__(self):
        nombre = (self.cliente.get_full_name() or self.cliente.username) if self.cliente else (
            self.cliente_provisional.nombre if self.cliente_provisional else self.telefono
        )
        return f"{nombre} - {self.get_tipo_display()} ({self.fecha_envio:%Y-%m-%d})"

    @classmethod
    def opt_out_telefono(cls, telefono):
        """True si ese teléfono pidió alguna vez no recibir más win-backs."""
        if not telefono:
            return False
        return cls.objects.filter(telefono=telefono, opt_out=True).exists()
