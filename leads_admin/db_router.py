"""
Router de base de datos para leads_admin.
Todas las tablas de leads_admin van a leads_db:
  - Lead
  - LeadConversacion
  - ChatWhatsApp
  - MensajeWhatsApp
"""

LEADS_MODELS = {'lead', 'leadconversacion', 'chatwhatsapp', 'mensajewhatsapp'}


class LeadsRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'leads_admin':
            return 'leads_db'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'leads_admin':
            return 'leads_db'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # Permitir relaciones dentro de leads_admin
        if obj1._meta.app_label == 'leads_admin' and obj2._meta.app_label == 'leads_admin':
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == 'leads_admin':
            return db == 'leads_db'
        if db == 'leads_db':
            return False
        return None
