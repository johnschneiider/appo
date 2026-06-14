# GRAPH_REPORT.md — Appo (appo.com.co)

## Resumen
- **Archivos de código analizados:** 538
- **Nodos (entidades):** 3801
- **Aristas (relaciones):** 6678
- **Modo:** AST-only (sin LLM, costo 0)

## Top 20 archivos por actividad (edges)

| # | Archivo | Edges |
|---|--------|-------|
| 1 | staticfiles/admin/js/vendor/xregexp/xregexp.js | 584 |
| 2 | negocios/views.py | 215 |
| 3 | cuentas/views.py | 195 |
| 4 | clientes/views.py | 169 |
| 5 | staticfiles/admin/js/vendor/jquery/jquery.js | 151 |
| 6 | staticfiles/admin/js/vendor/jquery/jquery.min.js | 147 |
| 7 | clientes/models.py | 144 |
| 8 | negocios/models.py | 87 |
| 9 | recordatorios/services.py | 86 |
| 10 | backup_evolution/APPO_CRM_old/app-state-sync-version-regular.json | 85 |
| 11 | backup_evolution/instances_backup/APPO_CRM/app-state-sync-version-regular.json | 85 |
| 12 | staticfiles/admin/js/vendor/select2/select2.full.js | 76 |
| 13 | clientes/twilio_whatsapp_service.py | 70 |
| 14 | profesionales/models.py | 67 |
| 15 | clientes/forms.py | 66 |
| 16 | suscripciones/forms.py | 65 |
| 17 | staticfiles/admin/js/vendor/select2/select2.full.min.js | 63 |
| 18 | recordatorios/admin.py | 63 |
| 19 | fidelizacion/services.py | 59 |
| 20 | backup_evolution/APPO_CRM_old/creds.json | 58 |

## Distribución de tipos de relación

| Relación | Count |
|----------|-------|
| contains | 2311 |
| imports_from | 1318 |
| calls | 743 |
| rationale_for | 640 |
| uses | 592 |
| imports | 495 |
| method | 437 |
| defines | 77 |
| inherits | 60 |
| extends | 5 |

## Módulos del proyecto

| Módulo | Nodos | Edges |
|--------|-------|-------|
| _backup_untracked | 2 | 4 |
| backup_evolution | 824 | 870 |
| capture_raw.py | 2 | 9 |
| chat | 57 | 99 |
| check_message_status.py | 1 | 3 |
| clientes | 384 | 835 |
| cuentas | 329 | 672 |
| fidelizacion | 67 | 123 |
| ia_visagismo | 68 | 108 |
| leads_admin | 133 | 226 |
| manage.py | 3 | 4 |
| melissa | 30 | 58 |
| negocios | 179 | 439 |
| profesionales | 67 | 132 |
| recordatorios | 224 | 363 |
| scripts | 455 | 867 |
| simulate_incoming.py | 1 | 6 |
| simulate_incoming2.py | 1 | 6 |
| static | 81 | 95 |
| staticfiles | 595 | 1337 |
| suscripciones | 164 | 270 |
| test_agent_message.py | 2 | 9 |
| test_agent_simple.py | 1 | 4 |
| test_envio_whatsapp.py | 7 | 14 |
| test_filter.py | 3 | 7 |
| test_openrouter_models.py | 1 | 3 |
| test_twilio_direct.py | 2 | 5 |
| test_webhook.py | 1 | 5 |
| test_webhook_final.py | 1 | 5 |
| test_webhook_integration.py | 3 | 10 |
| test_whatsapp_django.py | 2 | 6 |
| test_whatsapp_twilio.py | 2 | 5 |
| vitalmix_pro | 2 | 0 |
| whatsapp-service | 54 | 79 |