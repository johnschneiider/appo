# PIPELINE PROSPECCIÓN APPO — Documentación del sistema

> Última actualización: 2026-06-08

## Visión general

Sistema automatizado de prospección de barberías vía WhatsApp usando LLM (Gemma 4 31B gratuito vía OpenRouter). El bot contacta barberías en frío con un guión criollo colombiano diseñado para no ser invasivo.

---

## Estado actual (08-Jun-2026)

| Componente | Estado |
|---|---|
| Pipeline | 🟢 Corriendo (1 contacto cada 40-45 min) |
| WhatsApp | 🟢 Conectado (whatsapp-web.js v1.34.7) |
| Webhook | 🟢 Activo |
| LLM | 🟢 google/gemma-4-31b-it:free |
| Leads DB | 718 barberías (Valle del Cauca) |

---

## Infraestructura

### Servicios

| Servicio | Puerto | Tecnología |
|---|---|---|
| Appo Django | unix socket → Nginx :443 | Daphne ASGI |
| Evolution API | 8080 | Docker (solo como proxy de webhook) |
| WhatsApp Service | 8081 | Node.js + whatsapp-web.js v1.34.7 |
| PostgreSQL | 5432 | DB principal (usuarios, negocios, reservas) |
| SQLite leads | archivo | `/var/www/appo.com.co/data/leads_colombia.db` |

### Cron

- **Frecuencia**: Lunes a Sábado 8:00 AM (hora Colombia)
- **Acción**: Dispara `prospectar.sh` → `manage.py prospectar_leads --ignore-hours`
- **Ritmo**: 1 lead cada 40-45 minutos hasta las 6PM
- **ID**: `19e09d46-7b7d-449e-8311-4bb8f78df6bb`

### Modelos LLM (OpenRouter)

```python
FREE_MODELS = [
    "google/gemma-4-31b-it:free",               # Primario - 262K ctx, no emite razonamiento
    "meta-llama/llama-3.3-70b-instruct:free",   # Fallback 1 - 131K ctx
    "nvidia/nemotron-3-super-120b-a12b:free",   # Último recurso - emite razonamiento
]
```

⚠️ **Nunca usar Nemotron como primario** — emite razonamiento en el campo `content` que el safety filter no siempre detecta.

---

## Guión de prospección (v2 criollo)

### Toque 1 — Día 1 (inmediato)
> Hola, buenos días 👋 ¿Aquí es [Nombre del Negocio]?

### Toque 2 — Si responden
> Listo, gracias. Mira, soy Juan, de Appo, una plataforma de reservas para barberías. La pregunta es simple: ¿ustedes cómo manejan las citas hoy, por WhatsApp o llamadas?

### Si dicen WhatsApp/Llamadas
> Claro, así manejan casi todas. Lo malo es que si uno no contesta, el cliente se va pa' otra barbería. Con Appo el cliente reserva solo desde el celular, a la hora que sea, y a ti solo te llega la notificación. Un negocio bajó las citas perdidas un 42%. Son 49.000 por barbero al mes, primer mes gratis. ¿Cuántos barberos tienen?

### Si rechazan
> Dale, tranqui. Quédate con el dato por si acaso: appo.com.co, primer mes gratis. Buen día 🙌

### Si ya tienen sistema
> Dale, entiendo. Si algún día te falla o te quita mucho tiempo, revisa appo.com.co. Primer mes gratis, sin permanencia. Buen día 🙌

### Toque 3 — Día 3 (follow-up)
> Hola 👋 Soy Juan, te escribí hace un par de días. Tengo una plataforma que deja que tus clientes agenden solos las citas, sin llamar ni escribir. Te ahorra como 30 minutos diarios en puro WhatsApp. ¿Te explico en 1 minuto o no va por ahí?

### Toque 4 — Día 6 (último)
> Juan otra vez, y ya esta es la última, tranqui. Solo te dejo el dato: appo.com.co, primer mes gratis, sin permanencia. Si algún día te sirve, ahí está. Buen día 🙌

---

## Reglas del bot (prompt system)

1. Máximo 3 líneas por mensaje
2. Lenguaje criollo colombiano: "pa'", "ahorita", "dale", "pilas", "tranqui"
3. Cero frases corporativas
4. Si dice NO → cerrar inmediatamente, sin insistir
5. No mentir sobre origen del número (Google Maps)
6. **NUNCA usar placeholders [Negocio]**
7. **NUNCA re-enviar saludo inicial si ya respondieron**
8. **NUNCA hacer contrapreguntas innecesarias** — si ya tienen sistema, link y despedida

---

## DB de leads

