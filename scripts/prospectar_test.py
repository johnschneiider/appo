#!/usr/bin/env python3
"""
Script de prueba para verificar el funcionamiento del comando prospectar_leads
sin problemas de entorno.
"""
import os
import sys
import django

# Configurar entorno
sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')

# Cargar variables de entorno desde .env
env_path = '/var/www/appo.com.co/.env'
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)

# Configurar Django
django.setup()

# Ejecutar comando
from django.core.management import call_command
sys.argv = ['manage.py', 'prospectar_leads', '--dry-run', '--ignore-hours', '--limit', '1']
try:
    call_command('prospectar_leads', '--dry-run', '--ignore-hours', '--limit', '1')
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)