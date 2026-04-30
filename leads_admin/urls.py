from django.urls import path
from . import views

app_name = 'leads_admin'

urlpatterns = [
    path('', views.crm_dashboard, name='dashboard'),
    path('conectar/', views.conectar_whatsapp, name='conectar'),
    path('webhook/', views.webhook_evolution, name='webhook'),
    path('estado/', views.obtener_estado_conexion, name='estado'),
    path('chats/', views.obtener_chats, name='chats'),
    path('mensajes/<str:chat_id>/', views.obtener_mensajes, name='mensajes'),
    path('qr/', views.qr_proxy, name='qr_proxy'),
]
