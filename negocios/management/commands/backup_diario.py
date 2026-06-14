"""
Backup automático diario de la base de datos.
Se ejecuta vía cron: 0 3 * * * (3 AM todos los días)
"""
import subprocess
import os
from datetime import date
from django.core.management.base import BaseCommand
from django.conf import settings

BACKUP_DIR = '/var/backups/appo'
RETENTION_DAYS = 7

class Command(BaseCommand):
    help = 'Realiza backup diario de la base de datos PostgreSQL'

    def handle(self, *args, **options):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        
        db_name = settings.DATABASES['default']['NAME']
        db_user = settings.DATABASES['default']['USER']
        today = date.today().strftime('%Y-%m-%d')
        filename = f'{BACKUP_DIR}/appo_db_{today}.sql.gz'
        
        cmd = f'pg_dump -U {db_user} {db_name} | gzip > {filename}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            size = os.path.getsize(filename)
            self.stdout.write(self.style.SUCCESS(f'✅ Backup: {filename} ({size/1024/1024:.1f} MB)'))
            
            # Limpiar backups viejos (>7 días)
            import glob, time
            for old in glob.glob(f'{BACKUP_DIR}/appo_db_*.sql.gz'):
                age = time.time() - os.path.getmtime(old)
                if age > RETENTION_DAYS * 86400:
                    os.remove(old)
                    self.stdout.write(f'🧹 Eliminado backup viejo: {old}')
        else:
            self.stderr.write(f'❌ Error backup: {result.stderr}')
