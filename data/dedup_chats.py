#!/usr/bin/env python3
"""Desduplica chats @lid/@c.us fusionando mensajes en el chat @c.us canónico.
Grupos verificados manualmente (mismo número de teléfono / mensajes compartidos).
- Reapunta mensaje_whatsapp.chat_id de los huérfanos al canónico.
- Recalcula last_message/last_message_timestamp/phone del canónico.
- Elimina los chats huérfanos.
Idempotente: si un huérfano ya no existe, lo salta.
Uso: python3 dedup_chats.py [--apply]
"""
import sqlite3, sys

DB = '/var/www/appo.com.co/data/leads_colombia.db'

# (canonical_chat_id_db, [orphan_chat_id_db, ...]) — todos verificados
GROUPS = [
    (137, [1, 6]),    # 573117451274  (@c.us <- @s.whatsapp.net viejo + @lid 167 msgs)
    (141, [140]),     # 573155022539  <- 175380996579359@lid
    (139, [138]),     # 573172906261  <- 275432662413376@lid
    (143, [142]),     # 573158965266  <- 210333239107764@lid
    (145, [144]),     # 573229896480  <- 98626021920860@lid
    (147, [146]),     # 573127738812  <- 275685847388199@lid
    (155, [154]),     # 573146182526  <- 109276886515925@lid
]

dry = '--apply' not in sys.argv
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

def nmsg(cid):
    return cur.execute("SELECT COUNT(*) c FROM mensaje_whatsapp WHERE chat_id=?", (cid,)).fetchone()['c']

print(f"{'[DRY-RUN]' if dry else '[APPLY]'} Desduplicando {len(GROUPS)} grupos\n")
total_moved = total_deleted = 0
for canon, orphans in GROUPS:
    crow = cur.execute("SELECT chat_id, phone FROM chat_whatsapp WHERE id=?", (canon,)).fetchone()
    if not crow:
        print(f"  ⚠️ Canónico id={canon} no existe, saltando grupo"); continue
    print(f"  Canónico id={canon} ({crow['chat_id']}) msgs={nmsg(canon)} phone={crow['phone']}")
    for orp in orphans:
        orow = cur.execute("SELECT chat_id, phone FROM chat_whatsapp WHERE id=?", (orp,)).fetchone()
        if not orow:
            print(f"    - huérfano id={orp} ya no existe (idempotente)"); continue
        m = nmsg(orp)
        print(f"    - huérfano id={orp} ({orow['chat_id']}) msgs={m} -> mover a {canon} y eliminar")
        if not dry:
            cur.execute("UPDATE mensaje_whatsapp SET chat_id=? WHERE chat_id=?", (canon, orp))
            total_moved += m
            cur.execute("DELETE FROM chat_whatsapp WHERE id=?", (orp,))
            total_deleted += 1
    if not dry:
        # Recalcular last_message del canónico desde el mensaje más reciente
        last = cur.execute("""SELECT message_text, timestamp FROM mensaje_whatsapp
                              WHERE chat_id=? ORDER BY timestamp DESC LIMIT 1""", (canon,)).fetchone()
        if last:
            cur.execute("UPDATE chat_whatsapp SET last_message=?, last_message_timestamp=? WHERE id=?",
                        (last['message_text'], last['timestamp'], canon))
        # Corregir phone del canónico: el @c.us tiene el número REAL en su chat_id.
        # Sobreescribe phones corruptos (18 dígitos del LID) con el número correcto.
        ph = crow['chat_id'].split('@')[0]
        if ph.isdigit() and len(ph) <= 13:
            cur.execute("UPDATE chat_whatsapp SET phone=? WHERE id=?", ('+' + ph, canon))
    print()

if not dry:
    con.commit()
    print(f"✅ Movidos {total_moved} mensajes, eliminados {total_deleted} chats huérfanos. Commit OK.")
else:
    print("Dry-run. Reejecuta con --apply para aplicar.")
con.close()
