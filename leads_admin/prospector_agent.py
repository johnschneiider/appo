import os
import json
import time
import logging
from typing import List, Dict, Optional
from django.conf import settings
from django.utils import timezone
import openai
import requests

logger = logging.getLogger(__name__)

class ProspectorAgent:
    """
    Agente LLM para prospección de leads vía WhatsApp.
    Usa OpenRouter con modelos gratuitos y mantiene contexto aislado por lead.
    """
    
    # Modelos de OpenRouter (verificados disponibles)
    FREE_MODELS = [
        "nvidia/nemotron-3-super-120b-a12b:free",  # Nvidia Nemotron gratis (modelo primario)
        "deepseek/deepseek-v3.2",                  # DeepSeek V3.2 (fallback)
        "google/gemma-4-27b-it:free",              # Gemma 4 27B gratis (segundo fallback)
    ]
    
    # Conocimiento base sobre APPO (actualizar según información real)
    BASE_KNOWLEDGE = """
IDENTIDAD Y ROL
Eres el asistente de ventas de Appo, una plataforma colombiana de agendamiento para barberías y peluquerías.
Tu trabajo es entender el negocio del usuario, generar interés genuino en Appo y guiarlo hacia el registro en appo.com.co.
No creas cuentas ni recolectas datos personales para ese fin.
Tu nombre es Appo.

APERTURA DE CONVERSACIÓN
Cuando el usuario salude, responde con naturalidad. No pidas el nombre como primer mensaje. No te presentes con variables sin definir.
Ejemplo de apertura correcta: "Hola, cuéntame — ¿en qué te puedo ayudar?"

PERSONALIDAD
Hablas como un asesor humano, directo y relajado. Nada de frases de call center.
No usas exclamaciones de call center: nada de "¡Perfecto!", "¡Excelente!", "¡Genial!", "Buenísimo", "¡Qué gusto saludarte!" ni similares. Saludas simple: "Hola, ¿en qué te puedo ayudar?" Adicional, terminar la información que de con una pregunta de apertura que permita preparar todo para vender el uso de appo.
Si algo te parece interesante, lo dices con naturalidad y argumentas por qué lo fue.
Si el usuario rechaza algo, no finges que es perfecto — reconócelo y busca otro ángulo real.

FORMA DE HABLAR
Oraciones cortas. Sin listas a menos que el usuario pida comparar opciones o precios.
Usas conectores naturales: "mira", "la verdad es que", "te cuento", "eso depende", "igual".
No terminas todos los mensajes con pregunta. A veces solo das información y dejas que el usuario reaccione.
Si el usuario ya te dio información en la conversación, la usas. No vuelves a preguntar lo que ya sabes.
Siempre termina tu respuesta con una pregunta corta y directa que lleve la conversación hacia el siguiente paso. No dejes respuestas abiertas sin dirección. Ejemplo: después de explicar qué es Appo, pregunta "¿Cómo manejas las reservas hoy?" — no lances los planes de entrada.

SOBRE APPO
Appo permite que los clientes reserven citas desde su celular, 24/7, sin llamadas ni WhatsApp.
El dueño controla la agenda, los barberos y las métricas desde un solo lugar.

Funcionalidades principales:
Reservas online 24/7 con link público propio
Recordatorios automáticos por WhatsApp
Lista negra de clientes incumplidos
Gestión de múltiples barberos
Cálculo automático de comisiones
Estadísticas y reportes de ventas
Días de descanso y bloqueo de agenda
Campañas de fidelización por SMS/Email
Asistente de agenda con auto-relleno
Acceso desde móvil

Resultado real documentado: una barbería redujo inasistencias un 42% y aumentó ingresos un 18% con Appo.

PLANES Y PRECIOS
Plan Esencial — Gratis siempre
Para 1 barbero. Incluye agenda básica, link de reservas, lista de servicios y precios, app móvil.
No incluye recordatorios por WhatsApp, lista negra, comisiones, estadísticas ni soporte VIP.

Plan Pro — $49.000 COP por barbero al mes
30 días gratis, sin contrato ni permanencia.
Incluye todo: múltiples barberos, recordatorios WhatsApp, lista negra, comisiones, estadísticas, perfil con fotos y calificaciones, marketing por SMS/Email, asistente de agenda, soporte VIP, backup diario de clientes.

Si el usuario pregunta por precio con número de barberos específico, multiplicas: barberos × $49.000 COP.

MANEJO DE OBJECIONES
Cuando el usuario diga que no necesita Appo o que ya tiene todo resuelto, no te rindas en el primer intento. Busca otro ángulo real. Ejemplos:

"No tengo inasistencias" → "¿Y cómo manejas las reservas actualmente? ¿Por WhatsApp, llamada, presencial?"
"Ya tengo todo organizado" → "¿Y cuánto tiempo al día te toma eso? La mayoría que dice eso igual gasta 20-30 minutos diarios solo en confirmaciones."
"No necesito nada" → "¿Tienes la agenda llena todos los días o hay huecos en la semana?"
"Es muy caro" → "Son $49.000 por barbero. Si con eso llenas un turno extra al mes, ya se pagó solo."
"No me interesa" → "¿Qué es lo que menos te convence? A veces hay algo puntual que puedo aclarar."

Cuando hayas intentado dos o tres ángulos distintos y el usuario sigue sin interés, ahí sí cierra con naturalidad y deja el link: appo.com.co.

RESPUESTA SOBRE ORIGEN DEL NÚMERO
Si un lead pregunta cómo obtuvimos su número, responde con naturalidad: el negocio aparece listado en directorios públicos como Google Maps o páginas amarillas, y de ahí se obtuvo el contacto. Tono directo, sin rodeos, sin disculpas excesivas. Ejemplo: "Tu negocio aparece listado en Google Maps/páginas amarillas, de ahí sacamos el contacto. Es normal que nos pongamos en contacto con negocios de barberías y peluquerías para ofrecer Appo."

LÍMITES
No ofreces crear la cuenta del usuario ni le pides datos para registrarlo.
Si el usuario quiere registrarse, lo diriges a appo.com.co y listo.
Para soporte técnico estás tú para ayudar.
No inventas funciones ni precios que no estén en este prompt.
Nunca uses variables sin definir como [tu nombre] o similares.
"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY no encontrada en variables de entorno")
        
        self.model = self.FREE_MODELS[0]
        self.fallback_model = self.FREE_MODELS[1]
        self.max_retries = 3
        self.retry_delay = 2  # segundos
    
    def _call_api(self, messages: List[Dict], model: str = None) -> Optional[str]:
        """Llamada a la API de OpenRouter con manejo de reintentos."""
        import requests as _requests
        if model is None:
            model = self.model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://appo.com.co",
            "X-Title": "APPO Lead Prospector",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1500,  # Aumentado para evitar respuestas truncadas
        }
        
        for attempt in range(self.max_retries):
            try:
                resp = _requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data['choices'][0]['message']['content']
                return content.strip() if content else None
                
            except Exception as e:
                logger.warning(f"Intento {attempt+1}/{self.max_retries} falló con modelo {model}: {e}")
                
                if "rate limit" in str(e).lower() or "429" in str(e):
                    wait_time = self.retry_delay * (attempt + 1)
                    logger.info(f"Rate limit detectado, esperando {wait_time}s")
                    time.sleep(wait_time)
                else:
                    time.sleep(self.retry_delay)
                
                # En último intento, probar con fallback
                if attempt == self.max_retries - 1 and model != self.fallback_model:
                    logger.info(f"Probando con modelo fallback: {self.fallback_model}")
                    return self._call_api(messages, model=self.fallback_model)
        
        return None
    
    def generar_mensaje_inicial(self, lead_info: Dict) -> Optional[str]:
        """
        Genera el primer mensaje de prospección para un lead.
        
        Args:
            lead_info: Diccionario con info del lead (nombre_establecimiento, ciudad, telefono, etc.)
        
        Returns:
            str: Mensaje personalizado o None si falla
        """
        prompt = f"""{self.BASE_KNOWLEDGE}
        
        Lead objetivo:
        - Negocio: {lead_info.get('nombre_establecimiento', 'No especificado')}
        - Ciudad: {lead_info.get('ciudad', 'No especificada')}
        - Teléfono: {lead_info.get('telefono', 'No especificado')}
        
        Escribe un saludo natural para WhatsApp (una o dos líneas) que siga las instrucciones de APERTURA DE CONVERSACIÓN en el conocimiento base."""
        
        messages = [
            {"role": "system", "content": "Eres el asistente de ventas de Appo. Tu nombre es Appo. Hablas como un asesor humano, directo y relajado."},
            {"role": "user", "content": prompt}
        ]
        
        mensaje = self._call_api(messages)
        if mensaje and len(mensaje.strip()) > 10:
            return mensaje.strip()
        
        # Fallback hardcoded si la API falla - usar saludo natural
        return "Hola, cuéntame — ¿en qué te puedo ayudar?"
    
    def generar_respuesta(self, 
                         historial_conversacion: List[Dict], 
                         ultimo_mensaje_cliente: str) -> Optional[str]:
        """
        Genera una respuesta contextual basada en el historial de conversación.
        
        Args:
            historial_conversacion: Lista de mensajes anteriores en formato:
                [{"role": "assistant"|"user", "content": "...", "timestamp": "..."}]
            ultimo_mensaje_cliente: Último mensaje recibido del lead
        
        Returns:
            str: Respuesta adecuada o None si falla
        """
        logger.error(f'[GENERAR_RESPUESTA] historial_conversacion length: {len(historial_conversacion)}')
        logger.error(f'[GENERAR_RESPUESTA] ultimo_mensaje_cliente: {ultimo_mensaje_cliente}')
        if len(historial_conversacion) == 0:
            logger.error('[GENERAR_RESPUESTA] Historial vacío - primera interacción')
        
        # Construir el contexto para el LLM con conocimiento base
        system_prompt = f"""{self.BASE_KNOWLEDGE}
        
        Sigue las instrucciones anteriores para responder al lead.
        """
        
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Agregar historial completo (modelo Nemotron soporta contexto extenso)
        for msg in historial_conversacion:
            if msg["role"] == "assistant":
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                messages.append({"role": "user", "content": msg["content"]})
        
        # Agregar último mensaje del cliente
        messages.append({"role": "user", "content": ultimo_mensaje_cliente})
        
        logger.error(f'[GENERAR_RESPUESTA] messages a enviar a API: {json.dumps(messages, ensure_ascii=False)[:1000]}')
        
        respuesta = self._call_api(messages)
        logger.error(f'[GENERAR_RESPUESTA] respuesta de API: {respuesta}')
        return respuesta.strip() if respuesta else None
    
    def evaluar_intencion(self, mensaje_cliente: str) -> Dict:
        """
        Evalúa la intención del lead basado en su mensaje.
        
        Returns:
            Dict con categoría y score (ej: {"categoria": "interesado", "score": 0.8})
        """
        prompt = f"""Clasifica la intención del siguiente mensaje de un lead:
        
        "{mensaje_cliente}"
        
        Opciones:
        1. "pregunta_precio" - Pregunta por precios, costos, tarifas
        2. "interesado" - Muestra interés en el servicio
        3. "informacion" - Pide más información general
        4. "negativo" - Rechazo o desinterés
        5. "neutral" - Saludo o mensaje neutro
        
        Responde SOLO con el nombre de la categoría (una palabra)."""
        
        messages = [
            {"role": "system", "content": "Eres un clasificador de intenciones comerciales. Devuelves solo la palabra clave."},
            {"role": "user", "content": prompt}
        ]
        
        categoria = self._call_api(messages)
        if categoria:
            categoria = categoria.strip().lower()
            # Mapear a categorías válidas
            validas = ["pregunta_precio", "interesado", "informacion", "negativo", "neutral"]
            if categoria not in validas:
                # Intentar inferir
                if "precio" in categoria or "cuesta" in categoria or "costo" in categoria:
                    categoria = "pregunta_precio"
                elif "interesa" in categoria or "me gusta" in categoria:
                    categoria = "interesado"
                elif "información" in categoria or "más info" in categoria:
                    categoria = "informacion"
                elif "no" in categoria or "gracias" in categoria or "adiós" in categoria:
                    categoria = "negativo"
                else:
                    categoria = "neutral"
        else:
            categoria = "neutral"
        
        # Score simple (podría mejorarse)
        score = 0.7 if categoria in ["interesado", "pregunta_precio"] else 0.3
        
        return {"categoria": categoria, "score": score}


# --- Nuevas funciones de envío en partes ---
import time
import random

PARTES_SALUDO = [
    "Hola, cuéntame — ¿en qué te puedo ayudar?"
]

def formatear_saludo(nombre: str) -> list[str]:
    return PARTES_SALUDO

def guardar_mensaje(conversacion, role: str, contenido: str):
    """Guarda un mensaje en la conversación."""
    ahora = timezone.now().isoformat()
    conversacion.mensajes.append({
        'role': role,
        'content': contenido,
        'timestamp': ahora
    })
    conversacion.save()

def procesar_lead_inicial(lead_id: int) -> list[str]:
    """Retorna lista de partes para envío separado en lugar de un bloque único."""
    from leads_admin.models import Lead, LeadConversacion
    lead = Lead.objects.using('leads_db').get(id=lead_id)
    nombre = lead.nombre_establecimiento or "amigo"
    conv, _ = LeadConversacion.objects.using('leads_db').get_or_create(
        lead=lead,
        defaults={'mensajes': [], 'estado': 'nuevo'}
    )
    partes = formatear_saludo(nombre)
    # Guardar en historial como un solo mensaje del assistant
    mensaje_completo = "\n\n".join(partes)
    guardar_mensaje(conv, "assistant", mensaje_completo)
    if conv.estado == 'nuevo':
        conv.estado = 'contactado'
        conv.save()
    return partes

def procesar_lead(lead_id: int, mensaje_entrante: str = None) -> str:
    """Procesa un lead y devuelve respuesta (string)."""
    from leads_admin.models import Lead, LeadConversacion
    from django.utils import timezone
    
    # Lead viene de leads_db (SQLite con los prospectos)
    lead = Lead.objects.using('leads_db').get(id=lead_id)
    
    # Conversación vive en la misma DB que el lead (leads_db) para mantener FK
    conv, _ = LeadConversacion.objects.using('leads_db').get_or_create(
        lead=lead,
        defaults={'mensajes': [], 'estado': 'nuevo'}
    )
    
    if mensaje_entrante is None:
        # Saludo inicial
        nombre = lead.nombre_establecimiento or "amigo"
        partes = formatear_saludo(nombre)
        mensaje_completo = "\n\n".join(partes)
        guardar_mensaje(conv, "assistant", mensaje_completo)
        if conv.estado == 'nuevo':
            conv.estado = 'contactado'
            conv.save()
        return mensaje_completo
    else:
        # Pasar historial previo al modelo (SIN incluir el mensaje actual todavía)
        agent = get_prospector_agent()
        historial_previo = list(conv.mensajes) if conv.mensajes else []
        logger.error(f'[PROCESAR_LEAD] historial_previo length: {len(historial_previo)}')
        logger.error(f'[PROCESAR_LEAD] mensaje entrante: {mensaje_entrante}')
        respuesta = agent.generar_respuesta(historial_previo, mensaje_entrante)
        logger.error(f'[PROCESAR_LEAD] respuesta generada: {respuesta}' if respuesta else '[PROCESAR_LEAD] respuesta generada: None')

        # Guardar mensaje del usuario Y respuesta DESPUES de generar (evita duplicados)
        guardar_mensaje(conv, "user", mensaje_entrante)
        if respuesta:
            guardar_mensaje(conv, "assistant", respuesta)
            conv.ultimo_contacto = timezone.now()
            conv.estado = 'contactado'
            conv.save(using='leads_db')
            return respuesta
        else:
            fallback = "Gracias por tu mensaje. Un asesor te contactará pronto."
            guardar_mensaje(conv, "assistant", fallback)
            conv.ultimo_contacto = timezone.now()
            conv.save(using='leads_db')
            return fallback


def procesar_mensaje_whatsapp(remote_jid: str, mensaje_cliente: str, phone: str = None) -> str:
    """
    Procesa un mensaje de WhatsApp para un número no registrado como lead.
    Usa historial de MensajeWhatsApp para contexto.
    Retorna respuesta generada.
    """
    from leads_admin.models import ChatWhatsApp, MensajeWhatsApp
    from django.utils import timezone
    
    agent = get_prospector_agent()
    
    # Obtener historial de mensajes previos para este chat
    historial_mensajes = MensajeWhatsApp.objects.using('leads_db').filter(
        chat__chat_id=remote_jid
    ).order_by('id')[:20]  # últimos 20 mensajes
    
    # Convertir a formato de historial conversacional
    historial_conversacion = []
    for msg in historial_mensajes:
        role = "assistant" if msg.from_me else "user"
        historial_conversacion.append({
            "role": role,
            "content": msg.message_text or "",
            "timestamp": msg.timestamp.isoformat() if hasattr(msg, 'timestamp') and msg.timestamp else ""
        })
    
    logger.info(f'[PROCESAR_WHATSAPP] Historial para {remote_jid}: {len(historial_conversacion)} mensajes')
    
    # Generar respuesta usando el agente
    respuesta = agent.generar_respuesta(historial_conversacion, mensaje_cliente)
    
    if respuesta:
        logger.info(f'[PROCESAR_WHATSAPP] Respuesta generada para {remote_jid}: {respuesta[:100]}...')
        # Aquí no guardamos nada en la base de datos; el webhook ya guardó el mensaje entrante
        # La respuesta se guardará al enviarse (si se desea)
        return respuesta
    else:
        fallback = "Gracias por tu mensaje. Un asesor te contactará pronto."
        logger.warning(f'[PROCESAR_WHATSAPP] Fallback usado para {remote_jid}')
        return fallback


# Instancia global (singleton)
_agent_instance = None

def get_prospector_agent() -> ProspectorAgent:
    """Obtener instancia única del agente."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ProspectorAgent()
    return _agent_instance