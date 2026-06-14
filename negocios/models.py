from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import JSONField
import os
import json
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.utils import timezone


def horario_default():
    """Horario por defecto: Abierto de 10:00 a 22:00 todos los días"""
    return {
        "Lunes": {"inicio": "10:00", "fin": "22:00"},
        "Martes": {"inicio": "10:00", "fin": "22:00"},
        "Miércoles": {"inicio": "10:00", "fin": "22:00"},
        "Jueves": {"inicio": "10:00", "fin": "22:00"},
        "Viernes": {"inicio": "10:00", "fin": "22:00"},
        "Sábado": {"inicio": "10:00", "fin": "22:00"},
        "Domingo": {"inicio": "10:00", "fin": "22:00"},
    }


class Servicio(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)

    def __str__(self):
        return self.nombre

class Negocio(models.Model):
    propietario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='negocios')
    nombre = models.CharField(max_length=100)
    direccion = models.TextField()
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    barrio = models.CharField(max_length=100, blank=True, null=True)
    latitud = models.FloatField(blank=True, null=True)
    longitud = models.FloatField(blank=True, null=True)
    logo = models.ImageField(upload_to='logos_negocios/', blank=True, null=True)
    portada = models.ImageField(upload_to='portadas_negocios/', blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    horario_atencion = models.JSONField(default=horario_default, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    activo = models.BooleanField(default=True)
    
    # ── Feature flags controlados por SaaSSubscription ──
    feature_whatsapp = models.BooleanField(default=False, verbose_name='Recordatorios WhatsApp')
    feature_blacklist = models.BooleanField(default=False, verbose_name='Lista Negra')
    feature_comisiones = models.BooleanField(default=False, verbose_name='Comisiones automáticas')
    feature_estadisticas = models.BooleanField(default=False, verbose_name='Estadísticas avanzadas')
    feature_marketing = models.BooleanField(default=False, verbose_name='Campañas SMS/Email')
    feature_asistente = models.BooleanField(default=False, verbose_name='Asistente de Agenda')
    feature_soporte_vip = models.BooleanField(default=False, verbose_name='Soporte VIP')
    feature_backup = models.BooleanField(default=False, verbose_name='Backup diario')
    
    def __str__(self):
        return self.nombre
    
    @property
    def matriculaciones_aprobadas(self):
        """Devuelve las matriculaciones aprobadas (profesionales activos del negocio)"""
        from profesionales.models import Matriculacion
        return Matriculacion.objects.filter(negocio=self, estado='aprobada').select_related('profesional')


Usuario = get_user_model()

class MetricaNegocio(models.Model):
    """Modelo para almacenar métricas diarias del negocio"""
    negocio = models.ForeignKey(Negocio, on_delete=models.CASCADE, related_name='metricas')
    fecha = models.DateField()
    
    # Métricas de reservas
    total_reservas = models.IntegerField(default=0)
    reservas_completadas = models.IntegerField(default=0)
    reservas_canceladas = models.IntegerField(default=0)
    reservas_no_show = models.IntegerField(default=0)
    
    # Métricas financieras
    ingresos_totales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    promedio_ticket = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Métricas de clientes
    clientes_nuevos = models.IntegerField(default=0)
    clientes_recurrentes = models.IntegerField(default=0)
    
    # El campo 'peluqueros_activos' ha sido eliminado
    horas_trabajadas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    class Meta:
        unique_together = ['negocio', 'fecha']
        ordering = ['-fecha']
    
    def __str__(self):
        return f"{self.negocio.nombre} - {self.fecha}"

class ReporteMensual(models.Model):
    """Modelo para reportes mensuales consolidados"""
    negocio = models.ForeignKey(Negocio, on_delete=models.CASCADE, related_name='reportes_mensuales')
    año = models.IntegerField()
    mes = models.IntegerField()
    
    # Resumen mensual
    total_reservas = models.IntegerField(default=0)
    reservas_completadas = models.IntegerField(default=0)
    ingresos_totales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    promedio_ticket = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Métricas de clientes
    clientes_unicos = models.IntegerField(default=0)
    clientes_nuevos = models.IntegerField(default=0)
    tasa_retencion = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # Porcentaje
    
    # Días más ocupados
    dia_mas_ocupado = models.CharField(max_length=20, blank=True)
    hora_pico = models.CharField(max_length=10, blank=True)
    
    class Meta:
        unique_together = ['negocio', 'año', 'mes']
        ordering = ['-año', '-mes']
    
    def __str__(self):
        return f"{self.negocio.nombre} - {self.año}/{self.mes:02d}"

class ImagenNegocio(models.Model):
    negocio = models.ForeignKey(Negocio, on_delete=models.CASCADE, related_name='imagenes')
    imagen = models.ImageField(upload_to='galeria_negocio/')
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.titulo

# Servicios iniciales fijos - Barbería Masculina
SERVICIOS_FIJOS = [
    'Corte con barba',
    'Corte sin barba',
    'Corte con cejas',
    'Solo trazo (Mickey)',
    'Barba completa',
    'Diseño de cejas',
    'Corte clásico',
    'Corte degradado (Fade)',
    'Afeitado tradicional',
]

def crear_servicios_iniciales():
    for nombre in SERVICIOS_FIJOS:
        Servicio.objects.get_or_create(nombre=nombre)

# Crear servicios base automáticamente después de migraciones
@receiver(post_migrate)
def ensure_servicios_fijos(sender, **kwargs):
    if sender.name == 'negocios':
        crear_servicios_iniciales()

class ServicioNegocio(models.Model):
    negocio = models.ForeignKey('Negocio', on_delete=models.CASCADE, related_name='servicios_negocio')
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE)
    duracion = models.PositiveIntegerField(default=30, help_text='Duración en minutos')
    precio = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, default=25000)
    activo = models.BooleanField(default=True, help_text='¿El servicio está activo/ofrecido por el negocio?')

    class Meta:
        unique_together = ('negocio', 'servicio')
        verbose_name = 'Servicio del Negocio'
        verbose_name_plural = 'Servicios del Negocio'

    def __str__(self):
        return f"{self.negocio.nombre} - {self.servicio.nombre} ({self.duracion} min)"

