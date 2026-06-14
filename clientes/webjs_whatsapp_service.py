"""
Servicio de WhatsApp usando whatsapp-web.js (microservicio local)
Reemplaza temporalmente a Twilio/Meta para notificaciones.
Usa la misma sesión de WhatsApp que el CRM (APPO_CRM).

Mensajes alineados con las plantillas de Twilio (contenido completo).
"""

import logging
import requests
from typing import Dict, Any, Optional
from datetime import date, time

logger = logging.getLogger(__name__)

WHATSAPP_SERVICE_URL = "http://localhost:8081/message/sendText/APPO_CRM"
REQUEST_TIMEOUT = 15

# ── helpers de formateo ──

MESES_ES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]


def _fmt_fecha_plantilla(f: Optional[date]) -> str:
    """Ej: 'lunes 09 de junio del 2026'"""
    if not f:
        return ""
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    dia_semana = dias[f.weekday()]
    return f"{dia_semana} {f.day} de {MESES_ES[f.month]} del {f.year}"


def _fmt_hora_plantilla(t: Optional[time]) -> str:
    """Ej: '10:00 AM'"""
    if not t:
        return ""
    return t.strftime("%I:%M %p").lstrip("0").lower()


def _extraer_datos_reserva(reserva) -> dict:
    """Extrae todos los datos relevantes de una reserva para construir mensajes."""
    datos = {}
    datos["fecha_larga"] = _fmt_fecha_plantilla(reserva.fecha if hasattr(reserva, 'fecha') else None)
    datos["hora"] = _fmt_hora_plantilla(reserva.hora_inicio if hasattr(reserva, 'hora_inicio') else None)

    # Cliente (cuenta registrada o provisional)
    cliente_nombre = "Cliente"
    cliente = getattr(reserva, 'cliente', None)
    if cliente:
        cliente_nombre = cliente.get_full_name() or getattr(cliente, 'username', cliente_nombre)
    elif hasattr(reserva, 'cliente_provisional') and reserva.cliente_provisional:
        cliente_nombre = getattr(reserva.cliente_provisional, 'nombre', cliente_nombre)
    datos["cliente_nombre"] = cliente_nombre

    # Negocio (peluquero)
    negocio = getattr(reserva, 'peluquero', None)
    if negocio:
        datos["negocio_nombre"] = getattr(negocio, 'nombre', '')
        datos["direccion"] = getattr(negocio, 'direccion', '') or ''
        datos["negocio_telefono"] = (
            getattr(negocio, 'celular', '') or
            getattr(negocio, 'telefono', '') or
            ''
        )
    else:
        datos["negocio_nombre"] = ''
        datos["direccion"] = ''
        datos["negocio_telefono"] = ''

    # Profesional asignado (solo nombre, sin duplicar el negocio)
    profesional = getattr(reserva, 'profesional', None)
    if profesional:
        prof_nombre = getattr(profesional, 'nombre_completo', None) or getattr(profesional, 'nombre', None) or str(profesional)
        datos["profesional"] = prof_nombre
    else:
        datos["profesional"] = ''

    # Servicio
    servicio = getattr(reserva, 'servicio', None)
    if servicio:
        servicio_nombre = getattr(servicio, 'servicio', None)
        datos["servicio_nombre"] = getattr(servicio_nombre, 'nombre', '') or str(servicio)
    else:
        datos["servicio_nombre"] = ''

    return datos


