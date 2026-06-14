from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.urls import reverse
from django.shortcuts import redirect
from .models import UsuarioPersonalizado

class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Adaptador personalizado para manejar la redirección después del registro/login
    """
    
    def get_login_redirect_url(self, request):
        """
        Redirige al usuario según su tipo después del login
        """
        if request.user.is_authenticated:
            try:
                # Como UsuarioPersonalizado extiende User, accedemos directamente
                if hasattr(request.user, 'tipo'):
                    if request.user.tipo == 'cliente':
                        return reverse('inicio')  # Redirige a la raíz
                    elif request.user.tipo == 'negocio':
                        return reverse('negocios:mis_negocios')  # Redirige al panel de negocio
                    elif request.user.tipo == 'profesional':
                        return reverse('profesionales:panel')
                    elif request.user.tipo == 'super_admin':
                        return reverse('dashboard_super_admin')
                    else:
                        return reverse('inicio')
                else:
                    # Si no tiene tipo, redirigir a seleccionar
                    return reverse('cuentas:seleccionar_tipo_google')
            except Exception:
                # Si hay algún error, redirigir a seleccionar tipo
                return reverse('cuentas:seleccionar_tipo_google')
        
        return super().get_login_redirect_url(request)

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Adaptador personalizado para manejar la redirección después del login social
    """
    
    def get_app(self, request, provider, client_id=None):
        """
        Obtiene la SocialApp, pero no falla si no existe
        """
        try:
            return super().get_app(request, provider, client_id)
        except Exception:
            # Si no existe la SocialApp, retornar None en lugar de fallar
            return None
    
    def pre_social_login(self, request, sociallogin):
        """
        Se ejecuta antes del login social.
        Si el usuario viene del registro con tipo seleccionado, lo asigna directamente.
        """
        # Intentar obtener el tipo desde el state de OAuth (pasado como query param)
        tipo_desde_registro = sociallogin.state.get('tipo') if hasattr(sociallogin, 'state') else None
        
        # Si no viene en state, intentar obtener de los query params del request
        if not tipo_desde_registro:
            tipo_desde_registro = request.GET.get('tipo') or request.POST.get('tipo')
        
        # Validar que el tipo sea válido
        tipos_validos = ['cliente', 'negocio', 'profesional']
        if tipo_desde_registro and tipo_desde_registro in tipos_validos:
            # Guardar en el state para que save_user lo use
            sociallogin.state['tipo'] = tipo_desde_registro
        
        # Verificar si el usuario ya existe
        if sociallogin.is_existing:
            user = sociallogin.user
            if hasattr(user, 'tipo') and user.tipo:
                pass  # Ya tiene tipo, continuar normal
            else:
                # Usuario existente sin tipo → redirigir a seleccionar
                sociallogin.state['next'] = reverse('cuentas:seleccionar_tipo_google')
        else:
            # Usuario nuevo
            if tipo_desde_registro and tipo_desde_registro in tipos_validos:
                # Ya tenemos el tipo → NO redirigir a seleccionar, continuar directo
                pass
            else:
                # Sin tipo → redirigir a seleccionar
                sociallogin.state['next'] = reverse('cuentas:seleccionar_tipo_google')
    
    def save_user(self, request, sociallogin, form=None):
        """
        Guarda usuario de Google con el tipo de cuenta correcto.
        Respeta el tipo seleccionado en el formulario de registro.
        """
        user = super().save_user(request, sociallogin, form)
        
        # Obtener tipo desde el state de OAuth (viene del query param ?tipo=)
        tipo_desde_state = sociallogin.state.get('tipo') if hasattr(sociallogin, 'state') else None
        
        # También verificar GET/POST params como respaldo
        tipo_desde_request = request.GET.get('tipo') or request.POST.get('tipo')
        
        tipo_final = tipo_desde_state or tipo_desde_request
        tipos_validos = ['cliente', 'negocio', 'profesional']
        
        if tipo_final and tipo_final in tipos_validos:
            user.tipo = tipo_final
        elif not hasattr(user, 'tipo') or not user.tipo:
            user.tipo = 'cliente'  # Fallback seguro
        
        user.save()
        
        return user 