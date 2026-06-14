
## 2026-06-13 — Rediseño bot CRM Appo (Owen)
- CAUSA RAÍZ baneo de interés: webhook IGNORABA (continue) los auto-replies de WA Business →
  el lead nunca "respondía" → pipeline lo arrastraba a despedida. Todos los envíos del día eran rendiciones.
- FIX: nuevo handler generar_respuesta_autoreply() + procesar_lead_autoreply() / _whatsapp_autoreply().
  Cruza la barrera UNA vez (marcador zero-width \u200b como loop-guard). Marca conv 'respondio'.
- LLM: primario gpt-oss-120b:free (probado en vivo, mejor que Gemma que soltaba frases de su blacklist).
  Cascada de 6 modelos free. Semáforo global concurrencia=4 (env LLM_MAX_CONCURRENCY) anti-truene.
- DOBLE follow-up: seguir_virtuales saltaba leads reales (16 solapados). Ahora excluye teléfonos de Lead real.
- Saludo inicial: 5 plantillas rotadas (anti-huella spam Meta).
- Rate: rampa calentamiento por edad del número (sem1=15, sem2=25, sem3=40, sem4+=60/día). env LEADS_DAILY_CAP override. Cron --limit 2/hora.

## 2026-06-13 23:30 UTC — Sistema Win-Back desplegado (no-show + inactivos)
- Modelo `clientes.RecuperacionCliente` (tracking anti-spam: tipo no_show|inactivo, enviado_ok, respondio, reagendo, opt_out). Migración 0015 aplicada (0010-0014 estaban físicamente en Postgres pero sin marcar → --fake).
- 2 mensajes texto-libre en webjs_whatsapp_service: send_winback_noshow / send_winback_inactivo (vía whatsapp-web.js, SIN plantillas Meta).
- Comando recordatorios/management/commands/recuperar_clientes.py (--tipo no_show|inactivo|todos, --dry-run, --dias-inactivo 5, ventana anti-reenvío 30d, cap por negocio, respeta horario Colombia, bloqueados, cita futura, opt-out).
- Cron: 0 15 * * * (10:00 Colombia) --tipo todos --dias-inactivo 5 → logs/winback.log
- Admin Django registrado para métricas.
- Backups: clientes/models.py.bak_winback_*, clientes/webjs_whatsapp_service.py.bak_winback_*
