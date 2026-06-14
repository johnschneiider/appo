"""
Asistente de Agenda para Plan Pro.
Sugiere al dueño cómo llenar huecos vacíos en la agenda.
"""
from datetime import date, timedelta, datetime
from django.utils import timezone


class AgendaAssistant:
    """Analiza la agenda del negocio y sugiere acciones."""

    def __init__(self, negocio):
        self.negocio = negocio

    def analizar_semana(self):
        """Analiza los próximos 7 días y retorna sugerencias."""
        from clientes.models import Reserva
        hoy = timezone.now().date()
        sugerencias = []

        for i in range(7):
            dia = hoy + timedelta(days=i)
            nombre_dia = {
                0: 'lunes', 1: 'martes', 2: 'miércoles',
                3: 'jueves', 4: 'viernes', 5: 'sábado', 6: 'domingo'
            }[dia.weekday()]

            # Verificar si el negocio trabaja ese día
            horario = (self.negocio.horario_atencion or {}).get(nombre_dia, {})
            if not horario:
                continue

            inicio = datetime.strptime(horario.get('inicio', '10:00'), '%H:%M').time()
            fin = datetime.strptime(horario.get('fin', '22:00'), '%H:%M').time()

            # Reservas de ese día
            reservas = Reserva.objects.filter(
                peluquero=self.negocio, fecha=dia,
                estado__in=['pendiente', 'confirmado']
            ).order_by('hora_inicio')

            # Detectar huecos de 60 min o más
            huecos = self._detectar_huecos(reservas, inicio, fin, dia)
            if huecos:
                sugerencias.append({
                    'dia': dia,
                    'nombre_dia': nombre_dia.capitalize(),
                    'huecos': huecos,
                    'total_reservas': reservas.count(),
                })

        # También sugerir horas pico con más demanda
        hora_pico = self._horas_pico()
        if hora_pico:
            sugerencias.insert(0, {
                'tipo': 'hora_pico',
                'horas': hora_pico,
            })

        return sugerencias

    def _detectar_huecos(self, reservas, inicio, fin, dia):
        """Encuentra bloques de 60+ minutos sin reservas."""
        huecos = []
        hora_actual = inicio
        dt_dia = datetime.combine(dia, datetime.min.time())

        for r in reservas:
            if r.hora_inicio > hora_actual:
                gap = datetime.combine(dia, r.hora_inicio) - datetime.combine(dia, hora_actual)
                minutos = gap.total_seconds() / 60
                if minutos >= 60:
                    huecos.append({
                        'inicio': hora_actual.strftime('%H:%M'),
                        'fin': r.hora_inicio.strftime('%H:%M'),
                        'minutos': int(minutos),
                    })
            hora_actual = max(hora_actual, r.hora_fin)

        # Último hueco del día
        if hora_actual < fin:
            gap = datetime.combine(dia, fin) - datetime.combine(dia, hora_actual)
            minutos = gap.total_seconds() / 60
            if minutos >= 60:
                huecos.append({
                    'inicio': hora_actual.strftime('%H:%M'),
                    'fin': fin.strftime('%H:%M'),
                    'minutos': int(minutos),
                })

        return huecos

    def _horas_pico(self):
        """Identifica las horas con más reservas en los últimos 30 días."""
        from clientes.models import Reserva
        from django.db.models import Count
        from django.db.models.functions import ExtractHour

        desde = timezone.now().date() - timedelta(days=30)
        horas = Reserva.objects.filter(
            peluquero=self.negocio,
            fecha__gte=desde,
            estado__in=['pendiente', 'confirmado', 'completado']
        ).annotate(hora=ExtractHour('hora_inicio')).values('hora').annotate(
            total=Count('id')
        ).order_by('-total')[:3]

        return [{'hora': f'{h["hora"]:02d}:00', 'reservas': h['total']} for h in horas if h['total'] >= 3]
