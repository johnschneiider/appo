from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import Reserva, MetricaCliente
from negocios.models import MetricaNegocio, ReporteMensual, Negocio
from profesionales.models import MetricaProfesional
from datetime import date
from django.db import transaction
from collections import Counter
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

@receiver([post_save, post_delete], sender=Reserva)
def actualizar_metricas_reserva(sender, instance, **kwargs):
    negocio = instance.peluquero
    fecha = instance.fecha
    # Actualizar métrica diaria
    metrica, _ = MetricaNegocio.objects.get_or_create(negocio=negocio, fecha=fecha)
    reservas = Reserva.objects.filter(peluquero=negocio, fecha=fecha)
    metrica.total_reservas = reservas.count()
    metrica.reservas_completadas = reservas.filter(estado='completado').count()
    metrica.reservas_canceladas = reservas.filter(estado='cancelado').count()
    metrica.reservas_no_show = reservas.filter(estado='no_show').count() if 'no_show' in dict(Reserva._meta.get_field('estado').choices) else 0
    # Ingresos y promedio ticket
    total_ingresos = 0
    for r in reservas:
        if r.servicio and hasattr(r.servicio, 'servicionegocio_set'):
            sn = r.servicio.servicionegocio_set.filter(negocio=negocio).first()
            if sn and sn.precio:
                total_ingresos += float(sn.precio)
    metrica.ingresos_totales = total_ingresos
    metrica.promedio_ticket = (total_ingresos / reservas.count()) if reservas.count() else 0
    metrica.save()
    # Actualizar reporte mensual
    año = fecha.year
    mes = fecha.month
    reporte, _ = ReporteMensual.objects.get_or_create(negocio=negocio, año=año, mes=mes)
    reservas_mes = Reserva.objects.filter(peluquero=negocio, fecha__year=año, fecha__month=mes)
    reporte.total_reservas = reservas_mes.count()
    reporte.reservas_completadas = reservas_mes.filter(estado='completado').count()
    reporte.ingresos_totales = 0
    for r in reservas_mes:
        if r.servicio and hasattr(r.servicio, 'servicionegocio_set'):
            sn = r.servicio.servicionegocio_set.filter(negocio=negocio).first()
            if sn and sn.precio:
                reporte.ingresos_totales += float(sn.precio)
    reporte.promedio_ticket = (reporte.ingresos_totales / reservas_mes.count()) if reservas_mes.count() else 0
    reporte.save()

@receiver([post_save, post_delete], sender=Reserva)
def actualizar_metricas_profesional_cliente(sender, instance, **kwargs):
    # Profesional
    if instance.profesional:
        profesional = instance.profesional
        fecha = instance.fecha
        metricap, _ = MetricaProfesional.objects.get_or_create(profesional=profesional, fecha=fecha)
        reservas_prof = Reserva.objects.filter(profesional=profesional, fecha=fecha)
        metricap.total_turnos = reservas_prof.count()
        metricap.turnos_completados = reservas_prof.filter(estado='completado').count()
        metricap.turnos_cancelados = reservas_prof.filter(estado='cancelado').count()
        # Ingresos
        total_ingresos = Decimal('0.00')
        for r in reservas_prof:
            if r.servicio and hasattr(r.servicio, 'servicionegocio_set'):
                sn = r.servicio.servicionegocio_set.filter(negocio=r.peluquero).first()
                if sn and sn.precio:
                    total_ingresos += Decimal(str(sn.precio))
        metricap.ingresos_totales = total_ingresos
        # Calificación promedio y horas trabajadas pueden calcularse aquí si se desea
        metricap.save()
    # Cliente (solo si tiene cuenta, no para clientes provisionales)
    cliente = instance.cliente
    if cliente:  # Solo actualizar métricas si hay un cliente con cuenta
        fecha = instance.fecha
        metricac, _ = MetricaCliente.objects.get_or_create(cliente=cliente, fecha=fecha)
        reservas_cli = Reserva.objects.filter(cliente=cliente, fecha=fecha)
        metricac.total_turnos = reservas_cli.count()
        metricac.turnos_completados = reservas_cli.filter(estado='completado').count()
        metricac.turnos_cancelados = reservas_cli.filter(estado='cancelado').count()
        # Servicios más solicitados y profesionales más reservados (solo del día)
        servicios = [r.servicio.servicio.nombre for r in reservas_cli if r.servicio and r.servicio.servicio]
        profesionales = [r.profesional.nombre_completo for r in reservas_cli if r.profesional]
        metricac.servicios_mas_solicitados = ', '.join([s for s, _ in Counter(servicios).most_common(3)])
        metricac.profesionales_mas_reservados = ', '.join([p for p, _ in Counter(profesionales).most_common(3)])
        metricac.save()


# ==================== SIGNALS FINANCIEROS ====================

@receiver(pre_save, sender=Reserva)
def capturar_estado_anterior(sender, instance, **kwargs):
    """Guarda el estado anterior de la reserva para detectar cambios"""
    if instance.pk:
        try:
            instance._estado_anterior = Reserva.objects.get(pk=instance.pk).estado
        except Reserva.DoesNotExist:
            instance._estado_anterior = None
    else:
        instance._estado_anterior = None


