#!/usr/bin/env python3
"""Migra leads zombie (>=3 msgs del bot, 0 respuestas del lead) a estado seguro.
- lead_conversacion.estado -> 'no_respondio'
- leads.no_contactar = 1, motivo + fecha
Doble candado anti-spam. Idempotente."""
import sqlite3, json, sys
from datetime import datetime, timezone

DB = '/var/www/appo.com.co/data/leads_colombia.db'
MOTIVO = "Spam preventivo: 3+ mensajes sin respuesta (batch Jun 2026)"
now = datetime.now(timezone.utc).isoformat()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

rows = cur.execute("""
    SELECT lc.id conv_id, lc.lead_id, lc.estado, lc.mensajes,
           l.nombre_establecimiento, l.no_contactar
    FROM lead_conversacion lc JOIN leads l ON l.id = lc.lead_id
""").fetchall()

targets = []
for r in rows:
    try:
        msgs = json.loads(r['mensajes']) if r['mensajes'] else []
    except Exception:
        msgs = []
    n_asst = sum(1 for m in msgs if m.get('role') == 'assistant')
    n_user = sum(1 for m in msgs if m.get('role') == 'user')
    if n_user == 0 and n_asst >= 3:
        targets.append((r['conv_id'], r['lead_id'], r['nombre_establecimiento'], n_asst, r['estado'], r['no_contactar']))

dry = '--apply' not in sys.argv
print(f"{'[DRY-RUN]' if dry else '[APPLY]'} {len(targets)} leads zombie a migrar\n")
for conv_id, lead_id, nombre, n, estado, nc in targets:
    print(f"  lead#{lead_id} conv#{conv_id} {estado}->no_respondio, no_contactar={nc}->1  ({n}msg) {nombre[:30]}")

if not dry:
    for conv_id, lead_id, *_ in targets:
        cur.execute("UPDATE lead_conversacion SET estado='no_respondio', updated_at=? WHERE id=?", (now, conv_id))
        cur.execute("""UPDATE leads SET no_contactar=1, motivo_no_contactar=?, fecha_no_contactar=?
                       WHERE id=? AND no_contactar=0""", (MOTIVO, now, lead_id))
    con.commit()
    print(f"\n✅ Migrados {len(targets)} leads. Commit OK.")
con.close()
