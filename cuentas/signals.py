from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse
from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import pre_social_login
from django.conf import settings
from .models import UsuarioPersonalizado

@receiver(user_signed_up)
def handle_user_signed_up(sender, request, user, **kwargs):
    """
    Signal que se ejecuta cuando un usuario se registra con Google
    """
    # Verificar si el usuario tiene una cuenta social (Google)
    if hasattr(user, 'socialaccount_set') and user.socialaccount_set.filter(provider='google').exists():
        # Asignar tipo por defecto si no tiene
        if not hasattr(user, 'tipo') or not user.tipo:
            user.tipo = 'cliente'
            user.save()

@receiver(pre_social_login)
def handle_pre_social_login(sender, request, sociallogin, **kwargs):
    """
    Signal que se ejecuta antes del login social.
    Si el usuario viene del registro con tipo seleccionado, lo pasa al state.
    """
    # Intentar obtener tipo desde query params del callback
    tipo_desde_request = request.GET.get('tipo') or request.POST.get('tipo')
    tipos_validos = ['cliente', 'negocio', 'profesional']
    
    if tipo_desde_request and tipo_desde_request in tipos_validos:
        sociallogin.state['tipo'] = tipo_desde_request
    
    if sociallogin.is_existing:
        user = sociallogin.user
        if not hasattr(user, 'tipo') or not user.tipo:
            sociallogin.state['next'] = reverse('cuentas:seleccionar_tipo_google')
    else:
        # Usuario nuevo: si ya tiene tipo desde el registro, no redirigir a seleccionar
        tipo_state = sociallogin.state.get('tipo') if hasattr(sociallogin, 'state') else None
        if not tipo_state or tipo_state not in tipos_validos:
            sociallogin.state['next'] = reverse('cuentas:seleccionar_tipo_google')

@receiver(post_save, sender=UsuarioPersonalizado)
def ensure_super_admin(sender, instance, **kwargs):
    if instance.is_superuser and instance.tipo != 'super_admin':
        instance.tipo = 'super_admin'
        instance.save(update_fields=['tipo']) 