@receiver(post_save, sender=Reserva)
def crear_transaccion_al_completar(sender, instance, created, **kwargs):
    """
    Crea una transacción financiera automáticamente cuando una reserva 
    cambia a estado 'completado'.
    """
    from negocios.models import TransaccionNegocio
    
    estado_anterior = getattr(instance, '_estado_anterior', None)
    
    # Solo crear transacción si:
    # 1. La reserva cambió a 'completado' (no era completado antes)
    # 2. Tiene un total definido
    # 3. No tiene ya una transacción asociada
    if (instance.estado == 'completado' and 
        estado_anterior != 'completado' and 
        instance.total and 
        instance.total > 0):
        
        # Verificar si ya existe una transacción para esta reserva
        if not TransaccionNegocio.objects.filter(reserva=instance).exists():
            try:
                transaccion = TransaccionNegocio.crear_desde_reserva(
                    reserva=instance,
                    metodo_pago=instance.metodo_pago or 'efectivo'
                )
                if transaccion:
                    logger.info(f"Transacción creada automáticamente: {transaccion}")
                    
                    # Marcar la reserva como pagada si se creó la transacción
                    if not instance.pagado:
                        Reserva.objects.filter(pk=instance.pk).update(pagado=True)
                    
                    # ── Calcular comisión automática del profesional ──
                    if instance.profesional and instance.total:
                        _calcular_comision_profesional(instance)
            except Exception as e:
                logger.error(f"Error al crear transacción para reserva {instance.pk}: {e}")


@receiver(post_save, sender=Reserva)
def actualizar_resumen_mensual(sender, instance, **kwargs):
    """
    Actualiza el resumen financiero mensual del negocio cuando 
    se modifica una reserva.
    """
    from negocios.models import ResumenFinancieroMensual, TransaccionNegocio
    from django.db.models import Sum, Count, Q
    
    try:
        negocio = instance.peluquero
        mes = instance.fecha.month
        anio = instance.fecha.year
        
        # Obtener o crear el resumen
        resumen, created = ResumenFinancieroMensual.objects.get_or_create(
            negocio=negocio,
            mes=mes,
            anio=anio
        )
        
        # Calcular totales del mes
        reservas_mes = Reserva.objects.filter(
            peluquero=negocio,
            fecha__year=anio,
            fecha__month=mes
        )
        
        resumen.total_reservas = reservas_mes.count()
        resumen.reservas_completadas = reservas_mes.filter(estado='completado').count()
        resumen.reservas_canceladas = reservas_mes.filter(estado='cancelado').count()
        
        # Calcular ingresos desde transacciones
        transacciones_mes = TransaccionNegocio.objects.filter(
            negocio=negocio,
            fecha__year=anio,
            fecha__month=mes,
            estado='completada'
        )
        
        ingresos = transacciones_mes.filter(tipo='ingreso', concepto='servicio').aggregate(
            total=Sum('monto')
        )['total'] or 0
        
        comisiones = transacciones_mes.filter(tipo='ingreso').aggregate(
            total_comisiones=Sum('comision_profesional')
        )['total_comisiones'] or 0
        
        resumen.ingresos_servicios = ingresos
        resumen.comisiones_profesionales = comisiones
        resumen.total_ingresos = ingresos
        
        resumen.save()
        
    except Exception as e:
        logger.error(f"Error al actualizar resumen mensual: {e}") 
def _calcular_comision_profesional(reserva):
    """Calcula y registra la comisión del profesional al completar una reserva."""
    from negocios.models import ComisionProfesional
    from profesionales.models import Notificacion
    
    try:
        comision_config = ComisionProfesional.objects.filter(
            profesional=reserva.profesional,
            negocio=reserva.peluquero,
            activa=True
        ).first()
        
        if not comision_config:
            return
        
        if comision_config.tipo_comision == 'porcentaje':
            monto = reserva.total * comision_config.valor / 100
        else:
            monto = comision_config.valor  # Monto fijo
        
        from clientes.models import TransaccionNegocio
        TransaccionNegocio.objects.create(
            negocio=reserva.peluquero,
            profesional=reserva.profesional,
            reserva=reserva,
            tipo='comision_profesional',
            monto=monto,
            descripcion=f'Comisión: {reserva.profesional.nombre_completo} - {reserva.fecha}',
            fecha=timezone.now(),
        )
        
        # Notificar al profesional
        Notificacion.objects.create(
            profesional=reserva.profesional,
            tipo='comision',
            titulo='💰 Nueva comisión generada',
            mensaje=f'Has generado ${monto:,.0f} COP de comisión por la reserva del {reserva.fecha}.',
            url_relacionada='/profesionales/panel/',
        )
        
        logger.info(f'Comisión calculada: {reserva.profesional.nombre_completo} → ${monto:,.0f}')
    except Exception as e:
        logger.error(f'Error calculando comisión: {e}')
