"""
Management command para limpiar y normalizar números de teléfono en la DB.
Elimina sufijos inválidos: lid, @lid, @c.us, @s.whatsapp.net, lid_, etc.
"""
import re
import logging
from django.core.management.base import BaseCommand
from leads_admin.models import Lead

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Limpia y normaliza números de teléfono en la base de datos de leads'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Solo mostrar cambios, no aplicar',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        mode = 'DRY RUN' if dry_run else 'PRODUCCIÓN'
        self.stdout.write(f"Iniciando limpieza de teléfonos ({mode})")

        leads = Lead.objects.using('leads_db').all()
        total = leads.count()
        self.stdout.write(f"Total leads en DB: {total}")

        limpiados = 0
        ya_limpios = 0
        invalidos = 0

        for lead in leads:
            tel_original = lead.telefono or ''
            tel_limpio = self._limpiar_telefono(tel_original)

            if tel_limpio is None:
                invalidos += 1
                self.stdout.write(f"  ❌ Lead {lead.id}: '{tel_original}' → INVÁLIDO (no se puede limpiar)")
                continue

            if tel_limpio == tel_original:
                ya_limpios += 1
                continue

            limpiados += 1
            self.stdout.write(f"  🔄 Lead {lead.id}: '{tel_original}' → '{tel_limpio}' ({lead.nombre_establecimiento})")

            if not dry_run:
                lead.telefono = tel_limpio
                lead.save(using='leads_db')

        self.stdout.write(f"\nResultado: {limpiados} limpiados, {ya_limpios} ya limpios, {invalidos} inválidos, {total} total")

        if dry_run:
            self.stdout.write("DRY RUN — no se aplicaron cambios. Usa sin --dry-run para aplicar.")

    def _limpiar_telefono(self, telefono: str) -> str | None:
        """
        Limpia un número de teléfono eliminando sufijos inválidos.
        Retorna el número limpio o None si es inválido.
        """
        if not telefono or not telefono.strip():
            return None

        tel = telefono.strip()

        # Caso especial: lid_XXXX (LID puro, no resuelto)
        if tel.startswith('lid_'):
            # Es un LID sin resolver, no se puede limpiar → inválido
            return None

        # Eliminar sufijos comunes de WhatsApp
        # @c.us, @s.whatsapp.net, @lid, @g.us
        tel = re.sub(r'@(c\.us|s\.whatsapp\.net|lid|g\.us)$', '', tel)

        # Eliminar "lid" pegado al final del número (sin @)
        # Ej: 573107115121lid → 573107115121
        tel = re.sub(r'lid$', '', tel)

        # Eliminar espacios, +, -, paréntesis
        tel = tel.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

        # Si después de limpiar queda vacío o muy corto
        if len(tel) < 7:
            return None

        # Si empieza con 11 dígitos sin código país (ej: 3101234567)
        # → añadir 57 si es colombiano (empieza con 3)
        if len(tel) == 10 and tel.startswith('3'):
            tel = '57' + tel

        # Si solo son dígitos, es válido
        if re.match(r'^\d{7,15}$', tel):
            return tel

        # Si contiene caracteres no numéricos después de limpiar → inválido
        return None