- **Archivo**: `/var/www/appo.com.co/data/leads_colombia.db`
- **Tabla principal**: `leads`
- **Conversaciones**: `lead_conversacion` (JSON `mensajes`)
- **Total**: 718 barberías en Valle del Cauca
- **Fuente**: Google Maps Places API (scraping con grid denso, Jun 2026)

### Distribución por ciudad (top 10)

| Ciudad | Leads |
|---|---|
| Cali | 316 |
| Palmira | 79 |
| Jamundí | 56 |
| Yumbo | 42 |
| Buga | 40 |
| Candelaria | 27 |
| Santander de Quilichao | 21 |
| El Cerrito | 18 |
| Florida | 8 |
| Puerto Tejada | 6 |

---

## Flujo de conversación

```
1. Pipeline envía saludo inicial
   ↓
2. DB guarda: lead_conversacion.mensajes = [{role: "assistant", content: "Hola..."}]
   ↓
3. Lead responde → whatsapp-service recibe → webhook a Django
   ↓
4. Django filtra fromMe=False → carga historial COMPLETO
   ↓
5. LLM (Gemma 4) recibe:
   [SYSTEM] Prompt de Juan + RAG de appo.com.co
   [historial conversación...]
   [USER] mensaje del lead
   ↓
6. LLM genera respuesta → enviada por whatsapp-service
   ↓
7. Ambos mensajes guardados en lead_conversacion.mensajes
```

---

## Auto-respuestas (WhatsApp Business)

Muchos negocios tienen mensajes automáticos. El prompt instruye al LLM a detectarlos y responder solo con `.` (el sistema no envía el punto).

Señales de auto-respuesta:
- "Gracias por comunicarte con..."
- "Te damos la bienvenida..."
- "En este momento no podemos responder..."
- Mensajes con listas de barberos/servicios

---

## Safety filter (código)

En `prospector_agent.py`, `generar_respuesta()`:

```python
if respuesta:
    razonamiento_markers = [
        'needs to stick to the script', 'according to the rules', ...
    ]
    is_razonamiento = any(m in respuesta.lower() for m in razonamiento_markers)
    is_too_long = len(respuesta) > 400
    if is_razonamiento or is_too_long:
        return None  # No enviar
```

---

## Comandos útiles

```bash
# Ver estado del pipeline
ps aux | grep prospectar

# Ver últimos mensajes enviados
tail -50 /var/www/appo.com.co/whatsapp-service/whatsapp-service.log | grep "Enviando"

# Lanzar pipeline manualmente
bash /var/www/appo.com.co/scripts/prospectar.sh --ignore-hours --limit 1

# Ver leads contactados hoy
sqlite3 /var/www/appo.com.co/data/leads_colombia.db \
  "SELECT COUNT(*) FROM lead_conversacion WHERE date(ultimo_contacto)=date('now');"

# Ver estado WhatsApp
curl -s http://localhost:8081/health | python3 -m json.tool

# Reiniciar Django
systemctl restart appo.service

# Reiniciar WhatsApp service (si se cae)
cd /var/www/appo.com.co/whatsapp-service && nohup node index.js > whatsapp-service.log 2>&1 &

# Regenerar QR (si se desvincula)
rm -rf /var/www/appo.com.co/whatsapp-service/.wwebjs_auth
# Reiniciar servicio ↑
curl -s http://localhost:8081/instance/qrBase64/APPO_CRM | python3 -c "..."
```

---

## Lecciones aprendidas (08-Jun-2026)

1. **Nemotron free emite razonamiento** → NO usar como primario. Gemma 4 es limpio.
2. **whatsapp-web.js debe estar actualizado** → v1.24.0 usaba Chrome 101 (2022), WhatsApp rechazaba mensajes silenciosamente. v1.34.7 usa Chrome 147 (actual).
3. **Formato de número**: `@lid` es más fiable que `@s.whatsapp.net` con whatsapp-web.js v1.34+
4. **Webhook kill-switch**: útil para debug pero peligroso en producción. Los leads que responden se pierden.
5. **Pipeline duplicado**: puede pasar si el proceso anterior no muere. Siempre verificar con `ps aux | grep prospectar`.
6. **ultimo_contacto**: debe setearse explícitamente en `guardar_mensaje()`.
7. **Placeholders en prompt**: el LLM puede repetir `[Negocio]` literal. Reglas 6+7 lo previenen.
8. **Contrapreguntas**: preguntar "¿qué usan?" a quien ya tiene sistema es molesto. Cierre directo.

---

## Próximos pasos

- [ ] Escalar a más departamentos (Antioquia, Cundinamarca, Atlántico)
- [ ] Dashboard de métricas (tasa de respuesta, conversión)
- [ ] A/B testing de guiones
- [ ] Integrar pago directamente desde el chat
- [ ] Migrar leads_colombia.db a PostgreSQL
