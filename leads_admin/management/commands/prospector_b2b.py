"""
Management command: prospector_b2b.py
Envía mensajes de prospección B2B a barberías vía WhatsApp.
Uso: python manage.py prospector_b2b --mode=[dry_run|send|list]
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
import logging
import json
import os

logger = logging.getLogger(__name__)

# Top 5 barberías más activas (por reservas) — listas para contactar
TOP_5_BARBERIAS = [
    {
        "nombre": 'Barber Studio "The Gentlemen"',
        "ciudad": "Cali",
        "telefono": None,  # Requiere contacto real
        "reservas": 7,
        "mensaje_inicial": None,
    },
    {
        "nombre": 'Barbería "El Corte Perfecto"',
        "ciudad": "Cali",
        "telefono": None,
        "reservas": 5,
    },
    {
        "nombre": 'Barber Shop "Classic Cut"',
        "ciudad": "Cali",
        "telefono": None,
        "reservas": 3,
    },
    {
        "nombre": 'Barbería "Los Capos"',
        "ciudad": "Cali",
        "telefono": None,
        "reservas": 3,
    },
    {
        "nombre": 'Barbería "Fade Masters"',
        "ciudad": "Cali",
        "telefono": None,
        "reservas": 3,
    },
]

MENSAJES_TEMPLATE = {
    "outbound_inicial": (
        "Hola, buenos días 👋 ¿Aquí es {nombre}?\n\n"
        "Soy Juan, del equipo de Appo. Vi que están en nuestra plataforma y quería "
        "contarles algo rápido: activamos el Bot de WhatsApp que agenda citas solo, "
        "manda recordatorios y recupera clientes que dejaron de ir.\n\n"
        "¿Les interesa probarlo 7 días gratis? Sin tarjeta, sin compromiso."
    ),
    "outbound_seguimiento": (
        "Hola de nuevo 👋 ¿Pudiste revisar lo de Appo?\n\n"
        "Sin presión — solo quería saber si te sirve probar el bot 7 días gratis "
        "para que tus clientes agenden solos 24/7. Si no es momento, tranqui 🙌"
    ),
    "cierre_activo": (
        "¡Perfecto, {nombre}! 🚀\n\n"
        "Te activo el trial de 7 días ya mismo. Solo necesito:\n"
        "1. Cuántos barberos tienen\n"
        "2. El número de WhatsApp de la barbería\n\n"
        "En 5 minutos está corriendo. ¿Le damos?"
    ),
}


class Command(BaseCommand):
    help = 'Envía prospección B2B a barberías vía WhatsApp'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            type=str,
            default='list',
            choices=['list', 'dry_run', 'send'],
            help='Modo: list (mostrar top 5), dry_run (simular), send (enviar)'
        )
        parser.add_argument(
            '--telefono',
            type=str,
            help='Teléfono para envío individual (+57... formato)'
        )
        parser.add_argument(
            '--nombre',
            type=str,
            help='Nombre del negocio para envío individual'
        )

    def handle(self, *args, **options):
        mode = options['mode']
        telefono = options.get('telefono')
        nombre = options.get('nombre')

        if telefono and nombre:
            self._prospectar_individual(telefono, nombre, mode)
        else:
            self._prospectar_lote(mode)

    def _prospectar_lote(self, mode):
        """Muestra/prospecta el top 5 de barberías activas."""
        self.stdout.write(self.style.SUCCESS(
            '\n📊 TOP 5 BARBERÍAS MÁS ACTIVAS (por reservas)\n'
        ))

        for i, barberia in enumerate(TOP_5_BARBERIAS, 1):
            self.stdout.write(
                f'  {i}. {barberia["nombre"]} — {barberia["ciudad"]} '
                f'({barberia["reservas"]} reservas)'
            )

        self.stdout.write('\n')

        if mode == 'list':
            self.stdout.write(self.style.WARNING(
                'ℹ️  Para prospectar, asigna teléfonos reales en la lista TOP_5_BARBERIAS.\n'
                '    python manage.py prospector_b2b --nombre="Negocio" --telefono="+57300..."'
            ))
            return

        # Verificar si tienen teléfonos
        sin_telefono = [b for b in TOP_5_BARBERIAS if not b.get('telefono')]
        if sin_telefono:
            nombres = ', '.join(b['nombre'] for b in sin_telefono)
            self.stdout.write(self.style.ERROR(
                f'❌ Las siguientes barberías no tienen teléfono asignado:\n'
                f'   {nombres}\n'
                f'   Edita TOP_5_BARBERIAS en prospector_b2b.py para agregarlos.'
            ))
            return

        for barberia in TOP_5_BARBERIAS:
            self._enviar_mensaje(barberia, mode)

    def _prospectar_individual(self, telefono, nombre, mode):
        """Envía mensaje de prospección a un negocio específico."""
        barberia = {
            'nombre': nombre,
            'telefono': telefono,
            'reservas': 0,
        }
        self._enviar_mensaje(barberia, mode)

    def _enviar_mensaje(self, barberia, mode):
        """Envía el mensaje inicial de prospección."""
        mensaje = MENSAJES_TEMPLATE['outbound_inicial'].format(
            nombre=barberia['nombre']
        )

        if mode == 'dry_run':
            self.stdout.write(f'\n{"─"*60}')
            self.stdout.write(f'📱 Para: {barberia["nombre"]}')
            self.stdout.write(f'📞 Teléfono: {barberia["telefono"]}')
            self.stdout.write(f'💬 Mensaje:')
            self.stdout.write(f'   {mensaje}')
            self.stdout.write(f'{"─"*60}')
            return

        if mode == 'send':
            # Usar el mismo servicio de envío que el CRM
            from leads_admin.views import enviar_whatsapp
            try:
                exito = enviar_whatsapp(barberia['telefono'], mensaje)
                if exito:
                    self.stdout.write(self.style.SUCCESS(
                        f'✅ Enviado a {barberia["nombre"]} ({barberia["telefono"]})'
                    ))
                else:
                    self.stdout.write(self.style.ERROR(
                        f'❌ Falló envío a {barberia["nombre"]}'
                    ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'❌ Error enviando a {barberia["nombre"]}: {e}'
                ))
