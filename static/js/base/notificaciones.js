// Notificaciones
function actualizarBadgeNotificaciones(nuevoValor) {
  const countSpan = document.getElementById('notificacionesCount');
  const bell = document.getElementById('notificacionesBell');
  
  if (!countSpan || !bell) return;
  
  const valorAnterior = parseInt(countSpan.textContent) || 0;
  
  if (nuevoValor > 0) {
    countSpan.textContent = nuevoValor;
    // Usar Bootstrap d-none en lugar de display: flex
    countSpan.classList.remove('d-none');
    
    if (nuevoValor > valorAnterior && valorAnterior > 0) {
      // Animación más llamativa para nuevas notificaciones
      countSpan.classList.add('bounce');
      bell.classList.add('shake');
      
      // Cambiar color temporalmente
      countSpan.style.background = 'var(--color-teal-accent)';
      countSpan.style.color = 'white';
      
      setTimeout(() => {
        countSpan.classList.remove('bounce');
        bell.classList.remove('shake');
        countSpan.style.background = '';
        countSpan.style.color = '';
      }, 1000);
    } else if (nuevoValor > valorAnterior) {
      // Primera notificación
      countSpan.classList.add('pulse');
      bell.classList.add('pulse');
      
      setTimeout(() => {
        countSpan.classList.remove('pulse');
        bell.classList.remove('pulse');
      }, 500);
    }
  } else {
    countSpan.classList.add('d-none');
    countSpan.textContent = 0;
  }
}

// Chat (preparado para el futuro)
function actualizarBadgeChat(nuevoValor) {
  const chatCount = document.getElementById('chatCount');
  const chatIcon = document.getElementById('chatIcon');
  const valorAnterior = parseInt(chatCount.textContent) || 0;
  if (nuevoValor > 0) {
    chatCount.textContent = nuevoValor;
    chatCount.classList.remove('d-none');
    if (nuevoValor > valorAnterior) {
      chatCount.classList.add('bounce');
      chatIcon.classList.add('bounce');
      setTimeout(() => {
        chatCount.classList.remove('bounce');
        chatIcon.classList.remove('bounce');
      }, 700);
    }
  } else {
    chatCount.classList.add('d-none');
    chatCount.textContent = 0;
  }
}

// Consulta periódica de mensajes no leídos
function fetchMensajesNoLeidos() {
  fetch('/chat/api/mensajes-no-leidos/')
    .then(resp => resp.json())
    .then(data => {
      if (typeof data.no_leidos !== 'undefined') {
        actualizarBadgeChat(data.no_leidos);
      }
    })
    .catch(() => {});
}

// Consulta periódica de notificaciones (solo usuarios autenticados)
function fetchNotificaciones() {
  fetch('/cuentas/api/notificaciones/')
    .then(resp => {
      if (!resp.ok) return null;
      const ct = resp.headers.get('content-type') || '';
      if (ct.includes('text/html')) return null;
      return resp.json();
    })
    .then(data => {
      if (data && typeof data.no_leidas !== 'undefined') {
        actualizarBadgeNotificaciones(data.no_leidas);
        
        if (data.no_leidas > 0) {
          mostrarNotificacionPush('Nueva notificación', 'Tienes una nueva notificación en APPO');
        }
      }
    })
    .catch(() => {});
}

// Función para mostrar notificación push del navegador
function mostrarNotificacionPush(titulo, mensaje) {
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(titulo, {
      body: mensaje,
                  icon: '/static/images/ui/appo-pattern.png',
            badge: '/static/images/ui/appo-pattern.png'
    });
  }
}

// Solicitar permisos de notificación al cargar la página
document.addEventListener('DOMContentLoaded', function() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
});

// ── Polling inteligente: solo para usuarios autenticados ──
// Detecta si la API devuelve JSON (autenticado) o HTML/redirect (no autenticado)
// así evita errores de consola y tráfico innecesario en landing/login/registro

function initPolling() {
  // Primera llamada de prueba: si la API devuelve HTML → no autenticado, abortar
  fetch('/cuentas/api/notificaciones/')
    .then(resp => {
      const ct = resp.headers.get('content-type') || '';
      if (ct.includes('text/html') || resp.redirected) {
        // No autenticado: no iniciar polling
        return null;
      }
      // Autenticado: iniciar polling periódico
      startPolling();
      return resp.json();
    })
    .then(data => {
      if (data && typeof data.no_leidas !== 'undefined') {
        actualizarBadgeNotificaciones(data.no_leidas);
      }
    })
    .catch(() => {});
}

function startPolling() {
  fetchMensajesNoLeidos();
  setInterval(fetchMensajesNoLeidos, 60000);
  setInterval(fetchNotificaciones, 60000);
}

document.addEventListener('DOMContentLoaded', initPolling);

// Hook para integración con AJAX existente
document.addEventListener('DOMContentLoaded', function() {
  if (window.cargarNotificaciones) {
    const originalCargar = window.cargarNotificaciones;
    window.cargarNotificaciones = async function() {
      const data = await originalCargar.apply(this, arguments);
      if (data && typeof data.no_leidas !== 'undefined') {
        actualizarBadgeNotificaciones(data.no_leidas);
      }
      return data;
    };
  }
}); 