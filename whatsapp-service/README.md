# WhatsApp CRM Service

Microservicio Node.js para integración de WhatsApp usando `whatsapp-web.js`. Reemplaza Evolution API con mayor estabilidad y soporte nativo para LID.

## Características

- ✅ Compatible con API de Evolution (mismos endpoints)
- ✅ Soporte nativo para LID (`@lid`) - sin workarounds
- ✅ Sesiones persistentes con `LocalAuth`
- ✅ Webhooks para `MESSAGES_UPSERT` y `CONNECTION_UPDATE`
- ✅ Auto-reconexión ante desconexiones
- ✅ Logging estructurado con Winston
- ✅ Servicio systemd y PM2 para alta disponibilidad

## Instalación

```bash
cd /var/www/appo.com.co/whatsapp-service
npm install
```

## Configuración

Copiar `.env.example` a `.env` y ajustar variables:

```bash
cp .env.example .env
nano .env
```

Variables importantes:
- `PORT`: Puerto del servicio (8081)
- `INSTANCE_NAME`: Nombre de instancia (APPO_CRM)
- `API_KEY`: Clave API para autenticar webhooks
- `WEBHOOK_URL`: URL del webhook del CRM
- `DISPLAY`: Display Xvfb (:99)
- `PUPPETEER_EXECUTABLE_PATH`: Ruta a Chromium

## Uso

### Iniciar con systemd (recomendado)
```bash
sudo systemctl daemon-reload
sudo systemctl enable whatsapp-crm.service
sudo systemctl start whatsapp-crm.service
```

### Ver estado
```bash
sudo systemctl status whatsapp-crm.service
journalctl -u whatsapp-crm.service -f
```

### Iniciar con PM2
```bash
npm install -g pm2
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

### Pruebas manuales
```bash
npm start
```

## Endpoints de API

### Estado de conexión
```
GET /instance/connectionState/APPO_CRM
```
Respuesta:
```json
{
  "instance": {
    "instanceName": "APPO_CRM",
    "state": "open"
  }
}
```

### Enviar mensaje
```
POST /message/sendText/APPO_CRM
```
Body:
```json
{
  "number": "573019262619",
  "textMessage": {
    "text": "Hola, esto es una prueba"
  }
}
```

### Obtener QR
```
GET /instance/qr/APPO_CRM
```

### Reiniciar instancia
```
POST /instance/restart/APPO_CRM
```

### Cerrar sesión
```
DELETE /instance/logout/APPO_CRM
```

### Health check
```
GET /health
```

## Webhooks Compatibles

El servicio envía webhooks al CRM con los mismos formatos que Evolution API:

### 1. `MESSAGES_UPSERT`
```json
{
  "event": "MESSAGES_UPSERT",
  "instance": "APPO_CRM",
  "data": {
    "key": {
      "remoteJid": "573019262619@s.whatsapp.net",
      "fromMe": false,
      "id": "ABC123"
    },
    "message": {
      "conversation": "Hola, necesito información",
      "extendedTextMessage": {
        "text": "Hola, necesito información"
      }
    },
    "messageTimestamp": 1745847600,
    "pushName": "Juan Pérez",
    "broadcast": false,
    "status": "received"
  }
}
```

### 2. `CONNECTION_UPDATE`
```json
{
  "event": "CONNECTION_UPDATE",
  "instance": "APPO_CRM",
  "state": "open",
  "status": "connected"
}
```

## Reconexión Manual

Si la sesión de WhatsApp se cae:

1. **Verificar estado:**
   ```bash
   sudo systemctl status whatsapp-crm.service
   ```

2. **Ver logs:**
   ```bash
   journalctl -u whatsapp-crm.service -n 50
   ```

3. **Reiniciar servicio:**
   ```bash
   sudo systemctl restart whatsapp-crm.service
   ```

4. **Si persiste, regenerar QR:**
   ```bash
   curl -X POST http://localhost:8081/instance/restart/APPO_CRM
   ```
   Luego escanear nuevo QR en `http://localhost:8081/instance/qr/APPO_CRM`

## Solución de Problemas

### 1. "Error: Failed to launch the browser process"
- Verificar que Chromium esté instalado: `which chromium`
- Ajustar `PUPPETEER_EXECUTABLE_PATH` en `.env`
- Instalar dependencias: `apt-get install -y chromium`

### 2. "No se muestra QR"
- Verificar que Xvfb esté corriendo: `ps aux | grep Xvfb`
- Asegurar `DISPLAY=:99` en `.env`

### 3. "Webhooks no llegan al CRM"
- Verificar que `WEBHOOK_URL` sea correcta
- Revisar logs del servicio: `journalctl -u whatsapp-crm.service`
- Probar manualmente: `curl -X POST -H "apikey: KEY" WEBHOOK_URL`

### 4. "No se envían mensajes"
- Verificar estado de conexión: `GET /health`
- Revisar que el número tenga formato correcto: `573019262619@s.whatsapp.net`
- Verificar logs de errores

## Mantenimiento

### Rotación de logs
Los logs se guardan en:
- `whatsapp-service.log` (Winston)
- `logs/error.log` y `logs/out.log` (PM2)
- Journalctl: `journalctl -u whatsapp-crm.service`

### Actualización
```bash
cd /var/www/appo.com.co/whatsapp-service
git pull  # si usa git
npm install
sudo systemctl restart whatsapp-crm.service
```

## Monitoreo

- **Health check:** `curl http://localhost:8081/health`
- **Estado conexión:** `curl http://localhost:8081/instance/connectionState/APPO_CRM`
- **Métricas básicas:** `pm2 monit` o `systemctl status`

---

**Nota:** Este servicio es compatible con el CRM existente. No modificar el CRM hasta que el servicio esté probado y estable.