class WebJSWhatsAppService:
    """Adaptador para el microservicio whatsapp-web.js"""

    def __init__(self):
        self._enabled = None

    def is_enabled(self) -> bool:
        """Verifica que el microservicio esté respondiendo."""
        if self._enabled is not None:
            return self._enabled
        try:
            r = requests.get("http://localhost:8081/health", timeout=3)
            if r.status_code == 200:
                data = r.json()
                self._enabled = data.get("connectionState") == "open"
                return self._enabled
        except Exception:
            pass
        self._enabled = False
        return False

    def _clean_phone(self, phone: str) -> str:
        """Normaliza número colombiano: +57 → 57, quita +, espacios, etc."""
        cleaned = str(phone).replace("+", "").replace(" ", "").replace("-", "")
        if not cleaned.startswith("57") and len(cleaned) == 10:
            cleaned = "57" + cleaned
        return cleaned

    def send_text_message(self, to_phone: str, message: str) -> Dict[str, Any]:
        """Envía mensaje de texto libre via whatsapp-web.js"""
        if not self.is_enabled():
            return {"success": False, "error": "WhatsApp service no disponible"}

        numero = self._clean_phone(to_phone)

        try:
            r = requests.post(
                WHATSAPP_SERVICE_URL,
                json={
                    "number": f"{numero}@c.us",
                    "textMessage": {"text": message}
                },
                timeout=REQUEST_TIMEOUT
            )
            r.raise_for_status()
            data = r.json()
            logger.info(f"WebJS WhatsApp enviado a {numero}: {data.get('status', 'ok')}")
            return {"success": True, "message_id": data.get("key", {}).get("id", ""), "response": data}
        except requests.exceptions.HTTPError as e:
            logger.error(f"WebJS WhatsApp HTTP error a {numero}: {e}")
            try:
                err_body = e.response.text[:200]
            except Exception:
                err_body = str(e)
            return {"success": False, "error": err_body}
        except Exception as e:
            logger.error(f"WebJS WhatsApp error a {numero}: {e}")
            return {"success": False, "error": str(e)}

    # ── Métodos de notificación ──

    def send_reserva_confirmada(self, reserva) -> Dict[str, Any]:
        """Notifica que la cita fue agendada (plantilla: reserva_confirmada)."""
        telefono = self._get_telefono_reserva(reserva)
        if not telefono:
            return {"success": False, "error": "Sin teléfono"}

        d = _extraer_datos_reserva(reserva)

        mensaje = (
            f"✅ *Reserva confirmada*\n\n"
            f"Hola {d['cliente_nombre']}. Tu reserva quedó confirmada.\n"
            f"💈 Negocio: {d['negocio_nombre']}\n"
            f"✂️ Servicio: {d['servicio_nombre']}\n"
            f"📅 Fecha: {d['fecha_larga']}\n"
            f"🕐 Hora: {d['hora']}\n"
        )
        if d['profesional']:
            mensaje += f"👤 Profesional: {d['profesional']}\n"
        if d['direccion']:
            mensaje += f"📍 Dirección: {d['direccion']}\n"
        mensaje += (
            f"\nTe enviaremos recordatorios. ¿Dudas? Respondé este mensaje."
        )
        return self.send_text_message(telefono, mensaje)

    def send_reserva_cancelada(self, reserva, motivo: str = "") -> Dict[str, Any]:
        """Notifica cancelación de cita (plantilla: reserva_cancelada)."""
        telefono = self._get_telefono_reserva(reserva)
        if not telefono:
            return {"success": False, "error": "Sin teléfono"}

        d = _extraer_datos_reserva(reserva)
        motivo_texto = motivo if motivo else "Sin motivo especificado"

        mensaje = (
            f"❌ *Cita cancelada*\n\n"
            f"Hola {d['cliente_nombre']}. Tu cita fue cancelada.\n"
            f"💈 Negocio: {d['negocio_nombre']}\n"
            f"📅 Fecha: {d['fecha_larga']}\n"
            f"🕐 Hora: {d['hora']}\n"
            f"📝 Motivo: {motivo_texto}\n\n"
            f"Si deseas reagendar, ve a 👉 appo.com.co"
        )
        return self.send_text_message(telefono, mensaje)

    def send_reserva_reagendada(self, reserva, fecha_anterior, hora_anterior) -> Dict[str, Any]:
        """Notifica reprogramación de cita (plantilla: reserva_reagendada)."""
        telefono = self._get_telefono_reserva(reserva)
        if not telefono:
            return {"success": False, "error": "Sin teléfono"}

        d = _extraer_datos_reserva(reserva)
        fecha_ant = _fmt_fecha_plantilla(fecha_anterior) if hasattr(fecha_anterior, 'strftime') else str(fecha_anterior)
        hora_ant = _fmt_hora_plantilla(hora_anterior) if hasattr(hora_anterior, 'strftime') else str(hora_anterior)

        mensaje = (
            f"🔄 *Cita reprogramada*\n\n"
            f"Hola {d['cliente_nombre']}. Tu cita fue reprogramada.\n"
            f"💈 Negocio: {d['negocio_nombre']}\n"
            f"🗓 Antes: {fecha_ant} {hora_ant}\n"
            f"📅 Nueva: {d['fecha_larga']} {d['hora']}\n\n"
            f"Te confirmaremos 24h antes. ¿Dudas? Respondé este mensaje."
        )
        return self.send_text_message(telefono, mensaje)

    def send_recordatorio_dia_antes(self, reserva) -> Dict[str, Any]:
        """Recordatorio 24h antes de la cita (plantilla: recordatorio_dia_antes)."""
        telefono = self._get_telefono_reserva(reserva)
        if not telefono:
            return {"success": False, "error": "Sin teléfono"}

        d = _extraer_datos_reserva(reserva)

        mensaje = (
            f"⏰ *Recordatorio — mañana tienes tu cita*\n\n"
            f"Hola {d['cliente_nombre']}.\n"
            f"💈 Negocio: {d['negocio_nombre']}\n"
            f"✂️ Servicio: {d['servicio_nombre']}\n"
            f"📅 Fecha: {d['fecha_larga']}\n"
            f"🕐 Hora: {d['hora']}\n"
        )
        if d['direccion']:
            mensaje += f"📍 Dirección: {d['direccion']}\n"
        if d['negocio_telefono']:
            mensaje += f"📞 Teléfono: {d['negocio_telefono']}\n"
        mensaje += (
            f"🔗 Cambios aquí: appo.com.co\n\n"
            f"¿No podés asistir? Cancelá desde el enlace. ¡Gracias!"
        )
        return self.send_text_message(telefono, mensaje)

    def send_recordatorio_tres_horas(self, reserva) -> Dict[str, Any]:
        """Recordatorio 3h antes de la cita (plantilla: recordatorio_tres_horas)."""
        telefono = self._get_telefono_reserva(reserva)
        if not telefono:
            return {"success": False, "error": "Sin teléfono"}

        d = _extraer_datos_reserva(reserva)

        mensaje = (
            f"🔔 *Tu cita es en 3 horas*\n\n"
            f"Hola {d['cliente_nombre']}. Recordatorio.\n"
            f"💈 Negocio: {d['negocio_nombre']}\n"
            f"✂️ Servicio: {d['servicio_nombre']}\n"
            f"📅 Fecha: {d['fecha_larga']}\n"
            f"🕐 Hora: {d['hora']}\n"
        )
        if d['direccion']:
            mensaje += f"📍 Dirección: {d['direccion']}\n"
        if d['negocio_telefono']:
            mensaje += f"📞 Teléfono: {d['negocio_telefono']}\n"
        mensaje += (
            f"🔗 Cambios aquí: appo.com.co\n\n"
            f"Si no puedes asistir, este es el momento de gestionar tu cita. "
            f"Es un acto de solidaridad con otros clientes. ¡Gracias!"
        )
        return self.send_text_message(telefono, mensaje)

    def send_inasistencia(self, reserva, motivo: str = "") -> Dict[str, Any]:
        """Notifica inasistencia (plantilla: inasistencia)."""
        telefono = self._get_telefono_reserva(reserva)
        if not telefono:
            return {"success": False, "error": "Sin teléfono"}

        d = _extraer_datos_reserva(reserva)
        motivo_texto = motivo if motivo else "Sin motivo especificado"

        mensaje = (
            f"📵 *Inasistencia*\n\n"
            f"Hola {d['cliente_nombre']}. Notamos que no fue posible atenderte en tu cita.\n"
            f"💈 Negocio: {d['negocio_nombre']}\n"
            f"📅 Fecha: {d['fecha_larga']}\n"
            f"🕐 Hora: {d['hora']}\n"
            f"📝 Motivo: {motivo_texto}\n\n"
            f"Si deseas reagendar, ve a 👉 appo.com.co"
        )
        return self.send_text_message(telefono, mensaje)

    # ── Win-Back (recuperación de clientes) ──

    def send_winback_noshow(self, telefono: str, cliente_nombre: str,
                            negocio_nombre: str, link: str) -> Dict[str, Any]:
        """Invita a reagendar tras una inasistencia (texto libre, sin plantilla)."""
        nombre = (cliente_nombre or "").split(" ")[0] if cliente_nombre else ""
        saludo = f"¡Hola {nombre}!" if nombre else "¡Hola!"
        mensaje = (
            f"{saludo} 👋\n\n"
            f"Te perdimos en tu última cita en *{negocio_nombre}* 😅 "
            f"No pasa nada, a todos nos pasa.\n\n"
            f"¿Reagendamos para que sigas viéndote bien? ✂️\n"
            f"👉 {link}\n\n"
            f"Aquí te apartamos tu turno en segundos."
        )
        return self.send_text_message(telefono, mensaje)

    def send_winback_inactivo(self, telefono: str, cliente_nombre: str,
                              negocio_nombre: str, link: str, dias: int = None) -> Dict[str, Any]:
        """Recuerda amablemente que ya toca peluquearse (cliente inactivo)."""
        nombre = (cliente_nombre or "").split(" ")[0] if cliente_nombre else ""
        saludo = f"¡Hola {nombre}!" if nombre else "¡Hola!"
        tiempo = "Ya pasaron unos días desde tu último corte" if not dias else (
            f"Ya van {dias} días desde tu último corte"
        )
        mensaje = (
            f"{saludo} ✂️\n\n"
            f"{tiempo} en *{negocio_nombre}*. "
            f"Es buen momento para refrescar el look y seguir viéndote impecable 💈\n\n"
            f"¿Te apartamos un turno?\n"
            f"👉 {link}"
        )
        return self.send_text_message(telefono, mensaje)

    # ── Utilidad ──

    def _get_telefono_reserva(self, reserva) -> str:
        """Extrae el teléfono del cliente de la reserva (registrado o provisional)."""
        try:
            # Usar el método del modelo que cubre ambos casos
            if hasattr(reserva, 'get_cliente_telefono'):
                return reserva.get_cliente_telefono() or ''
            # Fallback manual
            if hasattr(reserva, 'cliente') and reserva.cliente:
                cliente = reserva.cliente
                if hasattr(cliente, 'telefono') and cliente.telefono:
                    return cliente.telefono
                if hasattr(cliente, 'celular') and cliente.celular:
                    return cliente.celular
            if hasattr(reserva, 'cliente_provisional') and reserva.cliente_provisional:
                cp = reserva.cliente_provisional
                if hasattr(cp, 'telefono') and cp.telefono:
                    return cp.telefono
            if hasattr(reserva, 'telefono_cliente') and reserva.telefono_cliente:
                return reserva.telefono_cliente
        except Exception as e:
            logger.warning(f"No se pudo obtener teléfono de reserva {reserva.id}: {e}")
        return ""


# Instancia global
webjs_whatsapp_service = WebJSWhatsAppService()
