"""
Sistema Win-Back (recuperación de clientes) — Appo CRM.

Dos flujos:
  --tipo no_show   → clientes con inasistencia reciente (~1 día después) → invitar a reagendar.
  --tipo inactivo  → clientes que llevan >= N días sin peluquearse (default 5) → recordar que toca cita.
  --tipo todos     → ambos (default).

Envío vía whatsapp-web.js (texto libre, misma sesión del CRM). No requiere plantillas Meta.

Reglas éticas / anti-spam:
  - Máx 1 win-back por cliente+tipo dentro de la ventana (--ventana-dias, default 30).
  - No se escribe a clientes bloqueados (BloqueoCliente) del negocio.
  - No se escribe a quien ya tiene reserva futura (pendiente/confirmada).
  - Respeta opt-out (RecuperacionCliente.opt_out=True por teléfono).
  - Tope diario por negocio (--cap-negocio, default 30).
  - Respeta horario comercial (8-20) salvo --force-horario.

Uso:
  manage.py recuperar_clientes --dry-run --verbose
  manage.py recuperar_clientes --tipo no_show
  manage.py recuperar_clientes --tipo inactivo --dias-inactivo 5
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q, Max
from datetime import timedelta

from clientes.models import Reserva, BloqueoCliente, RecuperacionCliente
from clientes.utils import get_whatsapp_service

import logging

logger = logging.getLogger(__name__)

DOMINIO = "https://appo.com.co"


class Command(BaseCommand):
    help = 'Win-Back: recupera clientes con inasistencia reciente o inactivos (sin peluquearse).'

    def add_arguments(self, parser):
        parser.add_argument('--tipo', type=str,
                            choices=['no_show', 'inactivo', 'todos'], default='todos',
                            help='Flujo a ejecutar')
        parser.add_argument('--dry-run', action='store_true',
                            help='Simula sin enviar mensajes')
        parser.add_argument('--verbose', action='store_true',
                            help='Salida detallada')
        parser.add_argument('--dias-inactivo', type=int, default=5,
                            help='Días desde el último corte para considerar inactivo (default 5)')
        parser.add_argument('--dias-inactivo-max', type=int, default=120,
                            help='No molestar a clientes con más de N días de inactividad (default 120)')
        parser.add_argument('--ventana-dias', type=int, default=30,
                            help='No reenviar el mismo tipo al mismo cliente dentro de N días (default 30)')
        parser.add_argument('--noshow-min-horas', type=int, default=18,
                            help='Horas mínimas tras la inasistencia antes de escribir (default 18)')
        parser.add_argument('--noshow-max-dias', type=int, default=3,
                            help='Ventana máxima (días) para invitar tras inasistencia (default 3)')
        parser.add_argument('--cap-negocio', type=int, default=30,
                            help='Tope de mensajes win-back por negocio por corrida (default 30)')
        parser.add_argument('--force-horario', action='store_true',
                            help='Ignora la verificación de horario comercial')

    def handle(self, *args, **opts):
        self.dry_run = opts['dry_run']
        self.verbose = opts['verbose']
        self.ventana_dias = opts['ventana_dias']
        self.cap_negocio = opts['cap_negocio']
        tipo = opts['tipo']

        ahora = timezone.localtime(timezone.now())

        if self.dry_run:
            self.stdout.write(self.style.WARNING('⚠️  MODO SIMULACIÓN — no se envía nada'))

        # Horario comercial (8:00–20:00) salvo override
        if not opts['force_horario'] and not (8 <= ahora.hour < 20):
            self.stdout.write(self.style.WARNING(
                f'⏰ Fuera de horario comercial ({ahora:%H:%M}). Usa --force-horario para forzar.'))
            return

        # Servicio WhatsApp (solo si vamos a enviar de verdad)
        self.wa = None
        if not self.dry_run:
            self.wa = get_whatsapp_service()
            if not (self.wa and self.wa.is_enabled()):
                self.stdout.write(self.style.ERROR('❌ WhatsApp no disponible. Abortando.'))
                return

        self._cap_usado = {}  # negocio_id -> count

        if tipo in ('no_show', 'todos'):
            self._procesar_no_show(ahora, opts)
        if tipo in ('inactivo', 'todos'):
            self._procesar_inactivos(ahora, opts)

    # ────────────────────────────────────────────────────────────
    # Helpers comunes
    # ────────────────────────────────────────────────────────────

    def _link_negocio(self, negocio_id, campaign):
        return (f"{DOMINIO}/clientes/peluquero/{negocio_id}/"
                f"?utm_source=winback&utm_campaign={campaign}")

    def _tiene_reserva_futura(self, cliente, cliente_prov, negocio, hoy):
        qs = Reserva.objects.filter(
            peluquero=negocio,
            estado__in=['pendiente', 'confirmado'],
            fecha__gte=hoy,
        )
        if cliente:
            qs = qs.filter(cliente=cliente)
        elif cliente_prov:
            qs = qs.filter(cliente_provisional=cliente_prov)
        else:
            return False
        return qs.exists()

    def _ya_contactado(self, cliente, cliente_prov, telefono, tipo, ahora):
        """True si ya hubo win-back del mismo tipo dentro de la ventana, o opt-out."""
        if telefono and RecuperacionCliente.opt_out_telefono(telefono):
            return True
        desde = ahora - timedelta(days=self.ventana_dias)
        qs = RecuperacionCliente.objects.filter(tipo=tipo, fecha_envio__gte=desde)
        cond = Q()
        if cliente:
            cond |= Q(cliente=cliente)
        if cliente_prov:
            cond |= Q(cliente_provisional=cliente_prov)
        if telefono:
            cond |= Q(telefono=telefono)
        if not cond:
            return False
        return qs.filter(cond).exists()

    def _cap_ok(self, negocio_id):
        usado = self._cap_usado.get(negocio_id, 0)
        return usado < self.cap_negocio

    def _registrar_envio(self, *, cliente, cliente_prov, negocio, reserva, telefono,
                         tipo, ok, detalle):
        self._cap_usado[negocio_id_of(negocio)] = self._cap_usado.get(negocio_id_of(negocio), 0) + 1
        if self.dry_run:
            return
        try:
            RecuperacionCliente.objects.create(
                cliente=cliente,
                cliente_provisional=cliente_prov,
                negocio=negocio,
                reserva_origen=reserva,
                telefono=telefono or '',
                tipo=tipo,
                enviado_ok=ok,
                detalle=detalle[:500] if detalle else '',
            )
        except Exception as e:
            logger.error(f"Error registrando RecuperacionCliente: {e}")

    # ────────────────────────────────────────────────────────────
    # Flujo 1: No-show (inasistencia reciente)
    # ────────────────────────────────────────────────────────────

    def _procesar_no_show(self, ahora, opts):
        self.stdout.write('\n😅 Procesando NO-SHOW (inasistencias recientes)...')
        limite_min = ahora - timedelta(hours=opts['noshow_min_horas'])
        limite_max = ahora - timedelta(days=opts['noshow_max_dias'])
        hoy = ahora.date()

        reservas = Reserva.objects.filter(
            estado='inasistencia',
            creado_en__lte=limite_min,
            creado_en__gte=limite_max,
        ).select_related('cliente', 'cliente_provisional', 'peluquero')

        # Ordenar por fecha de creación para procesar las más recientes primero
        reservas = reservas.order_by('-creado_en')

        if self.verbose:
            self.stdout.write(f'   Candidatas (inasistencia {opts["noshow_min_horas"]}h–{opts["noshow_max_dias"]}d): {reservas.count()}')

        enviados = omitidos = errores = 0

        for r in reservas:
            negocio = r.peluquero
            cliente = r.cliente
            cliente_prov = r.cliente_provisional
            telefono = (r.get_cliente_telefono() or '').strip()
            nombre = r.get_cliente_nombre()

            motivo_omit = None
            if not telefono:
                motivo_omit = 'sin teléfono'
            elif cliente and BloqueoCliente.esta_bloqueado(cliente, negocio):
                motivo_omit = 'bloqueado'
            elif self._tiene_reserva_futura(cliente, cliente_prov, negocio, hoy):
                motivo_omit = 'ya tiene cita futura'
            elif self._ya_contactado(cliente, cliente_prov, telefono, 'no_show', ahora):
                motivo_omit = 'ya contactado / opt-out'
            elif not self._cap_ok(negocio_id_of(negocio)):
                motivo_omit = 'cap negocio alcanzado'

            if motivo_omit:
                omitidos += 1
                if self.verbose:
                    self.stdout.write(f'   ⏭️  #{r.id} {nombre} ({negocio.nombre}): {motivo_omit}')
                continue

            link = self._link_negocio(negocio_id_of(negocio), 'noshow')

            if self.dry_run:
                enviados += 1
                self._cap_usado[negocio_id_of(negocio)] = self._cap_usado.get(negocio_id_of(negocio), 0) + 1
                if self.verbose:
                    self.stdout.write(f'   📤 [DRY] #{r.id} → {nombre} ({telefono}) | {negocio.nombre}')
                continue

            res = self.wa.send_winback_noshow(telefono, nombre, negocio.nombre, link)
            ok = bool(res.get('success'))
            self._registrar_envio(cliente=cliente, cliente_prov=cliente_prov, negocio=negocio,
                                  reserva=r, telefono=telefono, tipo='no_show',
                                  ok=ok, detalle=str(res.get('error') or ''))
            if ok:
                enviados += 1
                if self.verbose:
                    self.stdout.write(f'   ✅ #{r.id} → {nombre} ({telefono})')
            else:
                errores += 1
                if self.verbose:
                    self.stdout.write(f'   ❌ #{r.id} {nombre}: {res.get("error")}')

        self.stdout.write(self.style.SUCCESS(
            f'😅 NO-SHOW: {enviados} enviados, {omitidos} omitidos, {errores} errores'))

    # ────────────────────────────────────────────────────────────
    # Flujo 2: Inactivos (toca peluquearse)
    # ────────────────────────────────────────────────────────────

    def _procesar_inactivos(self, ahora, opts):
        dias = opts['dias_inactivo']
        dias_max = opts['dias_inactivo_max']
        self.stdout.write(f'\n✂️  Procesando INACTIVOS (>= {dias} días sin corte)...')
        hoy = ahora.date()
        corte_min = hoy - timedelta(days=dias)       # última cita debe ser <= esta fecha
        corte_max = hoy - timedelta(days=dias_max)    # pero no más vieja que esto

        # Última reserva COMPLETADA por (cliente|provisional, negocio)
        completadas = Reserva.objects.filter(
            estado='completado',
            fecha__lte=corte_min,
            fecha__gte=corte_max,
        ).select_related('cliente', 'cliente_provisional', 'peluquero')

        # Agrupamos: nos quedamos con la última completada por cliente+negocio
        vistos = {}  # (tipo_id, negocio_id) -> reserva (la más reciente)
        for r in completadas.order_by('fecha'):
            if r.cliente_id:
                key = ('u', r.cliente_id, r.peluquero_id)
            elif r.cliente_provisional_id:
                key = ('p', r.cliente_provisional_id, r.peluquero_id)
            else:
                continue
            vistos[key] = r  # al iterar ascendente, queda la última (mayor fecha)

        if self.verbose:
            self.stdout.write(f'   Candidatos (última cita {dias}-{dias_max}d): {len(vistos)}')

        enviados = omitidos = errores = 0

        for key, r in vistos.items():
            negocio = r.peluquero
            cliente = r.cliente
            cliente_prov = r.cliente_provisional
            telefono = (r.get_cliente_telefono() or '').strip()
            nombre = r.get_cliente_nombre()
            dias_real = (hoy - r.fecha).days

            motivo_omit = None
            if not telefono:
                motivo_omit = 'sin teléfono'
            elif cliente and BloqueoCliente.esta_bloqueado(cliente, negocio):
                motivo_omit = 'bloqueado'
            elif self._tiene_reserva_futura(cliente, cliente_prov, negocio, hoy):
                motivo_omit = 'ya tiene cita futura'
            elif self._ya_contactado(cliente, cliente_prov, telefono, 'inactivo', ahora):
                motivo_omit = 'ya contactado / opt-out'
            elif not self._cap_ok(negocio_id_of(negocio)):
                motivo_omit = 'cap negocio alcanzado'

            if motivo_omit:
                omitidos += 1
                if self.verbose:
                    self.stdout.write(f'   ⏭️  {nombre} ({negocio.nombre}, {dias_real}d): {motivo_omit}')
                continue

            link = self._link_negocio(negocio_id_of(negocio), 'inactivo')

            if self.dry_run:
                enviados += 1
                self._cap_usado[negocio_id_of(negocio)] = self._cap_usado.get(negocio_id_of(negocio), 0) + 1
                if self.verbose:
                    self.stdout.write(f'   📤 [DRY] {nombre} ({telefono}) {dias_real}d | {negocio.nombre}')
                continue

            res = self.wa.send_winback_inactivo(telefono, nombre, negocio.nombre, link, dias_real)
            ok = bool(res.get('success'))
            self._registrar_envio(cliente=cliente, cliente_prov=cliente_prov, negocio=negocio,
                                  reserva=r, telefono=telefono, tipo='inactivo',
                                  ok=ok, detalle=str(res.get('error') or ''))
            if ok:
                enviados += 1
                if self.verbose:
                    self.stdout.write(f'   ✅ {nombre} ({telefono}) {dias_real}d')
            else:
                errores += 1
                if self.verbose:
                    self.stdout.write(f'   ❌ {nombre}: {res.get("error")}')

        self.stdout.write(self.style.SUCCESS(
            f'✂️  INACTIVOS: {enviados} enviados, {omitidos} omitidos, {errores} errores'))


def negocio_id_of(negocio):
    return getattr(negocio, 'id', None) or getattr(negocio, 'pk', None)