class NotificacionNegocio(models.Model):
    TIPO_CHOICES = (
        ('matriculacion', 'Nueva Solicitud de Matriculación'),
        ('reserva', 'Nueva Reserva'),
        ('solicitud_ausencia', 'Nueva Solicitud de Ausencia'),
        ('sistema', 'Notificación del Sistema'),
    )
    negocio = models.ForeignKey('Negocio', on_delete=models.CASCADE, related_name='notificaciones_negocio')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    titulo = models.CharField(max_length=200)
    mensaje = models.TextField()
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_lectura = models.DateTimeField(null=True, blank=True)
    url_relacionada = models.URLField(blank=True)

    class Meta:
        verbose_name = 'Notificación Negocio'
        verbose_name_plural = 'Notificaciones Negocio'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"{self.negocio.nombre} - {self.titulo}"

    def marcar_como_leida(self):
        self.leida = True
        self.fecha_lectura = timezone.now()
        self.save()

class DiaDescanso(models.Model):
    """Modelo para gestionar días de descanso de los negocios"""
    TIPO_CHOICES = [
        ('feriado', 'Feriado'),
        ('cierre_especial', 'Cierre Especial'),
        ('mantenimiento', 'Mantenimiento'),
        ('vacaciones', 'Vacaciones'),
        ('otro', 'Otro'),
    ]
    
    negocio = models.ForeignKey(Negocio, on_delete=models.CASCADE, related_name='dias_descanso')
    fecha = models.DateField()
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='feriado')
    motivo = models.CharField(max_length=200, blank=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['negocio', 'fecha']
        ordering = ['-fecha']
    
    def __str__(self):
        return f"{self.negocio.nombre} - {self.fecha} ({self.get_tipo_display()})"
    
    def save(self, *args, **kwargs):
        # Si es un día nuevo, notificar a los profesionales
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new and self.activo:
            self.notificar_profesionales()
    
    def notificar_profesionales(self):
        """Notificar a todos los profesionales del negocio sobre el día de descanso"""
        from profesionales.models import Notificacion, Matriculacion
        
        # Obtener profesionales matriculados y aprobados en este negocio
        matriculaciones_aprobadas = Matriculacion.objects.filter(
            negocio=self.negocio,
            estado='aprobada'
        ).select_related('profesional')
        
        for matriculacion in matriculaciones_aprobadas:
            Notificacion.objects.create(
                profesional=matriculacion.profesional,
                tipo='dia_descanso',
                titulo=f'Día de descanso programado - {self.negocio.nombre}',
                mensaje=f'El negocio {self.negocio.nombre} ha programado un día de descanso el {self.fecha} ({self.get_tipo_display()}). No se podrán realizar reservas en esa fecha.',
                url_relacionada='/profesionales/panel/',
            )


# ==================== MODELOS FINANCIEROS ====================

class ComisionProfesional(models.Model):
    """
    Define la comisión que gana cada profesional por los servicios prestados.
    Puede ser un porcentaje del servicio o un monto fijo.
    """
    TIPO_COMISION_CHOICES = [
        ('porcentaje', 'Porcentaje del servicio'),
        ('fijo', 'Monto fijo por servicio'),
    ]
    
    profesional = models.ForeignKey(
        'profesionales.Profesional', 
        on_delete=models.CASCADE, 
        related_name='comisiones'
    )
    negocio = models.ForeignKey(
        'Negocio', 
        on_delete=models.CASCADE, 
        related_name='comisiones_profesionales'
    )
    
    tipo_comision = models.CharField(
        max_length=20, 
        choices=TIPO_COMISION_CHOICES, 
        default='porcentaje'
    )
    valor = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text='Si es porcentaje: 0-100. Si es fijo: monto en pesos.'
    )
    
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('profesional', 'negocio')
        verbose_name = 'Comisión de Profesional'
        verbose_name_plural = 'Comisiones de Profesionales'
    
    def __str__(self):
        if self.tipo_comision == 'porcentaje':
            return f"{self.profesional.nombre_completo} - {self.valor}% en {self.negocio.nombre}"
        return f"{self.profesional.nombre_completo} - ${self.valor} fijo en {self.negocio.nombre}"
    
    def calcular_comision(self, monto_servicio):
        """Calcula la comisión del profesional basado en el monto del servicio"""
        if self.tipo_comision == 'porcentaje':
            return (monto_servicio * self.valor) / 100
        return self.valor  # Monto fijo


