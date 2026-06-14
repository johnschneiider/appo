#!/usr/bin/env python3
"""
Script para enviar mensaje de prueba a un lead usando Evolution API.
Simula el comportamiento del sistema de prospección pero sin base de datos.
"""
import os
import sys
import time
import random
import requests
import json

# Configurar entorno Django
sys.path.insert(0, '/var/www/appo.com.co')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')
import django
django.setup()

# Configuración Evolution API
EVOLUTION_API_URL = "http://localhost:8080"
API_KEY = "OWEN_STRATEGIC_KEY_2026_COL"
INSTANCE_NAME = "APPO_CRM"

def enviar_whatsapp(telefono: str, mensaje: str) -> bool:
    """Envía un mensaje de WhatsApp usando Evolution API."""
    # Formatear número
    numero = telefono.replace("+", "").replace(" ", "")
    if not numero.startswith("57"):
        numero = "57" + numero
    
    headers = {
        "apikey": API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": numero,
        "textMessage": {
            "text": mensaje
        }
    }
    try:
        r = requests.post(
            f"{EVOLUTION_API_URL}/message/sendText/{INSTANCE_NAME}",
            headers=headers,
            json=payload,
            timeout=15
        )
        r.raise_for_status()
        respuesta = r.json()
        print(f"✅ WhatsApp enviado a {numero}: {respuesta.get('status', 'unknown')}")
        return True
    except Exception as e:
        print(f"❌ Error enviando WhatsApp a {telefono}: {e}")
        return False

def enviar_saludo(nombre: str, telefono: str):
    """Envía saludo en 3 partes con delays."""
    PARTES = [
        f"Hola {nombre} 👋",
        "Te escribo desde *Appo* — la app que usan barberías en Colombia para que sus clientes reserven solos desde el celular, sin llamadas ni WhatsApp manual.",
        "¿Todavía manejas tus citas a mano?\n\n👉 appo.com.co"
    ]
    
    print(f"Enviando saludo a {telefono} ({nombre})...")
    for i, parte in enumerate(PARTES):
        print(f"\nParte {i+1}/{len(PARTES)}: '{parte[:50]}...'")
        exito = enviar_whatsapp(telefono, parte)
        if not exito:
            print("❌ Falló el envío.")
            return False
        if i < len(PARTES) - 1:
            delay = random.uniform(2, 4)
            print(f"Esperando {delay:.1f}s...")
            time.sleep(delay)
    
    print("\n✅ Saludo completo enviado.")
    return True

def verificar_conexion():
    """Verifica que la instancia esté conectada."""
    headers = {'apikey': API_KEY}
    try:
        resp = requests.get(f"{EVOLUTION_API_URL}/instance/connectionState/{INSTANCE_NAME}", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            estado = data.get('instance', {}).get('state', 'close')
            print(f"Estado conexión: {estado}")
            return estado == 'open'
        else:
            print(f"Error estado conexión: {resp.status_code}")
            return False
    except Exception as e:
        print(f"Error verificando conexión: {e}")
        return False

if __name__ == "__main__":
    print("=== Test envío WhatsApp ===")
    
    if not verificar_conexion():
        print("❌ Instancia no conectada. Abortando.")
        sys.exit(1)
    
    # Datos de prueba
    telefono = "573117451274"  # Número del lead (sin +)
    nombre = "amigo"
    
    print(f"\nEnviando a: {telefono}")
    enviar_saludo(nombre, telefono)
    
    print("\n=== Test completado ===")
    print("\nPara probar la respuesta automática, envía un mensaje desde WhatsApp a este número.")
    print("El webhook debería procesarlo y responder usando el agente.")