class TransaccionNegocio(models.Model):
    """
    Registra todas las transacciones financieras del negocio.
    Se crea automáticamente cuando una reserva se completa.
    """
    TIPO_CHOICES = [
        ('ingreso', 'Ingreso'),
        ('egreso', 'Egreso'),
    ]
    
    CONCEPTO_CHOICES = [
        ('servicio', 'Servicio prestado'),
        ('suscripcion', 'Pago de suscripción'),
        ('propina', 'Propina'),
        ('comision_profesional', 'Comisión a profesional'),
        ('comision_plataforma', 'Comisión plataforma'),
        ('reembolso', 'Reembolso'),
        ('ajuste', 'Ajuste contable'),
        ('otro', 'Otro'),
    ]
    
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('completada', 'Completada'),
        ('cancelada', 'Cancelada'),
    ]
    
    # Relaciones principales
    negocio = models.ForeignKey(
        'Negocio', 
        on_delete=models.CASCADE, 
        related_name='transacciones'
    )
    profesional = models.ForeignKey(
        'profesionales.Profesional', 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='transacciones'
    )
    reserva = models.ForeignKey(
        'clientes.Reserva', 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='transacciones'
    )
    
    # Información de la transacción
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    concepto = models.CharField(max_length=50, choices=CONCEPTO_CHOICES)
    descripcion = models.CharField(max_length=300, blank=True)
    
    # Montos
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    comision_profesional = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Monto que corresponde al profesional'
    )
    comision_negocio = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Monto que corresponde al negocio'
    )
    
    # Estado y método de pago
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='completada')
    metodo_pago = models.CharField(
        max_length=50, blank=True, null=True,
        choices=[
            ('efectivo', 'Efectivo'),
            ('tarjeta', 'Tarjeta'),
            ('transferencia', 'Transferencia'),
            ('mixto', 'Mixto'),
        ]
    )
    
    # Auditoría
    fecha = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='transacciones_creadas'
    )
    notas = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Transacción del Negocio'
        verbose_name_plural = 'Transacciones del Negocio'
        indexes = [
            models.Index(fields=['negocio', 'fecha']),
            models.Index(fields=['profesional', 'fecha']),
            models.Index(fields=['tipo', 'concepto']),
        ]
    
    def __str__(self):
        return f"{self.get_tipo_display()} - ${self.monto} - {self.get_concepto_display()} ({self.fecha.strftime('%d/%m/%Y')})"
    
    @classmethod
    def crear_desde_reserva(cls, reserva, metodo_pago='efectivo', creado_por=None):
        """
        Crea una transacción de ingreso a partir de una reserva completada.
        También calcula y registra las comisiones.
        """
        if not reserva.total:
            return None
        
        monto_total = reserva.total
        comision_prof = 0
        comision_neg = monto_total
        
        # Calcular comisión del profesional si existe configuración
        if reserva.profesional:
            try:
                config_comision = ComisionProfesional.objects.get(
                    profesional=reserva.profesional,
                    negocio=reserva.peluquero,
                    activo=True
                )
                comision_prof = config_comision.calcular_comision(monto_total)
                comision_neg = monto_total - comision_prof
            except ComisionProfesional.DoesNotExist:
                # Si no hay configuración, todo va al negocio
                pass
        
        # Crear la transacción principal (ingreso)
        transaccion = cls.objects.create(
            negocio=reserva.peluquero,
            profesional=reserva.profesional,
            reserva=reserva,
            tipo='ingreso',
            concepto='servicio',
            descripcion=f"Servicio: {reserva.servicio.servicio.nombre if reserva.servicio else 'N/A'} - Cliente: {reserva.cliente.username}",
            monto=monto_total,
            comision_profesional=comision_prof,
            comision_negocio=comision_neg,
            estado='completada',
            metodo_pago=metodo_pago,
            creado_por=creado_por,
        )
        
        return transaccion


class ResumenFinancieroMensual(models.Model):
    """
    Resumen pre-calculado de las finanzas mensuales del negocio.
    Se actualiza automáticamente o mediante un comando de gestión.
    """
    negocio = models.ForeignKey(
        'Negocio', 
        on_delete=models.CASCADE, 
        related_name='resumenes_financieros'
    )
    mes = models.PositiveIntegerField()  # 1-12
    anio = models.PositiveIntegerField()
    
    # Totales
    ingresos_servicios = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    ingresos_suscripciones = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    ingresos_otros = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_ingresos = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    total_egresos = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    comisiones_profesionales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Contadores
    total_reservas = models.PositiveIntegerField(default=0)
    reservas_completadas = models.PositiveIntegerField(default=0)
    reservas_canceladas = models.PositiveIntegerField(default=0)
    
    # Auditoría
    fecha_calculo = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('negocio', 'mes', 'anio')
        ordering = ['-anio', '-mes']
        verbose_name = 'Resumen Financiero Mensual'
        verbose_name_plural = 'Resúmenes Financieros Mensuales'
    
    def __str__(self):
        return f"{self.negocio.nombre} - {self.mes}/{self.anio}"

